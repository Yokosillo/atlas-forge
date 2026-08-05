import uuid
from pathlib import Path

import libtmux
import pytest

from brain.core.session_lifecycle import activate, assign_agent
from brain.dispatcher import JobCreationError, create_job, dispatch_job
from brain.models import Agent, DevelopmentSession, Job, Runtime
from brain.runtime import start_runtime, stop_runtime

_COOPERATIVE_AGENT_SCRIPT = str(
    Path(__file__).parent / "fixtures" / "cooperative_agent_sim.sh"
)


@pytest.fixture
def isolated_socket():
    """Aísla los tests de esta Task en su propio servidor tmux, para no
    interferir con sesiones tmux reales del entorno (nunca lanzar los
    binarios reales de Claude Code/OpenCode en tests). Se garantiza la
    limpieza del servidor incluso si el test falla a medio camino."""
    name = f"brain-test-{uuid.uuid4().hex[:8]}"
    try:
        yield name
    finally:
        try:
            libtmux.Server(socket_name=name).kill()
        except Exception:
            pass


def _active_session_with_agent(agent: Agent) -> DevelopmentSession:
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    assign_agent(session, agent)
    return session


def _completed_job_with_result(result: str) -> Job:
    return Job(
        id="j-prev",
        session_id="s1",
        agent_id="a-dev",
        description="implement something",
        status="completed",
        result=result,
    )


def test_create_job_with_completed_previous_job_includes_its_result_verbatim() -> None:
    developer = Agent(
        id="a-dev", name="Developer", role="developer", prompt="p", runtime_id="r1"
    )
    critic = Agent(
        id="a-critic", name="Critic", role="critic", prompt="p", runtime_id="r2"
    )
    session = _active_session_with_agent(developer)
    session.agents.append(critic)
    previous_job = _completed_job_with_result("def add(a, b): return a + b")

    new_job = create_job(
        "review this implementation",
        critic,
        session,
        previous_job=previous_job,
    )

    assert new_job.status == "created"
    assert "review this implementation" in new_job.description
    # El resultado del Job anterior se incluye literal, sin alterarlo.
    assert "def add(a, b): return a + b" in new_job.description


def test_create_job_rejects_chaining_developer_result_into_another_developer() -> None:
    """T-FB008-US07-01, criterio 1: encadenar Developer→Developer se
    rechaza con mensaje explícito, sin crear el Job."""
    developer = Agent(
        id="a-dev", name="Developer", role="developer", prompt="p", runtime_id="r1"
    )
    session = _active_session_with_agent(developer)
    previous_job = _completed_job_with_result("def add(a, b): return a + b")

    with pytest.raises(JobCreationError, match="debe encadenarse a un Critic"):
        create_job(
            "implement something else",
            developer,
            session,
            previous_job=previous_job,
        )


def test_create_job_allows_chaining_developer_result_into_critic() -> None:
    """T-FB008-US07-01, criterio 2: encadenar Developer→Critic sigue
    funcionando exactamente igual que antes de esta Task."""
    developer = Agent(
        id="a-dev", name="Developer", role="developer", prompt="p", runtime_id="r1"
    )
    critic = Agent(
        id="a-critic", name="Critic", role="critic", prompt="p", runtime_id="r2"
    )
    session = _active_session_with_agent(developer)
    session.agents.append(critic)
    previous_job = _completed_job_with_result("def add(a, b): return a + b")

    new_job = create_job(
        "review this implementation",
        critic,
        session,
        previous_job=previous_job,
    )

    assert new_job.status == "created"
    assert "def add(a, b): return a + b" in new_job.description


def test_create_job_allows_chaining_critic_result_into_any_role() -> None:
    """T-FB008-US07-01, criterio 3: encadenar Critic→cualquier rol no se ve
    afectado por esta Task (no hay regla explícita que lo restrinja)."""
    critic = Agent(
        id="a-critic", name="Critic", role="critic", prompt="p", runtime_id="r2"
    )
    developer = Agent(
        id="a-dev", name="Developer", role="developer", prompt="p", runtime_id="r1"
    )
    session = _active_session_with_agent(critic)
    session.agents.append(developer)
    critic_job = Job(
        id="j-critic-prev",
        session_id="s1",
        agent_id="a-critic",
        description="review something",
        status="completed",
        result="verdict: approved",
    )

    new_job = create_job(
        "implement the approved changes",
        developer,
        session,
        previous_job=critic_job,
    )

    assert new_job.status == "created"
    assert "verdict: approved" in new_job.description


