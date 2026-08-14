from brain.backlog.validator import (
    ValidationError,
    ValidationResult,
    validate_backlog_content,
    validate_backlog_file,
)


_VALID_EPIC = """# FB-001 · Gestión de Workspace

## Objetivo

Crear la capacidad base para gestionar el entorno de trabajo.

## Alcance

FB-001 debe permitir crear y configurar Workspaces.

## Estado

TODO

## Dependencias

Ninguna.

## Criterios de aceptación

- El sistema permite crear un Workspace.
- El sistema permite seleccionar un Workspace activo.
"""

_VALID_US = """# US-FB020-01 · Ver el estado del backlog

**Epic:** FB-020

## Historia

Como desarrollador, quiero ver el estado del backlog para saber qué tareas
están pendientes.

## Criterios de aceptación

- Se muestra una lista con todas las User Stories y Tasks.
- Cada elemento muestra su estado actual.

## Prioridad

Alta

## Dependencias

**FB-020**

## Estado

IN_PROGRESS
"""

_VALID_TASK = """# T-FB022-US01-01 · Generalizar el registro de tipos de agente

**Epic:** FB-022
**User Story:** US-FB022-01

## Objetivo

Implementar el registro de tipos de agente.

## Descripción

Sustituir el patrón hardcodeado por un mecanismo configurable.

## Criterios de aceptación

- Los 3 puntos hardcodeados se sustituyen.
- Registrar un rol nuevo no requiere tocar el registry.

## Prioridad

Crítica

## Dependencias

Ninguna.

## Estado

DONE
"""


def test_valid_epic_passes() -> None:
    result = validate_backlog_content(_VALID_EPIC)
    assert result.valid is True
    assert result.file_type == "epic"
    assert result.errors == []


def test_valid_us_passes() -> None:
    result = validate_backlog_content(_VALID_US)
    assert result.valid is True
    assert result.file_type == "user-story"
    assert result.errors == []


def test_valid_task_passes() -> None:
    result = validate_backlog_content(_VALID_TASK)
    assert result.valid is True
    assert result.file_type == "task"
    assert result.errors == []


# -- Title format --


def test_invalid_title_no_middle_dot() -> None:
    content = "# FB-001 Sin punto medio\n\n## Objetivo\n\nTest.\n\n## Alcance\n\nTest.\n\n## Estado\n\nTODO\n\n## Dependencias\n\nNinguna.\n\n## Criterios de aceptación\n\nTest.\n"
    result = validate_backlog_content(content)
    assert result.valid is False
    assert any("Título" in e.message for e in result.errors)


def test_invalid_title_wrong_prefix() -> None:
    content = "# XX-001 · Título incorrecto\n\n## Objetivo\n\nTest.\n\n## Alcance\n\nTest.\n\n## Estado\n\nTODO\n\n## Dependencias\n\nNinguna.\n\n## Criterios de aceptación\n\nTest.\n"
    result = validate_backlog_content(content)
    assert result.valid is False
    assert any("Título" in e.message for e in result.errors)


# -- Missing required sections --


def test_missing_required_section_in_epic() -> None:
    content = "# FB-001 · Epic sin Criterios\n\n## Objetivo\n\nTest.\n\n## Alcance\n\nTest.\n\n## Estado\n\nTODO\n\n## Dependencias\n\nNinguna.\n"
    result = validate_backlog_content(content)
    assert result.valid is False
    assert any("Criterios de aceptación" in e.message for e in result.errors)


def test_missing_required_section_in_task() -> None:
    content = "# T-FB022-US01-01 · Task sin Descripción\n\n**Epic:** FB-022\n**User Story:** US-FB022-01\n\n## Objetivo\n\nTest.\n\n## Criterios de aceptación\n\nTest.\n\n## Prioridad\n\nCrítica\n\n## Dependencias\n\nNinguna.\n\n## Estado\n\nTODO\n"
    result = validate_backlog_content(content)
    assert result.valid is False
    assert any("Descripción" in e.message for e in result.errors)


# -- Estado --


def test_invalid_status_value() -> None:
    content = _VALID_EPIC.replace("\nTODO\n", "\nCOMPLETADO\n")
    result = validate_backlog_content(content)
    assert result.valid is False
    assert any("Estado" in e.message for e in result.errors)


def test_status_value_with_blank_lines_between_header_and_value() -> None:
    content = "# FB-001 · Epic\n\n## Objetivo\n\nTest.\n\n## Alcance\n\nTest.\n\n## Estado\n\n\nDONE\n\n## Dependencias\n\nNinguna.\n\n## Criterios de aceptación\n\nTest.\n"
    result = validate_backlog_content(content)
    assert result.valid is True


def test_status_value_on_same_line() -> None:
    content = "# FB-001 · Epic\n\n## Objetivo\n\nTest.\n\n## Alcance\n\nTest.\n\n## Estado: REVIEW\n\n## Dependencias\n\nNinguna.\n\n## Criterios de aceptación\n\nTest.\n"
    result = validate_backlog_content(content)
    assert result.valid is True


