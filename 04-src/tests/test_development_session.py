import pytest

from brain.core import (
    InvalidSessionTransitionError,
    activate,
    close,
    get_session_state,
)
from brain.models import DevelopmentSession


def test_development_session_constructed_in_created_state() -> None:
    session = DevelopmentSession(id="s1", project_id="p1")

    assert session.status == "created"
    assert session.agents == []


def test_activate_transitions_from_created_to_active() -> None:
    session = DevelopmentSession(id="s1", project_id="p1")

    activate(session)

    assert session.status == "active"


def test_close_transitions_from_active_to_closed() -> None:
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)

    close(session)

    assert session.status == "closed"


def test_close_rejects_transition_from_created() -> None:
    session = DevelopmentSession(id="s1", project_id="p1")

    with pytest.raises(InvalidSessionTransitionError):
        close(session)

    assert session.status == "created"


def test_activate_rejects_transition_from_closed() -> None:
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    close(session)

    with pytest.raises(InvalidSessionTransitionError):
        activate(session)

    assert session.status == "closed"


def test_get_session_state_for_freshly_created_session() -> None:
    session = DevelopmentSession(id="s1", project_id="p1")

    state = get_session_state(session)

    assert state == {
        "id": "s1",
        "project_id": "p1",
        "status": "created",
        "agents": [],
    }
