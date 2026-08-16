"""Dispatcher de fondo de la cola de despacho (T-FB008-US10-02,
US-FB008-10): revisa periódicamente `brain.dispatcher.dispatch_queue`
(`T-FB008-US10-01`, ya cerrada — el mecanismo de cola en sí, sin
despachar nada) y, cuando hay un Developer `idle`, le asigna la
siguiente Task encolada elegible por prioridad/dependencias.

## Mecanismo de disparo elegido: polling periódico, no reactivo

Se decidió **polling** (un hilo daemon que revisa la cola cada
`DEFAULT_POLL_INTERVAL_SECONDS`) en vez de **reactivo** (disparado
cuando un agente pasa a `idle`, p. ej. al terminar un Job), por dos
motivos concretos:

1. **Superficie de enganche menor.** Un disparo reactivo real exigiría
   interceptar cada punto del código donde un `Agent.status` transiciona
   a `idle` (`mark_idle` en `agents/lifecycle.py`, invocado desde
   `dispatch_job`/`job_dispatch.py` al terminar cualquier Job, no solo
   los que el propio Dispatcher despachó) — un callback ahí acopla un
   módulo de dominio genérico (ciclo de vida de agentes) a esta cola
   concreta, mismo tipo de acoplamiento que `job_plan_dispatch.py` evita
   deliberadamente con `on_step_status_changed` (callback opcional
   inyectado, nunca una dependencia dura). Polling no necesita ningún
   cambio en `agents/lifecycle.py`/`job_dispatch.py`.
2. **El propio intervalo de referencia ya citado en la Task
   (`FB-030`, revisión de 10 minutos del Arquitecto) es demasiado lento
   para el caso de uso real** — un usuario que marca una Task para
   desarrollo espera que se despache en segundos, no minutos, si ya hay
   un Developer libre en ese momento. Se elige un intervalo mucho más
   corto, `DEFAULT_POLL_INTERVAL_SECONDS = 5.0` — sigue siendo polling
   (simplicidad de un hilo con `Event().wait(interval)`, sin
   suscripciones), pero con una latencia percibida baja. El coste de
   revisar la cola cada 5s es despreciable (lectura de un fichero JSON
   pequeño + `list_agents` en memoria), muy por debajo de donde un
   intervalo tan corto sería un problema real de carga.

## Por qué un hilo `daemon` dentro del propio proceso `brain-api`, no un
## proceso/script externo

`architect_queue_watcher.sh` (`FB-030`) es un script `bash` externo
porque su trabajo es teclear en un pane tmux (una operación de shell) —
no necesita ningún estado en memoria del proceso `brain-api`. Este
Dispatcher, en cambio, necesita `list_agents(session)`/`dispatch_job`
reales sobre el mismo `DevelopmentSession`/`_AgentRuntimeRegistry` que
ya vive en memoria de `brain-api` (`_find_agent_by_role`,
`get_runtime_instance_for_agent`) — un proceso externo tendría que
reconstruir o exponer ese estado por otra vía (HTTP interno, fichero),
complejidad innecesaria cuando ya se puede vivir en el mismo proceso.
Mismo patrón arquitectónico ya usado por `_ArchitectVerdictQueue`
(`architect_verdict_queue.py`): `threading.Thread(daemon=True)`."""

from __future__ import annotations

import re
import threading
from pathlib import Path

from brain.backlog.parser import load_backlog
from brain.backlog.report import priority_rank
from brain.core.session_lifecycle import list_agents
from brain.dispatcher.dispatch_queue import (
    STATUS_QUEUED,
    QueueEntry,
    dispatch_queue_path,
    get_queue,
    mark_dispatched,
    mark_failed,
)
from brain.dispatcher.job_creation import JobCreationError, create_job
from brain.dispatcher.job_dispatch import dispatch_job
from brain.dispatcher.job_plan_dispatch import (
    AGENT_STEP_TIMEOUT_SECONDS,
    _NoAgentAvailableError,
    _find_agent_by_role,
)
from brain.models import Agent, DevelopmentSession
from brain.runtime.agent_runtime_registry import get_runtime_instance_for_agent
from brain.tmux.manager import DEFAULT_SOCKET_NAME

