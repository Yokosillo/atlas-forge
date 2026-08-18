"""Tests del validador de formato YAML frontmatter + Markdown (FB-027)."""

import pytest

from brain.backlog.validator_v2 import (
    validate_backlog_content_v2,
    ValidationResultV2,
)


VALID_TASK = """---
id: T-FB022-US05-02
type: task
epic: FB-022
user_story: US-FB022-05
title: Disparo automatico del Job de veredicto
state: DONE
dependencies:
  - T-FB022-US05-01
  - US-FB022-06
priority: Crítica
---

## Objetivo

Hacer algo importante.

## Descripcion

Mas detalles aqui.
"""

VALID_US = """---
id: US-FB022-05
type: user_story
epic: FB-022
title: Veredicto estructurado
state: TO_DO
dependencies:
  - US-FB022-06
priority: Alta
fase: Fase 1.0
---

## Historia

Como desarrollador...

## Criterios de aceptacion

- Criterio 1
- Criterio 2
"""

VALID_EPIC = """---
id: FB-022
type: epic
title: Pipeline Backlog-centrico
state: TO_DO
dependencies:
  - FB-005
  - FB-008
fase: Fase 1.0
---

## Objetivo

Reorientar Factory Brain...

## Criterios de aceptacion

- Criterio 1
"""

VALID_TASK_NO_DEPS = """---
id: T-FB022-US01-01
type: task
epic: FB-022
user_story: US-FB022-01
title: Tarea sin dependencias
state: TO_DO
dependencies: []
priority: Media
---

## Objetivo

Hacer algo.
"""

VALID_US_NO_DEPS = """---
id: US-FB001-01
type: user_story
epic: FB-001
title: Historia sin dependencias
state: DONE
dependencies: []
priority: Baja
---

## Historia

Como usuario...
"""


class TestValidFiles:
    def test_valid_task(self):
        result = validate_backlog_content_v2(VALID_TASK, "T-FB022-US05-02-algo.md")
        assert result.valid, f"Errores: {result.errors}"
        assert result.file_type == "task"

    def test_valid_us(self):
        result = validate_backlog_content_v2(VALID_US, "US-FB022-05-algo.md")
        assert result.valid, f"Errores: {result.errors}"
        assert result.file_type == "user_story"

    def test_valid_epic(self):
        result = validate_backlog_content_v2(VALID_EPIC, "FB-022-algo.md")
        assert result.valid, f"Errores: {result.errors}"
        assert result.file_type == "epic"

    def test_valid_task_no_deps(self):
        result = validate_backlog_content_v2(VALID_TASK_NO_DEPS, "T-FB022-US01-01-algo.md")
        assert result.valid, f"Errores: {result.errors}"

    def test_valid_us_no_deps(self):
        result = validate_backlog_content_v2(VALID_US_NO_DEPS, "US-FB001-01-algo.md")
        assert result.valid, f"Errores: {result.errors}"


class TestMissingFrontmatter:
    def test_no_frontmatter(self):
        content = "# T-FB022-US05-02 · Titulo\n\n## Objetivo\n..."
        result = validate_backlog_content_v2(content, "T-FB022-US05-02.md")
        assert not result.valid
        assert any("frontmatter" in e.message.lower() for e in result.errors)

    def test_frontmatter_not_closed(self):
        content = "---\nid: T-FB022-US05-02\ntype: task\nstate: TO_DO\ndependencies: []\n"
        result = validate_backlog_content_v2(content, "T-FB022-US05-02.md")
        assert not result.valid
        assert any("no cerrado" in e.message for e in result.errors)

    def test_frontmatter_empty(self):
        content = "---\n---\n\n## Objetivo\n..."
        result = validate_backlog_content_v2(content, "T-FB022-US05-02.md")
        assert not result.valid
        assert any("vacio" in e.message for e in result.errors)

    def test_frontmatter_invalid_yaml(self):
        content = "---\nid: [unclosed\nstate: TO_DO\n---\n\n## Objetivo\n..."
        result = validate_backlog_content_v2(content, "T-FB022-US05-02.md")
        assert not result.valid
        assert any("yaml" in e.message.lower() for e in result.errors)

    def test_frontmatter_not_dict(self):
        content = "---\n- item1\n- item2\n---\n\n## Objetivo\n..."
        result = validate_backlog_content_v2(content, "T-FB022-US05-02.md")
        assert not result.valid
        assert any("diccionario" in e.message for e in result.errors)


