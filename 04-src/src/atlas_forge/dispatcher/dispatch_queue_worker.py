"""Dispatcher de fondo de la cola de despacho (T-AF008-US10-02,
US-AF008-10): revisa periódicamente `atlas_forge.dispatcher.dispatch_queue`
(`T-AF008-US10-01`, ya cerrada — el mecanismo de cola en sí, sin
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
   concreta. Polling no necesita ningún cambio en
   `agents/lifecycle.py`/`job_dispatch.py`.
2. **El propio intervalo de referencia ya citado en la Task
   (`AF-030`, revisión de 10 minutos del Arquitecto) es demasiado lento**
   para el caso de uso real — un usuario que marca una Task para
   desarrollo espera que se despache en segundos, no minutos, si ya hay
   un Developer libre en ese momento. Se elige un intervalo mucho más
   corto, `DEFAULT_POLL_INTERVAL_SECONDS = 5.0` — sigue siendo polling
   (simplicidad de un hilo con `Event().wait(interval)`, sin
   suscripciones), pero con una latencia percibida baja. El coste de
   revisar la cola cada 5s es despreciable (lectura de un fichero JSON
   pequeño + `list_agents` en memoria), muy por debajo de donde un
   intervalo tan corto sería un problema real de carga.

## Por qué un hilo `daemon` dentro del propio proceso `atlas-forge-api`, no un
## proceso/script externo

`architect_queue_watcher.sh` (`AF-030`) es un script `bash` externo
porque su trabajo es teclear en un pane tmux (una operación de shell) —
no necesita ningún estado en memoria del proceso `atlas-forge-api`. Este
Dispatcher, en cambio, necesita `list_agents(session)`/`dispatch_job`
reales sobre el mismo `DevelopmentSession`/`_AgentRuntimeRegistry` que
ya vive en memoria de `atlas-forge-api` (`_find_agent_by_role`,
`get_runtime_instance_for_agent`) — un proceso externo tendría que
reconstruir o exponer ese estado por otra vía (HTTP interno, fichero),
complejidad innecesaria cuando ya se puede vivir en el mismo proceso.
Mismo patrón arquitectónico ya usado por `_ArchitectVerdictQueue`
(`architect_verdict_queue.py`): `threading.Thread(daemon=True)`.

## Nota de decisión de producto (2026-08-23)

Los Developer/Tester lanzados desde la UI NO mueren al terminar su Job:
la retirada automática por `persistent=false` es parte de una User Story
de versión 0.9.2 que, de momento, no se implementa. Este módulo despacha
trabajo pero nunca retira a un agente al completar una Task.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from atlas_forge.agent_model import get_active_model, set_active_model
from atlas_forge.backlog.parser import load_backlog
from atlas_forge.backlog.promote import upsert_updated_at
from atlas_forge.backlog.report import priority_rank
from atlas_forge.backlog.watcher import consolidate_if_changed
from atlas_forge.core.session_lifecycle import list_agents
from atlas_forge.agents.launch import launch_agent
from atlas_forge.agents.stop import stop_agent
from atlas_forge.dispatcher.autonomous_scaling import (
    autonomous_scale,
    config_from_preferences,
    count_pending,
)
from atlas_forge.dispatcher.creation_queue import (
    mark_creation_in_flight,
    pick_next_pending_creation_request,
)
from atlas_forge.dispatcher.dispatch_queue import (
    STATUS_DISPATCHED,
    STATUS_QUEUED,
    QueueEntry,
    get_queue,
    mark_completed,
    mark_dispatched,
    mark_failed,
    reconcile_dispatch_queue_entries,
    reconcile_orphaned_in_progress_tasks,
    set_entry_report_file,
)
from atlas_forge.dispatcher.job_creation import JobCreationError
from atlas_forge.dispatcher.job_orchestration import create_and_record_job
from atlas_forge.dispatcher.job_dispatch import (
    AgentNotReadyError,
    dispatch_job_send,
    fail_job_finished_in_pane,
    fail_job_on_timeout,
    is_agent_ready_for_input,
    pane_indicates_finished_without_report,
    read_finished_report,
    wait_and_finalize_job,
)
from atlas_forge.dispatcher.job_plan_dispatch import (
    AGENT_STEP_TIMEOUT_SECONDS,
    _collect_story_reports,
    _process_verdict_result,
)
from atlas_forge.dispatcher.architect_verdict_store import (
    reconcile_architect_verdict_queue,
    save_architect_verdict_queue,
)
from atlas_forge.dispatcher.model_selection import get_models_for_difficulty
from atlas_forge.dispatcher.task_verdict import VERDICT_PASSED, parse_task_verdict
from atlas_forge.models import Agent, DevelopmentSession, Job
from atlas_forge.runtime.agent_runtime_registry import get_runtime_instance_for_agent
from atlas_forge.system_preferences import (
    get_auto_reenqueue_orphaned,
    get_autonomous_config,
    get_developer_waits_for_tester_review,
)
from atlas_forge.tmux.manager import DEFAULT_SOCKET_NAME

DEFAULT_POLL_INTERVAL_SECONDS = 5.0

_DEVELOPER_ROLE = "developer"
_TESTER_ROLE = "tester"
_ARQUITECTO_ROLE = "arquitecto"


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


def _pick_next_eligible_task_id(
    graph,
    entries: list[QueueEntry],
    done_ids: set[str],
    dependencies_of: dict[str, tuple[str, ...]],
) -> str | None:
    """Elige la siguiente Task a despachar (T-AF008-US14-01): la fuente
    de verdad de "lista para desarrollo" pasa a ser `state == "TO_DEVELOP"`
    (AF-040; antes EN_DESARROLLO)
    en el propio fichero del backlog, no solo la presencia de una
    entrada `queued` en `dispatch_queue.json` — una Task puede llegar a
    `TO_DEVELOP` por el selector de estado de `US-AF036-08` sin pasar nunca
    por `POST /backlog/{id}/enqueue` (y por tanto sin entrada JSON).

    Candidatas: cualquier Task del grafo con `state == "TO_DEVELOP"`.
    Orden: mismo criterio que antes (prioridad, luego FIFO por
    `enqueued_at`) para las que SÍ tienen entrada JSON — es el caso
    normal, ya que el flujo real (botón "Marcar para desarrollo") sigue
    escribiendo esa entrada además del `state`. Las que no tienen entrada
    JSON (marcadas a mano) se ordenan al final de su grupo de prioridad,
    por `item.id` ascendente — determinista, sin depender de ningún
    timestamp que no existe para ellas.

    Salta cualquier candidata cuyas dependencias no estén TODAS `DONE`
    (mismo criterio ya vigente), probando la siguiente en orden."""
    entry_by_task_id = {e.task_id: e for e in entries if e.status == STATUS_QUEUED}
    candidates = [
        item for item in graph.items.values()
        if item.kind == "T" and item.state == "TO_DEVELOP"
    ]

    def _sort_key(item):
        entry = entry_by_task_id.get(item.id)
        priority = entry.priority if entry is not None else item.priority
        # Las que tienen entrada JSON ordenan por su enqueued_at real
        # (FIFO genuino); las que no, se agrupan detrás de todas las que
        # sí lo tienen (mismo grupo de prioridad) mediante un prefijo
        # constante mayor que cualquier ISO-8601 real, luego por id.
        order_key = entry.enqueued_at if entry is not None else "9999" + item.id
        return (priority_rank(priority), order_key)

    for item in sorted(candidates, key=_sort_key):
        deps = dependencies_of.get(item.id, ())
        if all(dep_id in done_ids for dep_id in deps):
            return item.id
    return None


def _read_task_state(text: str) -> str:
    match = re.search(r"^state:\s*(.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _update_task_file_state(tasks_dir: Path, task_id: str, new_state: str) -> None:
    """Reescribe el campo `state:` del fichero real de `task_id` a
    `new_state`, actualizando también `updated_at` (T-AF036-US13-01) —
    mismo patrón de reemplazo textual ya usado por
    `_mark_story_tasks_done` (`job_plan_dispatch.py`), aplicado aquí a
    una única Task concreta en vez de todas las `TO_DEVELOP` de una Story."""
    candidates = sorted(tasks_dir.glob(f"{task_id}-*.md")) or sorted(tasks_dir.glob(f"{task_id}.md"))
    task_path = next(iter(candidates), None)
    if task_path is None:
        return
    text = task_path.read_text(encoding="utf-8")
    current_state = _read_task_state(text)
    if not current_state:
        return
    updated = text.replace(f"state: {current_state}", f"state: {new_state}", 1)
    updated = upsert_updated_at(updated)
    task_path.write_text(updated, encoding="utf-8")


def _retained_developer_agent_ids(
    graph, project_root: Path | str, project_name: str
) -> set[str]:
    """T-AF008-US14-02: `agent_id` de cualquier Developer que cerró una
    Task todavía en `IN_REVIEW` (esperando veredicto del Tester) o cuya
    Task de corrección derivada sigue sin resolver — ver
    `get_developer_waits_for_tester_review` (`system_preferences.py`,
    decisión de producto explícita del usuario: "el developer debe
    esperar hasta que el tester le responda", no coger Task nueva
    mientras tanto, para que nunca certifique su propio trabajo en
    paralelo).

    Cruza las Tasks `IN_REVIEW` reales del backlog con las entradas
    `dispatched` de `dispatch_queue.json` (que ya guardan `agent_id` de
    quien la despachó, `mark_dispatched`) — una Task puede estar en
    `IN_REVIEW` sin entrada JSON (marcada a mano), en cuyo caso no hay
    ningún Developer que retener por esta vía.

    El llamador (`run_dispatch_cycle`) ya comprueba
    `get_developer_waits_for_tester_review` antes de invocar esta
    función — si la preferencia está en `False`, ni se llama."""
    review_task_ids = {
        item.id for item in graph.items.values()
        if item.kind == "T" and item.state == "IN_REVIEW"
    }
    if not review_task_ids:
        return set()
    entries = get_queue(project_root, project_name)
    return {
        e.agent_id
        for e in entries
        if e.task_id in review_task_ids and e.status == STATUS_DISPATCHED and e.agent_id
    }


def _pick_developer_for_difficulty(
    session: DevelopmentSession,
    difficulty: str | None,
    project_root: Path | str,
    socket_name: str = DEFAULT_SOCKET_NAME,
    retained_agent_ids: frozenset[str] = frozenset(),
) -> tuple[Agent, str] | None:
    """Elige el Developer `idle` más adecuado para una Task de cierta
    dificultad, aplicando la lógica de T-AF008-US12-02:

    1. Si no hay dificultad, retorna cualquier Developer `idle` ("sin requisito")
    2. Consulta get_models_for_difficulty para saber qué tier se requiere
    3. Busca entre TODOS los Developers `idle` cuyo modelo ya encaja
    4. Si no hay uno que encaje, intenta cambiar el modelo de un Developer
       `idle` de OpenCode (runtime que soporta cambio)
    5. Si no se puede cambiar a OpenCode, registra degradación

    Retorna tupla (agent, dispatch_reason) o None si no hay Developer elegible.
    Nunca intenta cambiar modelo en un agente `working`."""
    idle_developers = [
        agent for agent in list_agents(session)
        if isinstance(agent, Agent) and agent.role == _DEVELOPER_ROLE and agent.status == "idle"
        and agent.id not in retained_agent_ids
    ]

    if not idle_developers:
        return None

    if not difficulty:
        return (idle_developers[0], "sin requisito de dificultad")

    try:
        required_models = get_models_for_difficulty(difficulty, project_root)
    except (KeyError, Exception):
        return (idle_developers[0], f"dificultad '{difficulty}' no reconocida, degradado")

    if not required_models:
        return (idle_developers[0], f"no hay modelos disponibles para dificultad '{difficulty}', degradado")

    # PASO 3: Busca un Developer cuyo modelo ya encaja (sin cambiar)
    for agent in idle_developers:
        current_model = get_active_model(agent.id, socket_name=socket_name)
        if current_model:
            for req_model in required_models:
                if (req_model.name in current_model or
                    req_model.id in current_model or
                    req_model.name.lower() in current_model.lower()):
                    return (agent, f"encaja directo: modelo actual satisface dificultad '{difficulty}'")

    # PASO 4: Si ninguno encaja, intenta cambiar el modelo de un Developer OpenCode
    for agent in idle_developers:
        runtime_instance = get_runtime_instance_for_agent(agent.id)
        if runtime_instance and runtime_instance.runtime.type == "opencode":
            target_model = required_models[0]
            try:
                success = set_active_model(agent.id, target_model.id, socket_name=socket_name)
                if success:
                    return (agent, f"cambio de modelo aplicado: {target_model.id} para dificultad '{difficulty}'")
            except Exception:
                pass

    return (idle_developers[0], f"runtime no soporta cambio de modelo, degradado con modelo actual")


def _get_task_difficulty(graph, task_id: str) -> str | None:
    """Extrae la dificultad de una Task del grafo del backlog."""
    item = graph.items.get(task_id)
    if item and item.kind == "T":
        return item.difficulty
    return None


@dataclass
class InFlightJob:
    """Registro de un Job de implementación en vuelo (T-AF022-US06-05):
    despachado de forma NO BLOQUEANTE por `run_dispatch_cycle`, aún sin
    reporte del Developer. El ciclo de completión
    (`poll_inflight_job_completions`) lo vigila por polling.

    T-AF008-US18-02: el registro `inflight` del Dispatcher se clavea por
    `job.id` (NO por `task_id`) — un re-despacho del MISMO `task_id`
    produce DOS entradas independientes en vuelo, ambas vigiladas por su
    propio `report_file`, sin orfear el Job previo (causal raíz del
    hallazgo "Agentic stuck" 2026-08-24). `task_id` se conserva como
    atributo para las operaciones de estado sobre la Task."""

    task_id: str
    agent_id: str
    report_file: Path
    job: Job
    dispatched_at: float


def poll_inflight_job_completions(
    project_root: Path | str,
    project_name: str,
    session: DevelopmentSession,
    inflight: dict[str, InFlightJob],
    timeout_seconds: float = AGENT_STEP_TIMEOUT_SECONDS,
    socket_name: str = DEFAULT_SOCKET_NAME,
) -> list[str]:
    """Nivel de completión NO BLOQUEANTE del ciclo de despacho
    (T-AF022-US06-05): revisa cada Job en vuelo del registro `inflight`
    (claveado por `job.id -> InFlightJob`, T-AF008-US18-02) y finaliza los
    que ya terminaron:

    - Reporte con marcador presente (`read_finished_report`): el Developer
      cerró la Task → `job` `completed`, agente `idle`, Task `IN_REVIEW`, y
      se retira el Job del registro (la entrada `dispatched` de
      `dispatch_queue.json` se deja intacta a propósito: el Developer que
      la cerró queda retenido hasta que el Tester la resuelva).
    - Sin reporte y `now - dispatched_at >= timeout_seconds`: Job `failed`,
      agente `idle`, entrada de cola `failed`, Task `TO_DEVELOP` (tras un
      fallo la Task no vuelve a `READY`, solo un humano la revierte).

    No bloquea: comprueba cada fichero una vez y vuelve. Devuelve la lista
    de `task_id` que dejaron de estar en vuelo este ciclo (deduplicada: dos
    Jobs del MISMO `task_id` pueden resolverse en el mismo ciclo, ambos se
    vigilan y se finalizan independientemente)."""
    tasks_dir = Path(project_root) / "02-backlog" / "tasks"
    agent_by_id = {a.id: a for a in list_agents(session)}
    resolved: list[str] = []
    now = time.monotonic()
    for job_key, infl in list(inflight.items()):
        task_id = infl.task_id
        agent = agent_by_id.get(infl.agent_id)
        report = read_finished_report(infl.report_file)
        if report is not None:
            wait_and_finalize_job(
                infl.job, agent, infl.report_file,
                timeout_seconds, poll_interval_seconds=0,
            )
            _update_task_file_state(tasks_dir, task_id, "IN_REVIEW")
            del inflight[job_key]
            resolved.append(task_id)
        elif pane_indicates_finished_without_report(agent, infl.report_file, socket_name):
            # T-AF008-US10-06: el agente terminó su reporte en el pane pero
            # no escribió el fichero — se cierra el Job como `failed`
            # (recuperable) sin esperar el timeout, y la Task vuelve a
            # `TO_DEVELOP` (mismo criterio que el timeout).
            fail_job_finished_in_pane(infl.job, agent, infl.report_file)
            mark_failed(
                project_root, project_name, task_id,
                result=(
                    "Agente terminó en el pane sin escribir el fichero de "
                    "auto-reporte."
                ),
            )
            _update_task_file_state(tasks_dir, task_id, "TO_DEVELOP")
            del inflight[job_key]
            resolved.append(task_id)
        elif now - infl.dispatched_at >= timeout_seconds:
            fail_job_on_timeout(infl.job, agent, infl.report_file, timeout_seconds)
            mark_failed(
                project_root, project_name, task_id,
                result=f"Timeout esperando reporte del agente (>{timeout_seconds:.0f}s).",
            )
            _update_task_file_state(tasks_dir, task_id, "TO_DEVELOP")
            del inflight[job_key]
            resolved.append(task_id)
    return list(dict.fromkeys(resolved))


@dataclass
class InFlightReviewJob:
    """Registro de una verificación del Tester en vuelo (T-AF022-US06-06):
    despachada de forma NO BLOQUEANTE por `run_review_dispatch_cycle`, aún
    sin veredicto."""

    task_id: str
    tester_agent_id: str
    report_file: Path
    job: Job
    dispatched_at: float
    task_item: object


@dataclass
class InFlightArchitectVerdict:
    """Registro de un veredicto de User Story en vuelo (T-AF022-US06-06):
    despachado de forma NO BLOQUEANTE hacia el Arquitecto, aún sin
    veredicto."""

    story_id: str
    architect_agent_id: str
    report_file: Path
    job: Job
    dispatched_at: float
    reports: list[str]
    reports_root: Path | None
    backlog_dir: Path | None
    socket_name: str
    session: DevelopmentSession


@dataclass
class InFlightLandingJob:
    """Registro de un aterrizaje US→Tasks en vuelo (T-AF008-US16-01/02):
    despachado de forma NO BLOQUEANTE como Job al Arquitecto, aún sin
    propuesta."""

    us_id: str
    architect_agent_id: str
    report_file: Path
    job: Job
    dispatched_at: float
    us_item: object


@dataclass
class InFlightCreationJob:
    """Registro de una petición de creación (Epic/US/Task) en vuelo
    (T-AF036-US20-07, US-AF036-20): despachada de forma NO BLOQUEANTE como
    Job al Arquitecto, aún sin propuesta estructurada. `request_id` es el de
    la cola de peticiones de creación (T-AF036-US20-06); `tipo` ∈
    {epic, us, task} repite el de la petición para la completión
    (T-AF036-US20-08). El registro `_inflight_creation` del worker se clavea
    POR `request_id` (una entrada por petición pendiente despachada)."""
    request_id: str
    tipo: str
    architect_agent_id: str
    report_file: Path
    job: Job
    dispatched_at: float


def poll_inflight_landing_completions(
    project_root: Path | str,
    session: DevelopmentSession,
    inflight_landing: dict[str, InFlightLandingJob],
    timeout_seconds: float = AGENT_STEP_TIMEOUT_SECONDS,
) -> list[str]:
    """Nivel de completión NO BLOQUEANTE del aterrizaje US→Tasks
    (T-AF008-US16-02): revisa cada aterrizaje en vuelo del registro
    `inflight_landing` (`us_id -> InFlightLandingJob`) y procesa los que el
    Arquitecto ya resolvió.

    - Propuesta presente (`read_finished_report`): la interpreta
      (`parse_landing_proposal`), valida CADA Task con
      `validate_backlog_file_v2` y escribe solo las válidas
      (`write_validated_landing_tasks`). Si al menos una Task se escribe,
      la US transiciona `TO_PLAN` -> `READY` (`set_item_state`); si ninguna
      valida, la propuesta se descarta y la US queda `TO_PLAN` (reintento).
    - Sin propuesta y `now - dispatched_at >= timeout_seconds`: Job
      `failed`, la US queda `TO_PLAN` re-encolable.

    No bloquea: comprueba cada fichero una vez y vuelve. Devuelve la lista
    de `us_id` resueltos este ciclo."""
    from atlas_forge.architect.landing_proposal import (
        parse_landing_proposal,
        write_validated_landing_tasks,
    )
    from atlas_forge.backlog.edit import set_item_state

    tasks_dir = Path(project_root) / "02-backlog" / "tasks"
    agent_by_id = {a.id: a for a in list_agents(session)}
    resolved: list[str] = []
    now = time.monotonic()
    for us_id, infl in list(inflight_landing.items()):
        architect = agent_by_id.get(infl.architect_agent_id)
        report = read_finished_report(infl.report_file)
        if report is not None:
            wait_and_finalize_job(
                infl.job, architect, infl.report_file,
                timeout_seconds, poll_interval_seconds=0,
            )
            proposal = parse_landing_proposal(report)
            write_result = write_validated_landing_tasks(proposal, tasks_dir)
            if write_result.written:
                set_item_state(infl.us_item.path, "READY")
            del inflight_landing[us_id]
            resolved.append(us_id)
        elif now - infl.dispatched_at >= timeout_seconds:
            fail_job_on_timeout(infl.job, architect, infl.report_file, timeout_seconds)
            del inflight_landing[us_id]
            resolved.append(us_id)
    return resolved


def poll_inflight_review_completions(
    project_root: Path | str,
    project_name: str,
    session: DevelopmentSession,
    inflight_review: dict[str, InFlightReviewJob],
    inflight: dict[str, InFlightJob],
    socket_name: str = DEFAULT_SOCKET_NAME,
    timeout_seconds: float = AGENT_STEP_TIMEOUT_SECONDS,
) -> list[str]:
    """Nivel de completión NO BLOQUEANTE del ciclo de revisión
    (T-AF022-US06-06): revisa cada verificación en vuelo del registro
    `inflight_review` (`task_id -> InFlightReviewJob`) y procesa las que el
    Tester ya resolvió:

    - Veredicto presente (`read_finished_report`): `EXITO` -> Task `DONE`
      (el Developer retenido queda libre porque su Task ya no está
      `IN_REVIEW`); `FALLO` (o no parseable) -> la Task vuelve al MISMO
      Developer (`_redispatch_task_to_retained_developer`, registrando el
      Job de corrección en `inflight` para su completión). En ambos casos
      se retira la verificación del registro.
    - Sin veredicto y `now - dispatched_at >= timeout_seconds`: Job
      `failed`, veredicto descartado, Task queda `IN_REVIEW` (re-encolable).

    No bloquea: comprueba cada fichero una vez y vuelve."""
    tasks_dir = Path(project_root) / "02-backlog" / "tasks"
    agent_by_id = {a.id: a for a in list_agents(session)}
    resolved: list[str] = []
    now = time.monotonic()
    for task_id, infl in list(inflight_review.items()):
        tester = agent_by_id.get(infl.tester_agent_id)
        report = read_finished_report(infl.report_file)
        if report is not None:
            wait_and_finalize_job(
                infl.job, tester, infl.report_file,
                timeout_seconds, poll_interval_seconds=0,
            )
            resultado, resumen, siguiente_paso = parse_task_verdict(infl.job.result)
            if resultado == VERDICT_PASSED:
                _update_task_file_state(tasks_dir, task_id, "DONE")
                mark_completed(
                    project_root, project_name, task_id,
                    result="Veredicto EXITO del Tester.",
                )
            else:
                # FALLO, o veredicto no parseable — vuelve al mismo
                # Developer (decisión 2026-08-17), sin Task nueva.
                _redispatch_task_to_retained_developer(
                    project_root, project_name, session, infl.task_item,
                    resumen, siguiente_paso, tasks_dir, socket_name,
                    inflight=inflight,
                )
            del inflight_review[task_id]
            resolved.append(task_id)
        elif now - infl.dispatched_at >= timeout_seconds:
            fail_job_on_timeout(infl.job, tester, infl.report_file, timeout_seconds)
            del inflight_review[task_id]
            resolved.append(task_id)
    return resolved


def run_dispatch_cycle(
    project_root: Path | str,
    project_name: str,
    session: DevelopmentSession,
    socket_name: str = DEFAULT_SOCKET_NAME,
    inflight: dict[str, InFlightJob] | None = None,
) -> str | None:
    """Un único ciclo de revisión de la cola: si hay al menos un
    Developer `idle` y al menos una Task encolada elegible (dependencias
    cumplidas), despacha exactamente UNA Task y devuelve su `task_id`
    (`None` si no se despachó nada este ciclo).

    Despacha como máximo una Task por ciclo (no un bucle interno hasta
    vaciar la cola): el siguiente ciclo de polling ya vuelve a revisar el
    estado real de los Developers.

    ## Despacho NO BLOQUEANTE (T-AF022-US06-05)

    El despacho ya NO espera a que el Developer termine su Task. Envía la
    instrucción del Job al pane del Developer (asignación de Task,
    `state: IN_PROGRESS`, registro del Job en vuelo) y DEVUELVE de
    inmediato. La espera por el fichero de reporte y la promoción a
    `IN_REVIEW` (o el timeout a `TO_DEVELOP`/`failed`) viven en
    `poll_inflight_job_completions`, que el worker ejecuta en cada ciclo
    de polling.

    `inflight` es el registro de Jobs en vuelo del worker (`job.id ->
    InFlightJob`, T-AF008-US18-02); el llamador que quiera hacer un ciclo
    no bloqueante debe pasarlo para que el Job quede vigilado. Si es
    `None`, se usa un registro local desechable."""
    tasks_dir = Path(project_root) / "02-backlog" / "tasks"
    graph = load_backlog(Path(project_root) / "02-backlog")
    done_ids = {item_id for item_id, item in graph.items.items() if item.state == "DONE"}
    dependencies_of = dict(graph.dependencies_of)

    entries = get_queue(project_root, project_name)
    task_id = _pick_next_eligible_task_id(graph, entries, done_ids, dependencies_of)
    if task_id is None:
        return None

    difficulty = _get_task_difficulty(graph, task_id)
    retained_agent_ids = (
        frozenset(_retained_developer_agent_ids(graph, project_root, project_name))
        if get_developer_waits_for_tester_review()
        else frozenset()
    )

    excluded: set[str] = set()
    while True:
        result = _pick_developer_for_difficulty(
            session, difficulty, project_root, socket_name,
            retained_agent_ids=retained_agent_ids | frozenset(excluded),
        )
        if result is None:
            return None

        agent, dispatch_reason = result
        runtime_instance = get_runtime_instance_for_agent(agent.id)
        if runtime_instance is None:
            return None

        if is_agent_ready_for_input(
            agent, socket_name=socket_name, runtime_instance=runtime_instance
        ):
            break
        excluded.add(agent.id)

    mark_dispatched(project_root, project_name, task_id, agent_id=agent.id, agent_name=agent.name, dispatch_reason=dispatch_reason)
    _update_task_file_state(tasks_dir, task_id, "IN_PROGRESS")

    task_title = task_id
    task_path = next(iter(sorted(tasks_dir.glob(f"{task_id}-*.md"))), None)
    description = f"Desarrolla la Task {task_title} (encolada vía la pantalla Backlog)."
    if task_path is not None:
        description += f"\n\nFichero: {task_path.name}"

    try:
        job = create_and_record_job(description, agent, session)
        job.story_id = graph.items[task_id].user_story
        report_file = dispatch_job_send(
            job, agent, runtime_instance, socket_name=socket_name
        )
    except AgentNotReadyError:
        mark_failed(project_root, project_name, task_id, result="Agente no listo para recibir la orden (reintento en el siguiente ciclo).")
        _update_task_file_state(tasks_dir, task_id, "TO_DEVELOP")
        return task_id
    except (JobCreationError, Exception) as error:
        mark_failed(project_root, project_name, task_id, result=str(error))
        _update_task_file_state(tasks_dir, task_id, "TO_DEVELOP")
        return task_id

    set_entry_report_file(project_root, project_name, task_id, report_file)
    registry = inflight if inflight is not None else {}
    # T-AF008-US18-02: clavear por `job.id` (no `task_id`) — un re-despacho
    # del MISMO task_id crea DOS entradas independientes en vuelo, ambas
    # vigiladas por su propio report_file; ninguna se orfa.
    registry[job.id] = InFlightJob(
        task_id=task_id,
        agent_id=agent.id,
        report_file=report_file,
        job=job,
        dispatched_at=time.monotonic(),
    )
    return task_id


def _annotate_task_with_correction_note(tasks_dir: Path, task_id: str, resumen: str, siguiente_paso: str) -> None:
    """Añade una sección `## Corrección pendiente` al fichero de
    `task_id` con el hallazgo del Tester. Se sobreescribe en cada fallo."""
    candidates = sorted(tasks_dir.glob(f"{task_id}-*.md")) or sorted(tasks_dir.glob(f"{task_id}.md"))
    task_path = next(iter(candidates), None)
    if task_path is None:
        return
    text = task_path.read_text(encoding="utf-8")
    text = re.sub(r"\n## Corrección pendiente\n.*$", "", text, flags=re.DOTALL)
    text += (
        f"\n## Corrección pendiente\n\n"
        f"El Tester encontró un problema al verificar esta Task:\n\n"
        f"**Resumen:** {resumen or '(sin resumen)'}\n\n"
        f"**Siguiente paso:** {siguiente_paso or '(sin instrucción específica)'}\n"
    )
    task_path.write_text(text, encoding="utf-8")


def _redispatch_task_to_retained_developer(
    project_root: Path | str,
    project_name: str,
    session: DevelopmentSession,
    task_item,
    resumen: str,
    siguiente_paso: str,
    tasks_dir: Path,
    socket_name: str,
    inflight: dict[str, InFlightJob] | None = None,
) -> str | None:
    """Ante un veredicto FALLO del Tester, devuelve la Task DIRECTAMENTE
    al mismo Developer que la cerró — decisión explícita del usuario,
    2026-08-17 ("PIPELINE OPERATIVO Y RECONCILIACIÓN", sustituye el
    diseño anterior de Task de corrección nueva): "esa orden va a la
    cola, pasa al dispatcher y este se la manda al mismo developer que
    está esperando, no se crea nueva task".

    El `agent_id` del Developer que la cerró se lee de la entrada
    `dispatched` de `dispatch_queue.json` (`mark_dispatched`, mismo dato
    que ya usa `_retained_developer_agent_ids`). Si ese agente ya no
    está disponible (runtime caído, ya no está en la sesión), la Task
    queda anotada con el hallazgo y vuelve a `TO_DEVELOP` — el ciclo
    normal de `run_dispatch_cycle` la recogerá cuando un Developer quede
    libre.

    **No bloqueante (T-AF022-US06-06):** si `inflight` es un registro de
    Jobs en vuelo, el redespacho envía la instrucción de corrección al
    Developer y registra el Job en ese registro, devolviendo de inmediato
    el `task_id`."""
    entries = get_queue(project_root, project_name)
    dispatched_entry = next(
        (e for e in entries if e.task_id == task_item.id and e.status == STATUS_DISPATCHED and e.agent_id),
        None,
    )
    _annotate_task_with_correction_note(tasks_dir, task_item.id, resumen, siguiente_paso)

    developer_agent = None
    if dispatched_entry is not None:
        developer_agent = next(
            (
                agent for agent in list_agents(session)
                if isinstance(agent, Agent) and agent.id == dispatched_entry.agent_id
            ),
            None,
        )

    if developer_agent is None:
        _update_task_file_state(tasks_dir, task_item.id, "TO_DEVELOP")
        return None

    runtime_instance = get_runtime_instance_for_agent(developer_agent.id)
    if runtime_instance is None:
        _update_task_file_state(tasks_dir, task_item.id, "TO_DEVELOP")
        return None

    if not is_agent_ready_for_input(
        developer_agent, socket_name=socket_name, runtime_instance=runtime_instance
    ):
        _update_task_file_state(tasks_dir, task_item.id, "TO_DEVELOP")
        return None

    task_path = next(iter(sorted(tasks_dir.glob(f"{task_item.id}-*.md"))), None)
    description = (
        f"El Tester encontró un problema al verificar la Task {task_item.id}. "
        f"Corrígelo antes de darla por completada de nuevo.\n\n"
        f"Resumen del Tester: {resumen or '(sin resumen)'}\n\n"
        f"Siguiente paso sugerido: {siguiente_paso or '(sin instrucción específica)'}"
    )
    if task_path is not None:
        description += f"\n\nFichero: {task_path.name}"

    _update_task_file_state(tasks_dir, task_item.id, "IN_PROGRESS")

    try:
        job = create_and_record_job(description, developer_agent, session)
        job.story_id = task_item.user_story
        if inflight is None:
            dispatch_job_send(
                job, developer_agent, runtime_instance, socket_name=socket_name
            )
        else:
            report_file = dispatch_job_send(
                job, developer_agent, runtime_instance, socket_name=socket_name
            )
            set_entry_report_file(project_root, project_name, task_item.id, report_file)
            # T-AF008-US18-02: registro por `job.id` (mismo criterio que
            # `run_dispatch_cycle`) — nunca por task_id.
            inflight[job.id] = InFlightJob(
                task_id=task_item.id,
                agent_id=developer_agent.id,
                report_file=report_file,
                job=job,
                dispatched_at=time.monotonic(),
            )
            return task_item.id
    except AgentNotReadyError:
        _update_task_file_state(tasks_dir, task_item.id, "TO_DEVELOP")
        return None
    except (JobCreationError, Exception):
        return None

    return task_item.id


def run_review_dispatch_cycle(
    project_root: Path | str,
    project_name: str,
    session: DevelopmentSession,
    socket_name: str = DEFAULT_SOCKET_NAME,
    inflight_review: dict[str, InFlightReviewJob] | None = None,
    inflight: dict[str, InFlightJob] | None = None,
) -> str | None:
    """Segundo nivel de REVIEW (T-AF008-US14-02): si hay al menos una Task
    en `state == "IN_REVIEW"` (AF-040) y un Tester `idle`, despacha
    exactamente una verificación y procesa su veredicto
    (`RESULTADO: EXITO|FALLO`, `task_verdict.parse_task_verdict`):

    - `EXITO`: la Task pasa a `DONE`.
    - `FALLO`: la Task vuelve directamente al MISMO Developer que la
      cerró (`_redispatch_task_to_retained_developer`).

    ## Despacho NO BLOQUEANTE (T-AF022-US06-06)

    Este ciclo NO espera al Tester: envía la verificación, la registra en
    `inflight_review` (`task_id -> InFlightReviewJob`) y DEVUELVE de
    inmediato. El procesamiento del veredicto vive en
    `poll_inflight_review_completions`.

    `inflight_review` es el registro de verificaciones en vuelo del worker
    y `inflight` el registro de Jobs de implementación (que el FALLO usa
    para re-registrar el Job de corrección). Si no se pasan, se usan
    registros locales desechables."""
    tasks_dir = Path(project_root) / "02-backlog" / "tasks"
    backlog_dir = Path(project_root) / "02-backlog"
    graph = load_backlog(backlog_dir)

    review_tasks = sorted(
        (item for item in graph.items.values() if item.kind == "T" and item.state == "IN_REVIEW"),
        key=lambda item: item.id,
    )
    if not review_tasks:
        return None
    task_item = review_tasks[0]

    tester_agent = next(
        (
            agent for agent in list_agents(session)
            if isinstance(agent, Agent) and agent.role == _TESTER_ROLE and agent.status == "idle"
        ),
        None,
    )
    if tester_agent is None:
        return None

    runtime_instance = get_runtime_instance_for_agent(tester_agent.id)
    if runtime_instance is None:
        return None

    if not is_agent_ready_for_input(
        tester_agent, socket_name=socket_name, runtime_instance=runtime_instance
    ):
        return None

    task_path = next(iter(sorted(tasks_dir.glob(f"{task_item.id}-*.md"))), None)
    description = (
        f"Verifica la Task {task_item.id} (cerrada por el Developer, en IN_REVIEW)."
    )
    if task_path is not None:
        description += f"\n\nFichero: {task_path.name}"

    try:
        job = create_and_record_job(description, tester_agent, session)
        job.story_id = task_item.user_story
        report_file = dispatch_job_send(
            job, tester_agent, runtime_instance, socket_name=socket_name
        )
    except (JobCreationError, Exception):
        return None

    registry = inflight_review if inflight_review is not None else {}
    registry[task_item.id] = InFlightReviewJob(
        task_id=task_item.id,
        tester_agent_id=tester_agent.id,
        report_file=report_file,
        job=job,
        dispatched_at=time.monotonic(),
        task_item=task_item,
    )
    return task_item.id


def story_is_fully_done(graph, story_id: str) -> bool:
    """`True` si TODAS las Tasks de `story_id` en el grafo están `DONE`
    (y existe al menos una)."""
    story_tasks = [
        item for item in graph.items.values()
        if item.kind == "T" and item.user_story == story_id
    ]
    if not story_tasks:
        return False
    return all(item.state == "DONE" for item in story_tasks)


def run_architect_verdict_dispatch_cycle(
    project_root: Path | str,
    project_name: str,
    session: DevelopmentSession,
    socket_name: str = DEFAULT_SOCKET_NAME,
    reports_root: Path | None = None,
    inflight_architect_verdict: dict[str, InFlightArchitectVerdict] | None = None,
) -> str | None:
    """Tercer nivel (T-AF008-US14-02): si hay al menos una User Story en
    `state == "IN_REVIEW"` (AF-040) y un Arquitecto `idle`, despacha su
    veredicto.

    **Despacho NO BLOQUEANTE (T-AF022-US06-06):** igual que los niveles 1
    y 2, este ciclo NO espera al Arquitecto — envía el Job de veredicto,
    lo registra en `inflight_architect_verdict` y devuelve de inmediato.
    El procesamiento del veredicto lo hace
    `poll_inflight_architect_verdict_completions`."""
    backlog_dir = Path(project_root) / "02-backlog"
    graph = load_backlog(backlog_dir)

    review_stories = sorted(
        item.id for item in graph.items.values()
        if item.kind == "US" and item.state == "IN_REVIEW"
    )
    if not review_stories:
        return None
    story_id = review_stories[0]

    registry = inflight_architect_verdict if inflight_architect_verdict is not None else {}
    try:
        dispatched = dispatch_architect_verdict_send(
            story_id, session, socket_name, reports_root, backlog_dir, registry
        )
    except Exception:
        return None

    return dispatched


def _find_architect(session: DevelopmentSession, require_idle: bool = True) -> Agent | None:
    """Localiza un agente con rol Arquitecto (`ARQUITECTO_ROLE`), con
    filtro opcional de `idle`."""
    from atlas_forge.agents.arquitecto import ARQUITECTO_ROLE

    return next(
        (
            agent
            for agent in list_agents(session)
            if isinstance(agent, Agent) and agent.role == ARQUITECTO_ROLE
            and (agent.status == "idle" if require_idle else True)
        ),
        None,
    )


def _build_architect_verdict_description(story_id: str, reports: list[str]) -> str:
    """Construye la instrucción del Job de veredicto al Arquitecto."""
    if reports:
        report_blocks = "\n\n---\n\n".join(reports)
        return (
            f"Revisa el trabajo completado para la User Story {story_id}.\n\n"
            f"A continuación se incluyen los informes de cierre de cada Job "
            f"que trabajó en esta User Story. Emite tu veredicto en el "
            f"formato estructurado ESTADO:/JUSTIFICACIÓN:/"
            f"SIGUIENTE_PROMPT_PARA_WORKER:\n\n"
            f"{report_blocks}"
        )
    return (
        f"Revisa el trabajo completado para la User Story {story_id}.\n\n"
        f"(No se encontraron informes de cierre para esta User Story. "
        f"Emite tu veredicto basándote en el contexto disponible.)"
    )


def dispatch_architect_verdict_send(
    story_id: str,
    session: DevelopmentSession,
    socket_name: str,
    reports_root: Path | None,
    backlog_dir: Path | None,
    inflight_verdict: dict[str, InFlightArchitectVerdict],
) -> str | None:
    """Despacho NO BLOQUEANTE del veredicto de `story_id`: envía el Job al
    Arquitecto `idle`, lo registra en `inflight_verdict` y devuelve de
    inmediato. El procesamiento del veredicto (promoción de estado +
    Tester de UI) lo hace `poll_inflight_architect_verdict_completions`."""
    from atlas_forge.dispatcher.job_creation import JobCreationError
    from atlas_forge.dispatcher.job_orchestration import create_and_record_job
    from atlas_forge.dispatcher.job_dispatch import dispatch_job_send

    root = (
        reports_root
        if reports_root
        else Path(__file__).resolve().parents[4] / "07-informes"
    )
    reports = _collect_story_reports(story_id, root)

    architect_agent = _find_architect(session, require_idle=True)
    if architect_agent is None:
        return None

    runtime_instance = get_runtime_instance_for_agent(architect_agent.id)
    if runtime_instance is None:
        return None

    if not is_agent_ready_for_input(
        architect_agent, socket_name=socket_name, runtime_instance=runtime_instance
    ):
        return None

    description = _build_architect_verdict_description(story_id, reports)

    try:
        job = create_and_record_job(description, architect_agent, session)
        report_file = dispatch_job_send(
            job, architect_agent, runtime_instance, socket_name=socket_name
        )
    except (JobCreationError, Exception):
        return None

    inflight_verdict[story_id] = InFlightArchitectVerdict(
        story_id=story_id,
        architect_agent_id=architect_agent.id,
        report_file=report_file,
        job=job,
        dispatched_at=time.monotonic(),
        reports=reports,
        reports_root=reports_root,
        backlog_dir=backlog_dir,
        socket_name=socket_name,
        session=session,
    )
    return story_id


def poll_inflight_architect_verdict_completions(
    session: DevelopmentSession,
    inflight_verdict: dict[str, InFlightArchitectVerdict],
    timeout_seconds: float = AGENT_STEP_TIMEOUT_SECONDS,
) -> list[str]:
    """Nivel de completión NO BLOQUEANTE del veredicto de User Story
    (T-AF022-US06-06): revisa cada veredicto en vuelo y, cuando el
    Arquitecto reporta, procesa la promoción de estado
    (`_process_verdict_result`) y el disparo del Tester de UI
    (`_maybe_enqueue_ui_tester`); en timeout descarta el Job y deja la US
    en `IN_REVIEW` (re-encolable)."""
    from atlas_forge.dispatcher.architect_verdict_queue import _maybe_enqueue_ui_tester

    agent_by_id = {a.id: a for a in list_agents(session)}
    resolved: list[str] = []
    now = time.monotonic()
    for story_id, infl in list(inflight_verdict.items()):
        architect = agent_by_id.get(infl.architect_agent_id)
        report = read_finished_report(infl.report_file)
        if report is not None:
            wait_and_finalize_job(
                infl.job, architect, infl.report_file,
                timeout_seconds, poll_interval_seconds=0,
            )
            verdict_output = infl.job.result
            _process_verdict_result(story_id, verdict_output, backlog_dir=infl.backlog_dir)
            _maybe_enqueue_ui_tester(
                story_id, verdict_output, infl.reports,
                infl.session, infl.socket_name, infl.reports_root,
            )
            del inflight_verdict[story_id]
            resolved.append(story_id)
        elif now - infl.dispatched_at >= timeout_seconds:
            fail_job_on_timeout(infl.job, architect, infl.report_file, timeout_seconds)
            del inflight_verdict[story_id]
            resolved.append(story_id)
    return resolved


def dispatch_architect_verdict(
    story_id: str,
    session: DevelopmentSession,
    socket_name: str,
    reports_root: Path | None = None,
    backlog_dir: Path | None = None,
) -> str | None:
    """Despacha un Job de veredicto concreto hacia el Arquitecto y
    encadena su procesamiento. **Síncrono (se conserva):** este camino
    bloquea hasta que el Arquitecto reporta, devolviendo el `job.result` —
    es el que requieren la cola FIFO histórica y los caminos de
    `POST /jobs`/planes."""
    from atlas_forge.dispatcher.job_creation import JobCreationError
    from atlas_forge.dispatcher.job_orchestration import create_and_record_job
    from atlas_forge.dispatcher.job_dispatch import dispatch_job

    root = (
        reports_root
        if reports_root
        else Path(__file__).resolve().parents[4] / "07-informes"
    )
    reports = _collect_story_reports(story_id, root)

    architect_agent = _find_architect(session, require_idle=False)
    if architect_agent is None:
        return None

    runtime_instance = get_runtime_instance_for_agent(architect_agent.id)
    if runtime_instance is None:
        return None

    if not is_agent_ready_for_input(
        architect_agent, socket_name=socket_name, runtime_instance=runtime_instance
    ):
        return None

    description = _build_architect_verdict_description(story_id, reports)

    try:
        job = create_and_record_job(description, architect_agent, session)
        dispatch_job(job, architect_agent, runtime_instance, socket_name=socket_name)
        _process_verdict_result(story_id, job.result, backlog_dir=backlog_dir)
    except JobCreationError:
        return None

    return job.result


class DispatchQueueWorker:
    """Hilo `daemon` que llama a `run_dispatch_cycle` cada
    `poll_interval_seconds` mientras esté vivo. Un único worker por
    `(project_root, project_name)` — `start()` es idempotente."""

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
        self._inflight: dict[str, InFlightJob] = {}
        self._inflight_review: dict[str, InFlightReviewJob] = {}
        self._inflight_architect_verdict: dict[str, InFlightArchitectVerdict] = {}
        self._inflight_landing: dict[str, InFlightLandingJob] = {}
        self._inflight_creation: dict[str, InFlightCreationJob] = {}
        self._backlog_marks: dict | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        try:
            # Reconstruye y reconcilia los Jobs en vuelo legítimos
            # (T-AF008-US18-03): una Task `dispatched` en `dispatch_queue.json`
            # cuyo `report_file` aún no existe EN DISCO es el estado NORMAL de
            # un Job en curso (el fichero solo se crea cuando el agente termina
            # de escribir su informe) — NO es una "huérfana tras reinicio". Si
            # simplemente se reconciliara como huérfana al arrancar, se
            # marcaría `failed` (y revertiría a READY) trabajo que el agente
            # sigue haciendo, generando el re-despacho duplicado observado en
            # vivo. Así que: los Jobs en curso se re-registran para que el poll
            # de completión los vigile; los ya terminados (reporte con marcador)
            # se finalizan; y los que perdieron a su agente se marcan huérfanas
            # sin bloquear la cola.
            self._restore_inflight_from_queue()
        except Exception:
            pass
        # T-AF008-US18-02: `_inflight` se clavea por `job.id` — el conjunto
        # de task_ids protegidos se deriva de los valores, no de las claves.
        protected_arranque = (
            {infl.task_id for infl in self._inflight.values()}
            | set(self._inflight_review)
        )
        try:
            reconcile_dispatch_queue_entries(
                self._project_root, self._project_name,
                Path(self._project_root) / "02-backlog",
                auto_reenqueue_orphaned=get_auto_reenqueue_orphaned(),
                protected_task_ids=protected_arranque,
            )
        except Exception:
            pass
        # T-AF022-US20-01: la reconciliación de tasks `IN_PROGRESS` SIN
        # entrada `dispatched` (huérfanas reales, caso T-AF023-US03-01) también
        # se ejecuta al arrancar, con el MISMO `protected_arranque` (los Jobs
        # en vuelo restaurados nunca se revierten — no hay hueco por el que
        # una task protegida se trate como huérfana en el arranque).
        try:
            reconcile_orphaned_in_progress_tasks(
                self._project_root, self._project_name,
                Path(self._project_root) / "02-backlog",
                auto_reenqueue_orphaned=get_auto_reenqueue_orphaned(),
                protected_task_ids=protected_arranque,
            )
        except Exception:
            pass

        # T-AF022-US07-03: restaura la cola persistente de veredictos del
        # Arquitecto. Reconstruye (y re-persiste) el estado desde disco
        # reconciliándolo contra el backlog: ninguna US `IN_REVIEW` esperando
        # veredicto se pierde por un reinicio, y la US que estaba en vuelo
        # vuelve a quedar pendiente de revisión para que este worker la
        # re-despache. Un fallo de restauración no impide el arranque.
        try:
            reconcile_architect_verdict_queue(
                self._project_root, self._project_name,
                Path(self._project_root) / "02-backlog",
            )
        except Exception:
            pass
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="dispatch-queue-worker"
        )
        self._thread.start()

    @staticmethod
    def _new_job_id() -> str:
        """ID de Job reconstruido en vuelo (UUID hex) — no es el Job original
        (se perdió con el proceso anterior), pero basta para que el ciclo de
        completión vigile su `report_file` y lo finalice cuando aparezca."""
        import uuid
        return uuid.uuid4().hex

    def _restore_inflight_from_queue(self) -> None:
        """T-AF008-US10-05 + T-AF022-US18-02 + T-AF008-US18-03: reconstruye
        los Jobs en vuelo desde `dispatch_queue.json` en el arranque,
        RECONCILIANDO cada entrada `dispatched` con `report_file` contra la
        realidad — no la re-despacha a ciegas:

        - **Reporte con marcador** (el Job ya terminó): se finaliza ahora
          mismo (Job `completed`, Task a `IN_REVIEW`) y NO se re-despacha ni
          se vigila — evita la doble ejecución del mismo trabajo
          (criterio 1/4 de T-AF008-US18-03), aunque el agente ya no exista.
        - **Agente ya no existe** (crash/stop/tmx reiniciado) y el Job no
          puede terminar: se marca explícitamente como **huérfana** — la
          entrada pasa a `failed`, la Task vuelve a `TO_DEVELOP` (o `READY`
          según `get_auto_reenqueue_orphaned`) y se informa en
          `reconciliation_log.jsonl` (criterio 2). No bloquea la cola.
        - **Agente vivo y Job en curso**: se re-registra un `InFlightJob`
          (por `job.id`, T-AF008-US18-02) para que
          `poll_inflight_job_completions` vigile su `report_file` (criterio 1).

        Guarda especial: una Task ya en `IN_REVIEW` (su Job entregó el
        reporte en un arranque previo y el agente quedó retenido para el
        Tester) NO se re-vigila ni se re-despacha — la resuelve el ciclo de
        revisión; esto hace la reconstrucción idempotente entre reinicios
        (criterio 3: reiniciar dos veces no duplica Jobs ni cambia el estado
        de una Task sana).

        Las task_ids restauradas se pasan a la reconciliación del arranque
        como `protected_task_ids`, para que no las marque `failed` en el
        mismo `start()`. Mejor esfuerzo: un fallo puntual no rompe el resto
        del arranque."""
        entries = get_queue(self._project_root, self._project_name)
        agent_by_id = {a.id: a for a in list_agents(self._session)}
        auto_reenqueue = get_auto_reenqueue_orphaned()
        for entry in entries:
            if entry.status != STATUS_DISPATCHED:
                continue
            if any(infl.task_id == entry.task_id for infl in self._inflight.values()):
                continue
            if not entry.report_file:
                continue
            report_file = Path(entry.report_file)
            agent = agent_by_id.get(entry.agent_id)
            report = read_finished_report(report_file)

            # Criterio 1/4: reporte con marcador → Job terminado → finalizar.
            if report is not None:
                self._finalize_startup_completed_job(entry, report_file, agent)
                continue

            # Criterio 2: agente desaparecido y Job que no puede terminar.
            if agent is None:
                self._reconcile_startup_orphan(entry, auto_reenqueue)
                continue

            # Idempotencia (criterio 3): Job ya entregado en un arranque
            # previo (Task en IN_REVIEW) → lo gestiona el ciclo de revisión.
            if self._task_state_is(entry.task_id, "IN_REVIEW"):
                continue

            job = Job(
                id=self._new_job_id(),
                session_id=self._session.id,
                agent_id=entry.agent_id,
                description=f"Restaurado en vuelo tras reinicio (task {entry.task_id})",
                status="running",
            )
            # T-AF008-US18-02: clave por `job.id` (nunca task_id).
            self._inflight[job.id] = InFlightJob(
                task_id=entry.task_id,
                agent_id=entry.agent_id,
                report_file=report_file,
                job=job,
                dispatched_at=time.monotonic(),
            )

    def _tasks_dir(self) -> Path:
        return Path(self._project_root) / "02-backlog" / "tasks"

    def _task_state_is(self, task_id: str, expected: str) -> bool:
        """`True` si la Task `task_id` declara `state: <expected>` en su
        fichero real (búsqueda por sufijo de id en `tasks/`)."""
        tasks_dir = self._tasks_dir()
        candidates = sorted(tasks_dir.glob(f"{task_id}-*.md")) or sorted(
            tasks_dir.glob(f"{task_id}.md")
        )
        task_path = next(iter(candidates), None)
        if task_path is None:
            return False
        return _read_task_state(task_path.read_text(encoding="utf-8")).strip() == expected

    def _finalize_startup_completed_job(
        self, entry: QueueEntry, report_file: Path, agent: Agent | None
    ) -> None:
        """T-AF008-US18-03, criterio 1/4: un Job cuyo `report_file` ya tiene
        el marcador de fin es trabajo TERMINADO — se finaliza (Job
        `completed`, fichero de reporte consumido) y la Task pasa a
        `IN_REVIEW` sin re-despachar nada (evita la doble ejecución del mismo
        trabajo). El agente puede no existir (crash tras terminar): el Job se
        completa igualmente; la retención para el Tester se decide en el
        ciclo de revisión."""
        job = Job(
            id=self._new_job_id(),
            session_id=self._session.id,
            agent_id=entry.agent_id,
            description=f"Finalizado en el arranque (task {entry.task_id})",
            status="running",
        )
        try:
            wait_and_finalize_job(
                job, agent, report_file,
                timeout_seconds=AGENT_STEP_TIMEOUT_SECONDS,
                poll_interval_seconds=0,
            )
        except Exception:
            pass
        # Solo se promueve a IN_REVIEW si la Task sigue en IN_PROGRESS (el
        # estado del Job): nunca se degrada una Task DONE/READY a IN_REVIEW.
        if self._task_state_is(entry.task_id, "IN_PROGRESS"):
            _update_task_file_state(self._tasks_dir(), entry.task_id, "IN_REVIEW")

    def _reconcile_startup_orphan(self, entry: QueueEntry, auto_reenqueue: bool) -> None:
        """T-AF008-US18-03, criterio 2: el agente asignado a la entrada
        `dispatched` ya NO existe (crash/stop/tmux reiniciado) y el Job que
        dejó en vuelo jamás podrá terminar. La entrada se marca explícitamente
        como huérfana: la cola pasa a `failed`, la Task sale de `IN_PROGRESS`
        perpetuo a `TO_DEVELOP` (o `READY` si no hay auto-reencolado) y se
        informa en `reconciliation_log.jsonl` — todo sin bloquear la cola."""
        from atlas_forge.backlog.edit import set_item_state
        from atlas_forge.core.reconciliation_log import (
            append_dispatched_orphan_reconciliation,
        )

        tasks_dir = self._tasks_dir()
        candidates = sorted(tasks_dir.glob(f"{entry.task_id}-*.md")) or sorted(
            tasks_dir.glob(f"{entry.task_id}.md")
        )
        task_path = next(iter(candidates), None)
        target_state = "TO_DEVELOP" if auto_reenqueue else "READY"
        if task_path is not None and _read_task_state(
            task_path.read_text(encoding="utf-8")
        ).strip() == "IN_PROGRESS":
            set_item_state(task_path, target_state, force=True)
        mark_failed(
            self._project_root, self._project_name, entry.task_id,
            result=(
                "Reconciliada al arrancar: el agente ya no existe — Job "
                "huérfano tras reinicio."
            ),
        )
        append_dispatched_orphan_reconciliation(
            self._project_root, self._project_name,
            task_id=entry.task_id, target_state=target_state,
        )

    def _reconcile_orphaned_agent_entries(
        self, backlog_dir: Path, protected_task_ids: set[str], auto_reenqueue: bool
    ) -> list[str]:
        """T-AF008-US18-05, criterios 1/4: limpia en RUNTIME (sin esperar al
        reinicio) el residuo de Job huérfano `running`: una entrada
        `dispatched` de `dispatch_queue.json` cuyo agente ya NO está en la
        sesión (crash, stop que retira la instancia, tmux reiniciado) y cuya
        Task sigue `IN_PROGRESS` (el Job está colgado — su `report_file`
        existe sin marcador, caso que la reconciliación general no toca porque
        `report_file.is_file()` la salta).

        Para cada una: la entrada pasa a `failed` (con motivo), la Task sale
        de `IN_PROGRESS` a `TO_DEVELOP` (o `READY` según la preferencia) y se
        informa en `reconciliation_log.jsonl` — el visor
        (`GET /backlog/queue`) deja de mostrar "en curso" de inmediato.

        Nunca toca una entrada legítima: las `protected_task_ids` (Job en
        vuelo vigilado por este worker) y las entradas cuyo agente SIGUE en
        la sesión se respetan siempre (criterio 4). Mejor esfuerzo: devuelve
        la lista de `task_id` limpiadas."""
        from atlas_forge.backlog.edit import set_item_state
        from atlas_forge.core.reconciliation_log import (
            append_dispatched_orphan_reconciliation,
        )

        agent_ids = {agent.id for agent in list_agents(self._session)}
        tasks_dir = backlog_dir / "tasks"
        cleaned: list[str] = []
        for entry in get_queue(self._project_root, self._project_name):
            if entry.status != STATUS_DISPATCHED:
                continue
            if entry.task_id in protected_task_ids:
                continue
            if not entry.agent_id or entry.agent_id in agent_ids:
                continue

            candidates = sorted(tasks_dir.glob(f"{entry.task_id}-*.md")) or sorted(
                tasks_dir.glob(f"{entry.task_id}.md")
            )
            task_path = next(iter(candidates), None)
            if task_path is None or _read_task_state(
                task_path.read_text(encoding="utf-8")
            ).strip() != "IN_PROGRESS":
                # Sin Task en IN_PROGRESS no hay Job `running` que limpiar:
                # las entradas DONE/IN_REVIEW/READY las gobierna la
                # reconciliación general (criterio de no tocar lo sano).
                continue

            target_state = "TO_DEVELOP" if auto_reenqueue else "READY"
            set_item_state(task_path, target_state, force=True)
            mark_failed(
                self._project_root, self._project_name, entry.task_id,
                result=(
                    "Residuo de Job huérfano limpiado en runtime — el agente "
                    "ya no existe (entrada dispatched sin vigilar)."
                ),
            )
            append_dispatched_orphan_reconciliation(
                self._project_root, self._project_name,
                task_id=entry.task_id, target_state=target_state,
            )
            cleaned.append(entry.task_id)
        return cleaned

    def stop(self, timeout: float | None = 2.0) -> None:
        """Señala parada y espera (con `timeout`) a que el hilo termine."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def run_once(self) -> str | None:
        """Ejecuta un único ciclo de despacho de implementación (primer
        nivel) de forma síncrona, sin hilo — usado en tests."""
        return run_dispatch_cycle(
            self._project_root, self._project_name, self._session, self._socket_name,
            inflight=self._inflight,
        )

    def run_completion_poll_once(self, timeout_seconds: float = AGENT_STEP_TIMEOUT_SECONDS) -> list[str]:
        """Ejecuta un único ciclo de completión de los Jobs en vuelo."""
        return poll_inflight_job_completions(
            self._project_root, self._project_name, self._session, self._inflight,
            timeout_seconds=timeout_seconds,
        )

    def run_review_once(self) -> str | None:
        """Ejecuta un único ciclo del segundo nivel (Tester verifica una
        Task en IN_REVIEW) de forma síncrona."""
        return run_review_dispatch_cycle(
            self._project_root, self._project_name, self._session, self._socket_name,
            inflight_review=self._inflight_review, inflight=self._inflight,
        )

    def run_review_completion_once(self, timeout_seconds: float = AGENT_STEP_TIMEOUT_SECONDS) -> list[str]:
        """Ejecuta un único ciclo de completión de las verificaciones en
        vuelo."""
        return poll_inflight_review_completions(
            self._project_root, self._project_name, self._session,
            self._inflight_review, self._inflight, self._socket_name,
            timeout_seconds=timeout_seconds,
        )

    def run_architect_verdict_once(self, reports_root: Path | None = None) -> str | None:
        """Ejecuta un único ciclo del tercer nivel (Arquitecto veredicta
        una User Story en IN_REVIEW) de forma síncrona."""
        try:
            dispatched = run_architect_verdict_dispatch_cycle(
                self._project_root, self._project_name, self._session, self._socket_name,
                reports_root=reports_root,
                inflight_architect_verdict=self._inflight_architect_verdict,
            )
            return dispatched
        finally:
            self._persist_verdict_state()

    def run_architect_verdict_completion_once(self, timeout_seconds: float = AGENT_STEP_TIMEOUT_SECONDS) -> list[str]:
        """Ejecuta un único ciclo de completión de los veredictos en
        vuelo."""
        try:
            resolved = poll_inflight_architect_verdict_completions(
                self._session, self._inflight_architect_verdict,
                timeout_seconds=timeout_seconds,
            )
            return resolved
        finally:
            self._persist_verdict_state()

    def _persist_verdict_state(self) -> None:
        """T-AF022-US07-03: persiste el estado corriente de la cola de
        veredictos del Arquitecto a disco.

        Deriva `pending` (las US `IN_REVIEW` del backlog que no están en
        vuelo, en orden FIFO) e `inflight` (la US actualmente en vuelo, si
        la hay) del registro en memoria y del backlog real, y lo guarda.
        Un fallo de persistencia no rompe el ciclo de despacho."""
        try:
            backlog_dir = Path(self._project_root) / "02-backlog"
            graph = load_backlog(backlog_dir)
            inflight_ids = set(self._inflight_architect_verdict.keys())
            pending = sorted(
                item.id
                for item in graph.items.values()
                if item.kind == "US" and item.state == "IN_REVIEW"
                and item.id not in inflight_ids
            )
            inflight = next(iter(inflight_ids), None)
            save_architect_verdict_queue(
                self._project_root, self._project_name,
                pending=pending, inflight=inflight,
            )
        except Exception:
            pass

    def run_us_landing_once(self) -> str | None:
        """Ejecuta un único ciclo del aterrizaje US→Tasks (User Story en
        TO_PLAN) de forma síncrona."""
        return run_us_landing_dispatch_cycle(
            self._project_root, self._project_name, self._session, self._socket_name,
            inflight_landing=self._inflight_landing,
        )

    def run_creation_dispatch_once(self) -> str | None:
        """T-AF036-US20-07: ejecuta un único ciclo del quinto nivel (despacho
        de una petición de creación hacia el Arquitecto) de forma síncrona."""
        return run_creation_dispatch_cycle(
            self._project_root, self._project_name, self._session, self._socket_name,
            inflight_creation=self._inflight_creation,
        )

    def run_creation_completion_once(self, timeout_seconds: float = AGENT_STEP_TIMEOUT_SECONDS) -> list[str]:
        """T-AF036-US20-08: ejecuta un único ciclo de completión de las
        peticiones de creación en vuelo (parse + validación + escritura, o
        `failed`/`pending`)."""
        return poll_inflight_creation_completions(
            self._project_root, self._project_name, self._session,
            self._inflight_creation, timeout_seconds=timeout_seconds,
        )

    def run_landing_completion_once(self, timeout_seconds: float = AGENT_STEP_TIMEOUT_SECONDS) -> list[str]:
        """Ejecuta un único ciclo de completión de los aterrizajes en
        vuelo."""
        return poll_inflight_landing_completions(
            self._project_root, self._session, self._inflight_landing,
            timeout_seconds=timeout_seconds,
        )

    def run_consolidation_once(self) -> tuple[bool, list]:
        """Ejecuta un único ciclo de consolidación del `02-backlog/` del
        proyecto."""
        self._backlog_marks, changed, applied = consolidate_if_changed(
            Path(self._project_root) / "02-backlog", self._backlog_marks
        )
        return changed, applied

    def run_reconciliation_once(self) -> list[str]:
        """T-AF022-US18-02 (US-AF022-18, criterio 1/2/3): ejecuta UN ciclo
        de reconciliación del pipeline y las colas, de forma síncrona y
        testeable — la composición que `_run_loop` invoca periódicamente:

        - `reconcile_dispatch_queue_entries`: entradas de `dispatch_queue.json`
          desalineadas con el estado real (`dispatched` obsoletas -> 
          `completed`/`failed`; `queued` cuya Task ya no está `TO_DEVELOP`).
        - `reconcile_orphaned_in_progress_tasks`: tasks `IN_PROGRESS` huérfanas
          SIN entrada en la cola (T-AF022-US18-01), revertidas a
          `TO_DEVELOP`/`READY`.
        - `_reconcile_orphaned_agent_entries` (T-AF008-US18-05): residuos de
          Job huérfano `running` en runtime — entradas `dispatched` con Task
          `IN_PROGRESS` cuyo agente ya NO está en la sesión (crash/stop/tmux
          reiniciado) y cuyo `report_file` existe sin marcador: la
          reconciliación general no las toca (`report_file.is_file()` →
          `continue`), así que quedarían mostrando "en curso" hasta el
          reinicio. Aquí se limpian en el ciclo: entrada `failed` + Task a
          `TO_DEVELOP`/`READY` + registro en `reconciliation_log.jsonl`.

        Ambas respetan `get_auto_reenqueue_orphaned()` (system_preferences.py):
        si está activa, las huérfanas vuelven a `TO_DEVELOP` (candidatas del
        mismo ciclo); si no, a `READY` (requieren humano). Devuelve la lista
        de `task_id` reconciliados este ciclo (unión). Mejor esfuerzo:
        un fallo no debe salir de aquí — `_run_loop` la envuelve en
        `try/except: pass` (la reconciliación nunca mata el hilo ni impide los
        despachos)."""
        auto_reenqueue = get_auto_reenqueue_orphaned()
        backlog_dir = Path(self._project_root) / "02-backlog"
        # T-AF022-US18-02: las task_ids que este worker vigila en memoria
        # (Jobs en vuelo con `report_file` aún no creado) NO son huérfanas —
        # la reconciliación periódica debe respetarlas o marcaría `failed`
        # trabajo legítimamente en ejecución (bug observado en vivo: tareas
        # recién despachadas → `failed` a los pocos segundos → re-despacho
        # duplicado, con agentes completando trabajo ya dado por perdido).
        protected = (
            {infl.task_id for infl in self._inflight.values()}
            | set(self._inflight_review)
        )
        reconciled = reconcile_dispatch_queue_entries(
            self._project_root, self._project_name, backlog_dir,
            auto_reenqueue_orphaned=auto_reenqueue,
            protected_task_ids=protected,
        )
        reconciled += reconcile_orphaned_in_progress_tasks(
            self._project_root, self._project_name, backlog_dir,
            auto_reenqueue_orphaned=auto_reenqueue,
            protected_task_ids=protected,
        )
        # T-AF008-US18-05: residuo de Job huérfano `running` en runtime —
        # sin esperar al reinicio (las entradas de agente vivo/protegidas
        # nunca se tocan).
        reconciled += self._reconcile_orphaned_agent_entries(
            backlog_dir, protected, auto_reenqueue
        )
        # T-AF022-US18-03: reconcilia la cola de peticiones de creación
        # (T-AF036-US20-06) — una `in_flight` cuyo report_file se perdió
        # vuelve a `pending` para reintentalarla en el siguiente ciclo de
        # creación; la legítima (report_file presente) no se toca.
        try:
            from atlas_forge.dispatcher.creation_queue import (
                reconcile_creation_requests,
            )
            reconcile_creation_requests(self._project_root, self._project_name)
        except Exception:
            pass
        return reconciled

    def run_autonomous_scale_once(self) -> dict:
        """Ejecuta UN ciclo del modo autónomo (T-AF023-US03-02): si está
        habilitado en las preferencias de sistema, lanza Developers/Testers
        según la demanda de la cola y libera el excedente cuando no hay
        demanda (respetando mínimos/máximos por rol y el límite de
        saturación `max_agents_total`). Nunca libera agentes
        `persistent=true` ni rompe el redespacho por corrección del Tester
        (solo libera agentes `idle` no retenidos). Devuelve el resumen de
        acciones; `{"launched": [], "released": []}` si no está habilitado.

        La liberación de un agente activo (`idle`) usa `stop_agent`, que
        para Developer retira la instancia de `session.agents` y libera su
        plaza. Los fallos de lanzamiento/liberación se aíslan (no rompen el
        ciclo de despacho)."""
        config = config_from_preferences(get_autonomous_config())
        if not config.enabled:
            return {"launched": [], "released": []}

        pending = count_pending(get_queue(self._project_root, self._project_name))
        agents = list_agents(self._session)
        retained = _retained_developer_agent_ids(self._project_root, self._project_name)
        # T-AF008-US18-02: `_inflight` se clavea por `job.id` — para el modo
        # autónomo interesa el conjunto de AGENTES con un Job en vuelo
        # (`inflight_agent_ids`), derivado de los valores del registro.
        inflight = {infl.agent_id for infl in self._inflight.values()}

        def _launch(**kw):
            launch_agent(
                kw["role"], kw["runtime_type"], kw["model"],
                kw["session"], kw["project_path"], socket_name=kw["socket_name"],
            )

        def _release(agent, session):
            stop_agent(agent, session, socket_name=self._socket_name)

        try:
            return autonomous_scale(
                self._session,
                config=config,
                pending=pending,
                agents=agents,
                project_path=str(self._project_root),
                socket_name=self._socket_name,
                retained_agent_ids=retained,
                inflight_agent_ids=inflight,
                launch=_launch,
                release=_release,
                runtime_type="opencode",
                model=None,
            )
        except Exception:
            return {"launched": [], "released": []}

    def get_inflight_agent_ids(self) -> set[str]:
        """T-AF008-US18-04: agentes con un Job en vuelo LEGÍTIMO en este
        worker — unión de los `agent_id` de todos sus registros de vuelo
        (implementación nocturna `_inflight`, revisión `_inflight_review`,
        veredicto `_inflight_architect_verdict`, aterrizaje
        `_inflight_landing`). Es la señal EXCLUYENTE del watcher de
        "working sin Job en vuelo": un agente aquí nunca se libera."""
        inflight_agent_ids = {
            infl.agent_id for infl in self._inflight.values()
        }
        inflight_agent_ids |= {
            infl.tester_agent_id for infl in self._inflight_review.values()
        }
        inflight_agent_ids |= {
            infl.architect_agent_id
            for infl in self._inflight_architect_verdict.values()
        }
        inflight_agent_ids |= {
            infl.architect_agent_id for infl in self._inflight_landing.values()
        }
        inflight_agent_ids |= {
            infl.architect_agent_id for infl in self._inflight_creation.values()
        }
        return inflight_agent_ids

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                # T-AF022-US18-02: reconciliación periódica ANTES de los
                # ciclos de despacho (mismo patrón de colocación que
                # `run_consolidation_once`), para que una huérfana revertida a
                # `TO_DEVELOP` sea candidata de `_pick_next_eligible_task_id`
                # en el mismo ciclo, sin reiniciar el worker. Mejor esfuerzo.
                self.run_reconciliation_once()
            except Exception:
                pass
            try:
                self.run_consolidation_once()
            except Exception:
                pass
            try:
                self.run_autonomous_scale_once()
            except Exception:
                pass
            try:
                poll_inflight_job_completions(
                    self._project_root, self._project_name, self._session, self._inflight,
                    timeout_seconds=AGENT_STEP_TIMEOUT_SECONDS,
                    socket_name=self._socket_name,
                )
            except Exception:
                pass
            try:
                poll_inflight_review_completions(
                    self._project_root, self._project_name, self._session,
                    self._inflight_review, self._inflight, self._socket_name,
                    timeout_seconds=AGENT_STEP_TIMEOUT_SECONDS,
                )
            except Exception:
                pass
            try:
                poll_inflight_architect_verdict_completions(
                    self._session, self._inflight_architect_verdict,
                    timeout_seconds=AGENT_STEP_TIMEOUT_SECONDS,
                )
            except Exception:
                pass
            try:
                self._persist_verdict_state()
            except Exception:
                pass
            try:
                poll_inflight_landing_completions(
                    self._project_root, self._session, self._inflight_landing,
                    timeout_seconds=AGENT_STEP_TIMEOUT_SECONDS,
                )
            except Exception:
                pass
            try:
                # T-AF036-US20-08: completión de las peticiones de creación en
                # vuelo (parse + validación + escritura de la entidad real).
                poll_inflight_creation_completions(
                    self._project_root, self._project_name, self._session,
                    self._inflight_creation,
                    timeout_seconds=AGENT_STEP_TIMEOUT_SECONDS,
                )
            except Exception:
                pass
            for cycle, kwargs in (
                (run_dispatch_cycle, {"inflight": self._inflight}),
                (run_review_dispatch_cycle, {"inflight_review": self._inflight_review, "inflight": self._inflight}),
                (run_architect_verdict_dispatch_cycle, {"inflight_architect_verdict": self._inflight_architect_verdict}),
                (run_us_landing_dispatch_cycle, {"inflight_landing": self._inflight_landing}),
                # T-AF036-US20-07: quinto nivel — peticiones de creación hacia
                # el Arquitecto (Epic/US/Task desde descripción libre).
                (run_creation_dispatch_cycle, {"inflight_creation": self._inflight_creation}),
            ):
                try:
                    cycle(
                        self._project_root, self._project_name, self._session, self._socket_name,
                        **kwargs,
                    )
                except Exception:
                    pass
            try:
                self._persist_verdict_state()
            except Exception:
                pass
            self._stop_event.wait(self._poll_interval_seconds)


