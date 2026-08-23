"""Tests de T-AF036-US05-01: `compute_epic_coverage`
(`atlas_forge/backlog/coverage.py`) — el detector aproximado de cobertura del
alcance v1 declarado de una Epic frente a sus User Stories/Tasks reales.

Cubre los criterios de la Task:
- Epic con sección `## Alcance v1 (mínimo)` y puntos que referencian
  ids reales -> sin huecos.
- Un punto que referencia un id inexistente -> hueco detectado.
- Fallback de texto (punto en prosa sin id) -> cubierto/sin cubrir por
  solapamiento de tokens significativos.
- Epic sin la sección -> mensaje explícito "no se puede calcular
  cobertura", nunca vacío ambiguo.
- Epic sin fichero propio -> `None` (el llamador HTTP traduce a 404)."""

from pathlib import Path

import pytest

from atlas_forge.backlog import load_backlog
from atlas_forge.backlog.coverage import compute_epic_coverage

_EPIC = (
    "---\n"
    "id: AF-999\n"
    "type: epic\n"
    "title: Epic de prueba\n"
    "state: IN_PROGRESS\n"
    "dependencies: []\n"
    "---\n\n"
    "# AF-999 · Epic de prueba\n\n"
)


def _us(us_id: str, title: str, historia: str) -> str:
    return (
        "---\n"
        f"id: {us_id}\n"
        "type: user_story\n"
        f"title: {title}\n"
        "state: TODO\n"
        "dependencies: []\n"
        "epic: AF-999\n"
        "priority: Media\n"
        "---\n\n"
        f"# {us_id} · {title}\n\n"
        "## Historia\n\n"
        f"{historia}\n\n"
        "## Criterios de aceptación\n\n"
        "1. Y.\n"
    )


def _task(task_id: str, story_id: str) -> str:
    return (
        "---\n"
        f"id: {task_id}\n"
        "type: task\n"
        "title: Task de ejemplo\n"
        "state: READY\n"
        "dependencies: []\n"
        "epic: AF-999\n"
        f"user_story: {story_id}\n"
        "priority: Media\n"
        "---\n\n"
        f"# {task_id} · Task de ejemplo\n\n"
        "## Objetivo\n\nHacer algo.\n\n"
        "## Criterios de aceptación\n\n1. Hecho.\n"
    )


def _write(tmp_path: Path, subdir: str, filename: str, content: str) -> None:
    directory = tmp_path / subdir
    directory.mkdir(parents=True, exist_ok=True)
    (directory / filename).write_text(content, encoding="utf-8")


def test_alcance_points_referencing_real_us_ids_have_no_gaps(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "epics",
        "AF-999-epic.md",
        _EPIC
        + "## Alcance v1 (mínimo)\n\n"
        + "- **US-AF999-01**: gestionar los workspaces desde la interfaz.\n"
        + "- **US-AF999-02**: lanzar y detener agentes.\n",
    )
    _write(tmp_path, "user-stories", "US-AF999-01-gestionar.md", _us("US-AF999-01", "Gestionar workspaces", "Gestionar workspaces."))
    _write(tmp_path, "user-stories", "US-AF999-02-agentes.md", _us("US-AF999-02", "Lanzar agentes", "Lanzar agentes."))

    graph = load_backlog(tmp_path)
    result = compute_epic_coverage(tmp_path, graph, "AF-999")

    assert result is not None
    assert result["approximate"] is True
    assert result["declared_alcance"] is not None
    assert len(result["points"]) == 2
    assert result["gaps"] == []
    assert "aproximada" in result["message"]


def test_alcance_point_referencing_missing_us_id_is_a_gap(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "epics",
        "AF-999-epic.md",
        _EPIC
        + "## Alcance v1 (mínimo)\n\n"
        + "- **US-AF999-01**: gestionar los workspaces desde la interfaz.\n"
        + "- **US-AF999-99**: capacidad que nadie ha aterrizado todavia.\n",
    )
    _write(tmp_path, "user-stories", "US-AF999-01-gestionar.md", _us("US-AF999-01", "Gestionar workspaces", "Gestionar workspaces."))

    graph = load_backlog(tmp_path)
    result = compute_epic_coverage(tmp_path, graph, "AF-999")

    assert result is not None
    assert len(result["points"]) == 2
    assert len(result["gaps"]) == 1
    assert result["gaps"][0].startswith("US-AF999-99")
    # El punto cubierto (por id real) no aparece en huecos.
    assert not any(g.startswith("US-AF999-01") for g in result["gaps"])


