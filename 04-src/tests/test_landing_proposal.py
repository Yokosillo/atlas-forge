"""Tests de T-AF008-US16-02: procesar y validar la propuesta de aterrizaje
US→Tasks del Arquitecto (`atlas_forge/architect/landing_proposal.py`).

Cubre la interpretación del reporte (YAML `tasks:`), la validación
determinista de cada Task con `validate_backlog_file_v2` y la escritura
solo de Tasks válidas — el paso de completión del aterrizaje no bloqueante.
Todos los tests son deterministas y sin tmux."""
from __future__ import annotations

from pathlib import Path

import pytest

from atlas_forge.architect.landing_proposal import (
    parse_landing_proposal,
    write_validated_landing_tasks,
)
from atlas_forge.backlog.validator_v2 import validate_backlog_file_v2
from atlas_forge.models import BacklogItem


_VALID_PROPOSAL = """tasks:
  - id: T-AF999-US01-01
    title: Implementar modulo central
    objective: Implementar la logica central
    description: Descripcion detallada.
    criteria:
      - La logica funciona.
    priority: Alta
    difficulty: Alta
    dependencies: []
    epic_id: AF-999
    us_id: US-AF999-01
"""


def test_parse_valid_proposal_returns_tasks() -> None:
    tasks = parse_landing_proposal(_VALID_PROPOSAL)
    assert len(tasks) == 1
    assert tasks[0].id == "T-AF999-US01-01"
    assert tasks[0].epic_id == "AF-999"
    assert tasks[0].us_id == "US-AF999-01"
    assert tasks[0].objective == "Implementar la logica central"


def test_parse_invalid_yaml_returns_empty() -> None:
    assert parse_landing_proposal("tasks: [ { nok") == []


def test_parse_missing_tasks_key_returns_empty() -> None:
    assert parse_landing_proposal("notas: hola") == []
    assert parse_landing_proposal("- solo una lista") == []


def test_parse_task_missing_required_field_is_skipped() -> None:
    incomplete = """tasks:
  - id: T-AF999-US01-01
    title: Sin objetivo
"""
    assert parse_landing_proposal(incomplete) == []


def test_write_valid_task_persists_and_validates(tmp_path: Path) -> None:
    tasks = parse_landing_proposal(_VALID_PROPOSAL)
    result = write_validated_landing_tasks(tasks, tmp_path)
    assert result.has_written_tasks
    assert len(result.written) == 1
    assert len(result.rejected) == 0
    written = result.written[0]
    assert written.exists()
    validation = validate_backlog_file_v2(written)
    assert validation.valid


def test_write_rejects_invalid_task_and_does_not_persist(tmp_path: Path) -> None:
    """Una Task con id inválido no se persiste — el validador actúa como red
    de seguridad: `validate_backlog_file_v2` la rechaza y se elimina."""
    invalid = """tasks:
  - id: not-a-valid-id
    title: Task invalida
    objective: Objetivo.
    description: Desc.
    criteria:
      - C1
    priority: Alta
    difficulty: Alta
    dependencies: []
    epic_id: AF-999
    us_id: US-AF999-01
"""
    tasks = parse_landing_proposal(invalid)
    assert len(tasks) == 1
    result = write_validated_landing_tasks(tasks, tmp_path)
    assert not result.has_written_tasks
    assert len(result.written) == 0
    assert len(result.rejected) == 1
    assert result.rejected[0][0] == "not-a-valid-id"
    assert list(tmp_path.glob("*.md")) == []


def test_write_empty_proposal_writes_nothing(tmp_path: Path) -> None:
    result = write_validated_landing_tasks([], tmp_path)
    assert not result.has_written_tasks
    assert result.written == []
    assert list(tmp_path.glob("*.md")) == []


# ---------------------------------------------------------------------------
# T-AF008-US16-04: round-trip prompt→parser→validador. Si el contrato del
# prompt (`_build_landing_job_description`) y el del parser
# (`parse_landing_proposal`) divergen, este test falle — una propuesta
# escrita EXACTAMENTE como instruye el prompt debe parsear a 1 Task y
# validar con `validate_backlog_file_v2`.
# ---------------------------------------------------------------------------


