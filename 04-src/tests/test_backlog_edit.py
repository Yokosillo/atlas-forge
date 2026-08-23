"""Tests de T-AF036-US08-01: edición directa de `priority`/`state` en el
frontmatter de una User Story/Task ya existente (`atlas_forge.backlog.edit`).

Misma fixture de frontmatter YAML que `test_backlog_promote.py` — formato
real post-migración AF-027."""
from __future__ import annotations

from pathlib import Path

import pytest

from atlas_forge.backlog.edit import (
    BacklogValidationError,
    InvalidFieldValueError,
    set_item_fase,
    set_item_priority,
    set_item_state,
)
from atlas_forge.backlog.validator_v2 import validate_backlog_file_v2


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _task(tmp_path: Path, task_id: str = "T-AF100-US01-01", *, state: str = "READY", priority: str = "Alta") -> Path:
    path = tmp_path / f"{task_id}.md"
    _write(
        path,
        f"---\nid: {task_id}\ntype: task\ntitle: {task_id}\nstate: {state}\n"
        f"dependencies: []\nepic: AF-100\nuser_story: US-AF100-01\npriority: {priority}\n"
        "---\n\n## Objetivo\n\nTest.\n",
    )
    return path


def _user_story(tmp_path: Path, us_id: str = "US-AF100-01", *, state: str = "READY", priority: str = "Alta") -> Path:
    path = tmp_path / f"{us_id}.md"
    _write(
        path,
        f"---\nid: {us_id}\ntype: user_story\ntitle: {us_id}\nstate: {state}\n"
        f"dependencies: []\nepic: AF-100\npriority: {priority}\n"
        "---\n\n## Historia\n\nTest.\n",
    )
    return path


def _field(path: Path, field: str) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{field}:"):
            return line.split(":", 1)[1].strip()
    raise AssertionError(f"no {field} field in {path}")


def test_set_item_priority_cambia_el_campo_en_el_fichero_real(tmp_path: Path) -> None:
    path = _task(tmp_path, priority="Alta")

    set_item_priority(path, "Baja")

    assert _field(path, "priority") == "Baja"


def test_set_item_priority_none_escribe_null_y_pasa_el_validador(tmp_path: Path) -> None:
    path = _task(tmp_path, priority="Alta")

    set_item_priority(path, None)

    assert _field(path, "priority") == "null"
    result = validate_backlog_file_v2(path)
    assert result.valid, result.errors


def test_set_item_priority_valor_invalido_no_toca_el_fichero(tmp_path: Path) -> None:
    path = _task(tmp_path, priority="Alta")
    original = path.read_text(encoding="utf-8")

    with pytest.raises(InvalidFieldValueError):
        set_item_priority(path, "Urgentísima")

    assert path.read_text(encoding="utf-8") == original


def test_set_item_state_cambia_el_campo_en_el_fichero_real(tmp_path: Path) -> None:
    path = _task(tmp_path, state="READY")

    set_item_state(path, "TO_DEVELOP")

    assert _field(path, "state") == "TO_DEVELOP"


def test_set_item_state_valor_invalido_no_toca_el_fichero(tmp_path: Path) -> None:
    path = _task(tmp_path, state="READY")
    original = path.read_text(encoding="utf-8")

    with pytest.raises(InvalidFieldValueError):
        set_item_state(path, "CANCELADA")

    assert path.read_text(encoding="utf-8") == original


def test_set_item_state_sobre_user_story_funciona_igual(tmp_path: Path) -> None:
    path = _user_story(tmp_path, state="IN_PROGRESS")

    set_item_state(path, "IN_REVIEW")

    assert _field(path, "state") == "IN_REVIEW"


def test_backlog_validation_error_expone_los_mensajes_del_validador(tmp_path: Path) -> None:
    path = _task(tmp_path, state="READY")

    try:
        set_item_state(path, "TO_DEVELOP")
    except BacklogValidationError:
        pytest.fail("TO_DEVELOP es una transición legal, no debería lanzar BacklogValidationError")

    assert _field(path, "state") == "TO_DEVELOP"


# ---------------------------------------------------------------------------
# T-AF036-US22-01: el backend rechaza transiciones de estado ilegales
# (`can_transition`) — solo las que la máquina canónica permite se persisten.
# ---------------------------------------------------------------------------


def test_set_item_state_rechaza_transicion_ilegal_task_adelante(tmp_path: Path) -> None:
    """Task `READY -> DONE` (salto ilegal) se rechaza sin tocar disco."""
    path = _task(tmp_path, state="READY")
    original = path.read_text(encoding="utf-8")

    with pytest.raises(InvalidFieldValueError, match="ilegal"):
        set_item_state(path, "DONE")

    assert path.read_text(encoding="utf-8") == original


def test_set_item_state_rechaza_transicion_ilegal_task_atras(tmp_path: Path) -> None:
    """Task `DONE -> READY` (reabrir ilegalmente) se rechaza sin tocar disco."""
    path = _task(tmp_path, state="DONE")

    with pytest.raises(InvalidFieldValueError, match="ilegal"):
        set_item_state(path, "READY")

    assert _field(path, "state") == "DONE"


def test_set_item_state_permite_desencolar_task(tmp_path: Path) -> None:
    """Task `TO_DEVELOP -> READY` (desencolar) es legal y se persiste."""
    path = _task(tmp_path, state="TO_DEVELOP")

    set_item_state(path, "READY")

    assert _field(path, "state") == "READY"


def test_set_item_state_rechaza_transicion_ilegal_us_done_a_derivado(
    tmp_path: Path,
) -> None:
    """US `DONE -> READY` (reabrir a un estado derivado) es ilegal."""
    path = _user_story(tmp_path, state="DONE")

    with pytest.raises(InvalidFieldValueError, match="ilegal"):
        set_item_state(path, "READY")

    assert _field(path, "state") == "DONE"


