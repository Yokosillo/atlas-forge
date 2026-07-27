import tempfile
import time
import uuid
from pathlib import Path

from brain.agents.lifecycle import mark_idle, mark_working
from brain.dispatcher.job_lifecycle import mark_completed, mark_failed, mark_running
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


def _build_report_instruction(job: Job, report_file: Path) -> str:
    """Construye la instrucción que se envía al agente: su tarea original
    (`job.description`) más instrucciones explícitas de auto-reporte."""
    return (
        f"{job.description}\n\n"
        f"Cuando termines, escribe tu resultado completo en el fichero "
        f"'{report_file}' y añade la línea '{_REPORT_END_MARKER}' al final "
        f"de ese fichero para indicar que has terminado de escribir."
    )


def _wait_for_report(
    report_file: Path, timeout_seconds: float, poll_interval_seconds: float
) -> str:
    """Espera (polling simple) a que `report_file` exista y contenga el
    marcador de fin en su propia línea, y devuelve su contenido sin el
    marcador. Lanza `JobReportTimeoutError` si se agota el timeout."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
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

    report_file = Path(tempfile.gettempdir()) / f"factory-brain-job-{uuid.uuid4().hex}.txt"

    instruction = _build_report_instruction(job, report_file)
    run_command(runtime_instance.session_name, instruction, socket_name=socket_name)

    try:
        result = _wait_for_report(report_file, timeout_seconds, poll_interval_seconds)
    except JobReportTimeoutError as error:
        mark_failed(job, reason=f"Timeout esperando reporte del agente: {error}")
        mark_idle(agent)
        return
    finally:
        if report_file.exists():
            report_file.unlink()

    mark_completed(job, result=result)
    mark_idle(agent)