def run_us_landing_dispatch_cycle(
    project_root: Path | str,
    project_name: str,
    session: DevelopmentSession,
    socket_name: str = DEFAULT_SOCKET_NAME,
    inflight_landing: dict[str, InFlightLandingJob] | None = None,
) -> str | None:
    """Cuarto nivel: si hay al menos una User Story en `state == "TO_PLAN"`
    (AF-040) y un Arquitecto `idle`, despacha un Job de aterrizaje US→Tasks
    hacia el Arquitecto y lo registra en `inflight_landing` para su
    completión por polling. Devuelve el `us_id` cuyo aterrizaje se despachó
    este ciclo, o `None` si no había nada que hacer."""
    from atlas_forge.architect.propose_tasks import us_title_from_file
    from atlas_forge.dispatcher.job_creation import JobCreationError
    from atlas_forge.dispatcher.job_orchestration import create_and_record_job

    if inflight_landing is None:
        inflight_landing = {}

    backlog_dir = Path(project_root) / "02-backlog"
    graph = load_backlog(backlog_dir)

    designing_stories = sorted(
        item.id for item in graph.items.values()
        if item.kind == "US" and item.state == "TO_PLAN"
    )
    if not designing_stories:
        return None
    story_id = designing_stories[0]

    architect_agent = _find_architect(session, require_idle=True)
    if architect_agent is None:
        return None

    runtime_instance = get_runtime_instance_for_agent(architect_agent.id)
    if runtime_instance is None:
        return None

    if not is_agent_ready_for_input(
        architect_agent, socket_name=socket_name, runtime_instance=runtime_instance
    ):
        return None

    us_item = graph.items.get(story_id)
    if us_item is None:
        return None

    us_title = us_title_from_file(us_item.path)
    description = _build_landing_job_description(us_item, us_title)

    try:
        job = create_and_record_job(description, architect_agent, session)
        report_file = dispatch_job_send(
            job, architect_agent, runtime_instance, socket_name=socket_name
        )
    except (JobCreationError, Exception):
        return None

    inflight_landing[story_id] = InFlightLandingJob(
        us_id=story_id,
        architect_agent_id=architect_agent.id,
        report_file=report_file,
        job=job,
        dispatched_at=time.monotonic(),
        us_item=us_item,
    )
    return story_id


