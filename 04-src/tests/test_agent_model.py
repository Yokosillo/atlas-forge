import pytest

from brain.agents import (
    InvalidAgentTransitionError,
    get_agent_state,
    mark_idle,
    mark_stopped,
    mark_unavailable,
    mark_working,
)
from brain.models import Agent


def _make_agent(status: str = "idle") -> Agent:
    return Agent(
        id="a1",
        name="test-agent",
        role="developer",
        prompt="test prompt",
        runtime_id="r1",
        status=status,
    )


def test_agent_construction() -> None:
    agent = _make_agent()

    assert agent.id == "a1"
    assert agent.name == "test-agent"
    assert agent.role == "developer"
    assert agent.prompt == "test prompt"
    assert agent.runtime_id == "r1"
    assert agent.status == "idle"


def test_mark_working_transitions_from_idle() -> None:
    agent = _make_agent(status="idle")

    mark_working(agent)

    assert agent.status == "working"


def test_mark_idle_transitions_from_working() -> None:
    agent = _make_agent(status="working")

    mark_idle(agent)

    assert agent.status == "idle"


def test_mark_unavailable_from_idle_and_working() -> None:
    idle_agent = _make_agent(status="idle")
    mark_unavailable(idle_agent)
    assert idle_agent.status == "unavailable"

    working_agent = _make_agent(status="working")
    mark_unavailable(working_agent)
    assert working_agent.status == "unavailable"


def test_mark_working_rejected_from_unavailable() -> None:
    agent = _make_agent(status="unavailable")

    with pytest.raises(InvalidAgentTransitionError):
        mark_working(agent)

    assert agent.status == "unavailable"


def test_mark_stopped_reachable_from_idle_and_working() -> None:
    # Criterio de aceptación explícito de T-FB016-US01-03: `stopped` es
    # alcanzable tanto desde `idle` como desde `working` — detener un
    # agente ocupado también debe ser posible.
    idle_agent = _make_agent(status="idle")
    mark_stopped(idle_agent)
    assert idle_agent.status == "stopped"

    working_agent = _make_agent(status="working")
    mark_stopped(working_agent)
    assert working_agent.status == "stopped"


def test_stopped_has_no_outgoing_transition() -> None:
    # Un agente `stopped` no puede volver a `idle` (ni a ningún otro
    # estado) sin relanzarse desde cero — no confundir con `unavailable`,
    # que sí vuelve a `idle`.
    agent = _make_agent(status="stopped")

    with pytest.raises(InvalidAgentTransitionError):
        mark_idle(agent)
    with pytest.raises(InvalidAgentTransitionError):
        mark_working(agent)
    with pytest.raises(InvalidAgentTransitionError):
        mark_unavailable(agent)

    assert agent.status == "stopped"


def test_stopped_and_unavailable_are_distinct_states() -> None:
    # Distinción explícita pedida por la Task: "detenido a propósito"
    # (stopped) frente a "fallo no solicitado" (unavailable) deben ser
    # estados distintos y distinguibles.
    stopped_agent = _make_agent(status="idle")
    mark_stopped(stopped_agent)

    unavailable_agent = _make_agent(status="idle")
    mark_unavailable(unavailable_agent)

    assert stopped_agent.status != unavailable_agent.status
    assert get_agent_state(stopped_agent)["status"] == "stopped"
    assert get_agent_state(unavailable_agent)["status"] == "unavailable"


def test_get_agent_state_reflects_current_status() -> None:
    agent = _make_agent(status="idle")
    mark_working(agent)

    state = get_agent_state(agent)

    assert state == {
        "id": "a1",
        "name": "test-agent",
        "role": "developer",
        "runtime_id": "r1",
        "status": "working",
    }
