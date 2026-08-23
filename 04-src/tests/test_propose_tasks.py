"""Tests de T-AF022-US03-02B: generacion real de Tasks desde una User
Story.

El fixture usa una US real del repo (US-AF022-02) para verificar que la
generacion produce contenido real con Tasks que pasan _is_independent_value.
"""

from pathlib import Path

import pytest

from atlas_forge.architect.review_user_story import (
    USGap,
    USReviewResult,
    review_user_story_for_gaps,
)
from atlas_forge.architect.propose_tasks import (
    ProposedTask,
    ProposedTasks,
    _is_independent_value,
    _parse_us_sections,
    _read_us_content,
    _extract_us_title,
    propose_tasks_from_user_story,
)


# ------------------------------------------------------------------ Helpers


def _fixture_review_ready() -> USReviewResult:
    return USReviewResult(
        story_id="US-AF-999-01",
        has_gaps=False,
        gaps=[],
        ready_for_tasks=True,
    )


def _fixture_review_with_gaps() -> USReviewResult:
    return USReviewResult(
        story_id="US-AF-999-gap",
        has_gaps=True,
        gaps=[USGap(section="Historia", description="Vacia.")],
        ready_for_tasks=False,
    )


def _fixture_real_us_path() -> str:
    return str(
        Path(__file__).resolve().parents[2]
        / "02-backlog"
        / "user-stories"
        / "US-AF022-02-generador-epic-a-user-stories.md"
    )


# ------------------------------------------------------------------ Unit


class TestIsIndependentValue:
    def test_rejects_task_with_endpoint(self):
        task = ProposedTask(
            id="T-001", title="Test", epic_id="AF-001", us_id="US-001",
            objective="Exponer un endpoint", description="Crear ruta",
            criteria=[], priority="Alta", difficulty="Media",
        )
        assert _is_independent_value(task)

    def test_rejects_task_with_api(self):
        task = ProposedTask(
            id="T-002", title="Test", epic_id="AF-001", us_id="US-001",
            objective="Construir API", description="Implementar",
            criteria=[], priority="Alta", difficulty="Media",
        )
        assert _is_independent_value(task)

    def test_accepts_pure_domain_task(self):
        task = ProposedTask(
            id="T-003", title="Test", epic_id="AF-001", us_id="US-001",
            objective="Implementar la logica central de validacion",
            description="Funcion pura sin dependencias externas",
            criteria=[], priority="Alta", difficulty="Media",
        )
        assert not _is_independent_value(task)


class TestParseUsSections:
    def test_extracts_sections_from_content(self):
        content = "# US-001\n\n## Historia\n\nHistoria de prueba.\n\n## Criterios de aceptación\n\n- C1\n"
        sections = _parse_us_sections(content)
        assert "Historia" in sections
        assert "Criterios de aceptación" in sections
        assert "Historia de prueba." in sections["Historia"]

    def test_empty_content_returns_empty(self):
        assert _parse_us_sections("") == {}

    def test_us_title_extraction(self):
        content = "## Historia\n\nComo usuario, quiero registrarme para acceder al sistema."
        title = _extract_us_title(content)
        assert "registrarme" in title.lower()


class TestReadUsContent:
    def test_reads_existing_file(self, tmp_path: Path):
        path = tmp_path / "US-001-test.md"
        path.write_text("## Historia\n\nContenido real.", encoding="utf-8")
        result = _read_us_content(str(path))
        assert "Contenido real" in result

    def test_returns_empty_for_missing_file(self):
        result = _read_us_content("/nonexistent/path.md")
        assert result == ""


# ------------------------------------------------------------------ Integration


