"""Tests del endpoint del log de reconciliaciones y de la preferencia de
reencolado automático (T-AF022-US18-04, US-AF022-18 criterio 6):
- `GET /backlog/reconciliations` lee `reconciliation_log.jsonl` y devuelve
  las entradas más recientes primero (fecha descendente), con su motivo,
  item/petición y estados previo → nuevo;
- `auto_reenqueue_orphaned` se expone en `GET /system/preferences` y se
  persiste desde `PUT` (el toggle de la web la activa/desactiva).

Deterministas, sin tmux, sobre `tmp_path` aislado (mismo patrón que
`test_api_routes_system_preferences.py`)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import atlas_forge.api.routes as routes_module
from atlas_forge.api import create_app
from atlas_forge.core.reconciliation_log import (
    append_dispatched_orphan_reconciliation,
    read_reconciliation_log,
    reconciliation_log_path,
)


@pytest.fixture
def isolated_project(tmp_path: Path, monkeypatch):
    from atlas_forge.models import Project

    project_path = tmp_path / "workspace" / "project-a"
    project_path.mkdir(parents=True, exist_ok=True)
    project = Project(
        id=str(project_path),
        name="project-a",
        path=str(project_path),
        repository="",
        workspace_id="ws-test",
    )
    monkeypatch.setattr(routes_module, "get_active_project", lambda **_kwargs: project)
    return project_path


def test_read_reconciliation_log_orden_descendente_y_limit(tmp_path: Path) -> None:
    project_root = tmp_path / "p"
    # Se apendan con timestamps crecientes.
    append_dispatched_orphan_reconciliation(
        project_root, "proj", task_id="T-AF999-01", target_state="READY",
        ts="2026-08-25T05:00:00+00:00",
    )
    append_dispatched_orphan_reconciliation(
        project_root, "proj", task_id="T-AF999-02", target_state="TO_DEVELOP",
        ts="2026-08-25T06:00:00+00:00",
    )

    all_entries = read_reconciliation_log(project_root, "proj")
    assert len(all_entries) == 2
    # La más reciente primero (fecha descendente).
    assert all_entries[0]["task_id"] == "T-AF999-02"
    assert all_entries[1]["task_id"] == "T-AF999-01"

    limited = read_reconciliation_log(project_root, "proj", limit=1)
    assert [e["task_id"] for e in limited] == ["T-AF999-02"]


def test_read_reconciliation_log_sin_fichero_devuelve_vacio(tmp_path: Path) -> None:
    assert read_reconciliation_log(tmp_path / "nada", "proj") == []
    assert read_reconciliation_log(tmp_path / "p", "proj") == []


def test_get_backlog_reconciliations_endpoint(isolated_project) -> None:
    project_root = isolated_project
    append_dispatched_orphan_reconciliation(
        project_root, "project-a", task_id="T-AF999-01", target_state="TO_DEVELOP",
        ts="2026-08-25T06:00:00+00:00",
    )
    client = TestClient(create_app())

    response = client.get("/backlog/reconciliations")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["task_id"] == "T-AF999-01"
    assert body[0]["reason"] == "dispatched_orphan_reconciled"
    assert body[0]["target_state"] == "TO_DEVELOP"


def test_get_backlog_reconciliations_endpoint_404_sin_proyecto(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(routes_module, "get_active_project", lambda **_kwargs: None)
    client = TestClient(create_app())

    assert client.get("/backlog/reconciliations").status_code == 404


def test_put_system_preferences_persists_auto_reenqueue_orphaned(tmp_path: Path, monkeypatch) -> None:
    from atlas_forge.system_preferences import (
        DEFAULT_AUTO_REENQUEUE_ORPHANED,
        load_system_preferences,
    )

    state_dir = tmp_path / "state"
    monkeypatch.setattr(routes_module, "_STATE_DIR", state_dir)
    client = TestClient(create_app())

    # Default false.
    get_default = client.get("/system/preferences")
    assert get_default.status_code == 200
    assert get_default.json()["auto_reenqueue_orphaned"] == DEFAULT_AUTO_REENQUEUE_ORPHANED

    # Activar y persistir.
    put_on = client.put("/system/preferences", json={"auto_reenqueue_orphaned": True})
    assert put_on.status_code == 200
    assert put_on.json()["auto_reenqueue_orphaned"] is True
    assert load_system_preferences(state_dir=state_dir)["auto_reenqueue_orphaned"] is True

    # Sobrevive al reload.
    get_after = client.get("/system/preferences")
    assert get_after.json()["auto_reenqueue_orphaned"] is True

    # Desactivar de nuevo.
    put_off = client.put("/system/preferences", json={"auto_reenqueue_orphaned": False})
    assert put_off.status_code == 200
    assert put_off.json()["auto_reenqueue_orphaned"] is False