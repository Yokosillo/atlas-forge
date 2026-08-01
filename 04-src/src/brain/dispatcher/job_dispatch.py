import tempfile
import time
import uuid
from pathlib import Path

from brain.agents.lifecycle import mark_idle, mark_working
from brain.dispatcher.job_cancellation_registry import (
    clear_job_cancellation,
    is_job_cancellation_requested,
)
from brain.dispatcher.job_count_registry import (
    get_consecutive_job_count,
    record_job_dispatch,
    reset_consecutive_job_count,
)
from brain.dispatcher.job_lifecycle import (
    mark_cancelled,
    mark_completed,
    mark_failed,
    mark_running,
)
from brain.dispatcher.scribe_trigger import (
    compose_job_instruction_with_scribe_context,
    should_invoke_scribe,
)
from brain.local_tools import ScribeUnavailableError, summarize_document
from brain.models import Agent, Job
from brain.runtime import RuntimeInstance
from brain.tmux import run_command
from brain.tmux.manager import DEFAULT_SOCKET_NAME

# Marcador de fin de reporte cooperativo: el agente lo escribe en su
# propia línea, al final del fichero de resultado, cuando termina de
# volcar su respuesta. Distinto del marcador de fin de shell del mecanismo
# anterior (marcador de shell, descartado — ver más abajo "Historial de
# diseño").
_REPORT_END_MARKER = "___FACTORY_BRAIN_JOB_DONE___"


class JobDispatchError(ValueError):
    """No se puede despachar el Job (agente/runtime en un estado inválido)."""


class JobReportTimeoutError(TimeoutError):
    """El agente no reportó su resultado (fichero + marcador) antes del timeout."""


class JobCancelledError(RuntimeError):
    """El Job fue cancelado (T-FB008-US05-01) mientras `_wait_for_report`
    esperaba el reporte del agente — distinto de un timeout normal."""


_SCRIBE_UNAVAILABLE_NOTE_TEMPLATE = (
    "(Nota: se intentó pre-procesar este Job con Scribe antes de "
    "despacharlo, pero no está disponible — {reason} Continúa con la "
    "descripción original de abajo, sin ese resumen.)"
)


def _resolve_job_description(job: Job, agent: Agent) -> str:
    """Decide si toca invocar a Scribe para este despacho (T-FB008-US03-01,
    `should_invoke_scribe`, combinando ambos mecanismos con OR) y, si
    aplica, compone la descripción final del Job con su resultado
    delimitado (`compose_job_instruction_with_scribe_context`).

    Degradación explícita (T-FB014-US01-02, criterio 3 de la Descripción
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


def _wait_for_report(
    report_file: Path,
    timeout_seconds: float,
    poll_interval_seconds: float,
    job_id: str,
) -> str:
    """Espera (polling simple) a que `report_file` exista y contenga el
    marcador de fin en su propia línea, y devuelve su contenido sin el
    marcador. Lanza `JobReportTimeoutError` si se agota el timeout.

    En cada ciclo del polling ya existente comprueba también si se ha
    solicitado la cancelación de `job_id` (T-FB008-US05-01,
    `job_cancellation_registry`, señalizado desde otro hilo — p. ej.
    `POST /jobs/{id}/cancel`) — si es así, lanza `JobCancelledError`
    inmediatamente, sin esperar al timeout normal."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if is_job_cancellation_requested(job_id):
            raise JobCancelledError(
                f"Job '{job_id}' cancelado mientras se esperaba el reporte del agente."
            )
        if report_file.exists():
            content = report_file.read_text()
            if _REPORT_END_MARKER in content:
                result = content.replace(_REPORT_END_MARKER, "").rstrip("\n")
                return result
        time.sleep(poll_interval_seconds)

    raise JobReportTimeoutError(
        f"El agente no reportó su resultado en '{report_file}' dentro de "
        f"{timeout_seconds}s (marcador de fin no detectado)."
    )


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

    ## Disparo automático de Scribe (T-FB008-US03-02)

    Antes de construir la instrucción de auto-reporte, `dispatch_job`
    resuelve la descripción final del Job vía `_resolve_job_description`:
    si el contenido de `job.description` supera el umbral de tamaño, o el
    agente lleva ya el umbral de Jobs consecutivos sin pasar por Scribe
    (`should_invoke_scribe`, T-FB008-US03-01, combinando ambos mecanismos
    con OR), se invoca `summarize_document` (Scribe, FB-014) y su
    resultado se añade delimitado explícitamente
    (`compose_job_instruction_with_scribe_context`). Si Scribe lanza
    `ScribeUnavailableError`, el Job se despacha igualmente con su
    descripción original — la circunstancia se documenta como una nota
    breve en la instrucción, nunca en silencio, y nunca bloquea el
    despacho (degradación explícita, T-FB014-US01-02).

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
    T-FB008-US01-03)

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
    no una dependencia Python declarada en `T-FB000-01` (`pyproject.toml`
    solo declara `GitPython`/`libtmux`/`pytest`). Añadirlo implicaría
    gestionar un subproceso externo (parsear su salida, matarlo si hay
    timeout, manejar su ausencia) sin necesidad real en v1: el polling
    simple ya es el patrón establecido en este mismo módulo (idéntico al
    de `run_command_and_capture`, ahora sustituido) y es determinista de
    testear sin binarios externos.

    ## Cancelación (T-FB008-US05-01)

    `_wait_for_report` comprueba en cada ciclo de su polling si se ha
    solicitado la cancelación de este Job (`job_cancellation_registry`,
    `threading.Event` por `job_id` — mismo patrón que `plan_registry` para
    la idempotencia de aprobación de planes, pero con `Event` en vez de
    `Lock` porque aquí se señaliza un hecho de un hilo a otro, no se
    protege una sección crítica). Si se cancela, el `Job` pasa a
    `cancelled` (nunca `failed`) y el agente vuelve a `idle` de inmediato,
    igual que ante un timeout o un éxito normal.

    **Limitación explícita, documentada a propósito**: cancelar un Job NO
    toca la sesión tmux del agente ni mata ningún proceso — Factory Brain
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
    mark_running(job)
    mark_working(agent)

    description = _resolve_job_description(job, agent)
    record_job_dispatch(job.session_id, agent.id)

    report_file = Path(tempfile.gettempdir()) / f"factory-brain-job-{uuid.uuid4().hex}.txt"

    instruction = _build_report_instruction(description, report_file)
    run_command(runtime_instance.session_name, instruction, socket_name=socket_name)

    try:
        result = _wait_for_report(
            report_file, timeout_seconds, poll_interval_seconds, job_id=job.id
        )
    except JobCancelledError as error:
        mark_cancelled(job, reason=str(error))
        mark_idle(agent)
        return
    except JobReportTimeoutError as error:
        mark_failed(job, reason=f"Timeout esperando reporte del agente: {error}")
        mark_idle(agent)
        return
    finally:
        if report_file.exists():
            report_file.unlink()
        clear_job_cancellation(job.id)

    mark_completed(job, result=result)
    mark_idle(agent)