def run_creation_dispatch_cycle(
    project_root: Path | str,
    project_name: str,
    session: DevelopmentSession,
    socket_name: str = DEFAULT_SOCKET_NAME,
    inflight_creation: dict[str, InFlightCreationJob] | None = None,
) -> str | None:
    """Quinto nivel del worker (T-AF036-US20-07, US-AF036-20): recoge la
    siguiente petición de creación `pending` (FIFO, `creation_queue`) y, SOLO
    cuando el Arquitecto está `idle` y listo para recibir input, le despacha
    un Job con la descripción libre + el contexto (Epic/US padre) — "despachada
    cuando corresponda". Devuelve el `request_id` despachado o `None` si no
    había nada despachable en este ciclo.

    Mismo patrón NO BLOQUEANTE que `run_us_landing_dispatch_cycle`:
    - `pick_next_pending_creation_request` (sin cambiar su estado).
    - `_find_architect(require_idle=True)` — misma restricción secuencial
      que veredicto y aterrizaje: si el Arquitecto está ocupado la petición
      espera en el siguiente ciclo.
    - `get_runtime_instance_for_agent` registrado; si no, se reintenta.
    - Gate de readiness `is_agent_ready_for_input` (T-AF022-US06-07): un
      Arquitecto recién reconciliado que aún no acepta input NO recibe la
      petición (queda pending).
    - `create_and_record_job` + `dispatch_job_send` (NO bloqueante) con la
      descripción libre + contexto.
    - `mark_creation_in_flight(request_id, report_file)` y registro en
      `inflight_creation` (`request_id -> InFlightCreationJob`) para que la
      completión (T-AF036-US20-08) lo vigile.

    Este ciclo SOLO despacha: no genera ni escribe entidades (propuesta y
    escritura las resuelve `poll_inflight_creation_completions`)."""
    inflight = inflight_creation if inflight_creation is not None else {}
    if not inflight:
        request = pick_next_pending_creation_request(project_root, project_name)
    else:
        # El Arquitecto es secuencial (una petición de creación a la vez,
        # como veredicto/aterrizaje): con una ya en vuelo, no se despacha
        # otra en el mismo ciclo (se intenta la siguiente vez).
        request = None
    if request is None:
        return None

    architect = _find_architect(session, require_idle=True)
    if architect is None:
        return None

    runtime_instance = get_runtime_instance_for_agent(architect.id)
    if runtime_instance is None:
        return None

    if not is_agent_ready_for_input(
        architect, socket_name=socket_name, runtime_instance=runtime_instance
    ):
        return None

    description = _build_creation_job_description(request)

    try:
        job = create_and_record_job(description, architect, session)
        report_file = dispatch_job_send(
            job, architect, runtime_instance, socket_name=socket_name
        )
    except (JobCreationError, Exception):
        return None

    mark_creation_in_flight(project_root, project_name, request.request_id, report_file)
    inflight[request.request_id] = InFlightCreationJob(
        request_id=request.request_id,
        tipo=request.tipo,
        architect_agent_id=architect.id,
        report_file=report_file,
        job=job,
        dispatched_at=time.monotonic(),
    )
    return request.request_id


