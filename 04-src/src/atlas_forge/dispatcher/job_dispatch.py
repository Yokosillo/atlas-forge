import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from atlas_forge.agent_model import _MODEL_STATUS_PATTERN
from atlas_forge.agents.lifecycle import mark_idle, mark_working
from atlas_forge.dispatcher.job_cancellation_registry import (
    clear_job_cancellation,
    is_job_cancellation_requested,
)
from atlas_forge.dispatcher.job_count_registry import (
    get_consecutive_job_count,
    record_job_dispatch,
    reset_consecutive_job_count,
)
from atlas_forge.dispatcher.job_lifecycle import (
    mark_cancelled,
    mark_completed,
    mark_failed,
    mark_running,
)
from atlas_forge.dispatcher.scribe_trigger import (
    compose_job_instruction_with_scribe_context,
    should_invoke_scribe,
)
from atlas_forge.local_tools import ScribeUnavailableError, summarize_document
from atlas_forge.models import Agent, Job
from atlas_forge.runtime import RuntimeInstance, get_runtime_instance_for_agent
from atlas_forge.tmux import capture_pane_lines, is_alive, run_command
from atlas_forge.tmux.manager import DEFAULT_SOCKET_NAME

# Marcador de fin de reporte cooperativo: el agente lo escribe en su
# propia línea, al final del fichero de resultado, cuando termina de
# volcar su respuesta. Distinto del marcador de fin de shell del mecanismo
# anterior (marcador de shell, descartado — ver más abajo "Historial de
# diseño").
_REPORT_END_MARKER = "___ATLAS_FORGE_JOB_DONE___"

# Reintento acotado de lectura del fichero de marcador ante fallo
# TRANSITORIO (T-AF008-US01-05): un error puntual de lectura (p. ej. el
# fichero momentáneamente bloqueado por otro proceso durante unos
# milisegundos) no debe abortar el despacho ni considerarse timeout — se
# reintenta leer el MISMO fichero un número FIJO de veces con un pequeño
# retardo, nunca un bucle indefinido, y el retardo total añadido
# (2 × 0.1s = 0.2s) es despreciable frente al timeout, de modo que NO se
# enmascara un timeout real (un agente que de verdad no reporta sigue
# escuchando el timeout normal casi al mismo tiempo). Solo se reintenta
# ante errores de I/O de lectura; la ausencia del fichero (el agente aún no
# ha terminado) sigue siendo el caso "esperado" que cubre el polling.
_MAX_REPORT_READ_RETRIES = 2
_REPORT_READ_RETRY_DELAY_SECONDS = 0.1

# T-AF008-US10-06: fallback de detección de finalización en vuelo. El
# mecanismo primario de cierre es el fichero de auto-reporte (`report_file`
# + marcador). Si el agente TERMINA su trabajo pero no escribe el fichero,
# su pane tmux muestra al final el marcador del protocolo de reporte
# estructurado (`RESULTADO:` para veredicto de Task, `ESTADO:` para
# veredicto de Arquitecto). Este fallback comprueba el pane como señal
# secundaria de finalización.
#
# Para evitar el falso positivo del marcador obsoleto (el pane conserva todo
# el historial de scroll, así que un `RESULTADO:`/`ESTADO:` de un Job
# ANTERIOR sigue presente), se usa una BASELINE capturada en el momento del
# envío de la instrucción: solo cuenta un marcador que aparezca en líneas
# NUEVAS (no presentes en la baseline). Así un agente que acaba de empezar
# no se corta por un marcador viejo, y un agente que produjo su marcador de
# fin tras este Job sí se detecta.
_COMPLETION_MARKERS = ("RESULTADO:", "ESTADO:")

# Baseline del pane por `report_file` (único por Job): capturada en
# `dispatch_job_send` justo tras enviar la instrucción, consumida y limpiada
# en `wait_and_finalize_job`. `None` (o ausente) => runtime sin pane
# capturable (headless/sin tmux), se descarta el fallback.
_PANE_BASELINES: dict[str, list[str] | None] = {}


