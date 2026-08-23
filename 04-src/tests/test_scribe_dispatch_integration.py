import uuid
from pathlib import Path
from unittest.mock import patch

import libtmux
import pytest

from atlas_forge.dispatcher import dispatch_job, get_consecutive_job_count
from atlas_forge.dispatcher.job_count_registry import _reset_registry_for_tests
from atlas_forge.dispatcher.scribe_trigger import DEFAULT_SIZE_THRESHOLD_CHARACTERS
from atlas_forge.local_tools import ScribeUnavailableError
from atlas_forge.models import Agent, Job, Runtime
from atlas_forge.runtime import start_runtime, stop_runtime

_COOPERATIVE_AGENT_SCRIPT = str(
    Path(__file__).parent / "fixtures" / "cooperative_agent_sim.sh"
)


@pytest.fixture(autouse=True)
def _reset_job_count_registry():
    # Registro nuevo en memoria de proceso (T-AF008-US03-02) — se
    # resetea antes/después de cada test para no depender del orden de
    # ejecución, mismo patrón que `session_registry`/`_SessionRegistry`.
    _reset_registry_for_tests()
    yield
    _reset_registry_for_tests()


@pytest.fixture
def isolated_socket():
    """Aísla los tests de esta Task en su propio servidor tmux, con
    limpieza garantizada incluso si el test falla a medio camino — mismo
    patrón que test_job_dispatch.py."""
    name = f"atlas_forge-test-{uuid.uuid4().hex[:8]}"
    try:
        yield name
    finally:
        try:
            libtmux.Server(socket_name=name).kill()
        except Exception:
            pass


def _make_agent(agent_id: str = "a1") -> Agent:
    return Agent(
        id=agent_id, name="test-agent", role="developer", prompt="p", runtime_id="r1"
    )


def _make_job(description: str, session_id: str = "s1", agent_id: str = "a1") -> Job:
    return Job(
        id=str(uuid.uuid4()), session_id=session_id, agent_id=agent_id, description=description
    )


def _launch_scribe_check_runtime(isolated_socket: str, tmp_path, agent: Agent):
    # Doble cooperativo con SIM_ROLE=scribe_check: reporta explícitamente
    # si detectó (o no) la sección delimitada de Scribe en la instrucción
    # que recibió — verifica end-to-end (tmux real) que el agente recibe
    # el contexto, no solo que dispatch_job lo generó internamente.
    runtime = Runtime(
        id="test-runtime",
        name="Test Runtime",
        type="test",
        command="SIM_ROLE=scribe_check SIM_DELAY=0.1 bash",
        args=[_COOPERATIVE_AGENT_SCRIPT],
    )
    return start_runtime(runtime, agent, str(tmp_path), socket_name=isolated_socket)


def test_job_that_triggers_by_size_invokes_scribe_and_agent_receives_delimited_context(
    isolated_socket: str, tmp_path
) -> None:
    # Criterio de aceptación 1: un Job cuya descripción cumple el
    # criterio de disparo (aquí, por tamaño) invoca a Scribe antes de
    # dispatch_job, y el agente recibe su resultado correctamente
    # delimitado. Doble de Scribe controlado (mock de summarize_document)
    # — nunca se invoca Ollama real.
    agent = _make_agent()
    runtime_instance = _launch_scribe_check_runtime(isolated_socket, tmp_path, agent)

    large_description = "x" * (DEFAULT_SIZE_THRESHOLD_CHARACTERS + 1)
    job = _make_job(large_description)

    with patch("atlas_forge.dispatcher.job_dispatch.summarize_document") as mock_summarize:
        mock_summarize.return_value = "a concise summary of the long content"
        dispatch_job(job, agent, runtime_instance, socket_name=isolated_socket)

    mock_summarize.assert_called_once()
    assert job.status == "completed"
    assert "SCRIBE CONTEXT RECEIVED" in job.result
    assert "a concise summary of the long content" in job.result
    assert "--- Fin del contexto pre-procesado por Scribe ---" in job.result

    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_job_that_does_not_trigger_is_dispatched_without_scribe(
    isolated_socket: str, tmp_path
) -> None:
    # Criterio de aceptación 2: un Job que no cumple el criterio de
    # disparo se despacha sin pasar por Scribe.
    agent = _make_agent()
    runtime_instance = _launch_scribe_check_runtime(isolated_socket, tmp_path, agent)

    small_description = "implement a small feature"
    job = _make_job(small_description)

    with patch("atlas_forge.dispatcher.job_dispatch.summarize_document") as mock_summarize:
        dispatch_job(job, agent, runtime_instance, socket_name=isolated_socket)

    mock_summarize.assert_not_called()
    assert job.status == "completed"
    assert "NO SCRIBE CONTEXT WAS PROVIDED" in job.result

    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_scribe_unavailable_error_does_not_block_dispatch(
    isolated_socket: str, tmp_path
) -> None:
    # Criterio de aceptación 3: si Scribe lanza ScribeUnavailableError, el
    # Job se despacha igualmente al agente, sin el resultado de Scribe,
    # sin bloquear el flujo.
    agent = _make_agent()
    runtime_instance = _launch_scribe_check_runtime(isolated_socket, tmp_path, agent)

    large_description = "x" * (DEFAULT_SIZE_THRESHOLD_CHARACTERS + 1)
    job = _make_job(large_description)

    with patch("atlas_forge.dispatcher.job_dispatch.summarize_document") as mock_summarize:
        mock_summarize.side_effect = ScribeUnavailableError(
            "El modelo local de Scribe no está disponible en "
            "'http://localhost:11434' (modelo 'qwen2.5-coder:14b'): "
            "connection refused"
        )
        dispatch_job(job, agent, runtime_instance, socket_name=isolated_socket)

    assert job.status == "completed"
    # El Job se despachó igualmente (no se quedó bloqueado ni marcado
    # como failed por la ausencia de Scribe) — sin sección de Scribe...
    assert "NO SCRIBE CONTEXT WAS PROVIDED" in job.result
    # ...pero la circunstancia quedó registrada en la instrucción real
    # que recibió el agente, no en silencio: el propio texto de la
    # instrucción (visible a través del script cooperativo, que hace eco
    # de todo lo que recibe salvo la sección de Scribe explícita) no se
    # verifica aquí directamente porque el script solo reporta la
    # sección de Scribe o su ausencia — se verifica en un test aparte
    # sobre `_resolve_job_description` directamente.

    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_scribe_unavailable_note_is_documented_not_silent() -> None:
    # Complementa el test anterior verificando directamente el contenido
    # de la instrucción resuelta (sin pasar por tmux) — la circunstancia
    # de que Scribe no estaba disponible se documenta explícitamente, no
    # se silencia (T-AF014-US01-02, criterio de aceptación 3 de la
    # Descripción de esta Task).
    from atlas_forge.dispatcher.job_dispatch import _resolve_job_description

    agent = _make_agent()
    large_description = "x" * (DEFAULT_SIZE_THRESHOLD_CHARACTERS + 1)
    job = _make_job(large_description)

    with patch("atlas_forge.dispatcher.job_dispatch.summarize_document") as mock_summarize:
        mock_summarize.side_effect = ScribeUnavailableError("connection refused")
        resolved_description = _resolve_job_description(job, agent)

    assert "Scribe" in resolved_description
    assert "no está disponible" in resolved_description
    assert "connection refused" in resolved_description
    assert large_description in resolved_description


