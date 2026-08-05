"""Tests para el endpoint `POST /project/actions/{action_id}` (FB-025 Hilo 3)
y la lógica de dominio en `brain.actions.transversal`.
"""
import os
import tempfile

import pytest
from fastapi.testclient import TestClient

from brain.api.app import create_app


@pytest.fixture
def client():
    return TestClient(create_app())


def _get_or_create_session(client):
    resp = client.get("/session")
    if resp.status_code == 200:
        return
    projects = client.get("/projects").json()
    if not projects:
        pytest.skip("No projects discovered for test")
    project_id = projects[0]["id"]
    resp = client.post(
        "/project",
        json={"project_id": project_id},
        content_type="application/json",
    )
    assert resp.status_code == 200, f"Failed to select project: {resp.json()}"


class TestProjectActionsEndpoint:
    def test_unknown_action_returns_400(self, client):
        resp = client.post("/project/actions/accion-inexistente", json={})
        assert resp.status_code == 400
        detail = resp.json().get("detail", "")
        assert "Acción desconocida" in detail

    def test_action_list_is_known(self, client):
        resp = client.post("/project/actions/testear", json={})
        assert resp.status_code in (200, 404)
        if resp.status_code == 404:
            detail = resp.json().get("detail", "")
            assert "proyecto" in detail.lower() or "sesion" in detail.lower()

    def test_agent_action_requires_session(self, client):
        resp = client.post("/project/actions/documentar", json={})
        assert resp.status_code == 404
        detail = resp.json().get("detail", "")
        assert "sesión" in detail.lower() or "session" in detail.lower()

    def test_agent_action_requires_arquitecto(self, client):
        _get_or_create_session(client)
        resp = client.post("/project/actions/documentar", json={})
        assert resp.status_code in (400, 404)
        if resp.status_code == 400:
            detail = resp.json().get("detail", "")
            assert "Arquitecto" in detail or "arquitecto" in detail