def test_set_item_state_permite_us_done_a_out_of_scope(tmp_path: Path) -> None:
    """US `DONE -> OUT_OF_SCOPE` es legal y se persiste."""
    path = _user_story(tmp_path, state="DONE")

    set_item_state(path, "OUT_OF_SCOPE")

    assert _field(path, "state") == "OUT_OF_SCOPE"


def test_set_item_state_permite_us_toplan_a_ready(tmp_path: Path) -> None:
    """US `TO_PLAN -> READY` (aterrizaje de Tasks) es legal y se persiste."""
    path = _user_story(tmp_path, state="TO_PLAN")

    set_item_state(path, "READY")

    assert _field(path, "state") == "READY"


# ---------------------------------------------------------------------------
# T-AF036-US13-01: al cambiar el estado por la web, el frontmatter gana/
# actualiza `updated_at` (ISO-8601 UTC) sin romper el validador.
# ---------------------------------------------------------------------------


def test_set_item_state_escribe_updated_at_en_el_frontmatter(tmp_path: Path) -> None:
    """Criterio: al cambiar el estado de una US/Task (web), el fichero gana
    `updated_at` con timestamp ISO-8601 UTC y sigue pasando el validador."""
    path = _task(tmp_path, state="READY")

    set_item_state(path, "TO_DEVELOP")

    assert _field(path, "state") == "TO_DEVELOP"
    updated_at = _field(path, "updated_at")
    assert updated_at, "debe existir el campo updated_at tras el cambio de estado"
    # ISO-8601 UTC: termina en Z o lleva offset +00:00 / tz-aware con formato ISO.
    from datetime import datetime

    datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
    assert validate_backlog_file_v2(path).valid


def test_set_item_state_actualiza_updated_at_existente(tmp_path: Path) -> None:
    """Criterio: un segundo cambio de estado actualiza (no duplica) la línea
    `updated_at`, y el valor cambia respecto al primero."""
    path = _task(tmp_path, state="READY")

    set_item_state(path, "TO_DEVELOP")
    first = _field(path, "updated_at")
    count_after_first = path.read_text(encoding="utf-8").count("updated_at:")
    assert count_after_first == 1

    set_item_state(path, "IN_PROGRESS")
    second = _field(path, "updated_at")
    assert path.read_text(encoding="utf-8").count("updated_at:") == 1
    assert second != first


def _epic(tmp_path: Path, epic_id: str = "AF-100") -> Path:
    path = tmp_path / f"{epic_id}.md"
    _write(
        path,
        f"---\nid: {epic_id}\ntype: epic\ntitle: {epic_id}\nstate: TO_DO\n"
        "dependencies: []\n---\n\n## Objetivo\n\nTest.\n",
    )
    return path


def test_set_item_fase_actualiza_campo_en_fichero_real(tmp_path: Path) -> None:
    """Criterio: `set_item_fase` actualiza el campo `fase` del fichero real."""
    path = _user_story(tmp_path, state="READY")
    _add_fase(path, "Fase 0.1")

    set_item_fase(path, "Fase 0.9.1")

    assert _field(path, "fase") == "Fase 0.9.1"
    assert validate_backlog_file_v2(path).valid


def test_set_item_fase_inserta_campo_ausente_y_none_escribe_null(tmp_path: Path) -> None:
    """Si el item no declara `fase`, se inserta; con `None` se escribe null."""
    path = _user_story(tmp_path, state="READY")  # sin campo fase

    set_item_fase(path, "Fase 0.9")

    assert _field(path, "fase") == "Fase 0.9"
    assert validate_backlog_file_v2(path).valid

    set_item_fase(path, None)

    assert _field(path, "fase") == "null"
    assert validate_backlog_file_v2(path).valid


def test_set_item_fase_funciona_sobre_epic(tmp_path: Path) -> None:
    """Criterio: funciona para Epic (`AF-xxx`)."""
    path = _epic(tmp_path, "AF-100")

    set_item_fase(path, "Fase 0.9.2")

    assert _field(path, "fase") == "Fase 0.9.2"
    assert validate_backlog_file_v2(path).valid


def test_set_item_fase_rechaza_fase_fuera_del_conjunto(tmp_path: Path) -> None:
    """T-AF036-US14-05: un valor fuera del conjunto cerrado (p. ej. un 0.x
    legado) se rechaza con `InvalidFieldValueError` SIN tocar el fichero."""
    path = _user_story(tmp_path, state="READY")
    _add_fase(path, "Fase 0.9")

    with pytest.raises(InvalidFieldValueError):
        set_item_fase(path, "Fase 0.1")

    assert _field(path, "fase") == "Fase 0.9"  # no se modificó


def _add_fase(path: Path, value: str) -> None:
    content = path.read_text(encoding="utf-8")
    idx = content.index("\n---")
    content = content[:idx] + f"\nfase: {value}" + content[idx:]
    path.write_text(content, encoding="utf-8")


def test_set_item_state_permite_task_in_review_a_done(tmp_path: Path) -> None:
    """Task `IN_REVIEW -> DONE` (adelante, validación del Tester) es legal."""
    path = _task(tmp_path, state="IN_REVIEW")

    set_item_state(path, "DONE")

    assert _field(path, "state") == "DONE"


def test_set_item_state_permite_task_in_review_a_in_progress(tmp_path: Path) -> None:
    """Task `IN_REVIEW -> IN_PROGRESS` (rechazo del Tester, reabrir) es legal."""
    path = _task(tmp_path, state="IN_REVIEW")

    set_item_state(path, "IN_PROGRESS")

    assert _field(path, "state") == "IN_PROGRESS"
