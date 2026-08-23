import uuid

import pytest

from atlas_forge.agents import AgentReleaseError, mark_unavailable, release_agent
from atlas_forge.core.session_lifecycle import activate, list_agents
from atlas_forge.models import Agent, DevelopmentSession


def _active_session() -> DevelopmentSession:
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    return session


def _developer(status: str = "idle") -> Agent:
    return Agent(
        id=f"d-{uuid.uuid4().hex[:8]}",
        name="Developer-1",
        role="developer",
        prompt="p",
        runtime_id="r1",
        status=status,
    )


def test_release_agent_removes_an_unavailable_developer_from_session() -> None:
    """T-AF005-US01-09: un Developer `unavailable` (cayó fuera de atlas_forge) se
    retira de `session.agents`, liberando su plaza del límite."""
    session = _active_session()
    agent = _developer(status="idle")
    mark_unavailable(agent)
    session.agents.append(agent)
    assert agent in list_agents(session)

    release_agent(agent, session)

    assert agent not in list_agents(session)
    # El agente conserva su estado `unavailable` en el objeto Python (no se
    # reescribe a otra cosa) — solo se retira estructuralmente.
    assert agent.status == "unavailable"


def test_release_agent_removes_a_stopped_developer_from_session() -> None:
    session = _active_session()
    agent = _developer(status="stopped")
    session.agents.append(agent)

    release_agent(agent, session)

    assert agent not in list_agents(session)
    assert agent.status == "stopped"


def test_release_agent_rejects_a_working_developer() -> None:
    """Criterio 2: liberar un agente vivo (`working`) se rechaza — para eso
    existe "Detener"."""
    session = _active_session()
    agent = _developer(status="working")
    session.agents.append(agent)

    with pytest.raises(AgentReleaseError):
        release_agent(agent, session)

    # El agente sigue en la sesión intacto.
    assert agent in list_agents(session)
    assert agent.status == "working"


def test_release_agent_rejects_an_idle_developer() -> None:
    session = _active_session()
    agent = _developer(status="idle")
    session.agents.append(agent)

    with pytest.raises(AgentReleaseError):
        release_agent(agent, session)

    assert agent in list_agents(session)
    assert agent.status == "idle"


def test_release_agent_rejects_a_limited_developer() -> None:
    session = _active_session()
    agent = _developer(status="limited")
    session.agents.append(agent)

    with pytest.raises(AgentReleaseError):
        release_agent(agent, session)

    assert agent in list_agents(session)
    assert agent.status == "limited"


def test_release_agent_after_unavailable_allows_relaunching_the_slot() -> None:
    """Criterio 3: tras liberar un `unavailable` con nombre "Developer-N",
    relanzar con `developer_number: N` vuelve a funcionar (el duplicado ya
    no está en la sesión)."""
    from atlas_forge.agents.developer import ACTIVE_DEVELOPER_STATUSES

    session = _active_session()
    agent = _developer(status="unavailable")
    agent.name = "Developer-2"
    session.agents.append(agent)

    # Antes de liberar, el slot Developer-2 sigue bloqueado por el duplicado.
    assert any(
        a.name == "Developer-2" for a in list_agents(session)
    )
    assert agent.status not in ACTIVE_DEVELOPER_STATUSES

    release_agent(agent, session)

    assert all(a.name != "Developer-2" for a in list_agents(session))
