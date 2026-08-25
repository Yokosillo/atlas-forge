"""Tests del endpoint `POST /backlog/us/{us_id}/from-description-task`
(T-AF036-US20-03, US-AF036-20, criterio 4): encola la petición de creación
de una Task desde descripción libre para el Arquitecto — sin interpretar nada
de forma síncrona ni escribir ficheros de backlog en la petición web.

Contrato: body `{"description": "<texto libre>"}` con US que debe existir →
202 con `{request_id, tipo: task, status: pending}` y entrada `pending` con
`us_id` de contexto. `us_id` inexistente → 404. Descripción vacía → 400."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import atlas_forge.api.routes as routes_module
from atlas_forge.api.app import create_app
from atlas_forge.dispatcher.creation_queue import (
    STATUS_PENDING,
    get_creation_requests,
)


def _client() -> TestClient:
    return TestClient(create_app())


def _active_project(tmp_path: Path, monkeypatch, with_us: bool = True) -> Path:
    project_path = tmp_path / "workspace" / "project-a"
    (project_path / "02-backlog" / "user-stories").mkdir(parents=True, exist_ok=True)
    if with_us:
        (project_path / "02-backlog" / "user-stories" / "US-AF999-01-historia.md").write_text(
            "---\nid: US-AF999-01\ntype: user_story\ntitle: Historia\n"
            "state: TO_PLAN\ndependencies: []\nepic: AF-999\npriority: Alta\nversion: 0.9\n"
            "---\n\n## Historia\n\nComo usuario...\n\n## Criterios de aceptación\n\n- C.\n",
            encoding="utf-8",
        )

    from atlas_forge.models import Project

    project = Project(
        id=str(project_path),
        name="project-a",
        path=str(project_path),
        repository="",
        workspace_id="ws-test",
    )
    monkeypatch.setattr(routes_module, "get_active_project", lambda **_kwargs: project)
    return project_path


def test_from_description_task_encola_pending_con_us_id(tmp_path: Path, monkeypatch) -> None:
    _active_project(tmp_path, monkeypatch, with_us=True)
    client = _client()

    resp = client.post(
        "/backlog/us/US-AF999-01/from-description-task",
        json={"description": "Implementar el flujo de pago con tarjeta"},
    )

    assert resp.status_code == 202
    body = resp.json()
    assert body["tipo"] == "task"
    assert body["status"] == STATUS_PENDING
    assert body["request_id"]

    entries = get_creation_requests(tmp_path / "workspace" / "project-a", "project-a")
    assert len(entries) == 1
    entry = entries[0]
    assert entry.request_id == body["request_id"]
    assert entry.tipo == "task"
    assert entry.status == STATUS_PENDING
    assert entry.us_id == "US-AF999-01"
    assert entry.description == "Implementar el flujo de pago con tarjeta"


def test_from_description_task_us_inexistente_404(tmp_path: Path, monkeypatch) -> None:
    _active_project(tmp_path, monkeypatch, with_us=False)
    client = _client()

    resp = client.post(
        "/backlog/us/US-AF999-99/from-description-task",
        json={"description": "Task bajo una US que no existe"},
    )

    assert resp.status_code == 404
    assert "no existe" in resp.json()["detail"]


def test_from_description_task_descripcion_vacia_400(tmp_path: Path, monkeypatch) -> None:
    _active_project(tmp_path, monkeypatch, with_us=True)
    client = _client()

    resp = client.post(
        "/backlog/us/US-AF999-01/from-description-task",
        json={"description": "   "},
    )

    assert resp.status_code == 400
    assert "vacía" in resp.json()["detail"]


def test_from_description_task_no_escribe_task_ni_invoca_pipeline(tmp_path: Path, monkeypatch) -> None:
    _active_project(tmp_path, monkeypatch, with_us=True)
    client = _client()

    import atlas_forge.architect.us_landing as us_landing
    called = []
    monkeypatch.setattr(
        us_landing, "plan_us_landing", lambda *a, **k: called.append(True) or None
    )

    resp = client.post(
        "/backlog/us/US-AF999-01/from-description-task",
        json={"description": "Crear la Task del checkout"},
    )

    assert resp.status_code == 202
    assert called == [], "No debe invocarse el pipeline de interpretación de forma síncrona"
    tasks_dir = tmp_path / "workspace" / "project-a" / "02-backlog" / "tasks"
    assert not tasks_dir.exists() or list(tasks_dir.glob("*.md")) == []