class JobReportFinishedInPaneError(RuntimeError):
    """El agente produjo el marcador de fin de su reporte estructurado en el
    pane (baseline superada) pero NO escribió el fichero de auto-reporte —
    fallback de detección de finalización en vuelo (T-AF008-US10-06). El Job
    se marca `failed` con motivo claro (recuperable), nunca `completed`."""


def _capture_pane_snapshot(agent: Agent, socket_name: str) -> list[str] | None:
    """Contenido actual del pane de `agent` si su runtime es capturable
    (tmux real con `session_name`), o `None` si no (headless, sin runtime,
    sesión muerta o fallo puntual de lectura — el fallback se descarta)."""
    rt = get_runtime_instance_for_agent(agent.id)
    if rt is None or not getattr(rt, "session_name", None):
        return None
    try:
        if not is_alive(rt.session_name, socket_name=socket_name):
            return None
        return capture_pane_lines(rt.session_name, socket_name=socket_name)
    except Exception:
        return None


def _pane_has_new_completion_marker(
    agent: Agent, baseline: list[str] | None, socket_name: str
) -> bool:
    """`True` si el pane de `agent` muestra un marcador de fin en líneas NUEVAS
    respecto a la `baseline` (capturada al enviar la instrucción). Sin baseline
    (pane no capturable) nunca devuelve `True` — se descarta el fallback."""
    if baseline is None:
        return False
    current = _capture_pane_snapshot(agent, socket_name)
    if current is None:
        return False
    baseline_set = set(baseline)
    return any(
        any(marker in line for marker in _COMPLETION_MARKERS)
        for line in current
        if line not in baseline_set
    )


class JobDispatchError(ValueError):
    """No se puede despachar el Job (agente/runtime en un estado inválido)."""


class JobReportTimeoutError(TimeoutError):
    """El agente no reportó su resultado (fichero + marcador) antes del timeout."""


class JobCancelledError(RuntimeError):
    """El Job fue cancelado (T-AF008-US05-01) mientras `_wait_for_report`
    esperaba el reporte del agente — distinto de un timeout normal."""


class AgentNotReadyError(RuntimeError):
    """El agente no está listo para recibir input (runtime aún
    inicializándose o sin señal de readiness en su pane) — la orden NO se
    envía (T-AF022-US06-07). El Job queda `failed` por el propio
    `dispatch_job_send` y el agente NO llega a marcarse `working`."""


_SCRIBE_UNAVAILABLE_NOTE_TEMPLATE = (
    "(Nota: se intentó pre-procesar este Job con Scribe antes de "
    "despacharlo, pero no está disponible — {reason} Continúa con la "
    "descripción original de abajo, sin ese resumen.)"
)


def _resolve_job_description(job: Job, agent: Agent) -> str:
    """Decide si toca invocar a Scribe para este despacho (T-AF008-US03-01,
    `should_invoke_scribe`, combinando ambos mecanismos con OR) y, si
    aplica, compone la descripción final del Job con su resultado
    delimitado (`compose_job_instruction_with_scribe_context`).

    Degradación explícita (T-AF014-US01-02, criterio 3 de la Descripción
    de esta Task): si Scribe dispara pero lanza `ScribeUnavailableError`,
    el Job se despacha igualmente con su descripción original — la
    circunstancia no se silencia, se documenta como una nota breve al
    principio de la instrucción (visible para el agente y para cualquiera
    que inspeccione el Job después), sin necesidad de introducir logging
    nuevo en un proyecto que no usa `logging` en ningún otro sitio.

    No modifica `job.description` en el objeto `Job` — devuelve la
    descripción a usar solo para esta instrucción de despacho, para que
    el siguiente Job de la misma sesión/agente no arrastre el contexto de
    Scribe añadido a este (criterio de aceptación: "un segundo Job... no
    arrastra el contexto de Scribe añadido a un Job anterior")."""
    consecutive_count = get_consecutive_job_count(job.session_id, agent.id)

    if not should_invoke_scribe(job.description, consecutive_count):
        return job.description

    try:
        scribe_result = summarize_document(job.description)
    except ScribeUnavailableError as error:
        note = _SCRIBE_UNAVAILABLE_NOTE_TEMPLATE.format(reason=error)
        return f"{note}\n\n{job.description}"

    reset_consecutive_job_count(job.session_id, agent.id)
    return compose_job_instruction_with_scribe_context(job.description, scribe_result)


