"""Tests de `GET /scripts`/`POST /scripts/{script_id}/run` (T-FB001-US03-03):
envoltura fina de `discover_project_scripts`/`run_project_script`
(T-FB001-US03-01/02) sobre el proyecto activo — nunca contra un manifiesto
mockeado, se escribe uno real a disco y se ejecuta un comando de shell
real (mismo criterio de "comportamiento real" ya aplicado en el resto del
proyecto)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import brain.api.routes as routes_module
from brain.api import create_app
from brain.workspace.project_scripts import MANIFEST_RELATIVE_PATH


def _make_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()


def _write_manifest(project_path: Path, content: str) -> None:
    manifest_path = project_path / MANIFEST_RELATIVE_PATH
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(content, encoding="utf-8")


def _active_project(tmp_path: Path, monkeypatch) -> Path:
    """Activa un proyecto real y aislado (nunca el filesystem real del
    usuario) haciendo que `routes.get_active_project` (el que consulta
    el endpoint) lo devuelva — mismo patrón ya usado en
    `test_api_routes_agents.py`."""
    project_path = tmp_path / "workspace" / "project-a"
    _make_git_repo(project_path)

    from brain.models import Project

    project = Project(id=str(project_path), name="project-a", path=str(project_path), repository="")
    monkeypatch.setattr(routes_module, "get_active_project", lambda **_kwargs: project)
    return project_path


def test_get_scripts_returns_404_when_no_project_is_active(monkeypatch) -> None:
    monkeypatch.setattr(routes_module, "get_active_project", lambda **_kwargs: None)
    client = TestClient(create_app())

    response = client.get("/scripts")

    assert response.status_code == 404


def test_get_scripts_returns_an_empty_list_for_a_project_without_a_manifest(
    tmp_path: Path, monkeypatch
) -> None:
    _active_project(tmp_path, monkeypatch)
    client = TestClient(create_app())

    response = client.get("/scripts")

    assert response.status_code == 200
    assert response.json() == []


def test_get_scripts_returns_the_real_catalogued_scripts(
    tmp_path: Path, monkeypatch
) -> None:
    project_path = _active_project(tmp_path, monkeypatch)
    _write_manifest(
        project_path,
        """
        scripts:
          - id: lint
            name: "Lint"
            command: "ruff check ."
            description: "Ejecuta el linter."
        """,
    )
    client = TestClient(create_app())

    response = client.get("/scripts")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": "lint",
            "name": "Lint",
            "command": "ruff check .",
            "description": "Ejecuta el linter.",
        }
    ]


def test_get_scripts_returns_400_with_the_real_domain_message_for_a_malformed_manifest(
    tmp_path: Path, monkeypatch
) -> None:
    project_path = _active_project(tmp_path, monkeypatch)
    _write_manifest(project_path, "scripts: not-a-list\n")
    client = TestClient(create_app())

    response = client.get("/scripts")

    assert response.status_code == 400
    assert "scripts" in response.json()["detail"]


def test_post_script_run_returns_404_when_no_project_is_active(monkeypatch) -> None:
    monkeypatch.setattr(routes_module, "get_active_project", lambda **_kwargs: None)
    client = TestClient(create_app())

    response = client.post("/scripts/anything/run")

    assert response.status_code == 404


def test_post_script_run_executes_a_valid_script_and_returns_its_output(
    tmp_path: Path, monkeypatch
) -> None:
    project_path = _active_project(tmp_path, monkeypatch)
    _write_manifest(
        project_path,
        """
        scripts:
          - id: greet
            name: "Greet"
            command: "echo hello-from-api"
        """,
    )
    client = TestClient(create_app())

    response = client.post("/scripts/greet/run")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["exit_code"] == 0
    assert "hello-from-api" in body["stdout"]


def test_post_script_run_with_unknown_script_id_returns_200_with_an_error_result(
    tmp_path: Path, monkeypatch
) -> None:
    """Criterio de aceptación explícito: 'un script_id que no existe se
    rechaza con un mensaje claro, sin excepción no controlada' — a nivel
    HTTP esto es un resultado estructurado (200 con `success=False`), no
    un código de error HTTP: la petición en sí fue válida, el catalogado
    simplemente no encontró el id (mismo criterio ya verificado en
    dominio, `run_project_script`, T-FB001-US03-02)."""
    _active_project(tmp_path, monkeypatch)
    client = TestClient(create_app())

    response = client.post("/scripts/does-not-exist/run")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["exit_code"] is None
    assert "does-not-exist" in body["error_message"]


def test_post_script_run_reflects_a_failing_script_with_its_reason_without_breaking(
    tmp_path: Path, monkeypatch
) -> None:
    project_path = _active_project(tmp_path, monkeypatch)
    _write_manifest(
        project_path,
        """
        scripts:
          - id: broken
            name: "Broken"
            command: "echo failure-reason >&2; exit 3"
        """,
    )
    client = TestClient(create_app())

    response = client.post("/scripts/broken/run")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["exit_code"] == 3
    assert "failure-reason" in body["stderr"]
