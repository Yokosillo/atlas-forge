"""Tests de `POST /backlog/us/{us_id}/propose-tasks` (T-FB008-US15-02):
el endpoint solo acepta ejecutarse sobre una User Story en `EN_DISEÑO` —
antes de esta Task no comprobaba en absoluto el estado real de la US,
pudiendo generar Tasks duplicadas o incoherentes sobre una Story ya
desgranada."""

from pathlib import Path

from fastapi.testclient import TestClient

import brain.api.routes as routes_module
from brain.api import create_app


def _active_project(tmp_path: Path, monkeypatch) -> Path:
    project_path = tmp_path / "workspace" / "project-a"
    project_path.mkdir(parents=True, exist_ok=True)

    from brain.models import Project

    project = Project(
        id=str(project_path),
        name="project-a",
        path=str(project_path),
        repository="",
        workspace_id="ws-test",
    )
    monkeypatch.setattr(routes_module, "get_active_project", lambda **_kwargs: project)
    return project_path


def _write_us_yaml(us_dir: Path, us_id: str, *, epic: str, state: str, priority: str = "Alta") -> None:
    us_dir.mkdir(parents=True, exist_ok=True)
    (us_dir / f"{us_id}-titulo.md").write_text(
        "---\n"
        f"id: {us_id}\n"
        "type: user_story\n"
        f"title: {us_id} título de prueba\n"
        f"state: {state}\n"
        "dependencies: []\n"
        f"epic: {epic}\n"
        f"priority: {priority}\n"
        "---\n\n"
        f"# {us_id} · título de prueba\n\n"
        "## Historia\n\nConstruir cola de mensajes interna.\n\n"
        "## Criterios de aceptación\n\n- CR1: La cola encola y desencola.\n",
        encoding="utf-8",
    )


def test_post_propose_tasks_returns_404_for_unknown_story(tmp_path, monkeypatch) -> None:
    _active_project(tmp_path, monkeypatch)
    client = TestClient(create_app())

    response = client.post("/backlog/us/US-FB999-99/propose-tasks")

    assert response.status_code == 404


def test_post_propose_tasks_rejects_story_not_in_en_diseno(tmp_path, monkeypatch) -> None:
    """Criterio de aceptación 3: rechaza (400) una User Story fuera de
    `EN_DISEÑO` — verificado con una llamada directa al endpoint sin
    pasar por la web, sobre una US real en `NO_TASKS`."""
    project_path = _active_project(tmp_path, monkeypatch)
    backlog = project_path / "02-backlog"
    _write_us_yaml(backlog / "user-stories", "US-FB999-01", epic="FB-999", state="NO_TASKS")
    client = TestClient(create_app())

    response = client.post("/backlog/us/US-FB999-01/propose-tasks")

    assert response.status_code == 400
    assert "EN_DISEÑO" in response.json()["detail"]


def test_post_propose_tasks_rejects_story_already_in_todo(tmp_path, monkeypatch) -> None:
    """Mismo criterio, caso real relevante: una US ya desgranada
    (`TODO`) no debe permitir generar Tasks duplicadas."""
    project_path = _active_project(tmp_path, monkeypatch)
    backlog = project_path / "02-backlog"
    _write_us_yaml(backlog / "user-stories", "US-FB999-02", epic="FB-999", state="TO_DO")
    client = TestClient(create_app())

    response = client.post("/backlog/us/US-FB999-02/propose-tasks")

    assert response.status_code == 400
    assert "EN_DISEÑO" in response.json()["detail"]


def test_post_propose_tasks_accepts_story_in_en_diseno_and_lands_tasks(tmp_path, monkeypatch) -> None:
    """Camino feliz: una US real en `EN_DISEÑO` con contenido suficiente
    genera Tasks reales — mismo contrato que
    `run_us_landing_dispatch_cycle` (T-FB008-US15-02), pero ejercitado
    vía el endpoint HTTP directo."""
    project_path = _active_project(tmp_path, monkeypatch)
    backlog = project_path / "02-backlog"
    (backlog / "tasks").mkdir(parents=True)
    _write_us_yaml(backlog / "user-stories", "US-FB999-03", epic="FB-999", state="EN_DISEÑO")
    client = TestClient(create_app())

    response = client.post("/backlog/us/US-FB999-03/propose-tasks")

    assert response.status_code == 200
    body = response.json()
    assert len(body.get("tasks", [])) > 0

    # Criterio de aceptación 4: al completarse con éxito, la US
    # transiciona automáticamente de EN_DISEÑO a TODO.
    us_files = list((backlog / "user-stories").glob("US-FB999-03*.md"))
    assert len(us_files) == 1
    assert "state: TO_DO" in us_files[0].read_text(encoding="utf-8")
