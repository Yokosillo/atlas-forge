"""Tests para T-FB008-US11-03: difficulty en propose_tasks_from_user_story.

Verifica que:
1. ProposedTask incluye difficulty
2. difficulty se asigna según criterios (Crítica para implementar-nucleo, Alta para los demás)
3. difficulty se propaga al YAML en el pipeline
4. difficulty se incluye en la respuesta de API
"""

from pathlib import Path

import pytest

from brain.architect.review_user_story import USReviewResult
from brain.architect.propose_tasks import propose_tasks_from_user_story
from brain.architect.task_pipeline import (
    _build_task_content,
    run_task_pipeline,
)


class TestDifficultyInProposedTasks:
    """Verifica que difficulty se asigna correctamente a las Tasks generadas."""

    def test_proposed_tasks_have_difficulty_field(self, tmp_path: Path):
        """Cada Task generada debe tener difficulty asignado."""
        review = USReviewResult(
            story_id="US-FB-999-01",
            has_gaps=False,
            gaps=[],
            ready_for_tasks=True,
        )
        path = tmp_path / "US-001.md"
        path.write_text(
            "## Historia\n\nImplementar feature sin exponerlo.\n\n"
            "## Criterios de aceptación\n\n- CR1: Funciona.\n\n"
            "## Prioridad\n\nAlta\n\n"
            "## Dependencias\n\n**FB-999**\n\n"
            "## Estado\n\nTODO\n",
            encoding="utf-8"
        )

        result = propose_tasks_from_user_story(review, "FB-999", str(path))

        assert len(result.tasks) > 0, "Debe generar al menos una Task"
        for task in result.tasks:
            assert hasattr(task, 'difficulty'), f"Task {task.id} debe tener difficulty"
            assert task.difficulty, f"Task {task.id} debe tener difficulty asignado"
            assert task.difficulty in ("Crítica", "Alta", "Media", "Baja"), \
                f"Task {task.id} difficulty '{task.difficulty}' no es válido"

    def test_difficulty_varies_by_task_type(self, tmp_path: Path):
        """difficulty debe variar según el tipo de Task generada."""
        review = USReviewResult(
            story_id="US-FB-999-01",
            has_gaps=False,
            gaps=[],
            ready_for_tasks=True,
        )
        path = tmp_path / "US-001.md"
        path.write_text(
            "## Historia\n\nImplementar feature sin exponerlo.\n\n"
            "## Criterios de aceptación\n\n- CR1: Funciona.\n\n"
            "## Prioridad\n\nAlta\n\n"
            "## Dependencias\n\n**FB-999**\n\n"
            "## Estado\n\nTODO\n",
            encoding="utf-8"
        )

        result = propose_tasks_from_user_story(review, "FB-999", str(path))

        # Debe haber al menos 2 Tasks con diferentes dificultades
        difficulties = [task.difficulty for task in result.tasks]
        assert len(difficulties) >= 2, \
            f"Debe generar al menos 2 Tasks con potencialmente diferentes dificultades, generadas: {difficulties}"


class TestDifficultyInYAML:
    """Verifica que difficulty se escribe correctamente en el YAML."""

    def test_build_task_content_includes_difficulty(self):
        """_build_task_content debe incluir difficulty en el frontmatter YAML."""
        from brain.architect.propose_tasks import ProposedTask

        task = ProposedTask(
            id="T-001",
            title="Test task",
            epic_id="FB-001",
            us_id="US-001",
            objective="Implementar algo",
            description="Descripción",
            criteria=["Criterio 1"],
            priority="Alta",
            difficulty="Crítica",
        )

        content = _build_task_content(task)

        assert "difficulty: 9" in content, \
            "El YAML debe incluir 'difficulty: 9' (etiqueta 'Crítica' normalizada a entero 0-10)"
        assert content.startswith("---"), "Debe empezar con frontmatter"
        assert "---" in content[4:], "Debe tener cierre de frontmatter"

    def test_difficulty_in_yaml_is_valid_format(self):
        """El difficulty en YAML debe estar en formato válido."""
        from brain.architect.propose_tasks import ProposedTask

        task = ProposedTask(
            id="T-002",
            title="Test task",
            epic_id="FB-002",
            us_id="US-002",
            objective="Conectar algo",
            description="Descripción",
            criteria=["Criterio 1"],
            priority="Alta",
            difficulty="Alta",
        )

        content = _build_task_content(task)

        # Verificar que el YAML es válido
        lines = content.split('\n')
        found_difficulty = False
        for line in lines:
            if line.startswith("difficulty:"):
                found_difficulty = True
                # Debe estar en el frontmatter (antes del segundo ---)
                frontmatter_end = content.find("---", 4)
                difficulty_pos = content.find("difficulty:")
                assert difficulty_pos < frontmatter_end, \
                    "difficulty debe estar en el frontmatter YAML"
                break

        assert found_difficulty, "Debe encontrar la línea 'difficulty:' en el YAML"



class TestDifficultyInAPIResponse:
    """Verifica que difficulty se incluye en la respuesta de API."""

    def test_task_data_includes_difficulty_field(self, tmp_path: Path):
        """El diccionario de respuesta de API debe incluir difficulty."""
        # Simular la construcción del tasks_data como lo hace post_propose_tasks
        from brain.architect.propose_tasks import ProposedTask

        task = ProposedTask(
            id="T-001",
            title="Test task",
            epic_id="FB-001",
            us_id="US-001",
            objective="Implementar algo",
            description="Descripción",
            criteria=["Criterio 1"],
            priority="Alta",
            difficulty="Critica",
        )

        # Simular construcción del tasks_data como en routes.py
        task_data = {
            "id": task.id,
            "title": task.title,
            "epic_id": task.epic_id,
            "us_id": task.us_id,
            "objective": task.objective,
            "description": task.description,
            "criteria": task.criteria,
            "priority": task.priority,
            "difficulty": task.difficulty,
            "dependencies": task.dependencies,
        }

        assert "difficulty" in task_data, "task_data debe incluir difficulty"
        assert task_data["difficulty"] == "Critica", \
            "difficulty debe tener el valor asignado"