def _build_report_instruction(description: str, report_file: Path) -> str:
    """Construye la instrucción que se envía al agente: la descripción ya
    resuelta del Job (original, o enriquecida con el contexto de Scribe —
    ver `_resolve_job_description`) más instrucciones explícitas de
    auto-reporte."""
    return (
        f"{description}\n\n"
        f"Cuando termines, escribe tu resultado completo en el fichero "
        f"'{report_file}' y añade la línea '{_REPORT_END_MARKER}' al final "
        f"de ese fichero para indicar que has terminado de escribir."
    )


def _read_report_with_retry(report_file: Path) -> str | None:
    """Lee `report_file` e intenta detectar el marcador de fin, con un
    reintento ACOTADO ante fallos transitorios de lectura (T-AF008-US01-05).

    Devuelve el contenido sin el marcador si este está presente, o `None`
    en cualquier caso en que todavía no hay resultado leíble (el fichero no
    existe todavía, el marcador aún no está, o la lectura se reintentó sin
    éxito). Distingue explícitamente dos situaciones que el polling del
    llamador trata igual (esperando) pero que NO son lo mismo:

    - "El agente no ha terminado todavía" — `FileNotFoundError`: esperado,
      NO es candidato a reintento; se devuelve `None` de inmediato y el
      polling sigue hasta el `deadline`.
    - "Fallo transitorio del mecanismo de auto-reporte" — cualquier otro
      `OSError` al leer un fichero existente (p. ej. bloqueado durante un
      instante): sí es candidato a reintento; se vuelve a intentar leer el
      MISMO fichero hasta `_MAX_REPORT_READ_RETRIES` veces con un pequeño
      retardo. Si el marcador aparece en un reintento, se devuelve el
      resultado; si se agotan los reintentos, se devuelve `None` y el
      polling del llamador sigue — el Job solo pasa a timeout al agotarse
      el `deadline`, nunca por un fallo puntual de lectura.
    """
    content: str | None = None
    for attempt in range(_MAX_REPORT_READ_RETRIES + 1):
        try:
            content = report_file.read_text()
            break
        except FileNotFoundError:
            return None
        except OSError:
            if attempt < _MAX_REPORT_READ_RETRIES:
                time.sleep(_REPORT_READ_RETRY_DELAY_SECONDS)
                continue
            return None

    if content is None:
        return None
    if _REPORT_END_MARKER not in content:
        return None
    return content.replace(_REPORT_END_MARKER, "").rstrip("\n")


def _wait_for_report(
    report_file: Path,
    timeout_seconds: float,
    poll_interval_seconds: float,
    job_id: str,
    agent: Agent | None = None,
    socket_name: str = DEFAULT_SOCKET_NAME,
) -> str:
    """Espera (polling simple) a que `report_file` exista y contenga el
    marcador de fin en su propia línea, y devuelve su contenido sin el
    marcador. Lanza `JobReportTimeoutError` si se agota el timeout.

    En cada ciclo del polling ya existente comprueba también si se ha
    solicitado la cancelación de `job_id` (T-AF008-US05-01,
    `job_cancellation_registry`, señalizado desde otro hilo — p. ej.
    `POST /jobs/{id}/cancel`) — si es así, lanza `JobCancelledError`
    inmediatamente, sin esperar al timeout normal.

    La lectura del fichero de marcador pasa por `_read_report_with_retry`
    (T-AF008-US01-05): un fallo transitorio de lectura no aborta ni se
    considera timeout — se reintenta de forma acotada en el acto y, si aun
    así no hay resultado, el polling continúa hasta el `deadline`. De este
    modo un timeout REAL (agente colgado o sin responder) se sigue
    detectando en el mismo orden de tiempo, solo se cubren fallos punctuales
    de I/O.

    T-AF008-US10-06 (fallback por pane): si `agent` se pasa y el reporte
    sigue sin aparecer pero el pane del agente muestra un marcador de fin en
    líneas nuevas respecto a la baseline de envío
    (`_pane_has_new_completion_marker`), se lanza
    `JobReportFinishedInPaneError` — el agente terminó su salida pero no
    escribió el fichero; el llamador marca el Job `failed` (recuperable)."""
    deadline = time.monotonic() + timeout_seconds
    baseline = _PANE_BASELINES.get(str(report_file))
    while time.monotonic() < deadline:
        if is_job_cancellation_requested(job_id):
            raise JobCancelledError(
                f"Job '{job_id}' cancelado mientras se esperaba el reporte del agente."
            )
        result = _read_report_with_retry(report_file)
        if result is not None:
            return result
        if agent is not None and _pane_has_new_completion_marker(
            agent, baseline, socket_name
        ):
            raise JobReportFinishedInPaneError(
                f"El agente terminó su reporte estructurado en el pane "
                f"(marcador RESULTADO:/ESTADO: detectado) pero no escribió el "
                f"fichero de auto-reporte '{report_file}'."
            )
        time.sleep(poll_interval_seconds)

    raise JobReportTimeoutError(
        f"El agente no reportó su resultado en '{report_file}' dentro de "
        f"{timeout_seconds}s (marcador de fin no detectado)."
    )


