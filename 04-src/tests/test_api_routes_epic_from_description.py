"""Tests del endpoint `POST /backlog/epic/from-description` (T-AF036-US20-01,
US-AF036-20, criterio 4): encola la petición de creación de una Epic desde
descripción libre para el Arquitecto — sin interpretar nada de forma síncrona
ni escribir ficheros de backlog en la petición web.

Contrato: body `{"description": "<texto libre>"}` → 202 con
`{request_id, tipo, status}` y una entrada `pending` en la cola de peticiones
de creación (T-AF036-US20-06). Descripción vacía → 400. No se toca el
`02-backlog/` ni se invoca `plan_epic_landing`."""
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


def test_from_description_encola_peticion_pending_y_responde_202(
    tmp_path: Path, monkeypatch
) -> None:
    _active_project(tmp_path, monkeypatch)
    client = _client()

    resp = client.post(
        "/backlog/epic/from-description",
        json={"description": "Quiero un pipeline que orqueste la creación de items desde lenguaje natural"},
    )

    assert resp.status_code == 202
    body = resp.json()
    assert body["tipo"] == "epic"
    assert body["status"] == STATUS_PENDING
    assert body["request_id"]

    # La petición queda `pending` en la cola persistente.
    entries = get_creation_requests(tmp_path / "workspace" / "project-a", "project-a")
    assert len(entries) == 1
    entry = entries[0]
    assert entry.request_id == body["request_id"]
    assert entry.tipo == "epic"
    assert entry.status == STATUS_PENDING
    assert entry.description == (
        "Quiero un pipeline que orqueste la creación de items desde lenguaje natural"
    )
    # La Epic es raíz: sin contexto padre.
    assert entry.epic_id is None and entry.us_id is None


def test_from_description_no_escribe_backlog_ni_invoca_pipeline(
    tmp_path: Path, monkeypatch
) -> None:
    """Criterio: no se escribe ningún fichero de backlog ni se invoca el
    pipeline de interpretación en la petición."""
    _active_project(tmp_path, monkeypatch)

    # Espía: `plan_epic_landing` NO debe invocarse de forma síncrona.
    import atlas_forge.architect.epic_landing as epic_landing
    called = []
    monkeypatch.setattr(
        epic_landing, "plan_epic_landing", lambda *a, **k: called.append(True) or None
    )

    client = _client()
    resp = client.post(
        "/backlog/epic/from-description",
        json={"description": "Crear el motor de reglas de negocio"},
    )

    assert resp.status_code == 202
    assert called == [], "plan_epic_landing no debe invocarse de forma síncrona"
    # No se escribe ningún fichero en epics/ (la Epic raíz del workspace no
    # existe todavía — la escribe el Arquitecto en la completión).
    epics_dir = tmp_path / "workspace" / "project-a" / "02-backlog" / "epics"
    assert not epics_dir.exists() or list(epics_dir.glob("*.md")) == []


def test_from_description_descripcion_vacia_devuelve_400(
    tmp_path: Path, monkeypatch
) -> None:
    _active_project(tmp_path, monkeypatch)
    client = _client()

    resp = client.post("/backlog/epic/from-description", json={"description": "   "})
    assert resp.status_code == 400
    assert "vacía" in resp.json()["detail"]
