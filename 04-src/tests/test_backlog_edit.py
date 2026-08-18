"""Tests de T-FB036-US08-01: edición directa de `priority`/`state` en el
frontmatter de una User Story/Task ya existente (`brain.backlog.edit`).

Misma fixture de frontmatter YAML que `test_backlog_promote.py` — formato
real post-migración FB-027."""
from __future__ import annotations

from pathlib import Path

import pytest

from brain.backlog.edit import (
    BacklogValidationError,
    InvalidFieldValueError,
    set_item_priority,
    set_item_state,
)
from brain.backlog.validator_v2 import validate_backlog_file_v2


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _task(tmp_path: Path, task_id: str = "T-FB100-US01-01", *, state: str = "TO_DO", priority: str = "Alta") -> Path:
    path = tmp_path / f"{task_id}.md"
    _write(
        path,
        f"---\nid: {task_id}\ntype: task\ntitle: {task_id}\nstate: {state}\n"
        f"dependencies: []\nepic: FB-100\nuser_story: US-FB100-01\npriority: {priority}\n"
        "---\n\n## Objetivo\n\nTest.\n",
    )
    return path


def _user_story(tmp_path: Path, us_id: str = "US-FB100-01", *, state: str = "TO_DO", priority: str = "Alta") -> Path:
    path = tmp_path / f"{us_id}.md"
    _write(
        path,
        f"---\nid: {us_id}\ntype: user_story\ntitle: {us_id}\nstate: {state}\n"
        f"dependencies: []\nepic: FB-100\npriority: {priority}\n"
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
    path = _task(tmp_path, state="TO_DO")

    set_item_state(path, "IN_PROGRESS")

    assert _field(path, "state") == "IN_PROGRESS"


def test_set_item_state_valor_invalido_no_toca_el_fichero(tmp_path: Path) -> None:
    path = _task(tmp_path, state="TO_DO")
    original = path.read_text(encoding="utf-8")

    with pytest.raises(InvalidFieldValueError):
        set_item_state(path, "CANCELADA")

    assert path.read_text(encoding="utf-8") == original


def test_set_item_state_sobre_user_story_funciona_igual(tmp_path: Path) -> None:
    path = _user_story(tmp_path, state="IN_PROGRESS")

    set_item_state(path, "DONE")

    assert _field(path, "state") == "DONE"


def test_backlog_validation_error_expone_los_mensajes_del_validador(tmp_path: Path) -> None:
    path = _task(tmp_path, state="TO_DO")

    try:
        set_item_state(path, "DONE")
    except BacklogValidationError:
        pytest.fail("DONE es un estado válido, no debería lanzar BacklogValidationError")

    assert _field(path, "state") == "DONE"
