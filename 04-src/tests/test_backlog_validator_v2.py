"""Tests del validador de formato YAML frontmatter + Markdown (AF-027)."""

import pytest

from atlas_forge.backlog.validator_v2 import (
    validate_backlog_content_v2,
    validate_backlog_file_v2,
    find_duplicate_ids_in_dir,
    ValidationResultV2,
)


VALID_TASK = """---
id: T-AF022-US05-02
type: task
epic: AF-022
user_story: US-AF022-05
title: Disparo automatico del Job de veredicto
state: DONE
dependencies:
  - T-AF022-US05-01
  - US-AF022-06
priority: Crítica
---

## Objetivo

Hacer algo importante.

## Descripcion

Mas detalles aqui.
"""

VALID_US = """---
id: US-AF022-05
type: user_story
epic: AF-022
title: Veredicto estructurado
state: READY
dependencies:
  - US-AF022-06
priority: Alta
fase: Fase 0.9
---

## Historia

Como desarrollador...

## Criterios de aceptacion

- Criterio 1
- Criterio 2
"""

VALID_EPIC = """---
id: AF-022
type: epic
title: Pipeline Backlog-centrico
state: TO_DO
dependencies:
  - AF-005
  - AF-008
fase: Fase 0.9
---

## Objetivo

Reorientar Atlas Forge...

## Criterios de aceptacion

- Criterio 1
"""

VALID_TASK_NO_DEPS = """---
id: T-AF022-US01-01
type: task
epic: AF-022
user_story: US-AF022-01
title: Tarea sin dependencias
state: READY
dependencies: []
priority: Media
---

## Objetivo

Hacer algo.
"""

