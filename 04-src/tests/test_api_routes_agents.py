import uuid
from pathlib import Path

import libtmux
import pytest
from fastapi.testclient import TestClient

import brain.api.routes as routes_module
from brain.api import create_app
from brain.core import resolve_startup_session
from brain.core.session_registry import _reset_registry_for_tests
from brain.runtime import get_runtime_instance_for_agent, stop_runtime
from brain.workspace import discover_projects, select_active_project


@pytest.fixture(autouse=True)
def _clean_registry():
    _reset_registry_for_tests()
    yield
    _reset_registry_for_tests()


@pytest.fixture(autouse=True)
def _no_real_runtime(monkeypatch):
    """Mismo patrón de aislamiento ya usado en test_launch_agent.py: nunca
    invocar los binarios reales de Claude Code/OpenCode en tests."""
    import brain.runtime.claude_code as claude_code_module
    import brain.runtime.opencode as opencode_module

    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_COMMAND", "sleep")
    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_ARGS", ["5"])
    monkeypatch.setattr(opencode_module, "DEFAULT_OPENCODE_COMMAND", "sleep")
    monkeypatch.setattr(opencode_module, "DEFAULT_OPENCODE_AUTONOMY_FLAG", "5")
    monkeypatch.setattr(opencode_module, "DEFAULT_OPENCODE_ARGS", ["5"])


@pytest.fixture
def isolated_socket(monkeypatch):
    """Aísla el endpoint POST /agents en su propio servidor tmux (el
    socket real no es parámetro del body HTTP — ver `routes._SOCKET_NAME`),
    con limpieza garantizada incluso si el test falla a medio camino."""
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


def _active_project_and_session(tmp_path: Path, monkeypatch):
    """Arranca un proyecto activo y una sesión de desarrollo activa reales
    y aislados (nunca el estado real del sistema en `~/.local/share/brain`)
    y hace que `routes.get_active_project` (el que de verdad consulta el
    endpoint) devuelva ese proyecto — `load_active_project` sin `state_dir`
    explícito leería del filesystem real del usuario, ajeno a este test."""
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


def test_get_project_returns_404_when_no_project_is_active(monkeypatch) -> None:
    monkeypatch.setattr(routes_module, "get_active_project", lambda **_kwargs: None)
    client = TestClient(create_app())

    response = client.get("/project")

    assert response.status_code == 404


def test_get_project_returns_the_real_active_project(
    tmp_path: Path, monkeypatch
) -> None:
    project, _session = _active_project_and_session(tmp_path, monkeypatch)
    client = TestClient(create_app())

    response = client.get("/project")

    assert response.status_code == 200
    assert response.json() == {
        "id": project.id,
        "name": project.name,
        "path": project.path,
        "repository": project.repository,
    }


def test_get_session_returns_404_when_no_session_is_active() -> None:
    client = TestClient(create_app())

    response = client.get("/session")

    assert response.status_code == 404


def test_get_session_returns_the_real_active_session(
    tmp_path: Path, monkeypatch
) -> None:
    _project, session = _active_project_and_session(tmp_path, monkeypatch)
    client = TestClient(create_app())

    response = client.get("/session")

    assert response.status_code == 200
    assert response.json()["id"] == session.id
    assert response.json()["status"] == "active"


def test_get_agents_returns_404_when_no_session_is_active() -> None:
    client = TestClient(create_app())

    response = client.get("/agents")

    assert response.status_code == 404