def is_agent_ready_for_input(
    agent: Agent,
    socket_name: str = DEFAULT_SOCKET_NAME,
    runtime_instance: RuntimeInstance | None = None,
) -> bool:
    """Comprueba de forma DETERMINISTA si el runtime real de `agent` está
    listo para recibir input en su pane (T-AF022-US06-07).

    Bug que corrige: un agente recién lanzado o reconciliado se registra
    `idle` antes de que su opencode termine de arrancar ("Build auto"); si
    el Dispatcher le despacha una orden en ese momento, `run_command`
    teclea la instrucción en un pane que aún no acepta input y la orden se
    pierde — el agente queda `working` sin instrucción real hasta el
    timeout (3600s) sin resultado (reproducido en vivo 2026-08-18 con el
    Tester). Este chequeo se aplica ANTES de marcar al agente `working`
    (en `dispatch_job_send`) y como gate previo en los ciclos de despacho:
    si el agente no está listo, la orden no se envía y el ciclo reintenta
    en el siguiente poll — el agente nunca queda `working` sin orden.

    Señal por runtime (sin esperas arbitrarias, sin tocar el mecanismo de
    `send-keys`/tmux, solo lectura pasiva del pane):

    - `opencode`: la barra de estado `"Build · "`
      (`atlas_forge.agent_model._MODEL_STATUS_PATTERN`) solo aparece cuando la
      TUI de OpenCode está cargada y acepta input; durante la
      inicialización ("Build auto") NO está presente. Si la barra aparece
      en el pane, el agente está listo; si no, sigue inicializando (o su
      proceso murió dejando la sesión tmux viva) y NO debe recibir una
      orden.

    - Resto de runtimes (`claude-code`, `codex`, `test`): no hay un
      marcador determinista documentado para su TUI en el código actual —
      se consideran listos de forma conservadora (comportamiento vigente).
      Limitación explícita: el bug repro se observó en OpenCode; un
      marcador de readiness para Claude Code exigiría validación en vivo y
      se reporta como hallazgo al Arquitecto.

    Casos defensivos:
    - Sin `runtime_instance` registrado para el agente: `False` — no hay
      forma de enviar nada con seguridad.
    - Runtime de prueba sin atributos reales de tmux (dobles de tests que
      asumen envío inmediato): `True` — conservador para no romper la
      suite existente del dispatcher.
    - Fallo puntual de lectura del pane: `False` — ante la duda NO se
      despacha (seguro: nunca se pierde una orden; el ciclo reintenta)."""
    rt = (
        runtime_instance
        if runtime_instance is not None
        else get_runtime_instance_for_agent(agent.id)
    )
    if rt is None:
        return False

    runtime_type = getattr(getattr(rt, "runtime", None), "type", None)
    if runtime_type != "opencode":
        return True

    session_name = getattr(rt, "session_name", None)
    if not session_name:
        return False

    try:
        if not is_alive(session_name, socket_name=socket_name):
            return False
        lines = capture_pane_lines(session_name, socket_name=socket_name)
    except Exception:
        return False
    return any(_MODEL_STATUS_PATTERN in line for line in lines)