def _build_creation_job_description(request) -> str:
    """Construye la instrucción del Job de creación hacia el Arquitecto
    (T-AF036-US20-07): la descripción libre del humano + el contexto
    (Epic/US padre). La propuesta estructurada (id único del patrón del
    tipo, título, objetivo, criterios, fase/version, prioridad, dependencias)
    y su validación/escritura las resuelve la completión (T-AF036-US20-08)."""
    context = ""
    if request.tipo == "us" and request.epic_id:
        context = f"\n\nContexto: crea la User Story dentro de la Epic '{request.epic_id}'."
    elif request.tipo == "task" and request.us_id:
        context = f"\n\nContexto: crea la Task dentro de la User Story '{request.us_id}'."
    return (
        f"Convierte esta descripción en lenguaje natural en una entidad del "
        f"backlog (tipo: {request.tipo}) y escribe la propuesta estructurada "
        f"en el fichero de reporte, siguiendo el formato del backlog.\n\n"
        f"Descripción:\n{request.description}{context}"
    )


def _parse_creation_proposal(report_content: str, tipo: str) -> dict | None:
    """Interpreta la propuesta estructurada del Arquitecto para una petición
    de creación (T-AF036-US20-08). Formato YAML (mismo patrón que
    `parse_landing_proposal`):

    ```yaml
    proposal:
      id: AF-999            # o US-AF999-01 / T-AF999-US01-01 según tipo
      title: ...
      objetivo: ...         # epic: objetivo; us: historia; task: objetivo
      descripcion: ...      # solo task (opcional)
      criterios_aceptacion: ...  # us/task; epic no
      priority: ...         # us/task; epic no
      version: ...          # epic/us (conjunto 0.9/0.9.1/0.9.2 o null)
      epic_id: ...          # para us (contexto)
      us_id: ...            # para task (contexto)
      dependencies: [...]   # solo task
    ```

    Devuelve el dict de la propuesta o `None` si el YAML no es válido, no es
    un dict o no trae `proposal`, o el `id` no es string."""
    try:
        import yaml
        data = yaml.safe_load(report_content)
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    prop = data.get("proposal")
    if not isinstance(prop, dict):
        return None
    prop_id = prop.get("id")
    if not isinstance(prop_id, str) or not prop_id.strip():
        return None
    prop["id"] = prop_id.strip()
    for key in ("title", "objetivo", "descripcion", "criterios_aceptacion"):
        if key in prop and prop[key] is not None:
            prop[key] = str(prop[key]).strip()
    return prop