def test_text_fallback_marks_prose_point_covered_by_token_overlap(tmp_path: Path) -> None:
    # Un punto en prosa SIN id que sí está cubierto por el objetivo de una
    # US real (solapamiento de tokens significativos >= 60%).
    _write(
        tmp_path,
        "epics",
        "AF-999-epic.md",
        _EPIC
        + "## Alcance v1 (mínimo)\n\n"
        + "- Gestionar los workspaces desde la interfaz.\n",
    )
    _write(tmp_path, "user-stories", "US-AF999-01-gestionar.md", _us("US-AF999-01", "Gestionar workspaces", "Gestionar workspaces desde la interfaz web."))

    graph = load_backlog(tmp_path)
    result = compute_epic_coverage(tmp_path, graph, "AF-999")

    assert result is not None
    assert result["gaps"] == []


def test_text_fallback_marks_uncovered_prose_point_as_gap(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "epics",
        "AF-999-epic.md",
        _EPIC
        + "## Alcance v1 (mínimo)\n\n"
        + "- Indexar el conocimiento con scribe.\n",
    )
    _write(tmp_path, "user-stories", "US-AF999-01-gestionar.md", _us("US-AF999-01", "Gestionar workspaces", "Gestionar workspaces."))

    graph = load_backlog(tmp_path)
    result = compute_epic_coverage(tmp_path, graph, "AF-999")

    assert result is not None
    assert len(result["gaps"]) == 1
    assert result["gaps"][0] == "Indexar el conocimiento con scribe."


def test_task_of_a_user_story_counts_as_coverage_candidate(tmp_path: Path) -> None:
    # Un punto en prosa cubierto por el objetivo de una TASK real (no de la
    # US) también debe contar como cubierto — la Task es un item real de la
    # Epic (pertenece via `user_story`).
    _write(
        tmp_path,
        "epics",
        "AF-999-epic.md",
        _EPIC
        + "## Alcance v1 (mínimo)\n\n"
        + "- Gestionar los workspaces desde la interfaz.\n",
    )
    _write(tmp_path, "user-stories", "US-AF999-01-gestionar.md", _us("US-AF999-01", "Otra historia", "Otra historia sin relacion."))
    _write(tmp_path, "tasks", "T-AF999-US01-01-gestionar.md", _task("T-AF999-US01-01", "US-AF999-01").replace("Hacer algo.", "Gestionar workspaces desde la interfaz."))

    graph = load_backlog(tmp_path)
    result = compute_epic_coverage(tmp_path, graph, "AF-999")

    assert result is not None
    assert result["gaps"] == []


def test_epic_without_alcance_section_returns_explicit_message(tmp_path: Path) -> None:
    _write(tmp_path, "epics", "AF-999-epic.md", _EPIC)
    _write(tmp_path, "user-stories", "US-AF999-01-gestionar.md", _us("US-AF999-01", "Gestionar workspaces", "Gestionar workspaces."))

    graph = load_backlog(tmp_path)
    result = compute_epic_coverage(tmp_path, graph, "AF-999")

    assert result is not None
    assert result["declared_alcance"] is None
    assert "no se puede calcular cobertura" in result["message"]
    assert result["gaps"] == []


def test_epic_without_own_file_returns_none(tmp_path: Path) -> None:
    # No hay ningún fichero `epics/AF-999-*.md` (la Epic solo existe por
    # referencia de sus US) -> None, que el llamador HTTP traduce a 404.
    _write(tmp_path, "user-stories", "US-AF999-01-gestionar.md", _us("US-AF999-01", "Gestionar workspaces", "Gestionar workspaces."))

    graph = load_backlog(tmp_path)
    assert compute_epic_coverage(tmp_path, graph, "AF-999") is None


def test_alcance_header_with_suffix_is_still_matched(tmp_path: Path) -> None:
    # El backlog real mezcla sufijos en el encabezado
    # ("## Alcance v1 (mínimo) — Dispatcher manual"); el detector casa por
    # prefijo "Alcance v1".
    _write(
        tmp_path,
        "epics",
        "AF-999-epic.md",
        _EPIC
        + "## Alcance v1 (mínimo) — sin dependencias\n\n"
        + "- **US-AF999-01**: gestionar los workspaces desde la interfaz.\n",
    )
    _write(tmp_path, "user-stories", "US-AF999-01-gestionar.md", _us("US-AF999-01", "Gestionar workspaces", "Gestionar workspaces."))

    graph = load_backlog(tmp_path)
    result = compute_epic_coverage(tmp_path, graph, "AF-999")

    assert result is not None
    assert result["declared_alcance"] is not None
    assert result["gaps"] == []
