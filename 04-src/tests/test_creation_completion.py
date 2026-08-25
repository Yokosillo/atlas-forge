"""Tests del nivel de completión de peticiones de creación (T-AF036-US20-08,
US-AF036-20): `poll_inflight_creation_completions` parsea la propuesta del
Arquitecto, la valida con el validador determinista y escribe la entidad real
en `02-backlog/` — o no escribe nada y deja los motivos verbatim.

Cubre:
- propuesta válida → se escribe el fichero (Epic) que pasa el validador, la
  petición pasa a `done` y el item aparece en el backlog;
- propuesta inválida → no se escribe nada, petición `failed` con motivos;
- id duplicado → `failed` (single-flight);
- timeout sin reporte → petición vuelve a `pending`.
Deterministas, sin tmux."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from atlas_forge.backlog.validator_v2 import validate_backlog_file_v2
from atlas_forge.core.session_lifecycle import activate, assign_agent
from atlas_forge.dispatcher.creation_queue import (
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_PENDING,
    enqueue_creation_request,
    get_creation_requests,
    mark_creation_in_flight,
)
from atlas_forge.dispatcher.dispatch_queue_worker import (
    InFlightCreationJob,
    poll_inflight_creation_completions,
)
from atlas_forge.dispatcher.job_lifecycle import mark_running
from atlas_forge.agents.lifecycle import mark_working
from atlas_forge.models import Agent, DevelopmentSession, Job


def _report_file(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "report.md"
    path.write_text(content + "\n___ATLAS_FORGE_JOB_DONE___\n", encoding="utf-8")
    return path


def _valid_epic_proposal() -> str:
    import yaml
    return yaml.safe_dump(
        {"proposal": {"id": "AF-999", "title": "Pipeline de creación", "objetivo": "Orquestar la creación de items desde LN."}},
        sort_keys=False,
        allow_unicode=True,
    )


def _setup(project_root: Path, tmp_path: Path, tipo: str, description: str):
    backlog = project_root / "02-backlog"
    (backlog / "epics").mkdir(parents=True, exist_ok=True)
    (backlog / "user-stories").mkdir(parents=True, exist_ok=True)
    (backlog / "tasks").mkdir(parents=True, exist_ok=True)

    request = enqueue_creation_request(
        project_root, "proj", tipo=tipo, description=description
    )
    report_file = tmp_path / "report.md"
    mark_creation_in_flight(project_root, "proj", request.request_id, report_file)

    agent = Agent(id="arq-1", name="Arquitecto", role="arquitecto", prompt="p", runtime_id="r1")
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    assign_agent(session, agent)

    job = Job(id=request.request_id + "-job", session_id="s1", agent_id="arq-1", description="d")
    mark_running(job)
    mark_working(agent)
    inflight = {
        request.request_id: InFlightCreationJob(
            request_id=request.request_id,
            tipo=tipo,
            architect_agent_id="arq-1",
            report_file=report_file,
            job=job,
            dispatched_at=time.monotonic(),
        )
    }
    return backlog, request, report_file, session, inflight


def test_valid_epic_proposal_writes_file_and_marks_done(tmp_path: Path) -> None:
    project_root = tmp_path / "rep"
    backlog, request, report_file, session, inflight = _setup(
        project_root, tmp_path, "epic", "Crear un pipeline de creación de items"
    )
    report_file.write_text(_valid_epic_proposal() + "\n___ATLAS_FORGE_JOB_DONE___\n", encoding="utf-8")

    resolved = poll_inflight_creation_completions(project_root, "proj", session, inflight)

    assert resolved == [request.request_id]
    assert inflight == {}
    # Se escribió la Epic real y pasa el validador.
    epic_files = list((backlog / "epics").glob("AF-999-*.md"))
    assert len(epic_files) == 1
    assert validate_backlog_file_v2(epic_files[0]).valid
    # La petición queda done.
    entry = get_creation_requests(project_root, "proj")[0]
    assert entry.status == STATUS_DONE


def test_invalid_epic_proposal_failed_with_verbatim(tmp_path: Path) -> None:
    """Propuesta inválida (id mal formado): no se escribe nada y la petición
    pasa a `failed` con los motivos verbatim del validador."""
    import yaml
    project_root = tmp_path / "rep"
    backlog, request, report_file, session, inflight = _setup(
        project_root, tmp_path, "epic", "Epic con id inválido"
    )
    bad = yaml.safe_dump(
        {"proposal": {"id": "no-es-un-id", "title": "X", "objetivo": "Y"}},
        sort_keys=False, allow_unicode=True,
    )
    report_file.write_text(bad + "\n___ATLAS_FORGE_JOB_DONE___\n", encoding="utf-8")

    poll_inflight_creation_completions(project_root, "proj", session, inflight)

    assert list((backlog / "epics").glob("*.md")) == []  # no se escribió nada
    entry = get_creation_requests(project_root, "proj")[0]
    assert entry.status == STATUS_FAILED
    assert len(entry.errors) >= 1  # motivos verbatim
    assert any("AF" in e or "id" in e.lower() for e in entry.errors)


def test_duplicate_id_failed_single_flight(tmp_path: Path) -> None:
    """Criterio 9 de la US: un id duplicado generado por el pipeline se
    rechaza con mensaje explícito (petición `failed`), no se duplica."""
    project_root = tmp_path / "rep"
    backlog, request, report_file, session, inflight = _setup(
        project_root, tmp_path, "epic", "Epic que ya existe"
    )
    # Pre-crear la Epic con el mismo id.
    from atlas_forge.backlog.create import create_epic
    create_epic(backlog, "AF-999", "Ya existe", "Objetivo ya existente.")

    report_file.write_text(_valid_epic_proposal() + "\n___ATLAS_FORGE_JOB_DONE___\n", encoding="utf-8")

    poll_inflight_creation_completions(project_root, "proj", session, inflight)

    # Solo un fichero AF-999 (el preexistente) — no se duplicó.
    assert len(list((backlog / "epics").glob("AF-999-*.md"))) == 1
    entry = get_creation_requests(project_root, "proj")[0]
    assert entry.status == STATUS_FAILED
    assert any("ya existe" in e for e in entry.errors) or any("dupli" in e.lower() for e in entry.errors)


def test_timeout_without_report_returns_to_pending(tmp_path: Path) -> None:
    """Sin reporte y timeout vencido: la petición vuelve a `pending` (se
    reintenta sola) y el Job se marca `failed`."""
    project_root = tmp_path / "rep"
    _background, request, report_file, session, inflight = _setup(
        project_root, tmp_path, "epic", "Crear algo"
    )
    # report_file NO tiene marcador (el Arquitecto no terminó) y el timeout en
    # 0 segundos vence.
    report_file.write_text("sin marcador todavía\n", encoding="utf-8")
    for infl in inflight.values():
        infl.dispatched_at = time.monotonic() - 1000  # timeout vencido

    resolved = poll_inflight_creation_completions(
        project_root, "proj", session, inflight, timeout_seconds=0.0
    )

    assert resolved == [request.request_id]
    assert inflight == {}
    entry = get_creation_requests(project_root, "proj")[0]
    assert entry.status == STATUS_PENDING


def test_valid_us_proposal_writes_user_story(tmp_path: Path) -> None:
    import yaml
    from atlas_forge.backlog.create import create_epic

    project_root = tmp_path / "rep"
    backlog, request, report_file, session, inflight = _setup(
        project_root, tmp_path, "us", "Crear US de auditoría"
    )
    create_epic(backlog, "AF-999", "Epic", "Objetivo.")

    prop = yaml.safe_dump(
        {
            "proposal": {
                "id": "US-AF999-01",
                "epic_id": "AF-999",
                "title": "Auditar el producto",
                "objetivo": "Como usuario quiero auditar el producto.",
                "criterios_aceptacion": "- Que exista un informe.",
                "priority": "Alta",
                "version": "0.9",
            }
        },
        sort_keys=False, allow_unicode=True,
    )
    report_file.write_text(prop + "\n___ATLAS_FORGE_JOB_DONE___\n", encoding="utf-8")

    poll_inflight_creation_completions(project_root, "proj", session, inflight)

    us_files = list((backlog / "user-stories").glob("US-AF999-01-*.md"))
    assert len(us_files) == 1
    assert validate_backlog_file_v2(us_files[0]).valid
    assert get_creation_requests(project_root, "proj")[0].status == STATUS_DONE


def test_valid_task_proposal_writes_task(tmp_path: Path) -> None:
    """Propuesta válida de Task → se escribe el fichero que pasa el validador
    y la petición pasa a `done` (la US de contexto debe existir)."""
    import yaml
    from atlas_forge.backlog.create import create_epic, create_user_story

    project_root = tmp_path / "rep"
    backlog, request, report_file, session, inflight = _setup(
        project_root, tmp_path, "task", "Crear la Task del checkout"
    )
    create_epic(backlog, "AF-999", "Epic", "Objetivo.")
    create_user_story(
        backlog, "AF-999", "US-AF999-01", "Historia", "H.", "- C.", priority="Alta", version="0.9"
    )

    prop = yaml.safe_dump(
        {
            "proposal": {
                "id": "T-AF999-US01-01",
                "us_id": "US-AF999-01",
                "title": "Implementar checkout",
                "objetivo": "Implementar el flujo.",
                "descripcion": "Detalles.",
                "criterios_aceptacion": "- C1",
                "priority": "Alta",
                "dependencies": [],
            }
        },
        sort_keys=False, allow_unicode=True,
    )
    report_file.write_text(prop + "\n___ATLAS_FORGE_JOB_DONE___\n", encoding="utf-8")

    poll_inflight_creation_completions(project_root, "proj", session, inflight)

    task_files = list((backlog / "tasks").glob("T-AF999-US01-01-*.md"))
    assert len(task_files) == 1
    assert validate_backlog_file_v2(task_files[0]).valid
    assert get_creation_requests(project_root, "proj")[0].status == STATUS_DONE
