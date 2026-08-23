"""Tests de T-AF036-US02-01/-02/-03: creación de una Epic/User Story/Task
nueva desde cero (`atlas_forge.backlog.create`)."""
from __future__ import annotations

from pathlib import Path

import pytest

from atlas_forge.backlog.create import (
    BacklogValidationError,
    EpicAlreadyExistsError,
    EpicNotFoundError,
    InvalidEpicIdError,
    InvalidFieldValueError,
    InvalidPriorityError,
    InvalidTaskIdError,
    InvalidUserStoryIdError,
    TaskAlreadyExistsError,
    UserStoryAlreadyExistsError,
    UserStoryNotFoundError,
    create_epic,
    create_task,
    create_user_story,
)
from atlas_forge.backlog.validator_v2 import validate_backlog_file_v2


def test_create_epic_writes_a_real_file_that_passes_the_validator(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"

    path = create_epic(backlog, "AF-900", "Epic de prueba", "Objetivo real de prueba.")

    assert path.is_file()
    assert path == backlog / "epics" / "AF-900-epic-de-prueba.md"
    result = validate_backlog_file_v2(path)
    assert result.valid, result.errors


def test_create_epic_content_has_the_expected_frontmatter_and_sections(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"

    path = create_epic(backlog, "AF-900", "Epic de prueba", "Objetivo real.")
    content = path.read_text(encoding="utf-8")

    assert "id: AF-900" in content
    assert "type: epic" in content
    assert "title: Epic de prueba" in content
    assert "state: TO_DO" in content
    assert "dependencies: []" in content
    # T-AF036-US18-01: la Epic se versiona — frontmatter con `version`, sin `fase`.
    assert "version: '0.9'" in content or "version: \"0.9\"" in content
    assert "fase:" not in content
    assert "## Objetivo" in content
    assert "Objetivo real." in content


def test_create_epic_uses_version_0_9_and_passes_validator(tmp_path: Path) -> None:
    """T-AF036-US18-01: la Epic creada escribe `version: 0.9` y valida."""
    backlog = tmp_path / "02-backlog"

    path = create_epic(backlog, "AF-900", "Epic versionada", "Objetivo real.")
    content = path.read_text(encoding="utf-8")

    assert "version:" in content
    assert "fase:" not in content
    result = validate_backlog_file_v2(path)
    assert result.valid, result.errors


def test_create_epic_invalid_id_format_rejected_without_touching_disk(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"

    with pytest.raises(InvalidEpicIdError):
        create_epic(backlog, "AF-9", "Titulo", "Objetivo.")

    assert not (backlog / "epics").exists()


def test_create_epic_duplicate_id_rejected_without_overwriting(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    first_path = create_epic(backlog, "AF-900", "Primera epic", "Objetivo primero.")
    original_content = first_path.read_text(encoding="utf-8")

    with pytest.raises(EpicAlreadyExistsError):
        create_epic(backlog, "AF-900", "Segunda epic con mismo id", "Objetivo distinto.")

    assert first_path.read_text(encoding="utf-8") == original_content


def test_create_epic_duplicate_detected_even_against_legacy_filename_without_slug(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    epics_dir = backlog / "epics"
    epics_dir.mkdir(parents=True)
    (epics_dir / "AF-900.md").write_text(
        "---\nid: AF-900\ntype: epic\ntitle: Legacy\nstate: TODO\ndependencies: []\n---\n\n## Objetivo\n\nX.\n",
        encoding="utf-8",
    )

    with pytest.raises(EpicAlreadyExistsError):
        create_epic(backlog, "AF-900", "Nueva epic", "Objetivo.")


def test_create_epic_slug_strips_accents_and_special_characters(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"

    path = create_epic(backlog, "AF-900", "Gestión de Backlog: Crear/Editar", "Objetivo.")

    assert path.name.startswith("AF-900-")
    assert path.name.endswith(".md")
    # El slug no debe contener el título literal (con mayúsculas/acentos)
    # ni caracteres reservados de shell/filesystem.
    assert ":" not in path.name
    assert "/" not in path.name.split("AF-900-", 1)[1]


# ---------------------------------------------------------------------
# create_user_story (T-AF036-US02-02)
# ---------------------------------------------------------------------


def test_create_user_story_writes_a_real_file_that_passes_the_validator(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    create_epic(backlog, "AF-900", "Epic de prueba", "Objetivo.")

    path = create_user_story(
        backlog, "AF-900", "US-AF900-01", "US de prueba",
        "Como usuario quiero X para lograr Y.", "- Criterio uno.\n- Criterio dos.",
        priority="Alta",
    )

    assert path.is_file()
    assert path == backlog / "user-stories" / "US-AF900-01-us-de-prueba.md"
    result = validate_backlog_file_v2(path)
    assert result.valid, result.errors


def test_create_user_story_content_has_the_expected_frontmatter_and_sections(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    create_epic(backlog, "AF-900", "Epic de prueba", "Objetivo.")

    path = create_user_story(
        backlog, "AF-900", "US-AF900-01", "US de prueba",
        "Como usuario quiero X.", "- Criterio uno.", priority="Media",
    )
    content = path.read_text(encoding="utf-8")

    assert "id: US-AF900-01" in content
    assert "type: user_story" in content
    assert "title: US de prueba" in content
    # T-AF008-US15-01 (2026-08-17): toda User Story nueva nace en
    # NO_TASKS, no TODO — TODO queda reservado para cuando ya tiene al
    # menos una Task real.
    assert "state: NO_TASKS" in content
    assert "dependencies: []" in content
    assert "epic: AF-900" in content
    assert "priority: Media" in content
    assert "## Historia" in content
    assert "Como usuario quiero X." in content
    assert "## Criterios de aceptación" in content
    assert "- Criterio uno." in content


def test_create_user_story_epic_id_always_matches_the_one_passed_explicitly(tmp_path: Path) -> None:
    """Simula lo que hace la capa HTTP: `epic_id` viene de la URL, se
    pasa aquí como argumento posicional explícito — nunca se lee de
    ningún otro sitio dentro de esta función. El fichero resultante debe
    reflejar exactamente ese valor."""
    backlog = tmp_path / "02-backlog"
    create_epic(backlog, "AF-900", "Epic real", "Objetivo.")

    path = create_user_story(
        backlog, "AF-900", "US-AF900-01", "US", "Historia.", "Criterios.",
    )
    content = path.read_text(encoding="utf-8")

    assert "epic: AF-900" in content


def test_create_user_story_without_priority_defaults_to_null_and_still_passes_validator(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    create_epic(backlog, "AF-900", "Epic", "Objetivo.")

    path = create_user_story(backlog, "AF-900", "US-AF900-01", "US", "Historia.", "Criterios.")
    content = path.read_text(encoding="utf-8")

    assert "priority: null" in content
    result = validate_backlog_file_v2(path)
    assert result.valid, result.errors


def test_create_user_story_persists_valid_fase(tmp_path: Path) -> None:
    """T-AF036-US14-05: una fase válida del conjunto se persiste en la US."""
    backlog = tmp_path / "02-backlog"
    create_epic(backlog, "AF-900", "Epic", "Objetivo.")

    path = create_user_story(
        backlog, "AF-900", "US-AF900-01", "US", "Historia.", "Criterios.", fase="Fase 0.9.1"
    )
    content = path.read_text(encoding="utf-8")

    assert "fase: Fase 0.9.1" in content
    result = validate_backlog_file_v2(path)
    assert result.valid, result.errors


def test_create_user_story_fase_fuera_del_conjunto_se_rechaza_sin_tocar_disco(
    tmp_path: Path,
) -> None:
    """T-AF036-US14-05: crear una US con `fase` fuera del conjunto cerrado
    falla con rechazo explícito y no escribe nada."""
    backlog = tmp_path / "02-backlog"
    create_epic(backlog, "AF-900", "Epic", "Objetivo.")

    with pytest.raises(InvalidFieldValueError):
        create_user_story(
            backlog, "AF-900", "US-AF900-01", "US", "Historia.", "Criterios.", fase="Fase 0.1"
        )

    assert not (backlog / "user-stories").exists()


def test_create_user_story_nonexistent_epic_rejected_without_touching_disk(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"

    with pytest.raises(EpicNotFoundError):
        create_user_story(backlog, "AF-999", "US-AF999-01", "US", "Historia.", "Criterios.")

    assert not (backlog / "user-stories").exists()


def test_create_user_story_invalid_id_format_rejected_without_touching_disk(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    create_epic(backlog, "AF-900", "Epic", "Objetivo.")

    with pytest.raises(InvalidUserStoryIdError):
        create_user_story(backlog, "AF-900", "US-AF900-1", "US", "Historia.", "Criterios.")

    assert not (backlog / "user-stories").exists()


def test_create_user_story_invalid_priority_rejected_without_touching_disk(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    create_epic(backlog, "AF-900", "Epic", "Objetivo.")

    with pytest.raises(InvalidPriorityError):
        create_user_story(
            backlog, "AF-900", "US-AF900-01", "US", "Historia.", "Criterios.",
            priority="Urgentísima",
        )

    assert not (backlog / "user-stories").exists()


def test_create_user_story_duplicate_id_rejected_without_overwriting(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    create_epic(backlog, "AF-900", "Epic", "Objetivo.")
    first_path = create_user_story(backlog, "AF-900", "US-AF900-01", "Primera US", "Historia.", "Criterios.")
    original_content = first_path.read_text(encoding="utf-8")

    with pytest.raises(UserStoryAlreadyExistsError):
        create_user_story(backlog, "AF-900", "US-AF900-01", "Segunda US con mismo id", "Otra historia.", "Otros criterios.")

    assert first_path.read_text(encoding="utf-8") == original_content


def test_create_user_story_title_with_colon_does_not_break_the_generated_yaml(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    create_epic(backlog, "AF-900", "Epic", "Objetivo.")

    path = create_user_story(
        backlog, "AF-900", "US-AF900-01", "Título: con dos puntos",
        "Historia con acentos: gestión, edición.", "Criterios.",
    )

    result = validate_backlog_file_v2(path)
    assert result.valid, result.errors


# ---------------------------------------------------------------------
# create_task (T-AF036-US02-03)
# ---------------------------------------------------------------------


def test_create_task_writes_a_real_file_that_passes_the_validator(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    create_epic(backlog, "AF-900", "Epic", "Objetivo.")
    create_user_story(backlog, "AF-900", "US-AF900-01", "US", "Historia.", "Criterios.")

    path, epic_id = create_task(
        backlog, "US-AF900-01", "T-AF900-US01-01", "Task de prueba",
        "Objetivo real.", "Descripción real.", "- Criterio uno.",
        priority="Alta",
    )

    assert path.is_file()
    assert path == backlog / "tasks" / "T-AF900-US01-01-task-de-prueba.md"
    assert epic_id == "AF-900"
    result = validate_backlog_file_v2(path)
    assert result.valid, result.errors


def test_create_task_content_has_the_expected_frontmatter_and_sections(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    create_epic(backlog, "AF-900", "Epic", "Objetivo.")
    create_user_story(backlog, "AF-900", "US-AF900-01", "US", "Historia.", "Criterios.")

    path, _epic_id = create_task(
        backlog, "US-AF900-01", "T-AF900-US01-01", "Task de prueba",
        "Objetivo real.", "Descripción real.", "- Criterio uno.",
        priority="Media", dependencies=["T-AF900-US01-02"],
    )
    content = path.read_text(encoding="utf-8")

    assert "id: T-AF900-US01-01" in content
    assert "type: task" in content
    assert "title: Task de prueba" in content
    assert "state: READY" in content
    assert "- T-AF900-US01-02" in content
    assert "epic: AF-900" in content
    assert "user_story: US-AF900-01" in content
    assert "priority: Media" in content
    assert "## Objetivo" in content
    assert "Objetivo real." in content
    assert "## Descripción" in content
    assert "Descripción real." in content
    assert "## Criterios de aceptación" in content
    assert "## Bugs encontrados" in content


def test_create_task_resolves_epic_id_from_the_parent_user_story_frontmatter(tmp_path: Path) -> None:
    """Criterio de aceptación explícito: `epic_id` NUNCA se pide al
    cliente — se resuelve leyendo el frontmatter de la propia US
    encontrada, evitando la inconsistencia de una Task con una Epic
    distinta a la de su US real."""
    backlog = tmp_path / "02-backlog"
    create_epic(backlog, "AF-900", "Epic real", "Objetivo.")
    create_user_story(backlog, "AF-900", "US-AF900-01", "US", "Historia.", "Criterios.")

    _path, epic_id = create_task(
        backlog, "US-AF900-01", "T-AF900-US01-01", "Task", "O.", "D.", "C.",
    )

    assert epic_id == "AF-900"


def test_create_task_under_orphan_user_story_creates_with_null_epic(tmp_path: Path) -> None:
    """Criterio de aceptación explícito (caso borde documentado en la
    especificación UX): una US sin `epic` en su frontmatter no bloquea
    la creación de la Task — se crea igualmente con `epic_id: null`."""
    backlog = tmp_path / "02-backlog"
    stories_dir = backlog / "user-stories"
    stories_dir.mkdir(parents=True)
    (stories_dir / "US-AF901-01-huerfana.md").write_text(
        "---\nid: US-AF901-01\ntype: user_story\ntitle: US huerfana\nstate: READY\n"
        "dependencies: []\npriority: Alta\n---\n\n## Historia\n\nHistoria.\n",
        encoding="utf-8",
    )

    path, epic_id = create_task(
        backlog, "US-AF901-01", "T-AF901-US01-01", "Task huerfana", "O.", "D.", "C.",
    )

    assert epic_id is None
    content = path.read_text(encoding="utf-8")
    assert "epic: null" in content
    result = validate_backlog_file_v2(path)
    assert result.valid, result.errors


def test_create_task_nonexistent_user_story_rejected_without_touching_disk(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"

    with pytest.raises(UserStoryNotFoundError):
        create_task(backlog, "US-AF999-01", "T-AF999-US01-01", "T", "O", "D", "C")

    assert not (backlog / "tasks").exists()


def test_create_task_invalid_id_format_rejected_without_touching_disk(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    create_epic(backlog, "AF-900", "Epic", "Objetivo.")
    create_user_story(backlog, "AF-900", "US-AF900-01", "US", "Historia.", "Criterios.")

    with pytest.raises(InvalidTaskIdError):
        create_task(backlog, "US-AF900-01", "T-AF900-01-01", "T", "O", "D", "C")

    assert not (backlog / "tasks").exists()


def test_create_task_invalid_priority_rejected_without_touching_disk(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    create_epic(backlog, "AF-900", "Epic", "Objetivo.")
    create_user_story(backlog, "AF-900", "US-AF900-01", "US", "Historia.", "Criterios.")

    with pytest.raises(InvalidPriorityError):
        create_task(
            backlog, "US-AF900-01", "T-AF900-US01-01", "T", "O", "D", "C",
            priority="Urgentísima",
        )

    assert not (backlog / "tasks").exists()


def test_create_task_duplicate_id_rejected_without_overwriting(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    create_epic(backlog, "AF-900", "Epic", "Objetivo.")
    create_user_story(backlog, "AF-900", "US-AF900-01", "US", "Historia.", "Criterios.")
    first_path, _epic_id = create_task(
        backlog, "US-AF900-01", "T-AF900-US01-01", "Primera Task", "O.", "D.", "C.",
    )
    original_content = first_path.read_text(encoding="utf-8")

    with pytest.raises(TaskAlreadyExistsError):
        create_task(
            backlog, "US-AF900-01", "T-AF900-US01-01", "Segunda Task mismo id", "O2.", "D2.", "C2.",
        )

    assert first_path.read_text(encoding="utf-8") == original_content


def test_create_task_without_dependencies_defaults_to_empty_list(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    create_epic(backlog, "AF-900", "Epic", "Objetivo.")
    create_user_story(backlog, "AF-900", "US-AF900-01", "US", "Historia.", "Criterios.")

    path, _epic_id = create_task(
        backlog, "US-AF900-01", "T-AF900-US01-01", "Task", "O.", "D.", "C.",
    )
    content = path.read_text(encoding="utf-8")

    assert "dependencies: []" in content


def test_create_task_title_with_colon_does_not_break_the_generated_yaml(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    create_epic(backlog, "AF-900", "Epic", "Objetivo.")
    create_user_story(backlog, "AF-900", "US-AF900-01", "US", "Historia.", "Criterios.")

    path, _epic_id = create_task(
        backlog, "US-AF900-01", "T-AF900-US01-01", "Título: con dos puntos",
        "Objetivo con acentos: gestión.", "Descripción: detallada.", "Criterios.",
    )

    result = validate_backlog_file_v2(path)
    assert result.valid, result.errors