class TestRequiredFields:
    def test_missing_id(self):
        content = VALID_TASK.replace("id: T-FB022-US05-02\n", "")
        result = validate_backlog_content_v2(content, "T-FB022-US05-02.md")
        assert not result.valid
        assert any("'id'" in e.message for e in result.errors)

    def test_missing_type(self):
        content = VALID_TASK.replace("type: task\n", "")
        result = validate_backlog_content_v2(content, "T-FB022-US05-02.md")
        assert not result.valid
        assert any("'type'" in e.message for e in result.errors)

    def test_missing_state(self):
        content = VALID_TASK.replace("state: DONE\n", "")
        result = validate_backlog_content_v2(content, "T-FB022-US05-02.md")
        assert not result.valid
        assert any("'state'" in e.message for e in result.errors)

    def test_missing_dependencies(self):
        content = VALID_TASK.replace("dependencies:\n  - T-FB022-US05-01\n  - US-FB022-06\n", "")
        result = validate_backlog_content_v2(content, "T-FB022-US05-02.md")
        assert not result.valid
        assert any("'dependencies'" in e.message for e in result.errors)

    def test_missing_epic_in_us(self):
        content = VALID_US.replace("epic: FB-022\n", "")
        result = validate_backlog_content_v2(content, "US-FB022-05.md")
        assert not result.valid
        assert any("'epic'" in e.message for e in result.errors)

    def test_missing_user_story_in_task(self):
        content = VALID_TASK.replace("user_story: US-FB022-05\n", "")
        result = validate_backlog_content_v2(content, "T-FB022-US05-02.md")
        assert not result.valid
        assert any("'user_story'" in e.message for e in result.errors)

    def test_missing_title(self):
        content = VALID_TASK.replace("title: Disparo automatico del Job de veredicto\n", "")
        result = validate_backlog_content_v2(content, "T-FB022-US05-02.md")
        assert not result.valid
        assert any("'title'" in e.message for e in result.errors)


class TestInvalidState:
    def test_invalid_state(self):
        content = VALID_TASK.replace("state: DONE", "state: COMPLETED")
        result = validate_backlog_content_v2(content, "T-FB022-US05-02.md")
        assert not result.valid
        assert any("state" in e.message.lower() for e in result.errors)

    def test_state_not_string(self):
        content = VALID_TASK.replace("state: DONE", "state: 123")
        result = validate_backlog_content_v2(content, "T-FB022-US05-02.md")
        assert not result.valid
        assert any("state" in e.message.lower() for e in result.errors)


class TestInvalidDependencies:
    def test_deps_not_list(self):
        content = VALID_TASK.replace(
            "dependencies:\n  - T-FB022-US05-01\n  - US-FB022-06",
            "dependencies: T-FB022-US05-01"
        )
        result = validate_backlog_content_v2(content, "T-FB022-US05-02.md")
        assert not result.valid
        assert any("lista" in e.message for e in result.errors)

    def test_dep_not_string(self):
        content = VALID_TASK.replace(
            "dependencies:\n  - T-FB022-US05-01\n  - US-FB022-06",
            "dependencies:\n  - 123"
        )
        result = validate_backlog_content_v2(content, "T-FB022-US05-02.md")
        assert not result.valid
        assert any("string" in e.message for e in result.errors)

    def test_dep_invalid_format(self):
        content = VALID_TASK.replace("  - US-FB022-06", "  - algo-invalido")
        result = validate_backlog_content_v2(content, "T-FB022-US05-02.md")
        assert not result.valid
        assert any("ID valido" in e.message for e in result.errors)


class TestInvalidPriority:
    def test_invalid_priority(self):
        content = VALID_TASK.replace("priority: Crítica", "priority: Urgente")
        result = validate_backlog_content_v2(content, "T-FB022-US05-02.md")
        assert not result.valid
        assert any("priority" in e.message.lower() for e in result.errors)

    def test_priority_null_is_ok(self):
        content = VALID_TASK.replace("priority: Crítica", "priority: null")
        result = validate_backlog_content_v2(content, "T-FB022-US05-02.md")
        assert result.valid, f"Errores: {result.errors}"


class TestInvalidEpicRef:
    def test_invalid_epic_format_in_task(self):
        content = VALID_TASK.replace("epic: FB-022", "epic: algo-mal")
        result = validate_backlog_content_v2(content, "T-FB022-US05-02.md")
        assert not result.valid
        assert any("'epic'" in e.message for e in result.errors)


class TestInvalidUserStoryRef:
    def test_invalid_us_format_in_task(self):
        content = VALID_TASK.replace("user_story: US-FB022-05", "user_story: FB-022")
        result = validate_backlog_content_v2(content, "T-FB022-US05-02.md")
        assert not result.valid
        assert any("'user_story'" in e.message for e in result.errors)


class TestInvalidType:
    def test_invalid_type(self):
        content = VALID_TASK.replace("type: task", "type: proyecto")
        result = validate_backlog_content_v2(content, "T-FB022-US05-02.md")
        assert not result.valid
        assert any("'type'" in e.message for e in result.errors)


class TestIdMismatch:
    def test_id_mismatches_filename(self):
        content = VALID_TASK  # id: T-FB022-US05-02
        result = validate_backlog_content_v2(content, "T-FB999-US99-99-algo.md")
        assert not result.valid
        assert any("coincide" in e.message for e in result.errors)

    def test_id_matches_filename(self):
        content = VALID_TASK
        result = validate_backlog_content_v2(content, "T-FB022-US05-02-disparo.md")
        assert result.valid, f"Errores: {result.errors}"


class TestPriorityOptionalForEpic:
    def test_epic_without_priority(self):
        content = VALID_EPIC  # no priority field
        result = validate_backlog_content_v2(content, "FB-022.md")
        assert result.valid, f"Errores: {result.errors}"
