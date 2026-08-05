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
            non_existent_file,
            timeout_seconds=0.3,
            poll_interval_seconds=0.1,
            job_id="never-cancelled-job",
        )


def test_transient_read_failure_is_retried_and_marker_still_wins(
    tmp_path, monkeypatch
) -> None:
    """T-FB008-US01-05, criterio 1: 'Un fallo simulado de lectura puntual
    del fichero de marcador (p. ej. archivo bloqueado momentáneamente) no
    produce JobReportTimeoutError si el marcador aparece correctamente en el
    reintento inmediato.' La primera lectura del fichero lanza un
    `PermissionError` simulado (bloqueo puntual); el reintento inmediato la
    lee bien y devuelve el resultado — sin timeout, sin error."""
    from brain.dispatcher.job_dispatch import _wait_for_report

    report_file = tmp_path / "marker.txt"
    report_file.write_text("result here\n___FACTORY_BRAIN_JOB_DONE___\n")

    real_read_text = Path.read_text
    calls = {"n": 0}

    def flaky_read_text(self, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError("simulated momentary file lock")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", flaky_read_text)

    result = _wait_for_report(
        report_file,
        timeout_seconds=1.0,
        poll_interval_seconds=0.05,
        job_id="transient-failure-job",
    )

    assert result == "result here"
    # La lectura se reintentó tras el fallo (no abortó en el primer error).
    assert calls["n"] >= 2


def test_reading_that_keeps_failing_is_bounded_not_infinite(tmp_path, monkeypatch) -> None:
    """T-FB008-US01-05, punto 2: 'añadir un reintento acotado (1-2 intentos,
    no un bucle indefinido)'. Un fichero que SIEMPRE falla al leer es un
    fallo real (no transitorio): tras el intento inicial + los reintentos
    acotados, `_read_report_with_retry` devuelve `None` (no se queda
    reintentando para siempre) y el poll continúa hasta el timeout."""
    import brain.dispatcher.job_dispatch as dispatch_module

    report_file = tmp_path / "always_fails.txt"
    report_file.write_text("whatever")
    calls = {"n": 0}

    def always_fail(self, *args, **kwargs):
        calls["n"] += 1
        raise PermissionError

    monkeypatch.setattr(Path, "read_text", always_fail)

    result = dispatch_module._read_report_with_retry(report_file)

    assert result is None
    # Intento inicial + reintentos acotados (constante), nunca más.
    assert calls["n"] == dispatch_module._MAX_REPORT_READ_RETRIES + 1


def test_agent_never_reporting_times_out_in_the_same_order_of_time(tmp_path) -> None:
    """T-FB008-US01-05, criterio 2: 'Un agente que efectivamente no reporta
    nunca sigue produciendo JobReportTimeoutError en el mismo orden de tiempo
    que hoy.' Un fichero que nunca aparece (ausencia, no error de lectura) NO
    dispara reintentos, así que el timeout se percibe en ~mismo tiempo (los
    reintentos solo aplican ante OSError de lectura, no ante FileNotFoundError):
    el tiempo total transcurrido no supera sustancialmente el timeout pedido."""
    import time as time_mod

    from brain.dispatcher.job_dispatch import _wait_for_report

    non_existent_file = tmp_path / "never.txt"
    started = time_mod.monotonic()
    with pytest.raises(JobReportTimeoutError):
        _wait_for_report(
            non_existent_file,
            timeout_seconds=0.3,
            poll_interval_seconds=0.05,
            job_id="never-reports-job",
        )
    elapsed = time_mod.monotonic() - started
    # No ampliación sustancial del timeout percibido (ausencia -> sin reintento).
    assert elapsed < 0.8


def test_dispatch_job_recovers_from_a_transient_read_failure(
    isolated_socket: str, tmp_path, monkeypatch
) -> None:
    """T-FB008-US01-05, criterio 1 end-to-end con tmux real: durante un
    despacho real (agente cooperativo), la primera lectura del fichero de
    marcador de ESTE Job falla una vez (bloqueo puntual simulado) y se
    reintenta con éxito — el Job termina `completed`, nunca `failed` por
    timeout. Solo se simula el fallo para el fichero de reporte (uuid
    `factory-brain-job-*`), nunca para otras lecturas."""
    report_pattern = "factory-brain-job-"
    real_read_text = Path.read_text
    calls = {"n": 0}

    def flaky_report_read(self, *args, **kwargs):
        if report_pattern in str(self):
            calls["n"] += 1
            if calls["n"] == 1:
                raise PermissionError("simulated transient read failure")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", flaky_report_read)

    runtime_instance = _launch_cooperative_test_runtime(isolated_socket, tmp_path)
    agent = _make_agent()
    job = _make_job()

    try:
        dispatch_job(job, agent, runtime_instance, socket_name=isolated_socket)
    finally:
        stop_runtime(runtime_instance, socket_name=isolated_socket)

    assert job.status == "completed"
    assert "cooperative result" in job.result
    # El fichero de reporte se leyó (y reintentó) tras el fallo transitorio.
    assert calls["n"] >= 2
    assert agent.status == "idle"


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