VALID_US_NO_DEPS = """---
id: US-AF001-01
type: user_story
epic: AF-001
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
        result = validate_backlog_content_v2(VALID_TASK, "T-AF022-US05-02-algo.md")
        assert result.valid, f"Errores: {result.errors}"
        assert result.file_type == "task"

    def test_valid_us(self):
        result = validate_backlog_content_v2(VALID_US, "US-AF022-05-algo.md")
        assert result.valid, f"Errores: {result.errors}"
        assert result.file_type == "user_story"

    def test_valid_epic(self):
        result = validate_backlog_content_v2(VALID_EPIC, "AF-022-algo.md")
        assert result.valid, f"Errores: {result.errors}"
        assert result.file_type == "epic"

    def test_valid_task_no_deps(self):
        result = validate_backlog_content_v2(VALID_TASK_NO_DEPS, "T-AF022-US01-01-algo.md")
        assert result.valid, f"Errores: {result.errors}"

    def test_valid_us_no_deps(self):
        result = validate_backlog_content_v2(VALID_US_NO_DEPS, "US-AF001-01-algo.md")
        assert result.valid, f"Errores: {result.errors}"


class TestMissingFrontmatter:
    def test_no_frontmatter(self):
        content = "# T-AF022-US05-02 · Titulo\n\n## Objetivo\n..."
        result = validate_backlog_content_v2(content, "T-AF022-US05-02.md")
        assert not result.valid
        assert any("frontmatter" in e.message.lower() for e in result.errors)

    def test_frontmatter_not_closed(self):
        content = "---\nid: T-AF022-US05-02\ntype: task\nstate: READY\ndependencies: []\n"
        result = validate_backlog_content_v2(content, "T-AF022-US05-02.md")
        assert not result.valid
        assert any("no cerrado" in e.message for e in result.errors)

    def test_frontmatter_empty(self):
        content = "---\n---\n\n## Objetivo\n..."
        result = validate_backlog_content_v2(content, "T-AF022-US05-02.md")
        assert not result.valid
        assert any("vacio" in e.message for e in result.errors)

    def test_frontmatter_invalid_yaml(self):
        content = "---\nid: [unclosed\nstate: READY\n---\n\n## Objetivo\n..."
        result = validate_backlog_content_v2(content, "T-AF022-US05-02.md")
        assert not result.valid
        assert any("yaml" in e.message.lower() for e in result.errors)

    def test_frontmatter_not_dict(self):
        content = "---\n- item1\n- item2\n---\n\n## Objetivo\n..."
        result = validate_backlog_content_v2(content, "T-AF022-US05-02.md")
        assert not result.valid
        assert any("diccionario" in e.message for e in result.errors)


class TestRequiredFields:
    def test_missing_id(self):
        content = VALID_TASK.replace("id: T-AF022-US05-02\n", "")
        result = validate_backlog_content_v2(content, "T-AF022-US05-02.md")
        assert not result.valid
        assert any("'id'" in e.message for e in result.errors)

    def test_missing_type(self):
        content = VALID_TASK.replace("type: task\n", "")
        result = validate_backlog_content_v2(content, "T-AF022-US05-02.md")
        assert not result.valid
        assert any("'type'" in e.message for e in result.errors)

    def test_missing_state(self):
        content = VALID_TASK.replace("state: DONE\n", "")
        result = validate_backlog_content_v2(content, "T-AF022-US05-02.md")
        assert not result.valid
        assert any("'state'" in e.message for e in result.errors)

    def test_missing_dependencies(self):
        content = VALID_TASK.replace("dependencies:\n  - T-AF022-US05-01\n  - US-AF022-06\n", "")
        result = validate_backlog_content_v2(content, "T-AF022-US05-02.md")
        assert not result.valid
        assert any("'dependencies'" in e.message for e in result.errors)

    def test_missing_epic_in_us(self):
        content = VALID_US.replace("epic: AF-022\n", "")
        result = validate_backlog_content_v2(content, "US-AF022-05.md")
        assert not result.valid
        assert any("'epic'" in e.message for e in result.errors)

    def test_missing_user_story_in_task(self):
        content = VALID_TASK.replace("user_story: US-AF022-05\n", "")
        result = validate_backlog_content_v2(content, "T-AF022-US05-02.md")
        assert not result.valid
        assert any("'user_story'" in e.message for e in result.errors)

    def test_missing_title(self):
        content = VALID_TASK.replace("title: Disparo automatico del Job de veredicto\n", "")
        result = validate_backlog_content_v2(content, "T-AF022-US05-02.md")
        assert not result.valid
        assert any("'title'" in e.message for e in result.errors)


class TestInvalidState:
    def test_invalid_state(self):
        content = VALID_TASK.replace("state: DONE", "state: COMPLETED")
        result = validate_backlog_content_v2(content, "T-AF022-US05-02.md")
        assert not result.valid
        assert any("state" in e.message.lower() for e in result.errors)

    def test_state_not_string(self):
        content = VALID_TASK.replace("state: DONE", "state: 123")
        result = validate_backlog_content_v2(content, "T-AF022-US05-02.md")
        assert not result.valid
        assert any("state" in e.message.lower() for e in result.errors)


class TestInvalidDependencies:
    def test_deps_not_list(self):
        content = VALID_TASK.replace(
            "dependencies:\n  - T-AF022-US05-01\n  - US-AF022-06",
            "dependencies: T-AF022-US05-01"
        )
        result = validate_backlog_content_v2(content, "T-AF022-US05-02.md")
        assert not result.valid
        assert any("lista" in e.message for e in result.errors)

    def test_dep_not_string(self):
        content = VALID_TASK.replace(
            "dependencies:\n  - T-AF022-US05-01\n  - US-AF022-06",
            "dependencies:\n  - 123"
        )
        result = validate_backlog_content_v2(content, "T-AF022-US05-02.md")
        assert not result.valid
        assert any("string" in e.message for e in result.errors)

    def test_dep_invalid_format(self):
        content = VALID_TASK.replace("  - US-AF022-06", "  - algo-invalido")
        result = validate_backlog_content_v2(content, "T-AF022-US05-02.md")
        assert not result.valid
        assert any("ID valido" in e.message for e in result.errors)


class TestInvalidPriority:
    def test_invalid_priority(self):
        content = VALID_TASK.replace("priority: Crítica", "priority: Urgente")
        result = validate_backlog_content_v2(content, "T-AF022-US05-02.md")
        assert not result.valid
        assert any("priority" in e.message.lower() for e in result.errors)

    def test_priority_null_is_ok(self):
        content = VALID_TASK.replace("priority: Crítica", "priority: null")
        result = validate_backlog_content_v2(content, "T-AF022-US05-02.md")
        assert result.valid, f"Errores: {result.errors}"


class TestInvalidEpicRef:
    def test_invalid_epic_format_in_task(self):
        content = VALID_TASK.replace("epic: AF-022", "epic: algo-mal")
        result = validate_backlog_content_v2(content, "T-AF022-US05-02.md")
        assert not result.valid
        assert any("'epic'" in e.message for e in result.errors)


class TestInvalidUserStoryRef:
    def test_invalid_us_format_in_task(self):
        content = VALID_TASK.replace("user_story: US-AF022-05", "user_story: AF-022")
        result = validate_backlog_content_v2(content, "T-AF022-US05-02.md")
        assert not result.valid
        assert any("'user_story'" in e.message for e in result.errors)


class TestInvalidType:
    def test_invalid_type(self):
        content = VALID_TASK.replace("type: task", "type: proyecto")
        result = validate_backlog_content_v2(content, "T-AF022-US05-02.md")
        assert not result.valid
        assert any("'type'" in e.message for e in result.errors)


class TestIdMismatch:
    def test_id_mismatches_filename(self):
        content = VALID_TASK  # id: T-AF022-US05-02
        result = validate_backlog_content_v2(content, "T-AF999-US99-99-algo.md")
        assert not result.valid
        assert any("coincide" in e.message for e in result.errors)

    def test_id_matches_filename(self):
        content = VALID_TASK
        result = validate_backlog_content_v2(content, "T-AF022-US05-02-disparo.md")
        assert result.valid, f"Errores: {result.errors}"


class TestPriorityOptionalForEpic:
    def test_epic_without_priority(self):
        content = VALID_EPIC  # no priority field
        result = validate_backlog_content_v2(content, "AF-022.md")
        assert result.valid, f"Errores: {result.errors}"


class TestInvalidFase:
    def test_fase_fuera_del_conjunto_es_invalido(self):
        content = VALID_US.replace("fase: Fase 0.9", "fase: Fase 0.1")
        result = validate_backlog_content_v2(content, "US-AF022-05.md")
        assert not result.valid
        assert any("fase" in e.message.lower() for e in result.errors)
        assert any("Fase 0.9" in e.message for e in result.errors)

    def test_fase_not_string_is_invalid(self):
        content = VALID_US.replace("fase: Fase 0.9", "fase: 123")
        result = validate_backlog_content_v2(content, "US-AF022-05.md")
        assert not result.valid
        assert any("fase" in e.message.lower() for e in result.errors)

    def test_fase_null_is_ok(self):
        content = VALID_US.replace("fase: Fase 0.9", "fase: null")
        result = validate_backlog_content_v2(content, "US-AF022-05.md")
        assert result.valid, f"Errores: {result.errors}"

    def test_fase_sin_asignar_is_ok(self):
        content = VALID_US.replace("fase: Fase 0.9", "fase: SIN_ASIGNAR")
        result = validate_backlog_content_v2(content, "US-AF022-05.md")
        assert result.valid, f"Errores: {result.errors}"

    def test_fase_vacia_es_tratada_como_sin_fase(self):
        content = VALID_US.replace("fase: Fase 0.9", "fase: ''")
        result = validate_backlog_content_v2(content, "US-AF022-05.md")
        assert result.valid, f"Errores: {result.errors}"


class TestDuplicateId:
    """T-AF008-US18-01: checker determinista de unicidad de `id` por directorio
    en `validate_backlog_file_v2` — dos ficheros `.md` con el mismo `id` en el
    mismo directorio hacen la validación FALTA (error, no warning), causal raíz
    del hallazgo "Agentic stuck"."""

    def test_duplicate_id_in_directory_is_rejected(self, tmp_path):
        # Dos ficheros con el MISMO id (T-AF022-US05-02, el de VALID_TASK)
        # pero nombres de fichero distintos en el mismo directorio.
        first = tmp_path / "T-AF022-US05-02-primero.md"
        second = tmp_path / "T-AF022-US05-02-segundo.md"
        first.write_text(VALID_TASK, encoding="utf-8")
        second.write_text(VALID_TASK, encoding="utf-8")

        result_first = validate_backlog_file_v2(first)
        result_second = validate_backlog_file_v2(second)

        assert not result_first.valid
        assert not result_second.valid
        for result in (result_first, result_second):
            assert any("duplicado" in e.message for e in result.errors)
            assert "T-AF022-US05-02" in " ".join(e.message for e in result.errors)

    def test_single_file_with_unique_id_stays_valid(self, tmp_path):
        path = tmp_path / "T-AF022-US05-02-unico.md"
        path.write_text(VALID_TASK, encoding="utf-8")
        result = validate_backlog_file_v2(path)
        assert result.valid, f"Errores: {result.errors}"

    def test_duplicates_in_other_directories_do_not_pollute(self, tmp_path):
        # El mismo id en directorios DISTINTOS no es un duplicado: el checker
        # es por directorio (cada tipo de item vive en su propio directorio).
        other_dir = tmp_path / "otro"
        other_dir.mkdir()
        unique = tmp_path / "T-AF022-US05-02-unico.md"
        unique.write_text(VALID_TASK, encoding="utf-8")
        other = other_dir / "T-AF022-US05-02-otro.md"
        other.write_text(VALID_TASK, encoding="utf-8")

        assert validate_backlog_file_v2(unique).valid
        assert validate_backlog_file_v2(other).valid

    def test_content_validator_does_not_scan_directories(self):
        # `validate_backlog_content_v2` no tiene ruta de directorio: la
        # unicidad solo se comprueba en la validación de fichero en disco.
        assert validate_backlog_content_v2(VALID_TASK, "T-AF022-US05-02.md").valid

    def test_find_duplicate_ids_in_dir_maps_id_to_paths(self, tmp_path):
        (tmp_path / "A").mkdir()
        (tmp_path / "A" / "T-AA-01.md").write_text(VALID_TASK, encoding="utf-8")
        (tmp_path / "A" / "T-AA-02.md").write_text(VALID_TASK.replace("T-AF022-US05-02", "T-AF022-US05-03"), encoding="utf-8")
        assert find_duplicate_ids_in_dir(tmp_path / "A") == {}

        (tmp_path / "A" / "T-AA-03.md").write_text(VALID_TASK, encoding="utf-8")
        dups = find_duplicate_ids_in_dir(tmp_path / "A")
        assert set(dups) == {"T-AF022-US05-02"}
        assert len(dups["T-AF022-US05-02"]) == 2

    def test_find_duplicate_ids_in_dir_ignores_non_markdown_and_missing_dir(self, tmp_path):
        assert find_duplicate_ids_in_dir(tmp_path / "no-existe") == {}
        (tmp_path / "notas.txt").write_text("---\nid: X\n---\n", encoding="utf-8")
        assert find_duplicate_ids_in_dir(tmp_path) == {}
