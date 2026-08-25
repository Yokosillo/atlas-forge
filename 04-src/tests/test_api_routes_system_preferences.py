"""Tests de `GET`/`PUT /system/preferences` (US-AF024-12): mismo patrón
de aislamiento que `test_api_routes_project_selection.py` — no requieren
sesión de desarrollo activa ni runtime real, solo `_STATE_DIR` aislado."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import atlas_forge.api.routes as routes_module
from atlas_forge.api import create_app
from atlas_forge.system_preferences import (
    DEFAULT_AUTO_REENQUEUE_ORPHANED,
    DEFAULT_AUTONOMOUS_CONFIG,
    DEFAULT_BACKLOG_MULTIPLE_EXPANSION,
    DEFAULT_DEVELOPER_WAITS_FOR_TESTER_REVIEW,
    DEFAULT_MAX_SIMULTANEOUS_DEVELOPERS,
    DEFAULT_DIFFICULTY_MODEL_MAP,
    DEFAULT_TUI_ENABLED,
)


@pytest.fixture
def isolated_state_dir(tmp_path: Path, monkeypatch):
    state_dir = tmp_path / "state"
    monkeypatch.setattr(routes_module, "_STATE_DIR", state_dir)
    return state_dir


def test_get_system_preferences_returns_default_without_saved_file(isolated_state_dir) -> None:
    client = TestClient(create_app())
    response = client.get("/system/preferences")
    assert response.status_code == 200
    # El catálogo abierto incluye las claves añadidas tras US-AF024-12
    # (autonomous_config, T-AF023-US03-02; backlog_multiple_expansion,
    # T-AF036-US27-01). Default del modo: "single" (no rompe el
    # comportamiento actual, criterio 1 de la US-AF036-27).
    assert response.json() == {
        "max_simultaneous_developers": DEFAULT_MAX_SIMULTANEOUS_DEVELOPERS,
        "difficulty_model_map": DEFAULT_DIFFICULTY_MODEL_MAP,
        "tui_enabled": DEFAULT_TUI_ENABLED,
        "developer_waits_for_tester_review": DEFAULT_DEVELOPER_WAITS_FOR_TESTER_REVIEW,
        "auto_reenqueue_orphaned": DEFAULT_AUTO_REENQUEUE_ORPHANED,
        "autonomous_config": DEFAULT_AUTONOMOUS_CONFIG,
        "backlog_multiple_expansion": DEFAULT_BACKLOG_MULTIPLE_EXPANSION,
    }


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


def test_put_system_preferences_persists_tui_enabled(isolated_state_dir) -> None:
    client = TestClient(create_app())

    put_response = client.put("/system/preferences", json={"tui_enabled": True})
    assert put_response.status_code == 200
    assert put_response.json()["tui_enabled"] is True

    get_response = client.get("/system/preferences")
    assert get_response.status_code == 200
    assert get_response.json()["tui_enabled"] is True

    put_response_false = client.put("/system/preferences", json={"tui_enabled": False})
    assert put_response_false.status_code == 200
    assert put_response_false.json()["tui_enabled"] is False

    get_response_after = client.get("/system/preferences")
    assert get_response_after.json()["tui_enabled"] is False


# ---------------------------------------------------------------------------
# T-AF036-US27-04 (US-AF036-27): modo de expansión del backlog expuesto por la
# API — default "single", cambio a "multi" persistente, rechazo de inválido.
# ---------------------------------------------------------------------------


def test_get_system_preferences_exposes_backlog_multiple_expansion_default(isolated_state_dir) -> None:
    client = TestClient(create_app())
    response = client.get("/system/preferences")
    assert response.status_code == 200
    assert response.json()["backlog_multiple_expansion"] == "single"


def test_put_system_preferences_backlog_multiple_expansion_multi_persists_and_survives_reload(
    isolated_state_dir,
) -> None:
    client = TestClient(create_app())

    put_response = client.put("/system/preferences", json={"backlog_multiple_expansion": "multi"})
    assert put_response.status_code == 200
    assert put_response.json()["backlog_multiple_expansion"] == "multi"

    get_response = client.get("/system/preferences")
    assert get_response.json()["backlog_multiple_expansion"] == "multi"


@pytest.mark.parametrize("invalid_value", ["triple", "single;multi", ""])
def test_put_system_preferences_rejects_invalid_backlog_multiple_expansion(
    isolated_state_dir, invalid_value,
) -> None:
    client = TestClient(create_app())

    response = client.put("/system/preferences", json={"backlog_multiple_expansion": invalid_value})

    assert response.status_code == 400
    # No debe haberse persistido un estado roto: sigue el default.
    get_response = client.get("/system/preferences")
    assert get_response.json()["backlog_multiple_expansion"] == DEFAULT_BACKLOG_MULTIPLE_EXPANSION


def test_put_system_preferences_backlog_multiple_expansion_is_idempotent(isolated_state_dir) -> None:
    client = TestClient(create_app())
    for mode in ("single", "multi", "single"):
        put_response = client.put("/system/preferences", json={"backlog_multiple_expansion": mode})
        assert put_response.status_code == 200
        assert put_response.json()["backlog_multiple_expansion"] == mode
    get_response = client.get("/system/preferences")
    assert get_response.json()["backlog_multiple_expansion"] == "single"
