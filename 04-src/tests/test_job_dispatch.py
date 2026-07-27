import uuid
from pathlib import Path

import libtmux
import pytest

from brain.dispatcher import JobReportTimeoutError, dispatch_job
from brain.models import Agent, Job, Runtime
from brain.runtime import RuntimeInstance, start_runtime, stop_runtime

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


def _make_agent() -> Agent:
    return Agent(
        id="a1", name="test-agent", role="developer", prompt="p", runtime_id="r1"
    )


def _make_job(description: str = "implement the feature") -> Job:
    return Job(id="j1", session_id="s1", agent_id="a1", description=description)


def _launch_cooperative_test_runtime(
    isolated_socket: str, tmp_path, extra_env: str = ""
) -> RuntimeInstance:
    # Runtime de prueba: un script cooperativo determinista que simula el
    # comportamiento de un agente instruible (como Claude Code/OpenCode
    # real seguiría la instrucción de auto-reporte), NUNCA el binario real.
    # `extra_env` permite parametrizar el comportamiento del doble de
    # prueba (SIM_DELAY, SIM_FAIL) vía variables de entorno del comando.
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


def test_dispatch_job_success_registers_result_and_returns_agent_to_idle(
    isolated_socket: str, tmp_path
) -> None:
    runtime_instance = _launch_cooperative_test_runtime(isolated_socket, tmp_path)
    agent = _make_agent()
    job = _make_job()

    dispatch_job(job, agent, runtime_instance, socket_name=isolated_socket)

    assert job.status == "completed"
    assert "line one of the cooperative result" in job.result
    assert "line two of the cooperative result" in job.result
    # El marcador de fin no forma parte del resultado registrado.
    assert "___FACTORY_BRAIN_JOB_DONE___" not in job.result
    assert agent.status == "idle"

    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_dispatch_job_agent_reported_failure_registers_reason_and_returns_agent_to_idle(
    isolated_socket: str, tmp_path
) -> None:
    # El agente cooperativo reporta explícitamente que no pudo completar
    # la instrucción (SIM_FAIL=1) — pero SÍ escribe el fichero y el
    # marcador de fin, así que dispatch_job lo trata como un reporte
    # recibido, no como un timeout. En el mecanismo de auto-reporte, la
    # única señal de "fallo" que dispatch_job puede detectar por sí mismo
    # es la ausencia de reporte (timeout); el contenido de un reporte
    # recibido, aunque describa un fallo del agente, se registra como
    # resultado del Job en `completed` — el propio texto informa del
    # fallo, que es lo esperable en un mecanismo cooperativo sin exit code.
    runtime_instance = _launch_cooperative_test_runtime(
        isolated_socket, tmp_path, extra_env="SIM_FAIL=1"
    )
    agent = _make_agent()
    job = _make_job()

    dispatch_job(job, agent, runtime_instance, socket_name=isolated_socket)

    assert job.status == "completed"
    assert "the agent could not complete the instruction" in job.result
    assert agent.status == "idle"

    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_dispatch_job_no_report_marks_job_failed_by_timeout_and_agent_idle(
    isolated_socket: str, tmp_path
) -> None:
    # Runtime que nunca reporta (simula un cuelgue real o un agente que no
    # sigue la instrucción de auto-reporte): un shell puro que no
    # interpreta la instrucción de reporte en absoluto.
    runtime = Runtime(
        id="test-runtime", name="Test Runtime", type="test", command="bash", args=[]
    )
    agent = _make_agent()
    runtime_instance = start_runtime(
        runtime, agent, str(tmp_path), socket_name=isolated_socket
    )
    job = _make_job()

    dispatch_job(
        job,
        agent,
        runtime_instance,
        timeout_seconds=1.0,
        poll_interval_seconds=0.1,
        socket_name=isolated_socket,
    )

    assert job.status == "failed"
    assert "Timeout" in job.result
    assert agent.status == "idle"

    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_wait_for_report_raises_directly_on_timeout() -> None:
    from brain.dispatcher.job_dispatch import _wait_for_report

    non_existent_file = Path("/tmp/factory-brain-test-never-exists-12345.txt")

    with pytest.raises(JobReportTimeoutError):
        _wait_for_report(
            non_existent_file, timeout_seconds=0.3, poll_interval_seconds=0.1
        )


def test_dispatch_job_reused_runtime_does_not_leak_previous_job_report(
    isolated_socket: str, tmp_path
) -> None:
    # Reutilizar el mismo runtime (mismo agente) para un segundo Job usa
    # un fichero de reporte distinto (uuid por Job) — no hay posibilidad
    # de arrastrar el resultado del Job anterior, a diferencia del
    # mecanismo de capture-pane descartado.
    runtime_instance = _launch_cooperative_test_runtime(isolated_socket, tmp_path)
    agent = _make_agent()

    first_job = _make_job()
    dispatch_job(first_job, agent, runtime_instance, socket_name=isolated_socket)
    assert "cooperative result" in first_job.result

    second_job = _make_job()
    dispatch_job(second_job, agent, runtime_instance, socket_name=isolated_socket)

    assert "cooperative result" in second_job.result
    # Ambos resultados son idénticos en contenido (mismo script cooperativo
    # determinista), pero cada uno se generó a partir de un fichero de
    # reporte propio — no hay dependencia entre ambos.
    assert first_job.result == second_job.result

    stop_runtime(runtime_instance, socket_name=isolated_socket)
