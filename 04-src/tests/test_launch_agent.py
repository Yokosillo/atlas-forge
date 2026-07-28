import uuid

import libtmux
import pytest

from brain.agents import CRITIC_ROLE, DEVELOPER_ROLE
from brain.core.session_lifecycle import activate, list_agents
from brain.dashboard import AgentLaunchError, launch_agent
from brain.models import DevelopmentSession
from brain.runtime import is_runtime_alive, stop_runtime


@pytest.fixture(autouse=True)
def _no_real_runtime(monkeypatch):
    """Sustituye los comandos reales de Claude Code/OpenCode por un
    comando de prueba inocuo (`sleep`), para no invocar los binarios
    reales en ningún test de esta Task — mismo patrón ya usado en
    T-FB004-US01-02/US02-01."""
    import brain.runtime.claude_code as claude_code_module
    import brain.runtime.opencode as opencode_module

    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_COMMAND", "sleep")
    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_ARGS", ["5"])
    monkeypatch.setattr(opencode_module, "DEFAULT_OPENCODE_COMMAND", "sleep")
    monkeypatch.setattr(opencode_module, "DEFAULT_OPENCODE_AUTONOMY_FLAG", "5")
    monkeypatch.setattr(opencode_module, "DEFAULT_OPENCODE_ARGS", ["5"])


@pytest.fixture
def isolated_socket():
    """Aísla los tests de esta Task en su propio servidor tmux, con
    limpieza garantizada incluso si el test falla a medio camino."""
    name = f"brain-test-{uuid.uuid4().hex[:8]}"
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


def test_launch_critic_on_claude_code_and_developer_on_opencode_with_model(
    isolated_socket: str, tmp_path
) -> None:
    session = _active_session()

    critic_agent, critic_instance = launch_agent(
        CRITIC_ROLE,
        "claude-code",
        None,
        session,
        str(tmp_path),
        socket_name=isolated_socket,
    )
    developer_agent, developer_instance = launch_agent(
        DEVELOPER_ROLE,
        "opencode",
        "deepseek/deepseek-chat",
        session,
        str(tmp_path),
        socket_name=isolated_socket,
    )

    assert critic_agent.role == CRITIC_ROLE
    assert developer_agent.role == DEVELOPER_ROLE
    assert critic_agent in list_agents(session)
    assert developer_agent in list_agents(session)
    assert is_runtime_alive(critic_instance, socket_name=isolated_socket) is True
    assert is_runtime_alive(developer_instance, socket_name=isolated_socket) is True

    stop_runtime(critic_instance, socket_name=isolated_socket)
    stop_runtime(developer_instance, socket_name=isolated_socket)


def test_indicating_model_for_claude_code_is_rejected_without_launching_anything(
    isolated_socket: str, tmp_path
) -> None:
    session = _active_session()

    with pytest.raises(AgentLaunchError):
        launch_agent(
            DEVELOPER_ROLE,
            "claude-code",
            "some-model",
            session,
            str(tmp_path),
            socket_name=isolated_socket,
        )

    assert list_agents(session) == []


def test_launching_on_inactive_session_is_rejected(tmp_path) -> None:
    session = DevelopmentSession(id="s1", project_id="p1")
    # La sesión permanece en `created`, nunca se activa.

    with pytest.raises(AgentLaunchError):
        launch_agent(DEVELOPER_ROLE, "claude-code", None, session, str(tmp_path))


def test_launching_same_role_twice_reuses_the_existing_agent(
    isolated_socket: str, tmp_path
) -> None:
    session = _active_session()

    first_agent, first_instance = launch_agent(
        DEVELOPER_ROLE,
        "claude-code",
        None,
        session,
        str(tmp_path),
        socket_name=isolated_socket,
    )
    second_agent, second_instance = launch_agent(
        DEVELOPER_ROLE,
        "claude-code",
        None,
        session,
        str(tmp_path),
        socket_name=isolated_socket,
    )

    assert second_agent is first_agent
    assert second_instance.session_name == first_instance.session_name
    developers = [a for a in list_agents(session) if a.role == DEVELOPER_ROLE]
    assert len(developers) == 1

    stop_runtime(first_instance, socket_name=isolated_socket)


def test_unrecognized_role_is_rejected(tmp_path) -> None:
    session = _active_session()

    with pytest.raises(AgentLaunchError):
        launch_agent("architect", "claude-code", None, session, str(tmp_path))


def test_unrecognized_runtime_is_rejected(tmp_path) -> None:
    session = _active_session()

    with pytest.raises(AgentLaunchError):
        launch_agent(DEVELOPER_ROLE, "codex", None, session, str(tmp_path))
