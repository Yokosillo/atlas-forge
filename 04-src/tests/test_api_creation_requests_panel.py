"""Tests del panel "Peticiones para el Arquitecto" (T-AF036-US20-04): el
endpoint `GET /backlog/creation-requests` devuelve la cola con su estado y
motivos verbatim, y al marcar una petición `done`/`failed` se refleja; el
backend de encolado + lectura del panel (lo que alimenta la web) queda
cubierto de punta a punta.

Complementa a los tests web deterministas (`backlog_creacion_lenguaje_natural.test.js`):
aquí se verifica el contrato backend real que el panel consume."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import atlas_forge.api.routes as routes_module
from atlas_forge.api.app import create_app
from atlas_forge.dispatcher.creation_queue import (
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_PENDING,
    get_creation_requests,
    mark_creation_done,
    mark_creation_failed,
)


def _client() -> TestClient:
    return TestClient(create_app())


def _active_project(tmp_path: Path, monkeypatch) -> Path:
    project_path = tmp_path / "workspace" / "project-a"
    project_path.mkdir(parents=True, exist_ok=True)

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


def test_creation_requests_endpoint_returns_queue_with_status_and_errors(
    tmp_path: Path, monkeypatch
) -> None:
    """El panel alimenta de este endpoint: tras encolar y marcar una petición
    `failed`, `GET /backlog/creation-requests` devuelve las peticiones con su
    estado, descripción y motivos verbatim."""
    project = _active_project(tmp_path, monkeypatch)
    client = _client()

    # Encolar una Epic (US20-01).
    r = client.post("/backlog/epic/from-description", json={"description": "Crear el motor de reglas."})
    assert r.status_code == 202
    epic_id = r.json()["request_id"]

    # Encolar una US (US20-02) bajo una Epic que debe existir.
    from atlas_forge.backlog.create import create_epic
    create_epic(project / "02-backlog", "AF-999", "Epic", "Objetivo.")
    r2 = client.post("/backlog/epic/AF-999/from-description-us", json={"description": "Una historia."})
    assert r2.status_code == 202
    us_id = r2.json()["request_id"]

    # Marcar la US como failed con motivos verbatim (la completión lo hace).
    mark_creation_failed(project, "project-a", us_id, ["id duplicado: ya existe la US"])

    # El panel (GET) devuelve ambas con sus estados.
    resp = client.get("/backlog/creation-requests")
    assert resp.status_code == 200
    data = resp.json()
    by_req = {e["request_id"]: e for e in data}
    assert by_req[epic_id]["status"] == STATUS_PENDING
    assert by_req[epic_id]["tipo"] == "epic"
    assert by_req[us_id]["status"] == STATUS_FAILED
    assert by_req[us_id]["errors"] == ["id duplicado: ya existe la US"]
    assert by_req[us_id]["epic_id"] == "AF-999"


def test_creation_request_done_reflects_in_panel(tmp_path: Path, monkeypatch) -> None:
    """Al completarse una petición (la entidad se escribe), el panel la
    muestra `done` — lo que la web usa para saber que el item nuevo ya está
    en el backlog (padre expandida)."""
    project = _active_project(tmp_path, monkeypatch)
    client = _client()

    r = client.post("/backlog/epic/from-description", json={"description": "Epic que el Arquitecto materializará."})
    assert r.status_code == 202
    request_id = r.json()["request_id"]

    # Simular la completión (US20-08) marcando la petición done.
    mark_creation_done(project, "project-a", request_id)

    resp = client.get("/backlog/creation-requests")
    assert resp.status_code == 200
    entry = next(e for e in resp.json() if e["request_id"] == request_id)
    assert entry["status"] == STATUS_DONE
    # La cola persistente también lo refleja.
    assert get_creation_requests(project, "project-a")[0].status == STATUS_DONE