def _write_creation_proposal(
    backlog_path: Path,
    tipo: str,
    prop: dict,
) -> tuple[bool, list[str]]:
    """Valida la propuesta estructurada de una petición de creación con el
    validador determinista y, si es válida, escribe la entidad real en el
    `02-backlog/` correspondiente (T-AF036-US20-08). Reutiliza los creadores
    canónicos de `atlas_forge.backlog.create` (`create_epic`/
    `create_user_story`/`create_task`, que serializan con `_build_*_content`
    y validan con `validate_backlog_content_v2` antes de persistir).

    Devuelve `(ok, errores)`:
    - `(True, [])`: se escribió el fichero que pasa el validador.
    - `(False, errores)`: no se escribe nada y se devuelven los motivos
      verbatim (para `mark_creation_failed`)."""
    from atlas_forge.backlog import create as backlog_create

    try:
        if tipo == "epic":
            backlog_create.create_epic(
                backlog_path,
                prop.get("id", ""),
                prop.get("title", ""),
                prop.get("objetivo", ""),
            )
            return True, []

        if tipo == "us":
            backlog_create.create_user_story(
                backlog_path,
                prop.get("epic_id", ""),
                prop.get("id", ""),
                prop.get("title", ""),
                prop.get("objetivo", ""),
                prop.get("criterios_aceptacion", ""),
                prop.get("priority"),
                prop.get("version"),
            )
            return True, []

        if tipo == "task":
            backlog_create.create_task(
                backlog_path,
                prop.get("us_id", ""),
                prop.get("id", ""),
                prop.get("title", ""),
                prop.get("objetivo", ""),
                prop.get("descripcion", ""),
                prop.get("criterios_aceptacion", ""),
                prop.get("priority"),
                prop.get("dependencies") or [],
            )
            return True, []

        return False, [f"tipo de petición de creación desconocido: '{tipo}'."]
    except (
        backlog_create.InvalidEpicIdError,
        backlog_create.EpicAlreadyExistsError,
        backlog_create.InvalidUserStoryIdError,
        backlog_create.EpicNotFoundError,
        backlog_create.UserStoryAlreadyExistsError,
        backlog_create.InvalidTaskIdError,
        backlog_create.UserStoryNotFoundError,
        backlog_create.TaskAlreadyExistsError,
        backlog_create.InvalidPriorityError,
        backlog_create.BacklogValidationError,
        Exception,
    ) as error:
        # Errores de validación/duplicados/formato del creador: motivos
        # verbatim, sin escribir nada (single-flight, criterio 9 de la US).
        return False, [str(error)]


