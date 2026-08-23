import uuid
from pathlib import Path

import libtmux
import pytest
from fastapi.testclient import TestClient

import atlas_forge.api.routes as routes_module
from atlas_forge.api import create_app
from atlas_forge.core import resolve_startup_session
from atlas_forge.core.session_registry import _reset_registry_for_tests
from atlas_forge.agents.launch import launch_agent
from atlas_forge.runtime import is_runtime_alive
from atlas_forge.workspace import discover_projects, select_active_project


@pytest.fixture(autouse=True)
def _clean_registry():
    _reset_registry_for_tests()
    yield
    _reset_registry_for_tests()


@pytest.fixture(autouse=True)
def _no_real_runtime(monkeypatch):
    import atlas_forge.runtime.claude_code as claude_code_module
    import atlas_forge.runtime.opencode as opencode_module

    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_COMMAND", "sleep")
    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_ARGS", ["5"])
    monkeypatch.setattr(opencode_module, "DEFAULT_OPENCODE_COMMAND", "sleep")
    monkeypatch.setattr(opencode_module, "DEFAULT_OPENCODE_AUTONOMY_FLAG", "5")
    monkeypatch.setattr(opencode_module, "DEFAULT_OPENCODE_ARGS", ["5"])


@pytest.fixture
def isolated_socket(monkeypatch):
    name = f"atlas_forge-test-{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(routes_module, "_SOCKET_NAME", name)
    try:
        yield name
    finally:
        try:
            libtmux.Server(socket_name=name).kill()
        except Exception:
            pass


def _make_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()


def _active_project_and_session(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    _make_git_repo(workspace / "project-a")
    state_dir = tmp_path / "state"

    discovered = discover_projects(workspace)
    select_active_project(discovered[0], discovered=discovered, state_dir=state_dir)
    monkeypatch.setattr(
        routes_module, "get_active_project", lambda **_kwargs: discovered[0]
    )

    session = resolve_startup_session(workspace_root=workspace, state_dir=state_dir)
    assert session is not None
    return discovered[0], session


def test_post_agent_stop_reflects_in_get_agents_immediately(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """Criterio de aceptación: POST /agents/{agent_id}/stop refleja el
    cambio en GET /agents inmediatamente después.

    Rol no-Developer (Arquitecto) a propósito: con Developer
    (T-AF024-US12-02), detener elimina el agente por completo — ver
    `test_post_agent_stop_removes_a_developer_entirely` más abajo para ese
    caso específico."""
    _project, session = _active_project_and_session(tmp_path, monkeypatch)
    agent, runtime_instance = launch_agent(
        "arquitecto", "claude-code", None, session, str(tmp_path), socket_name=isolated_socket
    )
    assert is_runtime_alive(runtime_instance, socket_name=isolated_socket) is True

    client = TestClient(create_app())

    response = client.post(f"/agents/{agent.id}/stop")

    assert response.status_code == 200
    assert response.json()["status"] == "stopped"
    assert is_runtime_alive(runtime_instance, socket_name=isolated_socket) is False

    agents_after = client.get("/agents").json()
    assert agents_after == [
        {
            "id": agent.id,
            "name": agent.name,
            "role": agent.role,
            "status": "stopped",
            "runtime_id": agent.runtime_id,
            "model": None,
            "session_name": runtime_instance.session_name,
            "last_command_at": None,
            "limited_until": None,
            "supervision": "detenido",
        }
    ]


def test_post_agent_stop_removes_a_developer_entirely(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """T-AF024-US12-02: para Developer, POST /agents/{agent_id}/stop
    elimina el Agent por completo — GET /agents deja de listarlo, a
    diferencia del resto de roles (ver test de arriba)."""
    _project, session = _active_project_and_session(tmp_path, monkeypatch)
    agent, runtime_instance = launch_agent(
        "developer", "claude-code", None, session, str(tmp_path), socket_name=isolated_socket
    )
    assert is_runtime_alive(runtime_instance, socket_name=isolated_socket) is True

    client = TestClient(create_app())

    response = client.post(f"/agents/{agent.id}/stop")

    assert response.status_code == 200
    assert response.json()["status"] == "stopped"
    assert is_runtime_alive(runtime_instance, socket_name=isolated_socket) is False

    assert client.get("/agents").json() == []


def test_post_agent_stop_returns_404_for_unknown_agent_id(
    tmp_path: Path, monkeypatch
) -> None:
    _active_project_and_session(tmp_path, monkeypatch)
    client = TestClient(create_app())

    response = client.post("/agents/does-not-exist/stop")

    assert response.status_code == 404


def test_post_agent_stop_returns_404_when_no_session_is_active() -> None:
    client = TestClient(create_app())

    response = client.post("/agents/whatever/stop")

    assert response.status_code == 404
