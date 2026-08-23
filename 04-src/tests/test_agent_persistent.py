"""T-AF023-US03-01: campo `persistent` del modelo `Agent`, decidido por rol
al lanzar (no configurable por instancia): Arquitecto y otros roles de
instancia única -> `true`; Developer/Tester -> `false`."""

import uuid

import libtmux
import pytest

from atlas_forge.agents.launch import launch_agent
from atlas_forge.agents.roles import is_persistent_role
from atlas_forge.core.session_lifecycle import activate
from atlas_forge.core.session_registry import _reset_registry_for_tests
from atlas_forge.models import DevelopmentSession


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
    monkeypatch.setattr(opencode_module, "DEFAULT_OPENCODE_ARGS", ["5"])


@pytest.fixture
def isolated_socket():
    name = f"atlas_forge-test-{uuid.uuid4().hex[:8]}"
    try:
        yield name
    finally:
        try:
            libtmux.Server(socket_name=name).kill()
        except Exception:
            pass


def _active_session() -> DevelopmentSession:
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    return session


def _launch(role, isolated_socket, tmp_path):
    session = _active_session()
    agent, _ = launch_agent(
        role, "claude-code", None, session, str(tmp_path), socket_name=isolated_socket
    )
    return agent


def test_architect_agent_is_persistent(isolated_socket, tmp_path) -> None:
    agent = _launch("arquitecto", isolated_socket, tmp_path)
    assert agent.persistent is True
    assert is_persistent_role("arquitecto") is True


def test_developer_agent_is_not_persistent(isolated_socket, tmp_path) -> None:
    agent = _launch("developer", isolated_socket, tmp_path)
    assert agent.persistent is False
    assert is_persistent_role("developer") is False


def test_tester_agent_is_not_persistent(isolated_socket, tmp_path) -> None:
    agent = _launch("tester", isolated_socket, tmp_path)
    assert agent.persistent is False
    assert is_persistent_role("tester") is False


def test_ux_agent_is_persistent(isolated_socket, tmp_path) -> None:
    agent = _launch("ux", isolated_socket, tmp_path)
    assert agent.persistent is True


def test_persistent_role_mapping_is_complete() -> None:
    # La decisión por rol es explícita y completa para los roles del catálogo.
    assert is_persistent_role("auditor_oss") is True
    assert is_persistent_role("documentador") is True
    assert is_persistent_role("arquitecto") is True
    assert is_persistent_role("ux") is True
    assert is_persistent_role("developer") is False
    assert is_persistent_role("tester") is False


def test_agent_model_default_is_not_persistent() -> None:
    from atlas_forge.models import Agent

    agent = Agent(id="a1", name="X", role="developer", prompt="p", runtime_id="r")
    assert agent.persistent is False
