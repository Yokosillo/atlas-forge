"""Tests de T-FB005-US05-01: declarar preferencia de runtime/modelo al
registrar un agente. Verificado que el mecanismo YA EXISTÍA end-to-end
(`launch_agent`/`register_agent` ya aceptan `runtime`/`model` explícitos
desde T-FB002-US01-01) — el único hueco real cerrado por esta Task es que
`GET /agents` no reflejaba el `runtime_id`/`model` asociado a cada agente
en su respuesta."""

from pathlib import Path

import libtmux
import pytest
from fastapi.testclient import TestClient

import brain.api.routes as routes_module
from brain.api import create_app
from brain.core.session_registry import (
    _reset_registry_for_tests,
    resolve_startup_session,
)
from brain.runtime import extract_model_from_runtime, is_runtime_alive, stop_runtime
from brain.runtime.claude_code import register_claude_code_runtime
from brain.runtime.opencode import register_opencode_runtime
from brain.workspace import discover_projects, select_active_project


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


@pytest.fixture
def isolated_socket(monkeypatch):
    import uuid

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
    workspace = tmp_path / "workspace"
    _make_git_repo(workspace / "project-a")
    state_dir = tmp_path / "state"

    discovered = discover_projects(workspace)
    select_active_project(discovered[0], discovered=discovered, state_dir=state_dir)
    monkeypatch.setattr(routes_module, "get_active_project", lambda **_kwargs: discovered[0])

    session = resolve_startup_session(workspace_root=workspace, state_dir=state_dir)
    assert session is not None
    return discovered[0], session


def test_extract_model_from_runtime_returns_the_model_when_opencode_has_one() -> None:
    runtime = register_opencode_runtime(model="deepseek/deepseek-chat")

    assert extract_model_from_runtime(runtime) == "deepseek/deepseek-chat"


def test_extract_model_from_runtime_returns_none_for_opencode_without_a_model() -> None:
    runtime = register_opencode_runtime()

    assert extract_model_from_runtime(runtime) is None


def test_extract_model_from_runtime_returns_none_for_claude_code() -> None:
    runtime = register_claude_code_runtime()

    assert extract_model_from_runtime(runtime) is None


def test_registering_an_agent_with_an_explicit_model_associates_it_with_that_runtime(
    isolated_socket: str, tmp_path
) -> None:
    """Criterio de aceptación: 'Registrar un agente indicando
    explícitamente un runtime_id concreto lo asocia a ese runtime,
    verificado con tmux real.' Aquí verificado a través de `launch_agent`
    (dashboard), que ya construye el `Runtime` con el `model` indicado —
    mecanismo preexistente, no nuevo en esta Task."""
    from brain.core.session_registry import DevelopmentSession, activate
    from brain.agents.launch import launch_agent

    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)

    agent, runtime_instance = launch_agent(
        "developer",
        "opencode",
        "deepseek/deepseek-chat",
        session,
        str(tmp_path),
        socket_name=isolated_socket,
    )

    assert runtime_instance.runtime.type == "opencode"
    assert extract_model_from_runtime(runtime_instance.runtime) == "deepseek/deepseek-chat"
    assert is_runtime_alive(runtime_instance, socket_name=isolated_socket) is True

    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_not_indicating_a_model_keeps_the_current_default_behavior(
    isolated_socket: str, tmp_path
) -> None:
    """Criterio de aceptación: 'No indicar preferencia mantiene el
    comportamiento actual (runtime por defecto según rol).'"""
    from brain.core.session_registry import DevelopmentSession, activate
    from brain.agents.launch import launch_agent

    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)

    agent, runtime_instance = launch_agent(
        "developer", "claude-code", None, session, str(tmp_path), socket_name=isolated_socket
    )

    assert runtime_instance.runtime.type == "claude-code"
    assert extract_model_from_runtime(runtime_instance.runtime) is None

    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_get_agents_reflects_the_model_associated_with_the_agent(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """Criterio de aceptación: 'Consultar el agente muestra el
    runtime/modelo asociado' — GET /agents ahora incluye `runtime_id` y
    `model` (hueco real que esta Task cierra; el resto del mecanismo ya
    existía)."""
    _project, session = _active_project_and_session(tmp_path, monkeypatch)
    client = TestClient(create_app())

    response = client.post(
        "/agents",
        json={"role": "developer", "runtime_type": "opencode", "model": "opencode-go/deepseek-v4-flash"},
    )
    assert response.status_code == 201
    assert response.json()["runtime_id"] == "opencode"
    assert response.json()["model"] == "opencode-go/deepseek-v4-flash"

    agents = client.get("/agents").json()
    assert len(agents) == 1
    assert agents[0]["runtime_id"] == "opencode"
    assert agents[0]["model"] == "opencode-go/deepseek-v4-flash"


def test_get_agents_shows_none_model_for_an_agent_without_a_model_preference(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    _project, session = _active_project_and_session(tmp_path, monkeypatch)
    client = TestClient(create_app())

    response = client.post(
        "/agents", json={"role": "developer", "runtime_type": "claude-code"}
    )
    assert response.status_code == 201
    assert response.json()["runtime_id"] == "claude-code"
    assert response.json()["model"] is None

    agents = client.get("/agents").json()
    assert agents[0]["model"] is None
