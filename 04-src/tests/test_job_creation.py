import pytest

from atlas_forge.agents.lifecycle import mark_working
from atlas_forge.core.session_lifecycle import activate, assign_agent
from atlas_forge.dispatcher import JobCreationError, create_job
from atlas_forge.models import Agent, DevelopmentSession


def _make_agent(status: str = "idle") -> Agent:
    return Agent(
        id="a1",
        name="test-agent",
        role="developer",
        prompt="test prompt",
        runtime_id="r1",
        status=status,
    )


def _active_session_with_agent(agent: Agent) -> DevelopmentSession:
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    assign_agent(session, agent)
    return session


def test_create_job_with_idle_agent_in_active_session_produces_created_job() -> None:
    agent = _make_agent(status="idle")
    session = _active_session_with_agent(agent)

    job = create_job("implement the feature", agent, session)

    assert job.status == "created"
    assert job.description == "implement the feature"
    assert job.session_id == session.id
    assert job.agent_id == agent.id


def test_create_job_rejected_when_agent_not_in_active_session() -> None:
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    outsider_agent = _make_agent(status="idle")
    # `outsider_agent` nunca se asigna a `session`.

    with pytest.raises(JobCreationError):
        create_job("implement the feature", outsider_agent, session)


def test_create_job_rejected_when_no_active_session() -> None:
    agent = _make_agent(status="idle")
    session = DevelopmentSession(id="s1", project_id="p1")
    # La sesión permanece en `created`, nunca se activa.

    with pytest.raises(JobCreationError):
        create_job("implement the feature", agent, session)


def test_create_job_rejected_when_agent_is_not_idle() -> None:
    agent = _make_agent(status="idle")
    session = _active_session_with_agent(agent)
    mark_working(agent)

    with pytest.raises(JobCreationError):
        create_job("implement the feature", agent, session)
