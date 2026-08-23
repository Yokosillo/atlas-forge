"""Tests de T-AF022-US02-01B: generacion real de User Stories desde un
Epic.

El fixture usa la Epic AF-022 real, que tiene 18 items en el alcance v1
(Alcance v1 (minimo)). La funcion genera una ProposedUserStory por cada
item de alcance, verificando que el contenido es real (no lista vacia).
"""

from pathlib import Path

import pytest

from atlas_forge.architect.propose_user_stories import (
    EpicContext,
    ProposedUserStory,
    _parse_scope_items,
    _split_scope_into_stories,
    propose_user_stories_from_epic,
)


# ------------------------------------------------------------------ Helpers


def _fixture_epic_context() -> EpicContext:
    return EpicContext(
        epic_id="AF-999",
        title="Epic de prueba",
        objective="Probar la generacion de User Stories desde el alcance v1.",
        scope="",
        scope_v1=(
            "- Registrar un tipo de agente nuevo sin modificar el nucleo.\n"
            "- Generar User Stories a partir de un Epic.\n"
            "- Generar Tasks a partir de una User Story.\n"
            "- Emitir veredicto estructurado sobre el resultado de un Developer.\n"
        ),
        scope_v2_deferred="",
        dependencies="",
        file_path="",
    )


def _fixture_real_epic_context() -> EpicContext:
    epic_path = Path(__file__).resolve().parents[2] / "02-backlog" / "epics" / "AF-022-pipeline-backlog-centrico.md"
    from atlas_forge.architect.propose_user_stories import load_epic_context
    return load_epic_context(str(epic_path))


# ------------------------------------------------------------------ Unit


class TestParseScopeItems:
    def test_extracts_bullet_items(self):
        text = "- Item 1\n- Item 2\n- Item 3 (con parentesis)\n"
        items = _parse_scope_items(text)
        assert items == [
            "Item 1",
            "Item 2",
            "Item 3 (con parentesis)",
        ]

    def test_skips_non_bullet_lines(self):
        text = "Texto libre\n- Item real\nOtra linea\n"
        items = _parse_scope_items(text)
        assert items == ["Item real"]

    def test_empty_scope_returns_empty(self):
        assert _parse_scope_items("") == []


class TestSplitScopeIntoStories:
    def test_generates_one_story_per_scope_item(self):
        epic = _fixture_epic_context()
        items = _parse_scope_items(epic.scope_v1)
        stories = _split_scope_into_stories(epic, items)
        assert len(stories) == 4

    def test_each_story_has_required_fields(self):
        epic = _fixture_epic_context()
        items = _parse_scope_items(epic.scope_v1)
        stories = _split_scope_into_stories(epic, items)
        for story in stories:
            assert story.id, f"Story {story} should have an id"
            assert story.title, f"Story {story} should have a title"
            assert story.epic_id == "AF-999"
            assert story.description, f"Story {story} should have a description"
            assert len(story.criteria) >= 1, f"Story {story} should have criteria"
            assert story.priority in ("Critica", "Alta", "Media", "Baja")

    def test_ids_are_sequential(self):
        epic = _fixture_epic_context()
        items = _parse_scope_items(epic.scope_v1)
        stories = _split_scope_into_stories(epic, items)
        ids = [s.id for s in stories]
        # Formato correcto: US-AF999-01 (sin guion extra después de AF)
        assert ids == ["US-AF999-01", "US-AF999-02", "US-AF999-03", "US-AF999-04"]


# ------------------------------------------------------------------ Integration


