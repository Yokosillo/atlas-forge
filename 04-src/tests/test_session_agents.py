import pytest

from brain.core import (
    SessionNotActiveError,
    activate,
    assign_agent,
    close,
    list_agents,
)
from brain.models import DevelopmentSession


def test_assign_agent_to_active_session_is_listed() -> None:
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    agent = object()

    assign_agent(session, agent)

    assert list_agents(session) == [agent]


def test_assign_agent_rejected_when_session_is_created() -> None:
    session = DevelopmentSession(id="s1", project_id="p1")
    agent = object()

    with pytest.raises(SessionNotActiveError):
        assign_agent(session, agent)

    assert list_agents(session) == []


def test_assign_agent_rejected_when_session_is_closed() -> None:
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    close(session)
    agent = object()

    with pytest.raises(SessionNotActiveError):
        assign_agent(session, agent)

    assert list_agents(session) == []


def test_assign_same_agent_twice_does_not_duplicate() -> None:
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    agent = object()

    assign_agent(session, agent)
    assign_agent(session, agent)

    assert list_agents(session) == [agent]


def test_list_agents_returns_all_distinct_agents_assigned() -> None:
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    first_agent = object()
    second_agent = object()

    assign_agent(session, first_agent)
    assign_agent(session, second_agent)

    assert list_agents(session) == [first_agent, second_agent]
