import time
import uuid

import libtmux
import pytest

from brain.agents import get_agent_state, register_agent
from brain.core import activate, list_agents
from brain.models import DevelopmentSession, Runtime
from brain.runtime import is_runtime_alive


@pytest.fixture
def isolated_socket():
    """Aísla los tests de esta Task en su propio servidor tmux, para no
    interferir con sesiones tmux reales del entorno (misma precaución que
    en las Tasks de FB-004: nunca lanzar binarios reales de runtime en
    tests). Se pasa explícitamente como `socket_name` a `register_agent`
    en vez de depender de un default de módulo (que se congela en tiempo
    de definición y no es interceptable con monkeypatch — lección ya
    aplicada en T-FB004-US01-02)."""
    name = f"brain-test-{uuid.uuid4().hex[:8]}"
    yield name
    try:
        libtmux.Server(socket_name=name).kill()
    except Exception:
        pass


def _test_runtime() -> Runtime:
    # Comando de prueba inocuo (`sleep`), NO un binario real de runtime
    # (claude/opencode). Misma precaución ya aplicada en las Tasks de FB-004.
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


def test_register_agent_launches_runtime_and_is_listed_in_session(
    isolated_socket: str, tmp_path
) -> None:
    session = _active_session()
    runtime = _test_runtime()

    agent, runtime_instance = register_agent(
        name="test-agent",
        role="developer",
        prompt="test prompt",
        runtime=runtime,
        session=session,
        project_path=str(tmp_path),
        socket_name=isolated_socket,
    )
    time.sleep(0.3)

    assert agent in list_agents(session)
    assert is_runtime_alive(runtime_instance, socket_name=isolated_socket) is True


def test_newly_registered_agent_state_is_idle(isolated_socket: str, tmp_path) -> None:
    session = _active_session()
    runtime = _test_runtime()

    agent, _ = register_agent(
        name="test-agent",
        role="developer",
        prompt="test prompt",
        runtime=runtime,
        session=session,
        project_path=str(tmp_path),
        socket_name=isolated_socket,
    )

    assert get_agent_state(agent)["status"] == "idle"


def test_register_agent_does_not_assume_a_concrete_role(
    isolated_socket: str, tmp_path
) -> None:
    # El mecanismo genérico acepta cualquier role/prompt como parámetro,
    # sin fijar Developer/Critic — la especialización concreta vive en
    # Tasks posteriores (T-FB005-US01-02, T-FB005-US02-01).
    session = _active_session()
    runtime = _test_runtime()

    agent, _ = register_agent(
        name="future-role-agent",
        role="architect",
        prompt="future prompt",
        runtime=runtime,
        session=session,
        project_path=str(tmp_path),
        socket_name=isolated_socket,
    )

    assert agent.role == "architect"
    assert agent.prompt == "future prompt"
