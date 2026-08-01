import pytest

from brain.core.session_lifecycle import activate, assign_agent
from brain.dispatcher import JobCreationError, create_and_record_job, list_jobs_for_session
from brain.dispatcher.job_history_registry import _reset_registry_for_tests
from brain.models import Agent, DevelopmentSession


@pytest.fixture(autouse=True)
def _clean_job_history():
    _reset_registry_for_tests()
    yield
    _reset_registry_for_tests()


def _active_session_with_agent(agent: Agent) -> DevelopmentSession:
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    assign_agent(session, agent)
    return session


def test_create_and_record_job_creates_and_registers_in_history() -> None:
    developer = Agent(
        id="a-dev", name="Developer", role="developer", prompt="p", runtime_id="r1"
    )
    session = _active_session_with_agent(developer)

    job = create_and_record_job("implement the feature", developer, session)

    assert job.status == "created"
    assert list_jobs_for_session(session.id) == [job]


def test_create_and_record_job_does_not_register_when_creation_is_rejected() -> None:
    developer = Agent(
        id="a-dev",
        name="Developer",
        role="developer",
        prompt="p",
        runtime_id="r1",
        status="working",
    )
    session = _active_session_with_agent(developer)

    with pytest.raises(JobCreationError):
        create_and_record_job("implement the feature", developer, session)

    assert list_jobs_for_session(session.id) == []