def test_landing_job_prompt_round_trip_parses_and_validates(tmp_path: Path) -> None:
    from atlas_forge.dispatcher.dispatch_queue_worker import (
        _build_landing_job_description,
    )

    us_item = BacklogItem(
        id="US-AF999-01",
        kind="US",
        epic="AF-999",
        state="TO_PLAN",
        dependencies=(),
        priority="Alta",
        difficulty=None,
        fase=None,
        path=tmp_path / "02-backlog" / "user-stories" / "US-AF999-01.md",
    )
    us_title = "Aterrizaje US→Tasks ejecutado por el agente Arquitecto"

    prompt = _build_landing_job_description(us_item, us_title)

    # El prompt debe instruir la clave `us_id` (nunca `user_story:`) y el
    # patrón de id sin guion entre AF y el número (T-AF999-..., nunca
    # T-AF-999-...).
    assert "user_story:" not in prompt
    assert "us_id: US-AF999-01" in prompt
    assert "epic_id: AF-999" in prompt
    assert "T-AF999-USxx-NN" in prompt
    assert "T-AF-999-USxx-NN" not in prompt

    # Propuesta escrita exactamente como el prompt instruye.
    proposal = """tasks:
  - id: T-AF999-US01-01
    title: Implementar modulo central
    objective: Implementar la logica central
    description: Descripcion detallada.
    criteria:
      - La logica funciona.
    priority: Alta
    difficulty: Alta
    dependencies: []
    epic_id: AF-999
    us_id: US-AF999-01
"""

    tasks = parse_landing_proposal(proposal)
    assert len(tasks) == 1
    assert tasks[0].id == "T-AF999-US01-01"
    assert tasks[0].epic_id == "AF-999"
    assert tasks[0].us_id == "US-AF999-01"

    result = write_validated_landing_tasks(tasks, tmp_path)
    assert len(result.written) == 1
    assert len(result.rejected) == 0
    assert validate_backlog_file_v2(result.written[0]).valid


def test_landing_job_prompt_rejects_old_user_story_contract(tmp_path: Path) -> None:
    """Contrato roto detectado (T-AF008-US16-04): si la propuesta usa la
    clave antigua `user_story:` (o el id con guion `T-AF-999-US01-01`)
    exactamente como instruía el prompt defectuoso, NO debe parsear ni
    validar — el round-trip del prompt corregido sí lo hace."""
    proposal = """tasks:
  - id: T-AF-999-US01-01
    title: Implementar modulo central
    objective: Implementar la logica central
    description: Descripcion detallada.
    criteria:
      - La logica funciona.
    priority: Alta
    difficulty: Alta
    dependencies: []
    epic: AF-999
    user_story: US-AF999-01
"""
    tasks = parse_landing_proposal(proposal)
    assert tasks == []


# ---------------------------------------------------------------------------
# T-AF008-US18-01: el aterrizaje auto-deniegue cualquier id duplicado ANTES de
# escribir — bien porque ya existe en `tasks_dir` (refuerza
# `_collect_existing_task_ids`) o porque se repite DENTRO de la misma
# propuesta. La Task se registra en `rejected` y NO se escribe el fichero.
# ---------------------------------------------------------------------------


def test_within_proposal_duplicate_id_rejected_without_writing(tmp_path: Path) -> None:
    """Criterio 3: dos Tasks propuestas con el mismo `id` — la primera se
    escribe, la segunda se rechaza como duplicada y NO crea un segundo
    fichero."""
    proposal = """tasks:
  - id: T-AF999-US01-01
    title: Primera task
    objective: Objetivo uno.
    description: Desc uno.
    criteria:
      - C1
    priority: Alta
    difficulty: Alta
    dependencies: []
    epic_id: AF-999
    us_id: US-AF999-01
  - id: T-AF999-US01-01
    title: Segunda task con el mismo id
    objective: Objetivo dos.
    description: Desc dos.
    criteria:
      - C2
    priority: Media
    difficulty: Media
    dependencies: []
    epic_id: AF-999
    us_id: US-AF999-01
"""
    tasks = parse_landing_proposal(proposal)
    assert len(tasks) == 2

    result = write_validated_landing_tasks(tasks, tmp_path)

    assert len(result.written) == 1
    assert len(result.rejected) == 1
    assert result.rejected[0][0] == "T-AF999-US01-01"
    assert "no se duplica" in result.rejected[0][1][0].lower()
    # Solo UNA Task quedó en disco, nunca dos ficheros con el mismo id.
    md_files = list(tmp_path.glob("T-AF999-US01-01-*.md"))
    assert len(md_files) == 1


def test_id_already_in_backlog_rejected_without_overwriting(tmp_path: Path) -> None:
    """Criterio 2: un Task propuesto cuyo `id` YA existe en `tasks_dir` se
    auto-deniegue: se registra en `rejected` y NO se escribe ni sobreescribe
    el fichero existente (refuerza el guard `_collect_existing_task_ids`)."""
    first = write_validated_landing_tasks(
        parse_landing_proposal(_VALID_PROPOSAL), tmp_path
    )
    assert len(first.written) == 1
    original = first.written[0].read_text(encoding="utf-8")

    second = """tasks:
  - id: T-AF999-US01-01
    title: Distinto titulo con el mismo id
    objective: Otro objetivo.
    description: Otra descripcion.
    criteria:
      - C1
    priority: Baja
    difficulty: Baja
    dependencies: []
    epic_id: AF-999
    us_id: US-AF999-01
"""

    result = write_validated_landing_tasks(parse_landing_proposal(second), tmp_path)

    assert result.written == []
    assert len(result.rejected) == 1
    assert result.rejected[0][0] == "T-AF999-US01-01"
    # No se creó un segundo fichero ni se sobrescribió el original.
    assert list(tmp_path.glob("T-AF999-US01-01-*.md")) == [first.written[0]]
    assert first.written[0].read_text(encoding="utf-8") == original
