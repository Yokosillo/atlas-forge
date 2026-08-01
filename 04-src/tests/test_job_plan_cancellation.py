"""Tests de T-FB008-US08-01: transición `approved → cancelled` de un
`JobPlan` y detención del bucle de despacho de pasos pendientes,
reutilizando el mecanismo de cancelación de Job individual ya construido
en T-FB008-US05-01 para el paso `agent` que esté `running`.

`dispatch_plan` corre bloqueante (mismo patrón que `dispatch_job`) — para
simular "cancelar un plan en curso desde otra petición", estos tests
lanzan `dispatch_plan` en su propio hilo mientras el hilo principal llama
a `request_cancellation` y mide cuánto tarda `dispatch_plan` en devolver
el control, mismo criterio de aceptación que T-FB008-US05-01: "verificado
con tmux real y un test de tiempos"."""

import threading
import time
import uuid
from pathlib import Path

import libtmux
import pytest

from brain.core.session_lifecycle import activate, assign_agent
from brain.dispatcher import dispatch_plan
from brain.dispatcher.job_cancellation_registry import (
    _reset_registry_for_tests as _reset_job_cancellation,
)
from brain.dispatcher.job_plan_cancellation import (
    JobPlanCancellationRejectedError,
    request_cancellation,
)
from brain.dispatcher.job_plan_cancellation_registry import (
    _reset_registry_for_tests as _reset_plan_cancellation,
)
from brain.models import Agent, DevelopmentSession, JobPlan, JobPlanStep, Runtime
from brain.runtime import (
    is_runtime_alive,
    register_runtime_instance_for_agent,
    start_runtime,
    stop_runtime,
)

_COOPERATIVE_AGENT_SCRIPT = str(
    Path(__file__).parent / "fixtures" / "cooperative_agent_sim.sh"
)


@pytest.fixture(autouse=True)
def _clean_registries():
    _reset_job_cancellation()
    _reset_plan_cancellation()
    yield
    _reset_job_cancellation()
    _reset_plan_cancellation()


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


def _active_session_with_developer(agent: Agent) -> DevelopmentSession:
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    assign_agent(session, agent)
    return session


def _launch_cooperative_developer(
    isolated_socket: str, tmp_path, extra_env: str = ""
):
    command = f"{extra_env} bash".strip()
    runtime = Runtime(
        id="test-runtime",
        name="Test Runtime",
        type="test",
        command=command,
        args=[_COOPERATIVE_AGENT_SCRIPT],
    )
    agent = Agent(
        id="a-dev", name="developer", role="developer", prompt="p", runtime_id="r1"
    )
    runtime_instance = start_runtime(runtime, agent, str(tmp_path), socket_name=isolated_socket)
    register_runtime_instance_for_agent(agent.id, runtime_instance)
    return agent, runtime_instance


# --- request_cancellation: rechazo explícito para estados no approved -----


@pytest.mark.parametrize("status", ["proposed", "rejected", "blocked", "cancelled"])
def test_request_cancellation_is_rejected_for_a_plan_not_approved(status: str) -> None:
    plan = JobPlan(goal="FB999-US01", status=status)

    with pytest.raises(JobPlanCancellationRejectedError, match=status):
        request_cancellation(plan)

    assert plan.status == status


# --- Cancelación con un paso 'agent' running (tmux real, test de tiempos) --