# -- Reference fields --


def test_epic_field_with_extra_text() -> None:
    content = _VALID_US.replace("**Epic:** FB-020", "**Epic:** FB-020 (alcance v1)")
    result = validate_backlog_content(content)
    assert result.valid is False
    assert any("Epic" in e.message for e in result.errors)


def test_epic_field_wrong_format() -> None:
    content = _VALID_US.replace("**Epic:** FB-020", "**Epic:** Epic 20 Gestión Backlog")
    result = validate_backlog_content(content)
    assert result.valid is False
    assert any("Epic" in e.message for e in result.errors)


def test_user_story_field_wrong_format() -> None:
    content = _VALID_TASK.replace("**User Story:** US-FB022-01", "**User Story:** Historia 1 de la Epic 22")
    result = validate_backlog_content(content)
    assert result.valid is False
    assert any("User Story" in e.message for e in result.errors)


# -- Internal section must be H2 --


def test_internal_H1_section_is_rejected() -> None:
    content = _VALID_EPIC.replace("## Alcance", "# Alcance")
    result = validate_backlog_content(content)
    assert result.valid is False
    assert any("H1" in e.message or "H2" in e.message for e in result.errors)


# -- Dependencies --


def test_valid_dependencies_with_multiple_refs() -> None:
    content = "# FB-001 · Epic\n\n## Objetivo\n\nTest.\n\n## Alcance\n\nTest.\n\n## Estado\n\nTODO\n\n## Dependencias\n\n**FB-002**, **US-FB005-04**\n\n## Criterios de aceptación\n\nTest.\n"
    result = validate_backlog_content(content)
    assert result.valid is True


def test_valid_dependencies_with_task_ref() -> None:
    content = "# FB-001 · Epic\n\n## Objetivo\n\nTest.\n\n## Alcance\n\nTest.\n\n## Estado\n\nTODO\n\n## Dependencias\n\n**T-FB022-US01-01**, **FB-002**\n\n## Criterios de aceptación\n\nTest.\n"
    result = validate_backlog_content(content)
    assert result.valid is True


def test_valid_dependencies_with_us_suffix() -> None:
    content = "# FB-001 · Epic\n\n## Objetivo\n\nTest.\n\n## Alcance\n\nTest.\n\n## Estado\n\nTODO\n\n## Dependencias\n\n**US-FB022-03A**, **T-FB022-US03A-01**\n\n## Criterios de aceptación\n\nTest.\n"
    result = validate_backlog_content(content)
    assert result.valid is True


def test_malformed_dependency_line_with_bold() -> None:
    content = "# FB-001 · Epic\n\n## Objetivo\n\nTest.\n\n## Alcance\n\nTest.\n\n## Estado\n\nTODO\n\n## Dependencias\n\n**algo mal formado**\n\n## Criterios de aceptación\n\nTest.\n"
    result = validate_backlog_content(content)
    assert result.valid is False
    assert any("Dependencias" in e.message for e in result.errors)


# -- Existing valid files --


def test_existing_task_files_are_valid() -> None:
    from brain.backlog.validator_v2 import validate_backlog_file_v2
    import os
    tasks_dir = os.path.join(
        os.path.dirname(__file__), "..", "..", "02-backlog", "tasks"
    )
    file1 = os.path.join(tasks_dir, "T-FB022-US01-01-generalizar-registro-tipo-agente.md")
    file2 = os.path.join(tasks_dir, "T-FB022-US01-02-crear-rol-director.md")
    file3 = os.path.join(tasks_dir, "T-FB022-US01-03-renombrar-critico-a-arquitecto.md")
    file4 = os.path.join(tasks_dir, "T-FB022-US03A-01-implementar-validador-formato.md")

    for path in (file1, file2, file3, file4):
        result = validate_backlog_file_v2(path)
        assert result.valid is True, f"{path}: {result.errors}"


def test_existing_fb022_epic_is_valid() -> None:
    from brain.backlog.validator_v2 import validate_backlog_file_v2
    import os
    path = os.path.join(
        os.path.dirname(__file__), "..", "..", "02-backlog", "epics",
        "FB-022-pipeline-backlog-centrico.md"
    )
    result = validate_backlog_file_v2(path)
    assert result.valid is True, f"Errors: {result.errors}"


# -- Structured error output --


def test_errors_include_line_number() -> None:
    content = "# FB-001 · Epic\n\n## Objetivo\n\nTest.\n\n## Alcance\n\nTest.\n\n## Estado\n\nMAL\n\n## Dependencias\n\nNinguna.\n\n## Criterios de aceptación\n\nTest.\n"
    result = validate_backlog_content(content)
    assert result.valid is False
    for e in result.errors:
        assert e.line > 0
        assert isinstance(e.message, str) and len(e.message) > 0


def test_empty_content() -> None:
    result = validate_backlog_content("")
    assert result.valid is False
    assert len(result.errors) > 0