def poll_inflight_creation_completions(
    project_root: Path | str,
    project_name: str,
    session: DevelopmentSession,
    inflight_creation: dict[str, InFlightCreationJob],
    timeout_seconds: float = AGENT_STEP_TIMEOUT_SECONDS,
) -> list[str]:
    """Nivel de completión NO BLOQUEANTE de las peticiones de creación
    (T-AF036-US20-08, US-AF036-20: criterios de aceptación). Vigila
    `inflight_creation` (`request_id -> InFlightCreationJob`) y procesa las
    que el Arquitecto ya resolvió:

    - Reporte con marcador presente (`read_finished_report`): `_parse_creation_proposal`
      → `_write_creation_proposal` (valida con el validador determinista y
      escribe la entidad real). Si escribió → la petición pasa a `done`; si no
      valida → **no escribe nada** y `mark_creation_failed` con los motivos
      verbatim (la descripción queda editable). Id duplicado/mal formado →
      `failed` con mensaje explícito (single-flight, criterio 9 de la US).
    - Sin reporte y `now - dispatched_at >= timeout_seconds`: petición vuelve
      a `pending` (se reintenta sola en el siguiente ciclo de despacho) — misma
      decisión que el resto del pipeline.

    Deja la entrada de la cola en su estado final (done/failed) para que la web
    la muestre en el panel de peticiones (T-AF036-US20-04). No bloquea: comprueba
    cada fichero una vez y vuelve. Devuelve la lista de `request_id` resueltos
    este ciclo."""
    from atlas_forge.dispatcher.creation_queue import (
        mark_creation_done,
        mark_creation_failed,
        mark_creation_pending,
    )

    backlog_path = Path(project_root) / "02-backlog"
    agent_by_id = {a.id: a for a in list_agents(session)}
    resolved: list[str] = []
    now = time.monotonic()
    for request_id, infl in list(inflight_creation.items()):
        architect = agent_by_id.get(infl.architect_agent_id)
        report = read_finished_report(infl.report_file)
        if report is not None:
            wait_and_finalize_job(
                infl.job, architect, infl.report_file,
                timeout_seconds, poll_interval_seconds=0,
            )
            prop = _parse_creation_proposal(report, infl.tipo)
            if prop is None:
                mark_creation_failed(
                    project_root, project_name, request_id,
                    ["La propuesta del Arquitecto no es parseable (formato YAML 'proposal:' inválido o ausente)."],
                )
            else:
                ok, errores = _write_creation_proposal(backlog_path, infl.tipo, prop)
                if ok:
                    mark_creation_done(project_root, project_name, request_id)
                else:
                    mark_creation_failed(project_root, project_name, request_id, errores)
            del inflight_creation[request_id]
            resolved.append(request_id)
        elif now - infl.dispatched_at >= timeout_seconds:
            # Timeout: Job fallido, petición vuelve a pending (reintento solo).
            fail_job_on_timeout(infl.job, architect, infl.report_file, timeout_seconds)
            mark_creation_pending(project_root, project_name, request_id)
            del inflight_creation[request_id]
            resolved.append(request_id)
    return resolved