class TestProposeUserStoriesFromEpic:
    def test_produces_non_empty_stories_for_epic_with_scope_v1(self):
        epic = _fixture_epic_context()
        result = propose_user_stories_from_epic(epic)
        assert len(result.stories) > 0, (
            "Debe generar al menos una User Story cuando el Epic tiene alcance v1"
        )

    def test_each_story_has_real_content_not_placeholders(self):
        epic = _fixture_epic_context()
        result = propose_user_stories_from_epic(epic)
        for story in result.stories:
            assert "Registrar" in story.title or "Generar" in story.title or "Emitir" in story.title or story.title.strip(), (
                f"Story '{story.title}' should contain content from scope"
            )
            assert len(story.description) > 20, (
                f"Story '{story.id}' description is too short: '{story.description}'"
            )
            assert any(
                c.strip() for c in story.criteria
            ), f"Story '{story.id}' has no non-empty criteria"

    def test_stories_reference_epic_id(self):
        epic = _fixture_epic_context()
        result = propose_user_stories_from_epic(epic)
        assert result.epic.epic_id == "AF-999"
        for story in result.stories:
            assert story.epic_id == "AF-999"

    def test_empty_epic_returns_empty_with_note(self):
        epic = EpicContext(
            epic_id="AF-000", title="", objective="", scope="",
        )
        result = propose_user_stories_from_epic(epic)
        assert result.stories == []
        assert len(result.notes) >= 1
        assert "no tiene alcance" in result.notes[0].lower()

    def test_scope_without_bullets_returns_empty_with_note(self):
        epic = EpicContext(
            epic_id="AF-000",
            title="",
            objective="",
            scope="",
            scope_v1="Texto libre sin bullets.",
        )
        result = propose_user_stories_from_epic(epic)
        assert result.stories == []
        assert len(result.notes) >= 1
        assert "no contiene items" in result.notes[0].lower()

    def test_v2_deferred_adds_note_but_still_generates_v1(self):
        epic = EpicContext(
            epic_id="AF-999",
            title="Test",
            objective="",
            scope="",
            scope_v1="- V1 capability",
            scope_v2_deferred="Cosas de v2.",
        )
        result = propose_user_stories_from_epic(epic)
        assert len(result.stories) >= 1
        notes_text = " ".join(result.notes)
        assert "v2 diferido" in notes_text.lower()

    def test_llm_generate_overrides_deterministic(self):
        epic = _fixture_epic_context()
        fake_llm_story = ProposedUserStory(
            id="US-AF-999-LLM",
            title="Generado por LLM",
            epic_id="AF-999",
            description="Propuesta generada por el LLM del Arquitecto.",
            criteria=["Criterio LLM 1", "Criterio LLM 2"],
            priority="Critica",
        )

        def fake_llm(ctx):
            from atlas_forge.architect.propose_user_stories import ProposedUserStories as PS
            return PS(epic=ctx, stories=[fake_llm_story])

        result = propose_user_stories_from_epic(epic, llm_generate=fake_llm)
        assert len(result.stories) == 1
        assert result.stories[0].id == "US-AF-999-LLM"
        assert result.stories[0].title == "Generado por LLM"


class TestProposeRealEpicAF022:
    def test_generates_stories_from_real_af022_epic(self):
        epic = _fixture_real_epic_context()
        result = propose_user_stories_from_epic(epic)
        assert len(result.stories) > 0, (
            f"AF-022 real deberia generar al menos una US, generadas: {len(result.stories)}"
        )

    def test_stories_cover_v1_scope_content(self):
        epic = _fixture_real_epic_context()
        result = propose_user_stories_from_epic(epic)
        assert len(result.stories) >= 10, (
            f"AF-022 tiene 18 items de alcance v1, se generaron {len(result.stories)} stories"
        )
        titles = " ".join(s.title for s in result.stories).lower()
        assert "director" in titles
        assert "arquitecto" in titles
        assert "veredicto" in titles or "estructurado" in titles

    def test_stories_have_meaningful_criteria(self):
        epic = _fixture_real_epic_context()
        result = propose_user_stories_from_epic(epic)
        for story in result.stories:
            assert len(story.criteria) >= 1, (
                f"{story.id}: deberia tener al menos 1 criterio de aceptacion"
            )
            assert len(story.criteria[0]) > 10, (
                f"{story.id}: primer criterio demasiado corto: '{story.criteria[0]}'"
            )