def dispatch_job_send(
    job: Job,
    agent: Agent,
    runtime_instance: RuntimeInstance,
    socket_name: str = DEFAULT_SOCKET_NAME,
) -> Path:
    """Fase de ENVÍO NO BLOQUEANTE de un Job (T-AF022-US06-05).

    Marca `job` `running` y `agent` `working`, resuelve la descripción
    final (Scribe, `_resolve_job_description`), genera el fichero de
    reporte único por Job y envía la instrucción al pane del agente
    (`run_command`) — y DEVUELVE de inmediato con el `Path` del fichero
    de reporte que el agente debe escribir al terminar, SIN esperar su
    finalización.

    ## Gate de readiness (T-AF022-US06-07)

    ANTES de marcar al agente `working`, se comprueba
    `is_agent_ready_for_input`: un agente recién lanzado o reconciliado
    cuyo opencode aún está inicializando ("Build auto") NO acepta input —
    enviarle la orden la perdería y el agente quedaría `working` sin
    orden real hasta el timeout. Si el agente no está listo, el Job queda
    `failed` (con el motivo en `job.result`) y se lanza `AgentNotReadyError`
    — el agente NUNCA llega a marcarse `working` (nunca queda huérfano en
    `working` sin orden; el llamador reintenta en un ciclo posterior).

    El llamador decide si espera/finaliza de forma síncrona
    (`wait_and_finalize_job`, como hace `dispatch_job`) o de forma
    asíncrona por polling (el ciclo no bloqueante del Dispatcher, que
    comprueba los ficheros de sus Jobs en vuelo en cada ciclo — ver
    `poll_inflight_job_completions` en `dispatch_queue_worker.py`)."""
    mark_running(job)
    if not is_agent_ready_for_input(
        agent, socket_name=socket_name, runtime_instance=runtime_instance
    ):
        reason = (
            f"El agente '{agent.name}' no está listo para recibir input "
            f"(runtime aún inicializándose o sin señal de readiness en su pane)."
        )
        mark_failed(job, reason=reason)
        raise AgentNotReadyError(reason)
    mark_working(agent)
    agent.last_command_at = datetime.now(timezone.utc).isoformat()

    description = _resolve_job_description(job, agent)
    report_file = Path(tempfile.gettempdir()) / f"atlas-forge-job-{uuid.uuid4().hex}.txt"

    instruction = _build_report_instruction(description, report_file)
    run_command(runtime_instance.session_name, instruction, socket_name=socket_name)
    # T-AF008-US10-06: baseline del pane justo tras enviar la instrucción —
    # para el fallback de marcador de fin sin fichero (evita el falso
    # positivo del marcador obsoleto de un Job anterior). Solo si el runtime
    # tiene pane capturable; `None` descarta el fallback.
    _PANE_BASELINES[str(report_file)] = _capture_pane_snapshot(agent, socket_name)
    record_job_dispatch(job.session_id, agent.id)

    return report_file


