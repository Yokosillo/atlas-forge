"""Tests de `GET`/`PUT /system/preferences` (US-FB024-12): mismo patrón
de aislamiento que `test_api_routes_project_selection.py` — no requieren
sesión de desarrollo activa ni runtime real, solo `_STATE_DIR` aislado."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import brain.api.routes as routes_module
from brain.api import create_app
from brain.system_preferences import DEFAULT_MAX_SIMULTANEOUS_DEVELOPERS


@pytest.fixture
def isolated_state_dir(tmp_path: Path, monkeypatch):
    state_dir = tmp_path / "state"
    monkeypatch.setattr(routes_module, "_STATE_DIR", state_dir)
    return state_dir


def test_get_system_preferences_returns_default_without_saved_file(isolated_state_dir) -> None:
    client = TestClient(create_app())
    response = client.get("/system/preferences")
    assert response.status_code == 200
    assert response.json() == {"max_simultaneous_developers": DEFAULT_MAX_SIMULTANEOUS_DEVELOPERS}


def test_put_system_preferences_persists_and_survives_reload(isolated_state_dir) -> None:
    client = TestClient(create_app())

    put_response = client.put("/system/preferences", json={"max_simultaneous_developers": 5})
    assert put_response.status_code == 200
    assert put_response.json()["max_simultaneous_developers"] == 5

    get_response = client.get("/system/preferences")
    assert get_response.status_code == 200
    assert get_response.json()["max_simultaneous_developers"] == 5


@pytest.mark.parametrize("invalid_value", [0, -1, -100])
def test_put_system_preferences_rejects_non_positive_values(isolated_state_dir, invalid_value) -> None:
    client = TestClient(create_app())

    response = client.put("/system/preferences", json={"max_simultaneous_developers": invalid_value})

    assert response.status_code == 400
    # No debe haber persistido ningún estado tras el rechazo.
    get_response = client.get("/system/preferences")
    assert get_response.json()["max_simultaneous_developers"] == DEFAULT_MAX_SIMULTANEOUS_DEVELOPERS


def test_put_system_preferences_rejects_non_numeric_value(isolated_state_dir) -> None:
    client = TestClient(create_app())

    response = client.put("/system/preferences", json={"max_simultaneous_developers": "muchos"})

    assert response.status_code == 422  # validación de tipo de Pydantic/FastAPI