def test_cancelling_a_plan_with_a_running_step_cancels_it_and_the_plan(
    isolated_socket: str, tmp_path
) -> None:
    agent, runtime_instance = _launch_cooperative_developer(
        isolated_socket, tmp_path, extra_env="SIM_DELAY=10"
    )
    session = _active_session_with_developer(agent)
    plan = JobPlan(
        goal="FB999-US01",
        steps=[
            JobPlanStep(description="paso 1", mechanism="agent", agent_role="developer"),
            JobPlanStep(description="paso 2", mechanism="agent", agent_role="developer"),
        ],
        status="approved",
    )

    dispatch_thread = threading.Thread(
        target=dispatch_plan,
        args=(plan, session),
        kwargs={"socket_name": isolated_socket},
    )

    started_at = time.monotonic()
    dispatch_thread.start()

    deadline = time.monotonic() + 5.0
    while plan.steps[0].status != "running" and time.monotonic() < deadline:
        time.sleep(0.02)
    assert plan.steps[0].status == "running"

    request_cancellation(plan)
    dispatch_thread.join(timeout=5.0)
    elapsed = time.monotonic() - started_at

    assert not dispatch_thread.is_alive()
    assert plan.status == "cancelled"
    assert plan.steps[0].status == "cancelled"
    # Ningún paso posterior se despacha tras la cancelación.
    assert plan.steps[1].status == "pending"
    assert agent.status == "idle"
    # Muy por debajo del delay simulado del agente (10s).
    assert elapsed < 3.0

    assert is_runtime_alive(runtime_instance, socket_name=isolated_socket) is True

    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_no_pending_step_is_dispatched_after_cancellation_with_multiple_steps(
    isolated_socket: str, tmp_path
) -> None:
    """Criterio de aceptación explícito: 'Ningún paso pendiente posterior
    se despacha tras la cancelación, verificado con un plan de varios
    pasos.' Plan de 4 pasos — se cancela durante el primero, se verifica
    que NINGUNO de los 3 siguientes llega a ejecutarse (siguen `pending`,
    nunca `running`/`completed`/`failed`)."""
    agent, runtime_instance = _launch_cooperative_developer(
        isolated_socket, tmp_path, extra_env="SIM_DELAY=10"
    )
    session = _active_session_with_developer(agent)
    plan = JobPlan(
        goal="FB999-US01",
        steps=[
            JobPlanStep(description=f"paso {i}", mechanism="agent", agent_role="developer")
            for i in range(1, 5)
        ],
        status="approved",
    )

    dispatch_thread = threading.Thread(
        target=dispatch_plan,
        args=(plan, session),
        kwargs={"socket_name": isolated_socket},
    )
    dispatch_thread.start()

    deadline = time.monotonic() + 5.0
    while plan.steps[0].status != "running" and time.monotonic() < deadline:
        time.sleep(0.02)

    request_cancellation(plan)
    dispatch_thread.join(timeout=5.0)

    assert plan.status == "cancelled"
    assert plan.steps[0].status == "cancelled"
    assert [step.status for step in plan.steps[1:]] == ["pending", "pending", "pending"]

    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_agent_is_idle_after_plan_cancellation_and_can_receive_a_new_job(
    isolated_socket: str, tmp_path
) -> None:
    """Criterio de aceptación: 'El agente que estaba ejecutando el paso
    cancelado queda idle, disponible de inmediato para otro Job.'"""
    from brain.dispatcher import create_and_record_job, dispatch_job
    from brain.runtime import get_runtime_instance_for_agent

    agent, runtime_instance = _launch_cooperative_developer(
        isolated_socket, tmp_path, extra_env="SIM_DELAY=10"
    )
    session = _active_session_with_developer(agent)
    plan = JobPlan(
        goal="FB999-US01",
        steps=[JobPlanStep(description="paso 1", mechanism="agent", agent_role="developer")],
        status="approved",
    )

    dispatch_thread = threading.Thread(
        target=dispatch_plan,
        args=(plan, session),
        kwargs={"socket_name": isolated_socket},
    )
    dispatch_thread.start()

    deadline = time.monotonic() + 5.0
    while plan.steps[0].status != "running" and time.monotonic() < deadline:
        time.sleep(0.02)

    request_cancellation(plan)
    dispatch_thread.join(timeout=5.0)

    assert agent.status == "idle"

    new_job = create_and_record_job("un job nuevo tras cancelar el plan", agent, session)
    dispatch_job(
        new_job, agent, get_runtime_instance_for_agent(agent.id), socket_name=isolated_socket
    )

    assert new_job.status == "completed"
    assert agent.status == "idle"

    stop_runtime(runtime_instance, socket_name=isolated_socket)


# --- Rechazo de cancelación sobre planes ya terminados ----------------------


def test_cancelling_an_already_blocked_plan_is_rejected_with_explicit_message() -> None:
    plan = JobPlan(goal="FB999-US01", status="blocked")

    with pytest.raises(JobPlanCancellationRejectedError, match="blocked"):
        request_cancellation(plan)


def test_cancelling_a_plan_with_all_steps_completed_is_rejected() -> None:
    """Criterio de aceptación explícito: 'Cancelar un plan ya blocked o sin
    pasos pendientes (todos completed) se rechaza con mensaje explícito.'
    Un plan cuyo despacho ya terminó con éxito permanece `approved` (no
    hay estado 'completed' de plan en este dominio, ver
    job_plan_lifecycle.py) — "ya terminó" se detecta por la ausencia de
    pasos `pending`/`running`, no por `plan.status`."""
    plan = JobPlan(
        goal="FB999-US01",
        steps=[JobPlanStep(description="paso 1", mechanism="agent", status="completed")],
        status="approved",
    )

    with pytest.raises(JobPlanCancellationRejectedError, match="pendientes"):
        request_cancellation(plan)

    assert plan.status == "approved"