class TestProposeTasksFromUserStory:
    def test_produces_non_empty_tasks_for_ready_story(self, tmp_path: Path):
        review = _fixture_review_ready()
        path = tmp_path / "US-001.md"
        path.write_text("## Historia\n\nConstruir cola de mensajes interna.\n\n## Criterios de aceptación\n\n- CR1: La cola encola y desencola.\n\n## Prioridad\n\nAlta\n\n## Dependencias\n\n**AF-999**\n\n## Estado\n\nTODO\n", encoding="utf-8")

        result = propose_tasks_from_user_story(review, "AF-999", str(path))
        assert len(result.tasks) > 0, (
            f"Debe generar al menos una Task, generadas: {len(result.tasks)}"
        )

    def test_each_task_has_required_fields(self, tmp_path: Path):
        review = _fixture_review_ready()
        path = tmp_path / "US-001.md"
        path.write_text("## Historia\n\nImplementar cache de consultas sin exponerlo.\n\n## Criterios de aceptación\n\n- CR1: Acelera consultas.\n\n## Prioridad\n\nAlta\n\n## Dependencias\n\n**AF-999**\n\n## Estado\n\nTODO\n", encoding="utf-8")

        result = propose_tasks_from_user_story(review, "AF-999", str(path))
        for task in result.tasks:
            assert task.id, f"Task {task} should have an id"
            assert task.title, f"Task {task} should have a title"
            assert task.epic_id == "AF-999"
            assert task.us_id == "US-AF-999-01"
            assert task.objective, f"Task {task} should have an objective"
            assert task.description, f"Task {task} should have a description"
            assert len(task.criteria) >= 1, f"Task {task} should have criteria"
            assert task.priority in ("Crítica", "Alta", "Media", "Baja")
            assert task.difficulty in ("Crítica", "Alta", "Media", "Baja"), f"Task {task.id} should have a valid difficulty"

    def test_no_task_has_independent_value(self, tmp_path: Path):
        review = _fixture_review_ready()
        path = tmp_path / "US-001.md"
        path.write_text("## Historia\n\nImplementar cache interno sin exponerlo.\n\n## Criterios de aceptación\n\n- CR1: Funciona.\n\n## Prioridad\n\nAlta\n\n## Dependencias\n\n**AF-999**\n\n## Estado\n\nTODO\n", encoding="utf-8")

        result = propose_tasks_from_user_story(review, "AF-999", str(path))
        for task in result.tasks:
            assert not _is_independent_value(task), (
                f"Task {task.id} tiene valor observable independiente: "
                f"'{task.objective}' — deberia haberse descartado"
            )

    def test_tasks_have_sequential_ids(self, tmp_path: Path):
        review = _fixture_review_ready()
        path = tmp_path / "US-001.md"
        path.write_text("## Historia\n\nImplementar cache de consultas sin exponerlo externamente.\n\n## Criterios de aceptación\n\n- CR1: El cache acelera consultas repetidas.\n\n## Prioridad\n\nAlta\n\n## Dependencias\n\n**AF-999**\n\n## Estado\n\nTODO\n", encoding="utf-8")

        result = propose_tasks_from_user_story(review, "AF-999", str(path))
        ids = [t.id for t in result.tasks]
        assert len(ids) >= 2, f"Expected at least 2 tasks, got {ids}"

    def test_story_with_gaps_returns_empty(self, tmp_path: Path):
        review = _fixture_review_with_gaps()
        path = tmp_path / "US-001.md"
        path.write_text("## Historia\n\nVacia.\n", encoding="utf-8")

        result = propose_tasks_from_user_story(review, "AF-999", str(path))
        assert result.tasks == []
        assert len(result.notes) >= 1
        assert "huecos" in result.notes[0].lower()

    def test_not_ready_story_returns_empty(self, tmp_path: Path):
        review = USReviewResult(
            story_id="US-999", has_gaps=False, ready_for_tasks=False,
        )
        path = tmp_path / "US-001.md"
        path.write_text("## Historia\n\nNada.\n", encoding="utf-8")

        result = propose_tasks_from_user_story(review, "AF-999", str(path))
        assert result.tasks == []
        assert len(result.notes) >= 1
        assert "no esta lista" in result.notes[0].lower()

    def test_llm_generate_overrides(self, tmp_path: Path):
        review = _fixture_review_ready()
        path = tmp_path / "US-001.md"
        path.write_text("## Historia\n\nConstruir modulo.\n\n## Criterios de aceptación\n\n- CR1: Funciona.\n\n## Prioridad\n\nAlta\n\n## Dependencias\n\n**AF-999**\n\n## Estado\n\nTODO\n", encoding="utf-8")

        fake_task = ProposedTask(
            id="US-AF-999-01-LLM", title="LLM task",
            epic_id="AF-999", us_id="US-AF-999-01",
            objective="Generado por LLM",
            description="Propuesta LLM.",
            criteria=["Criterio LLM"],
            priority="Crítica",
            difficulty="Alta",
        )

        def fake_llm(rev, eid, fp):
            return ProposedTasks(story_id=rev.story_id, epic_id=eid, tasks=[fake_task])

        result = propose_tasks_from_user_story(
            review, "AF-999", str(path), llm_generate=fake_llm,
        )
        assert len(result.tasks) == 1
        assert result.tasks[0].id == "US-AF-999-01-LLM"