def test_get_agents_reflects_an_agent_launched_directly_via_domain(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """Criterio de aceptación: arrancar sesión, lanzar agente vía llamada
    directa a dominio (sin pasar por HTTP), consultar por HTTP y ver el
    mismo agente."""
    from brain.dashboard import launch_agent

    _project, session = _active_project_and_session(tmp_path, monkeypatch)
    agent, runtime_instance = launch_agent(
        "developer", "claude-code", None, session, str(tmp_path), socket_name=isolated_socket
    )

    client = TestClient(create_app())
    response = client.get("/agents")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": agent.id,
            "name": agent.name,
            "role": agent.role,
            "status": agent.status,
            "runtime_id": agent.runtime_id,
            "model": None,
        }
    ]

    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_post_agents_launches_a_real_agent_and_get_agents_reflects_it(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """Criterio de aceptación: POST /agents lanza un agente real (mismo
    mecanismo que la TUI) y aparece reflejado inmediatamente en GET
    /agents."""
    _project, _session = _active_project_and_session(tmp_path, monkeypatch)
    client = TestClient(create_app())

    post_response = client.post(
        "/agents", json={"role": "developer", "runtime_type": "claude-code"}
    )
    assert post_response.status_code == 201
    launched = post_response.json()
    assert launched["role"] == "developer"

    get_response = client.get("/agents")
    assert get_response.status_code == 200
    assert any(agent["id"] == launched["id"] for agent in get_response.json())

    runtime_instance = get_runtime_instance_for_agent(launched["id"])
    assert runtime_instance is not None
    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_post_agents_with_unrecognized_role_returns_400_with_domain_message(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """Criterio de aceptación: combinación inválida devuelve 4xx con el
    mismo mensaje de motivo que ya lanza AgentLaunchError, no un texto
    reinventado."""
    from brain.dashboard import AgentLaunchError, launch_agent

    _project, session = _active_project_and_session(tmp_path, monkeypatch)

    try:
        launch_agent(
            "unknown-role", "claude-code", None, session, str(tmp_path),
            socket_name=isolated_socket,
        )
        expected_message = None
    except AgentLaunchError as error:
        expected_message = str(error)

    assert expected_message is not None

    client = TestClient(create_app())
    response = client.post(
        "/agents", json={"role": "unknown-role", "runtime_type": "claude-code"}
    )

    assert response.status_code == 400
    assert response.json()["detail"] == expected_message


def test_post_agents_with_model_on_claude_code_returns_400_with_domain_message(
    tmp_path: Path, monkeypatch
) -> None:
    _project, _session = _active_project_and_session(tmp_path, monkeypatch)
    client = TestClient(create_app())

    response = client.post(
        "/agents",
        json={"role": "developer", "runtime_type": "claude-code", "model": "gpt-4"},
    )

    assert response.status_code == 400
    assert "Claude Code" in response.json()["detail"]


def test_post_agents_returns_404_when_no_session_is_active() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/agents", json={"role": "developer", "runtime_type": "claude-code"}
    )

    assert response.status_code == 404


def test_get_agents_reports_unavailable_when_runtime_died_externally(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """Criterio de aceptación explícito de T-FB016-US01-07: un agente
    cuyo proceso tmux se mata externamente (`tmux kill-session` directo,
    fuera de `POST /agents/{id}/stop`) pasa a reportarse como
    `unavailable` la próxima vez que se consulta `GET /agents` — nunca
    sigue como `idle`/`working`."""
    from brain.tmux.manager import kill_session

    _project, _session = _active_project_and_session(tmp_path, monkeypatch)
    client = TestClient(create_app())

    launched = client.post(
        "/agents", json={"role": "developer", "runtime_type": "claude-code"}
    ).json()
    assert launched["status"] == "idle"

    runtime_instance = get_runtime_instance_for_agent(launched["id"])
    kill_session(runtime_instance.session_name, socket_name=isolated_socket)

    response = client.get("/agents")

    assert response.status_code == 200
    refreshed = next(a for a in response.json() if a["id"] == launched["id"])
    assert refreshed["status"] == "unavailable"


def test_get_agents_does_not_rewrite_a_stopped_agent_to_unavailable(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """Criterio de aceptación explícito: un agente detenido a propósito
    (`stopped`, T-FB016-US01-03) no se ve afectado por la verificación de
    liveness — sigue `stopped`, nunca se reescribe a `unavailable`."""
    _project, _session = _active_project_and_session(tmp_path, monkeypatch)
    client = TestClient(create_app())

    launched = client.post(
        "/agents", json={"role": "developer", "runtime_type": "claude-code"}
    ).json()

    stop_response = client.post(f"/agents/{launched['id']}/stop")
    assert stop_response.status_code == 200
    assert stop_response.json()["status"] == "stopped"

    response = client.get("/agents")

    assert response.status_code == 200
    refreshed = next(a for a in response.json() if a["id"] == launched["id"])
    assert refreshed["status"] == "stopped"
