"""Tests de `GET /projects`/`POST /project` (T-FB016-US01-11): descubrir
repositorios y seleccionar uno como proyecto activo, re-arrancando la
sesión de desarrollo del proceso para él — incluyendo el criterio de
aceptación explícito sobre qué pasa con los agentes de la sesión
anterior (deben detenerse, no quedar huérfanos)."""

import uuid
from pathlib import Path

import libtmux
import pytest
from fastapi.testclient import TestClient

import brain.api.routes as routes_module
from brain.api import create_app
from brain.core.session_registry import _reset_registry_for_tests
from brain.runtime import get_runtime_instance_for_agent, is_runtime_alive
from brain.workspace import discover_projects


@pytest.fixture(autouse=True)
def _clean_registry():
    _reset_registry_for_tests()
    yield
    _reset_registry_for_tests()


@pytest.fixture(autouse=True)
def _no_real_runtime(monkeypatch):
    import brain.runtime.claude_code as claude_code_module
    import brain.runtime.opencode as opencode_module

    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_COMMAND", "sleep")
    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_ARGS", ["5"])
    monkeypatch.setattr(opencode_module, "DEFAULT_OPENCODE_COMMAND", "sleep")
    monkeypatch.setattr(opencode_module, "DEFAULT_OPENCODE_AUTONOMY_FLAG", "5")
    monkeypatch.setattr(opencode_module, "DEFAULT_OPENCODE_ARGS", ["5"])


@pytest.fixture
def isolated_socket(monkeypatch):
    name = f"brain-test-{uuid.uuid4().hex[:8]}"
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


@pytest.fixture
def isolated_workspace(tmp_path: Path, monkeypatch):
    """Aísla `GET /projects`/`POST /project` en un workspace y estado de
    proyecto activo propios (nunca el filesystem real del usuario) —
    mismo motivo que `isolated_socket` para tmux."""
    workspace = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    monkeypatch.setattr(routes_module, "_WORKSPACE_ROOT", workspace)
    monkeypatch.setattr(routes_module, "_STATE_DIR", state_dir)
    return workspace, state_dir


def test_get_projects_returns_the_same_repositories_workspace_screen_would_see(
    isolated_workspace,
) -> None:
    workspace, _state_dir = isolated_workspace
    _make_git_repo(workspace / "project-a")
    _make_git_repo(workspace / "project-b")

    expected = discover_projects(workspace)
    client = TestClient(create_app())

    response = client.get("/projects")

    assert response.status_code == 200
    assert {project["id"] for project in response.json()} == {
        project.id for project in expected
    }


def test_get_projects_returns_an_empty_list_when_no_repository_is_discovered(
    isolated_workspace,
) -> None:
    client = TestClient(create_app())

    response = client.get("/projects")

    assert response.status_code == 200
    assert response.json() == []


def test_post_project_selects_a_valid_project_and_get_project_reflects_it(
    isolated_workspace,
) -> None:
    workspace, _state_dir = isolated_workspace
    _make_git_repo(workspace / "project-a")
    discovered = discover_projects(workspace)

    client = TestClient(create_app())

    response = client.post("/project", json={"project_id": discovered[0].id})

    assert response.status_code == 200
    assert response.json()["id"] == discovered[0].id

    get_response = client.get("/project")
    assert get_response.status_code == 200
    assert get_response.json()["id"] == discovered[0].id


def test_post_project_makes_get_session_reflect_a_new_session_for_the_new_project(
    isolated_workspace,
) -> None:
    workspace, _state_dir = isolated_workspace
    _make_git_repo(workspace / "project-a")
    _make_git_repo(workspace / "project-b")
    discovered = discover_projects(workspace)
    project_a = next(p for p in discovered if p.name == "project-a")
    project_b = next(p for p in discovered if p.name == "project-b")

    client = TestClient(create_app())

    first = client.post("/project", json={"project_id": project_a.id})
    assert first.status_code == 200
    first_session = client.get("/session").json()
    assert first_session["project_id"] == project_a.id

    second = client.post("/project", json={"project_id": project_b.id})
    assert second.status_code == 200
    second_session = client.get("/session").json()

    assert second_session["project_id"] == project_b.id
    assert second_session["id"] != first_session["id"]


def test_post_project_with_unknown_project_id_returns_400(isolated_workspace) -> None:
    workspace, _state_dir = isolated_workspace
    _make_git_repo(workspace / "project-a")

    client = TestClient(create_app())

    response = client.post("/project", json={"project_id": "/does/not/exist"})

    assert response.status_code == 400
    assert "no pertenece" in response.json()["detail"]


def test_post_project_stops_agents_from_the_previous_session_real_tmux(
    isolated_workspace, isolated_socket: str
) -> None:
    """Criterio de aceptación explícito: los agentes de la sesión anterior
    no deben quedar huérfanos (proceso tmux real vivo, pero inalcanzable
    desde ningún endpoint una vez cambiada la sesión) — se detienen de
    verdad antes de descartar esa sesión."""
    workspace, _state_dir = isolated_workspace
    _make_git_repo(workspace / "project-a")
    _make_git_repo(workspace / "project-b")
    discovered = discover_projects(workspace)
    project_a = next(p for p in discovered if p.name == "project-a")
    project_b = next(p for p in discovered if p.name == "project-b")

    client = TestClient(create_app())
    client.post("/project", json={"project_id": project_a.id})

    launched = client.post(
        "/agents", json={"role": "developer", "runtime_type": "claude-code"}
    ).json()
    runtime_instance = get_runtime_instance_for_agent(launched["id"])
    assert is_runtime_alive(runtime_instance, socket_name=isolated_socket)

    client.post("/project", json={"project_id": project_b.id})

    # El proceso tmux real del agente de la sesión anterior debe haberse
    # detenido de verdad, no solo dejar de aparecer en un listado.
    assert not is_runtime_alive(runtime_instance, socket_name=isolated_socket)

    # Y ya no es alcanzable desde GET /agents (pertenece a la sesión
    # anterior, ahora descartada) — la propia sesión nueva no lo conoce.
    agents_now = client.get("/agents").json()
    assert all(agent["id"] != launched["id"] for agent in agents_now)


def test_post_project_ignores_an_agent_whose_runtime_already_died(
    isolated_workspace, isolated_socket: str
) -> None:
    """Un agente cuyo runtime ya murió externamente (antes del cambio de
    proyecto) no debe bloquear el cambio — `AgentRuntimeNotFoundError` de
    `stop_agent` se ignora para ese agente puntual."""
    from brain.tmux.manager import kill_session

    workspace, _state_dir = isolated_workspace
    _make_git_repo(workspace / "project-a")
    _make_git_repo(workspace / "project-b")
    discovered = discover_projects(workspace)
    project_a = next(p for p in discovered if p.name == "project-a")
    project_b = next(p for p in discovered if p.name == "project-b")

    client = TestClient(create_app())
    client.post("/project", json={"project_id": project_a.id})

    launched = client.post(
        "/agents", json={"role": "developer", "runtime_type": "claude-code"}
    ).json()
    runtime_instance = get_runtime_instance_for_agent(launched["id"])
    kill_session(runtime_instance.session_name, socket_name=isolated_socket)

    response = client.post("/project", json={"project_id": project_b.id})

    assert response.status_code == 200
    assert response.json()["id"] == project_b.id
