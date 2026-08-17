"""Tests de T-FB036-US02-01: creación de una Epic nueva desde cero
(`brain.backlog.create`)."""
from __future__ import annotations

from pathlib import Path

import pytest

from brain.backlog.create import (
    BacklogValidationError,
    EpicAlreadyExistsError,
    InvalidEpicIdError,
    create_epic,
)
from brain.backlog.validator_v2 import validate_backlog_file_v2


def test_create_epic_writes_a_real_file_that_passes_the_validator(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"

    path = create_epic(backlog, "FB-900", "Epic de prueba", "Objetivo real de prueba.")

    assert path.is_file()
    assert path == backlog / "epics" / "FB-900-epic-de-prueba.md"
    result = validate_backlog_file_v2(path)
    assert result.valid, result.errors


def test_create_epic_content_has_the_expected_frontmatter_and_sections(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"

    path = create_epic(backlog, "FB-900", "Epic de prueba", "Objetivo real.", fase="Fase 1.0")
    content = path.read_text(encoding="utf-8")

    assert "id: FB-900" in content
    assert "type: epic" in content
    assert "title: Epic de prueba" in content
    assert "state: TODO" in content
    assert "dependencies: []" in content
    assert "fase: Fase 1.0" in content
    assert "## Objetivo" in content
    assert "Objetivo real." in content


def test_create_epic_without_fase_defaults_to_null_and_still_passes_validator(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"

    path = create_epic(backlog, "FB-900", "Epic sin fase", "Objetivo real.")
    content = path.read_text(encoding="utf-8")

    assert "fase: null" in content
    result = validate_backlog_file_v2(path)
    assert result.valid, result.errors


def test_create_epic_invalid_id_format_rejected_without_touching_disk(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"

    with pytest.raises(InvalidEpicIdError):
        create_epic(backlog, "FB-9", "Titulo", "Objetivo.")

    assert not (backlog / "epics").exists()


def test_create_epic_duplicate_id_rejected_without_overwriting(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    first_path = create_epic(backlog, "FB-900", "Primera epic", "Objetivo primero.")
    original_content = first_path.read_text(encoding="utf-8")

    with pytest.raises(EpicAlreadyExistsError):
        create_epic(backlog, "FB-900", "Segunda epic con mismo id", "Objetivo distinto.")

    assert first_path.read_text(encoding="utf-8") == original_content


def test_create_epic_duplicate_detected_even_against_legacy_filename_without_slug(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    epics_dir = backlog / "epics"
    epics_dir.mkdir(parents=True)
    (epics_dir / "FB-900.md").write_text(
        "---\nid: FB-900\ntype: epic\ntitle: Legacy\nstate: TODO\ndependencies: []\n---\n\n## Objetivo\n\nX.\n",
        encoding="utf-8",
    )

    with pytest.raises(EpicAlreadyExistsError):
        create_epic(backlog, "FB-900", "Nueva epic", "Objetivo.")


def test_create_epic_slug_strips_accents_and_special_characters(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"

    path = create_epic(backlog, "FB-900", "Gestión de Backlog: Crear/Editar", "Objetivo.")

    assert path.name.startswith("FB-900-")
    assert path.name.endswith(".md")
    # El slug no debe contener el título literal (con mayúsculas/acentos)
    # ni caracteres reservados de shell/filesystem.
    assert ":" not in path.name
    assert "/" not in path.name.split("FB-900-", 1)[1]