def wait_and_finalize_job(
    job: Job,
    agent: Agent,
    report_file: Path,
    timeout_seconds: float = 30.0,
    poll_interval_seconds: float = 0.2,
    socket_name: str = DEFAULT_SOCKET_NAME,
) -> None:
    """Espera el reporte de `job` (fichero + marcador) y finaliza el Job y
    el agente — la fase que `dispatch_job` ejecutaba tras enviar la
    instrucción, extraída para poder esperar/finalizar también de forma
    asíncrona (T-AF022-US06-05).

    Comportamiento idéntico al bloque original de `dispatch_job`:
    cancelación → `cancelled`; timeout → `failed`; reporte → `completed`;
    en todos los casos el agente vuelve a `idle` (si sigue disponible) y
    se limpia el fichero de reporte y la señal de cancelación. Si
    `report_file` ya contiene el marcador, vuelve de inmediato sin dormir
    (usado por el ciclo no bloqueante, que solo invoca esta función
    cuando el reporte ya está confirmado).

    T-AF008-US10-06: si el agente terminó su reporte en el pane pero no
    escribió el fichero (`JobReportFinishedInPaneError`), el Job se marca
    `failed` con motivo claro (recuperable) y el agente vuelve a `idle` —
    nunca queda `working` hasta el timeout de 1h."""
    try:
        result = _wait_for_report(
            report_file, timeout_seconds, poll_interval_seconds,
            job_id=job.id, agent=agent, socket_name=socket_name,
        )
    except JobCancelledError as error:
        mark_cancelled(job, reason=str(error))
        if agent is not None:
            mark_idle(agent)
        return
    except JobReportFinishedInPaneError as error:
        mark_failed(job, reason=str(error))
        if agent is not None:
            mark_idle(agent)
        return
    except JobReportTimeoutError as error:
        mark_failed(job, reason=f"Timeout esperando reporte del agente: {error}")
        if agent is not None:
            mark_idle(agent)
        return
    finally:
        if report_file.exists():
            report_file.unlink()
        clear_job_cancellation(job.id)
        _PANE_BASELINES.pop(str(report_file), None)

    mark_completed(job, result=result)
    if agent is not None:
        mark_idle(agent)


def read_finished_report(report_file: Path) -> str | None:
    """Lee `report_file` una sola vez de forma NO BLOQUEANTE
    (T-AF022-US06-05): devuelve el contenido sin el marcador de fin si el
    agente ya terminó, o `None` si aún no ha escrito el marcador. Reutiliza
    `_read_report_with_retry` (mismo reintento acotado ante fallos
    transitorios de lectura)."""
    return _read_report_with_retry(report_file)


def pane_indicates_finished_without_report(
    agent: Agent | None, report_file: Path, socket_name: str
) -> bool:
    """`True` si el pane de `agent` muestra un marcador de fin NUEVO respecto
    a la baseline registrada al enviar el Job (y el fichero no aparece) —
    fallback de finalización en vuelo (T-AF008-US10-06) para el polling
    asíncrono del Dispatcher. `False` si no hay agente, no hay baseline
    (pane no capturable) o no hay marcador nuevo."""
    if agent is None:
        return False
    baseline = _PANE_BASELINES.get(str(report_file))
    return _pane_has_new_completion_marker(agent, baseline, socket_name)


def fail_job_finished_in_pane(
    job: Job, agent: Agent | None, report_file: Path
) -> None:
    """Marca `job` `failed` con el motivo de finalización-en-pane-sin-fichero
    y devuelve el agente a `idle`, limpiando el fichero, la señal de
    cancelación y la baseline — contrapartida no bloqueante de
    `wait_and_finalize_job` para el fallback por pane del polling asíncrono
    (T-AF008-US10-06)."""
    if report_file.exists():
        report_file.unlink()
    clear_job_cancellation(job.id)
    _PANE_BASELINES.pop(str(report_file), None)
    mark_failed(
        job,
        reason=(
            "El agente terminó su reporte estructurado en el pane "
            "(marcador RESULTADO:/ESTADO: detectado) pero no escribió el "
            f"fichero de auto-reporte '{report_file}'."
        ),
    )
    if agent is not None:
        mark_idle(agent)


def fail_job_on_timeout(
    job: Job,
    agent: Agent,
    report_file: Path,
    timeout_seconds: float,
) -> None:
    """Finaliza un Job en vuelo que excedió su timeout sin reporte, de
    forma no bloqueante (T-AF022-US06-05): marca el Job `failed`, el
    agente `idle` (si sigue disponible) y limpia el fichero de reporte y
    la señal de cancelación — la contrapartida de `wait_and_finalize_job`
    para el camino de expiración en el ciclo de completión del
    Dispatcher."""
    if report_file.exists():
        report_file.unlink()
    clear_job_cancellation(job.id)
    mark_failed(job, reason=f"Timeout esperando reporte del agente (>{timeout_seconds:.0f}s).")
    if agent is not None:
        mark_idle(agent)


