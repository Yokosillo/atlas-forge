import time
import uuid

import libtmux
import pytest

from brain.agents import (
    DEVELOPER_PROMPT,
    DEVELOPER_ROLE,
    get_agent_state,
    mark_working,
    register_developer,
)
from brain.core import activate, list_agents
from brain.models import DevelopmentSession, Runtime
from brain.runtime import is_runtime_alive


@pytest.fixture
def isolated_socket():
    """Aísla los tests de esta Task en su propio servidor tmux, para no
    interferir con sesiones tmux reales del entorno (nunca lanzar el
    binario real de Claude Code/OpenCode en tests — misma precaución ya
    aplicada en las Tasks de FB-004 y T-FB005-US01-01)."""
    name = f"brain-test-{uuid.uuid4().hex[:8]}"
    yield name
    try:
        libtmux.Server(socket_name=name).kill()
    except Exception:
        pass


def _test_runtime() -> Runtime:
    # Comando de prueba inocuo (`sleep`), NO el binario real de Claude
    # Code/OpenCode.
    return Runtime(
        id="test-runtime",
        name="Test Runtime",
        type="test",
        command="sleep",
        args=["5"],
    )


def _active_session() -> DevelopmentSession:
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    return session


def test_developer_registers_with_fixed_role_and_prompt(
    isolated_socket: str, tmp_path
) -> None:
    session = _active_session()
    runtime = _test_runtime()

    agent, _ = register_developer(
        session, runtime, str(tmp_path), socket_name=isolated_socket
    )

    assert agent.role == DEVELOPER_ROLE
    assert agent.prompt == DEVELOPER_PROMPT


def test_developer_associated_with_runtime_and_active_session(
    isolated_socket: str, tmp_path
) -> None:
    session = _active_session()
    runtime = _test_runtime()

    agent, runtime_instance = register_developer(
        session, runtime, str(tmp_path), socket_name=isolated_socket
    )
    time.sleep(0.3)

    assert agent in list_agents(session)
    assert agent.runtime_id == runtime.id
    assert is_runtime_alive(runtime_instance, socket_name=isolated_socket) is True


def test_developer_state_can_be_queried_idle_working_unavailable(
    isolated_socket: str, tmp_path
) -> None:
    session = _active_session()
    runtime = _test_runtime()

    agent, _ = register_developer(
        session, runtime, str(tmp_path), socket_name=isolated_socket
    )

    assert get_agent_state(agent)["status"] == "idle"

    mark_working(agent)
    assert get_agent_state(agent)["status"] == "working"


def test_reusing_developer_for_second_task_does_not_relaunch_runtime(
    isolated_socket: str, tmp_path
) -> None:
    session = _active_session()
    runtime = _test_runtime()

    first_agent, first_instance = register_developer(
        session, runtime, str(tmp_path), socket_name=isolated_socket
    )
    time.sleep(0.3)

    second_agent, second_instance = register_developer(
        session, runtime, str(tmp_path), socket_name=isolated_socket
    )

    # Mismo Agent, mismo RuntimeInstance (misma sesión tmux) — no una
    # segunda sesión creada desde cero.
    assert second_agent is first_agent
    assert second_instance.session_name == first_instance.session_name
    assert is_runtime_alive(second_instance, socket_name=isolated_socket) is True

    # Solo un Developer en la sesión, no dos copias.
    developers = [a for a in list_agents(session) if a.role == DEVELOPER_ROLE]
    assert len(developers) == 1
