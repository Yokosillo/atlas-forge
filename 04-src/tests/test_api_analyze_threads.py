"""Tests de `POST /backlog/epic/{epic_id}/analyze-threads` (T-FB026-US04-01,
corrección T-FB026-US02-02B): endpoint determinista de análisis de hilos de
desarrollo, sin Job al Arquitecto. Ningún test cubría este endpoint antes de
la corrección de la auditoría de cierre de Fase 1.0 (2026-08-06)."""

from pathlib import Path

from fastapi.testclient import TestClient

import brain.api.routes as routes_module
from brain.api import create_app


def _active_project(tmp_path: Path, monkeypatch) -> Path:
    project_path = tmp_path / "workspace" / "project-a"
    project_path.mkdir(parents=True, exist_ok=True)

    from brain.models import Project

    project = Project(
        id=str(project_path), name="project-a", path=str(project_path),
        repository="", workspace_id="ws-test",
    )
    monkeypatch.setattr(routes_module, "get_active_project", lambda **_kwargs: project)
    return project_path


def _write_epic(path: Path, epic_id: str) -> None:
    path.write_text(
        f"# {epic_id} Epic de prueba\n\n"
        f"## Objetivo\n\nObjetivo de prueba.\n\n"
        f"## Dependencias\n\nNinguna.\n\n"
        f"## Estado\n\nTODO\n",
        encoding="utf-8",
    )


def _write_task(path: Path, task_id: str, *, epic: str, dependencies: str = "Ninguna.") -> None:
    path.write_text(
        f"# {task_id}\n"
        f"**Epic:** {epic}\n\n"
        f"## Objetivo\n\nObjetivo de prueba.\n\n"
        f"## Criterios de aceptación\n\n- Criterio uno.\n\n"
        f"## Prioridad\n\nAlta.\n\n"
        f"## Dependencias\n\n{dependencies}\n\n"
        f"## Estado\n\nTODO\n",
        encoding="utf-8",
    )


def _seed_backlog_with_two_threads(project_path: Path) -> None:
    """Dos Tasks independientes (raíces distintas): deben quedar en dos
    hilos distintos, sin cruces."""
    backlog = project_path / "02-backlog"
    (backlog / "epics").mkdir(parents=True)
    (backlog / "tasks").mkdir(parents=True)

    _write_epic(backlog / "epics" / "FB-900-test.md", "FB-900")
    _write_task(backlog / "tasks" / "T-FB900-US01-01.md", "T-FB900-US01-01", epic="FB-900")
    _write_task(backlog / "tasks" / "T-FB900-US02-01.md", "T-FB900-US02-01", epic="FB-900")


def test_analyze_threads_returns_404_for_unknown_epic(tmp_path: Path, monkeypatch) -> None:
    project_path = _active_project(tmp_path, monkeypatch)
    (project_path / "02-backlog" / "epics").mkdir(parents=True)
    client = TestClient(create_app())

    response = client.post("/backlog/epic/FB-999/analyze-threads")

    assert response.status_code == 404


def test_analyze_threads_uses_default_num_agents_when_not_specified(
    tmp_path: Path, monkeypatch
) -> None:
    """Criterio de aceptación: `num_agents` tiene un default razonable
    (2) si no se especifica — nunca un error por parámetro ausente."""
    project_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog_with_two_threads(project_path)
    client = TestClient(create_app())

    response = client.post("/backlog/epic/FB-900/analyze-threads")

    assert response.status_code == 200
    body = response.json()
    assert body["num_agents"] == 2


def test_analyze_threads_accepts_configurable_num_agents(
    tmp_path: Path, monkeypatch
) -> None:
    """Criterio de aceptación (corrección T-FB026-US02-02B): N es un
    parámetro de entrada configurable, nunca fijo a 2."""
    project_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog_with_two_threads(project_path)
    client = TestClient(create_app())

    response = client.post("/backlog/epic/FB-900/analyze-threads?num_agents=5")

    assert response.status_code == 200
    body = response.json()
    assert body["num_agents"] == 5


def test_analyze_threads_rejects_zero_agents(tmp_path: Path, monkeypatch) -> None:
    project_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog_with_two_threads(project_path)
    client = TestClient(create_app())

    response = client.post("/backlog/epic/FB-900/analyze-threads?num_agents=0")

    assert response.status_code == 400