def _build_landing_job_description(us_item, us_title: str) -> str:
    """Construye la instrucción del Job de aterrizaje US→Tasks
    (T-AF008-US16-01): el Arquitecto lee la US y escribe su propuesta en
    el fichero de reporte en el formato YAML `tasks:` que
    `atlas_forge.architect.landing_proposal.parse_landing_proposal` interpreta
    en la completión."""
    epic_sin_guion = (us_item.epic or "").replace("-", "")
    return (
        f"Aterriza la User Story {us_item.id} en Tasks específicas y "
        f"verificables.\n\n"
        f"Título: {us_title}\n\n"
        f"Lee la User Story completa en:\n{us_item.path}\n\n"
        f"Escribe tu propuesta en este fichero de reporte en formato YAML "
        f"con una lista `tasks:`. Cada Task debe desglosar el alcance real "
        f"de la User Story y tener criterios de aceptación verificables, "
        f"NO plantillas genéricas. Campos por Task:\n"
        f"  id (patrón T-{epic_sin_guion}-USxx-NN), title, objective, "
        f"description, criteria (lista), priority, difficulty, "
        f"dependencies (lista), epic_id: {us_item.epic}, "
        f"us_id: {us_item.id}\n\n"
        f"Las Tasks se validarán con el validador determinista del backlog "
        f"antes de escribirse; cualquier Task que no valide se descartará "
        f"sin persistir."
    )