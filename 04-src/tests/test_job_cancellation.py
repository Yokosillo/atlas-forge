"""Tests de T-AF008-US05-01: transición `cancelled` de Job y mecanismo de
interrupción de `_wait_for_report` desde una petición concurrente.

`dispatch_job` es síncrono y bloqueante (corre en el hilo del threadpool
de FastAPI que atiende `POST /jobs`) — para simular "cancelar un Job en
curso desde otra petición", estos tests lanzan `dispatch_job` en su propio
hilo (`threading.Thread`, doble de un segundo hilo servidor real) mientras
el hilo principal del test llama a `request_cancellation` y mide cuánto
tarda `dispatch_job` en devolver el control, exactamente el criterio de
aceptación: "interrumpe la espera... antes de su timeout normal,
verificado con test de tiempos"."""

import threading
import time
import uuid
from pathlib import Path

import libtmux
import pytest

from atlas_forge.dispatcher import (
    JobCancellationRejectedError,
    dispatch_job,
    request_cancellation,
)
from atlas_forge.dispatcher.job_cancellation_registry import _reset_registry_for_tests
from atlas_forge.dispatcher.job_lifecycle import InvalidJobTransitionError, mark_cancelled
from atlas_forge.models import Agent, Job, Runtime
from atlas_forge.runtime import RuntimeInstance, is_runtime_alive, start_runtime, stop_runtime

_COOPERATIVE_AGENT_SCRIPT = str(
    Path(__file__).parent / "fixtures" / "cooperative_agent_sim.sh"
)


@pytest.fixture(autouse=True)
def _clean_cancellation_registry():
    _reset_registry_for_tests()
    yield
    _reset_registry_for_tests()


@pytest.fixture
def isolated_socket():
    name = f"atlas_forge-test-{uuid.uuid4().hex[:8]}"
    try:
        yield name
    finally:
        try:
            libtmux.Server(socket_name=name).kill()
        except Exception:
            pass


def _make_agent() -> Agent:
    return Agent(
        id="a1", name="test-agent", role="developer", prompt="p", runtime_id="r1"
    )


def _make_job(description: str = "implement the feature") -> Job:
    return Job(id="j1", session_id="s1", agent_id="a1", description=description)


def _launch_cooperative_test_runtime(
    isolated_socket: str, tmp_path, extra_env: str = ""
) -> RuntimeInstance:
    command = f"{extra_env} bash".strip()
    runtime = Runtime(
        id="test-runtime",
        name="Test Runtime",
        type="test",
        command=command,
        args=[_COOPERATIVE_AGENT_SCRIPT],
    )
    agent = _make_agent()
    return start_runtime(runtime, agent, str(tmp_path), socket_name=isolated_socket)


# --- Transición de estado (dominio puro, sin tmux) -------------------------


def test_running_job_can_transition_to_cancelled() -> None:
    job = _make_job()
    job.status = "running"

    mark_cancelled(job, reason="cancelado por el usuario")

    assert job.status == "cancelled"
    assert job.result == "cancelado por el usuario"


@pytest.mark.parametrize("status", ["created", "completed", "failed", "cancelled"])
def test_no_other_status_can_transition_to_cancelled(status: str) -> None:
    job = _make_job()
    job.status = status

    with pytest.raises(InvalidJobTransitionError):
        mark_cancelled(job, reason="cancelado por el usuario")


# --- request_cancellation: rechazo explícito para estados no running -------


@pytest.mark.parametrize("status", ["created", "completed", "failed", "cancelled"])
def test_request_cancellation_is_rejected_for_a_job_not_running(status: str) -> None:
    job = _make_job()
    job.status = status

    with pytest.raises(JobCancellationRejectedError, match=status):
        request_cancellation(job)

    # Sin efecto secundario: el estado del Job no cambia por el intento.
    assert job.status == status


# --- Interrupción real de dispatch_job/_wait_for_report (tmux real) --------