DEFAULT_POLL_INTERVAL_SECONDS = 5.0

_DEVELOPER_ROLE = "developer"


def _pick_next_eligible_entry(
    entries: list[QueueEntry], done_ids: set[str], dependencies_of: dict[str, tuple[str, ...]]
) -> QueueEntry | None:
    """Elige la siguiente entrada `queued` a despachar: prioridad
    (`Crítica` > `Alta` > `Media` > `Baja`/`null`) primero, a igualdad de
    prioridad orden de encolado (FIFO) — criterio 3 de la Task, mismo
    `priority_rank` ya usado por el resto del backlog para no duplicar
    el cálculo. Salta cualquier entrada cuyas dependencias declaradas no
    estén TODAS `DONE` (criterio 4) — nunca bloquea el resto de la cola
    por una Task no lista, sigue probando la siguiente candidata en
    orden. `None` si ninguna entrada `queued` es elegible ahora mismo."""
    queued = sorted(
        (e for e in entries if e.status == STATUS_QUEUED),
        key=lambda e: (priority_rank(e.priority), e.enqueued_at),
    )
    for entry in queued:
        deps = dependencies_of.get(entry.task_id, ())
        if all(dep_id in done_ids for dep_id in deps):
            return entry
    return None


def _read_task_state(text: str) -> str:
    match = re.search(r"^state:\s*(.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _update_task_file_state(tasks_dir: Path, task_id: str, new_state: str) -> None:
    """Reescribe el campo `state:` del fichero real de `task_id` a
    `new_state` — mismo patrón de reemplazo textual ya usado por
    `_mark_story_tasks_done` (`job_plan_dispatch.py`), aplicado aquí a
    una única Task concreta en vez de todas las `TODO` de una Story (esa
    función resuelve un caso distinto: el veredicto de Arquitecto sobre
    una Story completa, no el despacho individual de esta cola)."""
    candidates = sorted(tasks_dir.glob(f"{task_id}-*.md")) or sorted(tasks_dir.glob(f"{task_id}.md"))
    task_path = next(iter(candidates), None)
    if task_path is None:
        return
    text = task_path.read_text(encoding="utf-8")
    current_state = _read_task_state(text)
    if not current_state:
        return
    updated = text.replace(f"state: {current_state}", f"state: {new_state}", 1)
    task_path.write_text(updated, encoding="utf-8")


def run_dispatch_cycle(
    project_root: Path | str,
    project_name: str,
    session: DevelopmentSession,
    socket_name: str = DEFAULT_SOCKET_NAME,
) -> str | None:
    """Un único ciclo de revisión de la cola: si hay al menos un
    Developer `idle` y al menos una Task encolada elegible (dependencias
    cumplidas), despacha exactamente UNA Task y devuelve su `task_id`
    (`None` si no se despachó nada este ciclo — sin Developer libre, cola
    vacía, o ninguna entrada elegible por dependencias).

    Despacha como máximo una Task por ciclo (no un bucle interno hasta
    vaciar la cola): el siguiente ciclo de polling (`DEFAULT_POLL_INTERVAL_SECONDS`)
    ya vuelve a revisar el estado real de los Developers — evita mantener
    el proceso ocupado despachando en ráfaga si de repente hay muchas
    Tasks elegibles y solo un Developer libre (el segundo Job ya
    encontraría a ese Developer `working` en el ciclo siguiente, por
    construcción de `_find_agent_by_role`).

    No propaga ninguna excepción: cualquier fallo real de despacho ya se
    captura y se marca `failed` en la cola (criterio 6, "un fallo no
    bloquea el resto") — solo `run_dispatch_cycle` en sí nunca debe tumbar
    el hilo de fondo que lo invoca en bucle."""
    tasks_dir = Path(project_root) / "02-backlog" / "tasks"
    graph = load_backlog(Path(project_root) / "02-backlog")
    done_ids = {item_id for item_id, item in graph.items.items() if item.state == "DONE"}
    dependencies_of = dict(graph.dependencies_of)

    entries = get_queue(project_root, project_name)
    entry = _pick_next_eligible_entry(entries, done_ids, dependencies_of)
    if entry is None:
        return None

    try:
        agent = _find_agent_by_role(session, _DEVELOPER_ROLE)
    except _NoAgentAvailableError:
        # Sin Developer `idle` ahora mismo (todos ocupados, o ninguno en
        # la sesión) — criterio explícito: "no intenta despachar nada
        # hasta que alguno quede idle". La entrada sigue `queued`, se
        # reintenta en el siguiente ciclo.
        return None

    runtime_instance = get_runtime_instance_for_agent(agent.id)
    if runtime_instance is None:
        # Agente `idle` pero sin runtime registrado (caso borde real, ya
        # documentado en `_dispatch_agent_step`) — no hay nada que
        # despachar de forma segura este ciclo; se reintenta después.
        return None

    task_id = entry.task_id
    mark_dispatched(project_root, project_name, task_id, agent_id=agent.id, agent_name=agent.name)
    _update_task_file_state(tasks_dir, task_id, "IN_PROGRESS")

    task_title = task_id
    task_path = next(iter(sorted(tasks_dir.glob(f"{task_id}-*.md"))), None)
    description = f"Desarrolla la Task {task_title} (encolada vía la pantalla Backlog)."
    if task_path is not None:
        description += f"\n\nFichero: {task_path.name}"

    try:
        job = create_job(description, agent, session)
        job.story_id = entry.us_id
        dispatch_job(
            job,
            agent,
            runtime_instance,
            timeout_seconds=AGENT_STEP_TIMEOUT_SECONDS,
            socket_name=socket_name,
        )
    except (JobCreationError, Exception) as error:
        # Criterio 6, decisión de producto explícita: la cola es de items
        # independientes — un fallo de despacho de ESTA Task no debe
        # impedir que el Dispatcher siga con el resto en el siguiente
        # ciclo (a diferencia de `dispatch_plan`, que bloquea el lote
        # completo ante el primer fallo). `Exception` genérica incluida a
        # propósito: cualquier fallo real de `dispatch_job` (timeout,
        # runtime caído) debe marcar `failed` igual, no tumbar el hilo de
        # fondo entero.
        mark_failed(project_root, project_name, task_id, result=str(error))
        _update_task_file_state(tasks_dir, task_id, "TODO")
        return task_id

    if job.status != "completed":
        mark_failed(
            project_root, project_name, task_id,
            result=f"El Job no se completó (estado '{job.status}'): {job.result}",
        )
        _update_task_file_state(tasks_dir, task_id, "TODO")
        return task_id

    _update_task_file_state(tasks_dir, task_id, "DONE")
    return task_id


class DispatchQueueWorker:
    """Hilo `daemon` que llama a `run_dispatch_cycle` cada
    `poll_interval_seconds` mientras esté vivo. Un único worker por
    `(project_root, project_name)` — `start()` es idempotente (no lanza
    un segundo hilo si ya hay uno vivo, mismo criterio que
    `launch_architect_queue_watcher`)."""

    def __init__(
        self,
        project_root: Path | str,
        project_name: str,
        session: DevelopmentSession,
        socket_name: str = DEFAULT_SOCKET_NAME,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    ) -> None:
        self._project_root = project_root
        self._project_name = project_name
        self._session = session
        self._socket_name = socket_name
        self._poll_interval_seconds = poll_interval_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="dispatch-queue-worker"
        )
        self._thread.start()

    def stop(self, timeout: float | None = 2.0) -> None:
        """Señala parada y espera (con `timeout`) a que el hilo termine
        su ciclo en curso — usado en tests para no dejar hilos huérfanos
        entre casos."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def run_once(self) -> str | None:
        """Ejecuta un único ciclo de forma síncrona, sin hilo — usado en
        tests deterministas que no quieren depender del temporizador
        real del polling."""
        return run_dispatch_cycle(
            self._project_root, self._project_name, self._session, self._socket_name
        )

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                run_dispatch_cycle(
                    self._project_root, self._project_name, self._session, self._socket_name
                )
            except Exception:
                # Mismo criterio de "mejor esfuerzo" que `_notify` en
                # `dispatch_plan`: un fallo inesperado de un ciclo no debe
                # matar el hilo de fondo — se reintenta en el siguiente.
                pass
            self._stop_event.wait(self._poll_interval_seconds)
