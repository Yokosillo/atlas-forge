import time
import uuid

import libtmux
import pytest

from brain.agents import (
    CRITIC_PROMPT,
    CRITIC_ROLE,
    DEVELOPER_PROMPT,
    DEVELOPER_ROLE,
    get_agent_state,
    mark_working,
    register_critic,
    register_developer,
)
from brain.core import activate, list_agents
from brain.models import DevelopmentSession, Runtime
from brain.runtime import is_runtime_alive, stop_runtime


@pytest.fixture
def isolated_socket():
    """Aísla los tests de esta Task en su propio servidor tmux, para no
    interferir con sesiones tmux reales del entorno (nunca lanzar los
    binarios reales de Claude Code/OpenCode en tests — misma precaución ya
    aplicada en las Tasks de FB-004 y FB-005 anteriores)."""
    name = f"brain-test-{uuid.uuid4().hex[:8]}"
    yield name
    try:
        libtmux.Server(socket_name=name).kill()
    except Exception:
        pass


def _test_runtime(runtime_id: str = "test-runtime") -> Runtime:
    # Comando de prueba inocuo (`sleep`), NO un binario real de runtime.
    return Runtime(
        id=runtime_id, name="Test Runtime", type="test", command="sleep", args=["5"]
    )


def _active_session() -> DevelopmentSession:
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    return session


def test_critic_registers_with_fixed_role_and_prompt_distinct_from_developer(
    isolated_socket: str, tmp_path
) -> None:
    session = _active_session()
    runtime = _test_runtime()

    agent, _ = register_critic(
        session, runtime, str(tmp_path), socket_name=isolated_socket
    )

    assert agent.role == CRITIC_ROLE
    assert agent.prompt == CRITIC_PROMPT
    assert agent.role != DEVELOPER_ROLE
    assert agent.prompt != DEVELOPER_PROMPT


def test_critic_associated_with_own_runtime_and_active_session(
    isolated_socket: str, tmp_path
) -> None:
    session = _active_session()
    runtime = _test_runtime()

    agent, runtime_instance = register_critic(
        session, runtime, str(tmp_path), socket_name=isolated_socket
    )
    time.sleep(0.3)

    assert agent in list_agents(session)
    assert agent.runtime_id == runtime.id
    assert is_runtime_alive(runtime_instance, socket_name=isolated_socket) is True


def test_critic_state_can_be_queried_same_as_developer(
    isolated_socket: str, tmp_path
) -> None:
    session = _active_session()
    runtime = _test_runtime()

    agent, _ = register_critic(
        session, runtime, str(tmp_path), socket_name=isolated_socket
    )

    assert get_agent_state(agent)["status"] == "idle"
    mark_working(agent)
    assert get_agent_state(agent)["status"] == "working"


def test_developer_and_critic_coexist_without_interference(
    isolated_socket: str, tmp_path
) -> None:
    session = _active_session()

    developer_agent, developer_instance = register_developer(
        session, _test_runtime("dev-runtime"), str(tmp_path), socket_name=isolated_socket
    )
    critic_agent, critic_instance = register_critic(
        session, _test_runtime("critic-runtime"), str(tmp_path), socket_name=isolated_socket
    )
    time.sleep(0.3)

    # Runtimes independientes: session_name distintos, ambos vivos.
    assert developer_instance.session_name != critic_instance.session_name
    assert is_runtime_alive(developer_instance, socket_name=isolated_socket) is True
    assert is_runtime_alive(critic_instance, socket_name=isolated_socket) is True

    # Ambos coexisten en la misma sesión, cada uno con su propio rol.
    agents_in_session = list_agents(session)
    assert developer_agent in agents_in_session
    assert critic_agent in agents_in_session
    assert developer_agent.role == DEVELOPER_ROLE
    assert critic_agent.role == CRITIC_ROLE

    # Estados independientes: cambiar uno no afecta al otro.
    mark_working(developer_agent)
    assert get_agent_state(developer_agent)["status"] == "working"
    assert get_agent_state(critic_agent)["status"] == "idle"

    # Detener el runtime de uno no afecta al del otro.
    stop_runtime(developer_instance, socket_name=isolated_socket)
    assert is_runtime_alive(developer_instance, socket_name=isolated_socket) is False
    assert is_runtime_alive(critic_instance, socket_name=isolated_socket) is True

    stop_runtime(critic_instance, socket_name=isolated_socket)