def test_second_job_on_same_agent_does_not_carry_over_scribe_context(
    isolated_socket: str, tmp_path
) -> None:
    # Criterio de aceptación 4: un segundo Job en la misma sesión/agente
    # no arrastra el contexto de Scribe añadido a un Job anterior.
    agent = _make_agent()
    runtime_instance = _launch_scribe_check_runtime(isolated_socket, tmp_path, agent)

    large_description = "x" * (DEFAULT_SIZE_THRESHOLD_CHARACTERS + 1)
    first_job = _make_job(large_description)

    with patch("atlas_forge.dispatcher.job_dispatch.summarize_document") as mock_summarize:
        mock_summarize.return_value = "summary of the first job"
        dispatch_job(first_job, agent, runtime_instance, socket_name=isolated_socket)

    assert "SCRIBE CONTEXT RECEIVED" in first_job.result
    assert "summary of the first job" in first_job.result

    # Segundo Job, pequeño (no dispara por tamaño), y el conteo de Jobs
    # consecutivos se reseteó tras el disparo del primero — no debería
    # disparar tampoco por conteo.
    second_job = _make_job("a small unrelated task")
    with patch("atlas_forge.dispatcher.job_dispatch.summarize_document") as mock_summarize:
        dispatch_job(second_job, agent, runtime_instance, socket_name=isolated_socket)
        mock_summarize.assert_not_called()

    assert "NO SCRIBE CONTEXT WAS PROVIDED" in second_job.result
    assert "summary of the first job" not in second_job.result

    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_scribe_invocation_only_uses_the_cataloged_operation_no_free_prompt() -> None:
    # Test que confirma que Scribe sigue limitado a sus operaciones ya
    # catalogadas: este mecanismo invoca `summarize_document` (única
    # operación de Scribe usada aquí, T-AF008-US03-01), que no acepta
    # ningún parámetro de prompt libre — ver también
    # `test_summarize_document_does_not_accept_arbitrary_prompt_parameter`
    # en test_scribe.py, verificado ahí sobre la propia función de Scribe.
    import inspect

    from atlas_forge.local_tools import summarize_document

    signature = inspect.signature(summarize_document)
    assert "prompt" not in signature.parameters
    assert set(signature.parameters) == {"text", "model", "base_url", "timeout_seconds"}


def test_job_count_registry_tracks_consecutive_dispatches_per_session_and_agent() -> (
    None
):
    # Verifica el registro nuevo (job_count_registry) de forma aislada:
    # incrementa por (session_id, agent_id), no se mezcla entre agentes o
    # sesiones distintas.
    from atlas_forge.dispatcher.job_count_registry import record_job_dispatch

    assert get_consecutive_job_count("s1", "a1") == 0
    record_job_dispatch("s1", "a1")
    assert get_consecutive_job_count("s1", "a1") == 1
    record_job_dispatch("s1", "a1")
    assert get_consecutive_job_count("s1", "a1") == 2

    # Otro agente en la misma sesión, o el mismo agente en otra sesión:
    # conteos independientes.
    assert get_consecutive_job_count("s1", "a2") == 0
    assert get_consecutive_job_count("s2", "a1") == 0
