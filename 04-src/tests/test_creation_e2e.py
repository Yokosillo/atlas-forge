"""T-AF036-US20-05 (US-AF036-20): test end-to-end determinista del flujo
completo de creación desde descripción en lenguaje natural —

    humano describe → cola (pending) → Arquitecto dispacha (in_flight) →
    completión valida y escribe → petición done → item aparece en el backlog.

Combina los eslabones ya unitariamente cubiertos (T-AF036-US20-01/02/03
encolado, US20-06 cola, US20-07 despacho, US20-08 completión) en UN recorrido
que deja la entidad real escrita y validada — el criterio de aceptación 2 de la
Task ("el flujo queda cubierto end-to-end por al menos un test determinista").

Determinista, SIN tmux: se sustituye solo el envío no bloqueante del Job
(`dispatch_job_send`) por un doble que entrega el reporte de la propuesta; el
resto (cola, despacho, completión, creador del backlog, validador determinista)
es REAL."""
from __future__ import annotations

from pathlib import Path

from atlas_forge.backlog.validator_v2 import validate_backlog_file_v2
from atlas_forge.core.session_lifecycle import activate, assign_agent
from atlas_forge.dispatcher.creation_queue import (
    STATUS_DONE,
    enqueue_creation_request,
    get_creation_requests,
)
from atlas_forge.dispatcher.dispatch_queue_worker import (
    poll_inflight_creation_completions,
    run_creation_dispatch_cycle,
)
from atlas_forge.models import Agent, DevelopmentSession


def _e2e_mocks(tmp_path, monkeypatch, proposal_text: str) -> Path:
    """Doble determinista del envío del Job de creación: `dispatch_job_send`
    entrega el reporte con la propuesta del Arquitecto ya escrito (con el
    marcador de fin), de modo que el ciclo de completión lo lee y procesa."""
    from atlas_forge.agents.lifecycle import mark_working
    from atlas_forge.dispatcher import dispatch_queue_worker as worker_module
    from atlas_forge.dispatcher.job_lifecycle import mark_running

    class _FakeRuntime:
        session_name = "test-session"

    monkeypatch.setattr(worker_module, "get_runtime_instance_for_agent", lambda agent_id: _FakeRuntime())

    report_path = tmp_path / "reporte-creacion.md"

    def _fake_send(job, agent, runtime_instance, socket_name=None):
        mark_running(job)
        mark_working(agent)
        report_path.write_text(proposal_text + "\n___ATLAS_FORGE_JOB_DONE___\n", encoding="utf-8")
        return report_path

    monkeypatch.setattr(worker_module, "dispatch_job_send", _fake_send)
    return report_path


def _architect_session():
    architect = Agent(id="arch-1", name="Arquitecto", role="arquitecto", prompt="p", runtime_id="r1")
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    assign_agent(session, architect)
    return session


import yaml  # noqa: E402


def _epic_proposal() -> str:
    return yaml.safe_dump(
        {"proposal": {"id": "AF-777", "title": "Gestión de plantillas", "objetivo": "Permitir crear plantillas de items."}},
        sort_keys=False, allow_unicode=True,
    )


def test_e2e_creacion_epic_humano_a_backlog(tmp_path, monkeypatch) -> None:
    """Flujo completo: el humano encola una descripción libre de Epic → el
    Arquitecto la despacha (in_flight) → la completión procesa la propuesta,
    la valida y escribe af-777 → la petición queda `done` y el fichero pasa el
    validador determinista (el item está en el backlog)."""
    from fastapi.testclient import TestClient

    # ── 1. Encolado por el endpoint web (US20-01): human describe ──
    # Se simula el endpoint real con un proyecto activo para no salir del
    # flujo real; encolamos directamente por la API de dominio + endpoint.
    import atlas_forge.api.routes as routes_module
    from atlas_forge.api.app import create_app
    from atlas_forge.models import Project

    project_root = tmp_path / "workspace" / "project-a"
    (project_root / "02-backlog" / "epics").mkdir(parents=True, exist_ok=True)
    (project_root / "02-backlog" / "user-stories").mkdir(parents=True, exist_ok=True)
    (project_root / "02-backlog" / "tasks").mkdir(parents=True, exist_ok=True)

    project = Project(
        id=str(project_root), name="project-a", path=str(project_root),
        repository="", workspace_id="ws-test",
    )
    monkeypatch.setattr(routes_module, "get_active_project", lambda **_kwargs: project)

    client = TestClient(create_app())
    resp = client.post(
        "/backlog/epic/from-description",
        json={"description": "Quiero un gestor de plantillas para el backlog."},
    )
    assert resp.status_code == 202
    request_id = resp.json()["request_id"]

    # ── 2. Despacho por el worker (US20-07): Arquitecto idle y listo ──
    report_path = _e2e_mocks(tmp_path, monkeypatch, _epic_proposal())
    session = _architect_session()
    inflight_creation: dict = {}
    dispatched = run_creation_dispatch_cycle(
        project_root, "project-a", session, inflight_creation=inflight_creation,
    )
    assert dispatched == request_id
    assert get_creation_requests(project_root, "project-a")[0].status == "in_flight"

    # ── 3. Completión (US20-08): valida y escribe la Epic real ──
    resolved = poll_inflight_creation_completions(
        project_root, "project-a", session, inflight_creation,
        timeout_seconds=5.0,
    )
    assert resolved == [request_id]
    assert inflight_creation == {}

    # ── 4. La petición quedó done y el item está escrito y válido ──
    entry = get_creation_requests(project_root, "project-a")[0]
    assert entry.status == STATUS_DONE
    epic_files = list((project_root / "02-backlog" / "epics").glob("AF-777-*.md"))
    assert len(epic_files) == 1
    assert validate_backlog_file_v2(epic_files[0]).valid
    assert "Gestión de plantillas" in epic_files[0].read_text(encoding="utf-8")


def test_e2e_propuesta_invalida_queda_failed_sin_escribir(tmp_path, monkeypatch) -> None:
    """Flujo completo con propuesta inválida del Arquitecto (id mal formado):
    no se escribe nada en el backlog y la petición queda `failed` con los
    motivos (para que la web los muestre y la descripción se reintente)."""
    from fastapi.testclient import TestClient

    import atlas_forge.api.routes as routes_module
    from atlas_forge.api.app import create_app
    from atlas_forge.models import Project

    project_root = tmp_path / "workspace" / "project-a"
    (project_root / "02-backlog" / "epics").mkdir(parents=True, exist_ok=True)

    project = Project(
        id=str(project_root), name="project-a", path=str(project_root),
        repository="", workspace_id="ws-test",
    )
    monkeypatch.setattr(routes_module, "get_active_project", lambda **_kwargs: project)

    client = TestClient(create_app())
    resp = client.post(
        "/backlog/epic/from-description",
        json={"description": "Epic con id que dará error."},
    )
    assert resp.status_code == 202
    request_id = resp.json()["request_id"]

    bad = yaml.safe_dump(
        {"proposal": {"id": "no-es-valido", "title": "X", "objetivo": "Y"}},
        sort_keys=False, allow_unicode=True,
    )
    _e2e_mocks(tmp_path, monkeypatch, bad)
    session = _architect_session()
    inflight_creation: dict = {}
    run_creation_dispatch_cycle(project_root, "project-a", session, inflight_creation=inflight_creation)
    poll_inflight_creation_completions(project_root, "project-a", session, inflight_creation)

    assert list((project_root / "02-backlog" / "epics").glob("*.md")) == []
    entry = get_creation_requests(project_root, "project-a")[0]
    assert entry.status == "failed"
    assert len(entry.errors) >= 1