def test_cancelling_a_running_job_interrupts_the_wait_well_before_timeout(
    isolated_socket: str, tmp_path
) -> None:
    runtime_instance = _launch_cooperative_test_runtime(
        isolated_socket, tmp_path, extra_env="SIM_DELAY=10"
    )
    agent = _make_agent()
    job = _make_job()

    dispatch_thread = threading.Thread(
        target=dispatch_job,
        args=(job, agent, runtime_instance),
        kwargs={
            "timeout_seconds": 30.0,
            "poll_interval_seconds": 0.1,
            "socket_name": isolated_socket,
        },
    )

    started_at = time.monotonic()
    dispatch_thread.start()

    # Espera a que el Job esté realmente `running` antes de cancelarlo
    # (evita una condición de carrera contra el arranque del propio hilo).
    deadline = time.monotonic() + 5.0
    while job.status != "running" and time.monotonic() < deadline:
        time.sleep(0.02)
    assert job.status == "running"

    request_cancellation(job)
    dispatch_thread.join(timeout=5.0)
    elapsed = time.monotonic() - started_at

    assert not dispatch_thread.is_alive()
    assert job.status == "cancelled"
    assert agent.status == "idle"
    # Muy por debajo tanto del timeout configurado (30s) como del delay
    # simulado del agente cooperativo (10s) — la cancelación interrumpe el
    # polling, no espera a ninguno de los dos.
    assert elapsed < 3.0

    # La sesión tmux del agente NO se toca al cancelar (criterio explícito
    # de la Task) — el runtime sigue vivo, listo para que stop_agent lo
    # detenga si se decide hacerlo por separado.
    assert is_runtime_alive(runtime_instance, socket_name=isolated_socket) is True

    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_agent_is_idle_after_cancellation_and_can_receive_a_new_job_immediately(
    isolated_socket: str, tmp_path
) -> None:
    runtime_instance = _launch_cooperative_test_runtime(
        isolated_socket, tmp_path, extra_env="SIM_DELAY=10"
    )
    agent = _make_agent()
    job = _make_job()

    dispatch_thread = threading.Thread(
        target=dispatch_job,
        args=(job, agent, runtime_instance),
        kwargs={
            "timeout_seconds": 30.0,
            "poll_interval_seconds": 0.1,
            "socket_name": isolated_socket,
        },
    )
    dispatch_thread.start()

    deadline = time.monotonic() + 5.0
    while job.status != "running" and time.monotonic() < deadline:
        time.sleep(0.02)

    request_cancellation(job)
    dispatch_thread.join(timeout=5.0)

    assert agent.status == "idle"

    # Criterio de aceptación explícito: el agente puede recibir un Job
    # nuevo de inmediato tras la cancelación — se despacha un segundo Job
    # real sobre el mismo runtime/agente y se verifica que se completa con
    # normalidad (sin SIM_DELAY esta vez, el doble de prueba reporta rápido).
    second_job = _make_job(description="second job after cancellation")
    dispatch_job(second_job, agent, runtime_instance, socket_name=isolated_socket)

    assert second_job.status == "completed"
    assert agent.status == "idle"

    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_cancellation_registry_is_cleared_after_dispatch_resolves(
    isolated_socket: str, tmp_path
) -> None:
    """No se acumulan entradas del registro de cancelación indefinidamente:
    tras resolverse el despacho (con o sin cancelación), la entrada de ese
    `job.id` se limpia."""
    from atlas_forge.dispatcher.job_cancellation_registry import (
        is_job_cancellation_requested,
    )

    runtime_instance = _launch_cooperative_test_runtime(isolated_socket, tmp_path)
    agent = _make_agent()
    job = _make_job()

    dispatch_job(job, agent, runtime_instance, socket_name=isolated_socket)

    assert job.status == "completed"
    assert is_job_cancellation_requested(job.id) is False

    stop_runtime(runtime_instance, socket_name=isolated_socket)