def test_create_job_rejects_chaining_a_previous_job_not_completed() -> None:
    developer = Agent(
        id="a-dev", name="Developer", role="developer", prompt="p", runtime_id="r1"
    )
    session = _active_session_with_agent(developer)
    running_previous_job = Job(
        id="j-prev",
        session_id="s1",
        agent_id="a-dev",
        description="implement something",
        status="running",
        result="",
    )

    with pytest.raises(JobCreationError):
        create_job(
            "review this implementation",
            developer,
            session,
            previous_job=running_previous_job,
        )


def test_create_job_rejects_chaining_a_completed_job_without_result() -> None:
    # Estado inconsistente que no debería darse en la práctica (mark_completed
    # siempre registra un resultado), pero se valida explícitamente por
    # robustez: un Job "completed" con resultado vacío no es encadenable.
    developer = Agent(
        id="a-dev", name="Developer", role="developer", prompt="p", runtime_id="r1"
    )
    session = _active_session_with_agent(developer)
    empty_result_job = Job(
        id="j-prev",
        session_id="s1",
        agent_id="a-dev",
        description="implement something",
        status="completed",
        result="",
    )

    with pytest.raises(JobCreationError):
        create_job(
            "review this implementation",
            developer,
            session,
            previous_job=empty_result_job,
        )


def test_full_cycle_developer_produces_result_critic_reviews_it_end_to_end(
    isolated_socket: str, tmp_path
) -> None:
    # Ciclo completo de extremo a extremo: crear Job para Developer,
    # enviarlo, recibir resultado; crear Job para Critic encadenando ese
    # resultado, enviarlo, recibir veredicto. Sin copiar/pegar manual entre
    # sesiones tmux — todo pasa por create_job/dispatch_job.
    developer_runtime = Runtime(
        id="dev-runtime",
        name="Developer Runtime",
        type="test",
        command="bash",
        args=[_COOPERATIVE_AGENT_SCRIPT],
    )
    critic_runtime = Runtime(
        id="critic-runtime",
        name="Critic Runtime",
        type="test",
        command="SIM_ROLE=critic bash",
        args=[_COOPERATIVE_AGENT_SCRIPT],
    )

    developer = Agent(
        id="a-dev", name="Developer", role="developer", prompt="p", runtime_id="dev-runtime"
    )
    critic = Agent(
        id="a-critic", name="Critic", role="critic", prompt="p", runtime_id="critic-runtime"
    )

    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    assign_agent(session, developer)
    assign_agent(session, critic)

    developer_instance = start_runtime(
        developer_runtime, developer, str(tmp_path), socket_name=isolated_socket
    )
    critic_instance = start_runtime(
        critic_runtime, critic, str(tmp_path), socket_name=isolated_socket
    )

    try:
        # Job 1: Developer implementa.
        dev_job = create_job("implement the feature", developer, session)
        dispatch_job(dev_job, developer, developer_instance, socket_name=isolated_socket)

        assert dev_job.status == "completed"
        assert developer.status == "idle"
        assert "cooperative result" in dev_job.result

        # Job 2: Critic revisa, encadenando el resultado de Developer.
        critic_job = create_job(
            "review this implementation", critic, session, previous_job=dev_job
        )
        dispatch_job(critic_job, critic, critic_instance, socket_name=isolated_socket)

        assert critic_job.status == "completed"
        assert critic.status == "idle"
        # Critic recibió y usó el resultado real de Developer, no un texto fijo.
        assert "CRITIC VERDICT" in critic_job.result
        assert "cooperative result" in critic_job.result
        assert "verdict: approved" in critic_job.result
    finally:
        stop_runtime(developer_instance, socket_name=isolated_socket)
        stop_runtime(critic_instance, socket_name=isolated_socket)