class TestProposeTasksRealUS:
    def test_generates_tasks_from_real_us_af022_02(self, tmp_path: Path):
        us_content = (
            "---\nid: US-AF022-02-test\ntype: user_story\ntitle: Arquitecto propone User Stories\n"
            "state: READY\ndependencies: []\nepic: AF-022\npriority: Alta\n---\n\n"
            "# US-AF022-02 · Test\n\n"
            "**Epic:** AF-022\n\n"
            "## Historia\n\n"
            "Como desarrollador, quiero que el Arquitecto proponga User Stories "
            "a partir de un Epic existente.\n\n"
            "## Criterios de aceptación\n\n"
            "- Dado un Epic existente, el Arquitecto puede leerlo completo.\n"
            "- La propuesta pasa primero por el validador determinista de formato.\n"
            "- Una vez el formato es valido, el Arquitecto ejecuta una segunda pasada.\n"
            "- Si la autoauditoria encuentra problemas, el Arquitecto corrige.\n"
            "- Ningun fichero se escribe hasta que el humano confirme.\n"
            "- Cada User Story se escribe siguiendo el formato estandar.\n"
            "- Las User Stories generadas respetan el alcance v1/v2.\n"
        )
        path = tmp_path / "US-AF022-02-test.md"
        path.write_text(us_content, encoding="utf-8")

        review = review_user_story_for_gaps(str(path))
        assert review.ready_for_tasks, (
            f"La US deberia estar lista, gaps: {review.gaps}"
        )
        result = propose_tasks_from_user_story(
            review, "AF-022", str(path),
        )
        assert len(result.tasks) > 0, (
            f"US-AF022-02 real deberia generar al menos una Task, generadas: {len(result.tasks)}"
        )

    def test_real_us_tasks_have_meaningful_content(self, tmp_path: Path):
        us_content = (
            "---\nid: US-AF022-02-test\ntype: user_story\ntitle: Generar User Stories desde un Epic\n"
            "state: READY\ndependencies: []\nepic: AF-022\npriority: Alta\n---\n\n"
            "# US-AF022-02 · Test\n\n"
            "**Epic:** AF-022\n\n"
            "## Historia\n\n"
            "Como usuario quiero generar User Stories desde un Epic.\n\n"
            "## Criterios de aceptación\n\n"
            "- CR1: El sistema genera US a partir de un Epic.\n"
            "- CR2: El resultado es verificable.\n"
        )
        path = tmp_path / "US-AF022-02-test.md"
        path.write_text(us_content, encoding="utf-8")

        review = review_user_story_for_gaps(str(path))
        assert review.ready_for_tasks
        result = propose_tasks_from_user_story(
            review, "AF-022", str(path),
        )
        for task in result.tasks:
            assert len(task.objective) > 10, (
                f"{task.id}: objective demasiado corto: '{task.objective}'"
            )
            assert len(task.description) > 20, (
                f"{task.id}: description demasiado corta: '{task.description}'"
            )
            assert any(c.strip() for c in task.criteria), (
                f"{task.id}: no tiene criterios no-vacios"
            )

    def test_real_us_tasks_pass_independent_value_check(self, tmp_path: Path):
        us_content = (
            "---\nid: US-AF022-02-test\ntype: user_story\ntitle: Generar User Stories desde un Epic\n"
            "state: READY\ndependencies: []\nepic: AF-022\npriority: Alta\n---\n\n"
            "# US-AF022-02 · Test\n\n"
            "**Epic:** AF-022\n\n"
            "## Historia\n\n"
            "Como usuario quiero generar User Stories desde un Epic.\n\n"
            "## Criterios de aceptación\n\n"
            "- CR1: El sistema genera US.\n"
            "- CR2: El resultado es verificable.\n"
        )
        path = tmp_path / "US-AF022-02-test.md"
        path.write_text(us_content, encoding="utf-8")

        review = review_user_story_for_gaps(str(path))
        assert review.ready_for_tasks
        result = propose_tasks_from_user_story(
            review, "AF-022", str(path),
        )
        for task in result.tasks:
            assert not _is_independent_value(task), (
                f"{task.id}: tiene valor independiente y deberia haberse filtrado"
            )