def dispatch_job(
    job: Job,
    agent: Agent,
    runtime_instance: RuntimeInstance,
    timeout_seconds: float = 30.0,
    poll_interval_seconds: float = 0.2,
    socket_name: str = DEFAULT_SOCKET_NAME,
) -> None:
    """Envía `job` al runtime de `agent` (su sesión tmux, `runtime_instance`),
    espera su finalización, y registra el resultado en `job`.

    Transiciona `job` a `running` y `agent` a `working` antes de enviar.
    Al finalizar (éxito o fallo), `agent` vuelve siempre a `idle` — nunca
    queda bloqueado en `working`.

    ## Disparo automático de Scribe (T-AF008-US03-02)

    Antes de construir la instrucción de auto-reporte, `dispatch_job`
    resuelve la descripción final del Job vía `_resolve_job_description`:
    si el contenido de `job.description` supera el umbral de tamaño, o el
    agente lleva ya el umbral de Jobs consecutivos sin pasar por Scribe
    (`should_invoke_scribe`, T-AF008-US03-01, combinando ambos mecanismos
    con OR), se invoca `summarize_document` (Scribe, AF-014) y su
    resultado se añade delimitado explícitamente
    (`compose_job_instruction_with_scribe_context`). Si Scribe lanza
    `ScribeUnavailableError`, el Job se despacha igualmente con su
    descripción original — la circunstancia se documenta como una nota
    breve en la instrucción, nunca en silencio, y nunca bloquea el
    despacho (degradación explícita, T-AF014-US01-02).

    El conteo de Jobs consecutivos por agente/sesión vive en
    `job_count_registry` (registro nuevo, ver su docstring para la
    justificación de por qué no se extendió `DevelopmentSession`), se
    consulta con el valor previo a este despacho (para decidir si ESTE
    Job dispara), y se incrementa después de resolver la descripción —
    de modo que el próximo Job de este mismo agente/sesión ya cuenta con
    este despacho. La descripción enriquecida con el contexto de Scribe
    nunca se escribe de vuelta en `job.description` — es una
    transformación local a esta llamada, así que un segundo Job no
    arrastra el contexto de Scribe añadido a uno anterior.

    ## Mecanismo: auto-reporte cooperativo (rediseño post-cierre de
    T-AF008-US01-03)

    En vez de enviar `job.description` como si fuera un comando de shell y
    esperar un marcador de fin de shell (mecanismo original, ver
    "Historial de diseño" más abajo), la instrucción enviada al agente
    incluye una petición explícita: que escriba su resultado en un fichero
    temporal único por Job, seguido de un marcador de fin en su propia
    línea. `dispatch_job` vigila (polling simple sobre el sistema de
    ficheros, sin `capture-pane`, sin `inotifywait`) la aparición de ese
    fichero con su marcador.

    **Premisa que hace esto viable**: Claude Code y OpenCode son procesos
    interactivos INSTRUIBLES — LLMs que siguen instrucciones de reporte en
    lenguaje natural, no procesos rígidos con un contrato de E/S fijo. Se
    les puede pedir explícitamente que escriban a un fichero pactado,
    igual que ya hace `00-gobierno/developer.md` con el ciclo real
    worker→crítico (`.claude/state/worker_output.txt` + marcador
    `### STORY_DONE ###`, vigilado por `watch_worker.sh`). Este mecanismo
    replica ese mismo patrón ya validado en producción, aplicado a Jobs.

    **Decisión: polling simple, no `inotifywait`.** `watch_worker.sh` usa
    `inotifywait` (evento-driven), pero es un binario externo del sistema,
    no una dependencia Python declarada en `T-AF000-01` (`pyproject.toml`
    declara dependencias base como `libtmux`/`PyYAML` y `pytest` como
    dependencia dev). Añadirlo implicaría
    gestionar un subproceso externo (parsear su salida, matarlo si hay
    timeout, manejar su ausencia) sin necesidad real en v1: el polling
    simple ya es el patrón establecido en este mismo módulo (idéntico al
    de `run_command_and_capture`, ahora sustituido) y es determinista de
    testear sin binarios externos.

    ## Cancelación (T-AF008-US05-01)

    `_wait_for_report` comprueba en cada ciclo de su polling si se ha
    solicitado la cancelación de este Job (`job_cancellation_registry`,
    `threading.Event` por `job_id` — mismo patrón que `plan_registry` para
    la idempotencia de aprobación de planes, pero con `Event` en vez de
    `Lock` porque aquí se señaliza un hecho de un hilo a otro, no se
    protege una sección crítica). Si se cancela, el `Job` pasa a
    `cancelled` (nunca `failed`) y el agente vuelve a `idle` de inmediato,
    igual que ante un timeout o un éxito normal.

    **Limitación explícita, documentada a propósito**: cancelar un Job NO
    toca la sesión tmux del agente ni mata ningún proceso — Atlas Forge
    simplemente deja de esperar su resultado. El runtime real (Claude
    Code/OpenCode) puede seguir "pensando" o escribiendo internamente
    aunque nadie espere ya ese resultado; no hay forma de interrumpir el
    propio proceso de razonamiento del runtime sin matarlo, y eso sigue
    siendo responsabilidad de `stop_agent`, no de la cancelación de un Job.
    Si el agente termina escribiendo su reporte tarde (después de
    cancelado), ese fichero queda huérfano en el directorio temporal del
    sistema — mismo destino que cualquier `report_file` no leído, ver más
    abajo.

    ## Limitaciones conocidas de este mecanismo

    - **Depende de que el agente siga la instrucción de reporte.** Si el
      runtime real (Claude Code/OpenCode) no escribe el fichero pactado —
      por un fallo del modelo en seguir instrucciones, un error de
      permisos de escritura, o un cuelgue real del proceso — el resultado
      es un timeout genérico (`JobReportTimeoutError`), igual que con el
      mecanismo anterior ante un runtime colgado. No hay forma de
      distinguir "el agente no entendió la instrucción" de "el agente
      sigue pensando" de "el proceso murió" solo con esta señal.
    - **No hay verificación de que el fichero pertenece a este Job y no a
      uno anterior con el mismo path** por colisión de nombres — mitigado
      generando el nombre del fichero con `uuid` por Job (ver
      `_build_report_instruction`), pero si dos Jobs se despachan con el
      mismo `report_file` por error del llamador, el resultado sería
      ambiguo. `dispatch_job` genera el fichero internamente, por lo que
      esto no debería ocurrir en el uso normal.
    - El fichero de resultado no se borra automáticamente tras leerlo —
      queda en el directorio temporal del sistema hasta que el SO lo
      limpie; no supone un problema de correctitud para v1, pero es
      basura acumulable si se despachan muchos Jobs.

    ## Historial de diseño (mecanismos descartados)

    1. **Marcador de fin de shell + `capture-pane`** (mecanismo original de
       esta Task, ya cerrado y aprobado): asumía que el comando enviado
       era un comando de shell que terminaba y devolvía el control al
       prompt — no garantizado para un runtime interactivo real. Descartado
       tras señalarse explícitamente este riesgo.
    2. **Heurística de quiescencia** (contenido del pane sin cambios
       durante N segundos): diseñada y probada experimentalmente;
       descartada por un falso positivo demostrado empíricamente (un paso
       intermedio del proceso más lento que el umbral de quiescencia
       provoca una captura truncada e incorrecta, sin ningún error
       visible) — inviable con un umbral fijo para un LLM real, cuyo
       tiempo de "pensamiento" entre líneas de salida no tiene límite
       superior predecible.
    3. **Auto-reporte cooperativo** (este mecanismo): elegido porque no
       depende de inferir el fin de la respuesta desde fuera —el propio
       agente lo declara explícitamente—, replicando el patrón ya
       validado del ciclo worker/crítico real de este mismo proyecto.
    """
    try:
        report_file = dispatch_job_send(job, agent, runtime_instance, socket_name=socket_name)
    except AgentNotReadyError:
        # T-AF022-US06-07: el agente no está listo para recibir input.
        # `dispatch_job_send` ya marcó el Job `failed` (con el motivo) y
        # dejó al agente sin marcar (`idle`) — no hay reporte que esperar
        # ni nada que revertir. Se mantiene el contrato de esta función:
        # nunca propaga una excepción por un fallo de despacho.
        return
    wait_and_finalize_job(job, agent, report_file, timeout_seconds, poll_interval_seconds, socket_name)
