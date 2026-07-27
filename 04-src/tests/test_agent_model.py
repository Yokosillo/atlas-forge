import pytest

from brain.agents import (
    InvalidAgentTransitionError,
    get_agent_state,
    mark_idle,
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
