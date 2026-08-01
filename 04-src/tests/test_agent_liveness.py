import uuid

import libtmux
import pytest

from brain.agents import mark_stopped, mark_unavailable, refresh_agent_liveness
from brain.core.session_lifecycle import activate
from brain.dashboard import launch_agent
from brain.models import Agent, DevelopmentSession
from brain.runtime import is_runtime_alive
from brain.tmux.manager import kill_session


@pytest.fixture(autouse=True)
def _no_real_runtime(monkeypatch):
    """Mismo patrón de aislamiento ya usado en test_launch_agent.py: nunca
    invocar los binarios reales de Claude Code/OpenCode en tests."""
    import brain.runtime.claude_code as claude_code_module

    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_COMMAND", "sleep")
    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_ARGS", ["5"])


@pytest.fixture
def isolated_socket():
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


def test_refresh_agent_liveness_transitions_to_unavailable_when_runtime_died_externally(
    isolated_socket: str, tmp_path
) -> None:
    # Criterio de aceptación: "un agente cuyo proceso tmux se mata
    # externamente (tmux kill-session directo, fuera de stop_agent) pasa
    # a reportarse como unavailable la próxima vez que se consulte su
    # estado" — nunca sigue como idle/working.
    session = _active_session()
    agent, runtime_instance = launch_agent(
        "developer", "claude-code", None, session, str(tmp_path), socket_name=isolated_socket
    )
    assert agent.status == "idle"

    # Muerte externa real, NO vía stop_agent: mata la sesión tmux
    # directamente, simulando un crash/OOM/kill manual accidental.
    kill_session(runtime_instance.session_name, socket_name=isolated_socket)
    assert is_runtime_alive(runtime_instance, socket_name=isolated_socket) is False

    result = refresh_agent_liveness(agent, socket_name=isolated_socket)

    assert result is agent
    assert agent.status == "unavailable"


def test_refresh_agent_liveness_does_not_touch_a_live_agent(
    isolated_socket: str, tmp_path
) -> None:
    session = _active_session()
    agent, runtime_instance = launch_agent(
        "developer", "claude-code", None, session, str(tmp_path), socket_name=isolated_socket
    )

    refresh_agent_liveness(agent, socket_name=isolated_socket)

    assert agent.status == "idle"

    from brain.runtime import stop_runtime

    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_refresh_agent_liveness_never_rewrites_a_stopped_agent() -> None:
    # Criterio de aceptación: un agente detenido a propósito (stopped) no
    # se ve afectado — sigue stopped, no se reescribe a unavailable, ni
    # siquiera si (por construcción) ya no tiene runtime vivo/registrado.
    agent = Agent(
        id="a1", name="test", role="developer", prompt="p", runtime_id="r1", status="idle"
    )
    mark_stopped(agent)
    assert agent.status == "stopped"

    result = refresh_agent_liveness(agent)

    assert result is agent
    assert agent.status == "stopped"


def test_refresh_agent_liveness_does_not_touch_an_already_unavailable_agent() -> None:
    agent = Agent(
        id="a1", name="test", role="developer", prompt="p", runtime_id="r1", status="idle"
    )
    mark_unavailable(agent)
    assert agent.status == "unavailable"

    # Sin runtime registrado en absoluto (no se llega a comprobar nada
    # real) — no debe lanzar ni intentar una transición unavailable->unavailable.
    refresh_agent_liveness(agent)

    assert agent.status == "unavailable"


def test_refresh_agent_liveness_with_no_registered_runtime_does_not_raise() -> None:
    # Un agente cuyo registro de runtime se perdió (p. ej. reinicio del
    # proceso) no debe hacer fallar la consulta de estado — no hay nada
    # que verificar, se devuelve tal cual.
    agent = Agent(
        id="never-registered",
        name="test",
        role="developer",
        prompt="p",
        runtime_id="r1",
        status="idle",
    )

    result = refresh_agent_liveness(agent)

    assert result is agent
    assert agent.status == "idle"


def test_refresh_agent_liveness_transitions_a_working_agent_too(
    isolated_socket: str, tmp_path
) -> None:
    # La verificación también aplica a un agente `working`, no solo `idle`.
    from brain.agents.lifecycle import mark_working

    session = _active_session()
    agent, runtime_instance = launch_agent(
        "developer", "claude-code", None, session, str(tmp_path), socket_name=isolated_socket
    )
    mark_working(agent)

    kill_session(runtime_instance.session_name, socket_name=isolated_socket)

    refresh_agent_liveness(agent, socket_name=isolated_socket)

    assert agent.status == "unavailable"
