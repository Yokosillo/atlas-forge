"""Tests de `POST /system/restart` (T-FB037-US05-01): el endpoint lanza
`systemctl restart` fire-and-forget con una lista de argumentos fija (nunca
interpolada del request) y responde `202 Accepted` de inmediato. `Popen` se
monkeypatchea — el test nunca lanza un proceso real."""

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import brain.api.routes as routes_module
from brain.api import create_app


@pytest.fixture
def isolated_state_dir(tmp_path: Path, monkeypatch):
    state_dir = tmp_path / "state"
    monkeypatch.setattr(routes_module, "_STATE_DIR", state_dir)
    return state_dir


def test_post_system_restart_launches_fixed_command_and_returns_202(
    isolated_state_dir, monkeypatch
) -> None:
    captured = {}

    class FakePopen:
        def __init__(self, command, **kwargs):
            captured["command"] = command
            captured["kwargs"] = kwargs

    monkeypatch.setattr(routes_module.subprocess, "Popen", FakePopen)

    client = TestClient(create_app())
    response = client.post("/system/restart")

    assert response.status_code == 202
    assert response.json() == {"status": "restarting"}
    # Comando fijo, sin interpolación de entrada del cliente.
    assert captured["command"] == [
        "sudo",
        "/usr/bin/systemctl",
        "restart",
        "factory-brain-api",
    ]
    assert captured["kwargs"]["stdout"] == subprocess.DEVNULL
    assert captured["kwargs"]["stderr"] == subprocess.DEVNULL
    assert captured["kwargs"]["start_new_session"] is True


def test_post_system_restart_returns_actionable_error_when_sudo_missing(
    isolated_state_dir, monkeypatch
) -> None:
    def raise_oserror(*args, **kwargs):
        raise OSError("sudo: no existe")

    monkeypatch.setattr(routes_module.subprocess, "Popen", raise_oserror)

    client = TestClient(create_app())
    response = client.post("/system/restart")

    assert response.status_code == 500
    detail = response.json()["detail"]
    assert "sudo" in detail
    assert "OPERACION.md" in detail