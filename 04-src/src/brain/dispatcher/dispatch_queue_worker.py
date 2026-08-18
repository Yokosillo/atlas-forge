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

from brain.agent_model import get_active_model, resolve_runtime_for_model, set_active_model
from brain.backlog.parser import load_backlog
from brain.backlog.report import priority_rank
from brain.core.session_lifecycle import list_agents
from brain.dispatcher.dispatch_queue import (
    STATUS_DISPATCHED,
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
from brain.dispatcher.model_selection import get_models_for_difficulty
from brain.dispatcher.task_verdict import VERDICT_PASSED, parse_task_verdict
from brain.models import Agent, DevelopmentSession
from brain.models_catalog import load_model_catalog
from brain.runtime.agent_runtime_registry import get_runtime_instance_for_agent
from brain.system_preferences import get_developer_waits_for_tester_review
from brain.tmux.manager import DEFAULT_SOCKET_NAME

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
    """Elige la siguiente Task a despachar (T-FB008-US14-01): la fuente
    de verdad de "lista para desarrollo" pasa a ser `state == "EN_DESARROLLO"`
    en el propio fichero del backlog, no solo la presencia de una
    entrada `queued` en `dispatch_queue.json` — una Task puede llegar a
    `EN_DESARROLLO` por el selector de estado de `US-FB036-08` sin pasar nunca
    por `POST /backlog/{id}/enqueue` (y por tanto sin entrada JSON).

    Candidatas: cualquier Task del grafo con `state == "EN_DESARROLLO"`.
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
        if item.kind == "T" and item.state == "EN_DESARROLLO"
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
    `new_state` — mismo patrón de reemplazo textual ya usado por
    `_mark_story_tasks_done` (`job_plan_dispatch.py`), aplicado aquí a
    una única Task concreta en vez de todas las `TO_DO` de una Story (esa
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


def _retained_developer_agent_ids(
    graph, project_root: Path | str, project_name: str
) -> set[str]:
    """T-FB008-US14-02: `agent_id` de cualquier Developer que cerró una
    Task todavía en `REVIEW` (esperando veredicto del Tester) o cuya
    Task de corrección derivada sigue sin resolver — ver
    `get_developer_waits_for_tester_review` (`system_preferences.py`,
    decisión de producto explícita del usuario: "el developer debe
    esperar hasta que el tester le responda", no coger Task nueva
    mientras tanto, para que nunca certifique su propio trabajo en
    paralelo).

    Cruza las Tasks `REVIEW` reales del backlog con las entradas
    `dispatched` de `dispatch_queue.json` (que ya guardan `agent_id` de
    quien la despachó, `mark_dispatched`) — una Task puede estar en
    `REVIEW` sin entrada JSON (marcada a mano), en cuyo caso no hay
    ningún Developer que retener por esta vía.

    El llamador (`run_dispatch_cycle`) ya comprueba
    `get_developer_waits_for_tester_review` antes de invocar esta
    función — si la preferencia está en `False`, ni se llama."""
    review_task_ids = {
        item.id for item in graph.items.values()
        if item.kind == "T" and item.state == "REVIEW"
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
    dificultad, aplicando la lógica de T-FB008-US12-02:

    1. Si no hay dificultad, retorna cualquier Developer `idle` ("sin requisito")
    2. Consulta get_models_for_difficulty para saber qué tier se requiere
    3. Busca entre TODOS los Developers `idle` cuyo modelo ya encaja
       (criterio 3: sin cambiar modelo innecesariamente)
    4. Si no hay uno que encaje, intenta cambiar el modelo de un Developer
       `idle` de OpenCode (runtime que soporta cambio)
    5. Si no se puede cambiar a OpenCode, registra degradación (devuelve con
       reason="degradado...")

    Retorna tupla (agent, dispatch_reason) o None si no hay Developer elegible.
    Nunca intenta cambiar modelo en un agente `working`."""
    from brain.core.session_lifecycle import list_agents

    # Obtiene TODOS los Developers `idle` disponibles (no solo el primero)
    idle_developers = [
        agent for agent in list_agents(session)
        if isinstance(agent, Agent) and agent.role == _DEVELOPER_ROLE and agent.status == "idle"
        and agent.id not in retained_agent_ids
    ]

    if not idle_developers:
        return None

    # Sin dificultad explícita: retorna cualquier Developer `idle`
    if not difficulty:
        return (idle_developers[0], "sin requisito de dificultad")

    try:
        # Consulta qué modelo/tier se requiere para esta dificultad
        required_models = get_models_for_difficulty(difficulty, project_root)
    except (KeyError, Exception):
        # Dificultad no reconocida o error consultando mapeo — se procede
        # con degradación (usa el primer Developer disponible tal como está)
        return (idle_developers[0], f"dificultad '{difficulty}' no reconocida, degradado")

    if not required_models:
        # No hay modelos disponibles en el catálogo para este tier
        return (idle_developers[0], f"no hay modelos disponibles para dificultad '{difficulty}', degradado")

    # PASO 3: Busca un Developer cuyo modelo ya encaja (sin cambiar)
    required_ids = {m.id for m in required_models}
    required_names = {m.name for m in required_models}

    for agent in idle_developers:
        current_model = get_active_model(agent.id, socket_name=socket_name)
        if current_model:
            # Matching: si el modelo actual contiene nombre/id de un modelo requerido
            for req_model in required_models:
                if (req_model.name in current_model or
                    req_model.id in current_model or
                    req_model.name.lower() in current_model.lower()):
                    return (agent, f"encaja directo: modelo actual satisface dificultad '{difficulty}'")

    # PASO 4: Si ninguno encaja, intenta cambiar el modelo de un Developer OpenCode
    for agent in idle_developers:
        runtime_instance = get_runtime_instance_for_agent(agent.id)
        if runtime_instance and runtime_instance.runtime.type == "opencode":
            # OpenCode soporta cambio de modelo — intenta aplicarlo
            target_model = required_models[0]  # Elige el primer modelo requerido
            try:
                success = set_active_model(agent.id, target_model.id, socket_name=socket_name)
                if success:
                    return (agent, f"cambio de modelo aplicado: {target_model.id} para dificultad '{difficulty}'")
            except Exception:
                pass  # Continúa con el siguiente Developer si falla

    # PASO 5: Si nadie de OpenCode pudo cambiar, degradación con el primer disponible
    # (runtime que no soporta cambio de modelo)
    return (idle_developers[0], f"runtime no soporta cambio de modelo, degradado con modelo actual")


def _get_task_difficulty(graph, task_id: str) -> str | None:
    """Extrae la dificultad de una Task del grafo del backlog."""
    item = graph.items.get(task_id)
    if item and item.kind == "T":
        return item.difficulty
    return None


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
    # T-FB008-US14-01: la elegibilidad se calcula sobre `state == EN_DESARROLLO`
    # real del backlog (`_pick_next_eligible_task_id`), no solo sobre
    # `dispatch_queue.json` — ver docstring de esa función.
    task_id = _pick_next_eligible_task_id(graph, entries, done_ids, dependencies_of)
    if task_id is None:
        return None

    # Elige Developer basado en dificultad de la Task (T-FB008-US12-02),
    # excluyendo Developers retenidos esperando veredicto del Tester
    # sobre una Task previa (T-FB008-US14-02).
    difficulty = _get_task_difficulty(graph, task_id)
    retained_agent_ids = (
        frozenset(_retained_developer_agent_ids(graph, project_root, project_name))
        if get_developer_waits_for_tester_review()
        else frozenset()
    )
    result = _pick_developer_for_difficulty(
        session, difficulty, project_root, socket_name, retained_agent_ids=retained_agent_ids
    )
    if result is None:
        # Sin Developer `idle` ahora mismo (todos ocupados, o ninguno en
        # la sesión) — criterio explícito: "no intenta despachar nada
        # hasta que alguno quede idle". La entrada sigue `queued`, se
        # reintenta en el siguiente ciclo.
        return None

    agent, dispatch_reason = result

    runtime_instance = get_runtime_instance_for_agent(agent.id)
    if runtime_instance is None:
        # Agente `idle` pero sin runtime registrado (caso borde real, ya
        # documentado en `_dispatch_agent_step`) — no hay nada que
        # despachar de forma segura este ciclo; se reintenta después.
        return None

    mark_dispatched(project_root, project_name, task_id, agent_id=agent.id, agent_name=agent.name, dispatch_reason=dispatch_reason)
    _update_task_file_state(tasks_dir, task_id, "IN_PROGRESS")

    task_title = task_id
    task_path = next(iter(sorted(tasks_dir.glob(f"{task_id}-*.md"))), None)
    description = f"Desarrolla la Task {task_title} (encolada vía la pantalla Backlog)."
    if task_path is not None:
        description += f"\n\nFichero: {task_path.name}"

    try:
        job = create_job(description, agent, session)
        job.story_id = graph.items[task_id].user_story
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
        _update_task_file_state(tasks_dir, task_id, "TO_DO")
        return task_id

    if job.status != "completed":
        mark_failed(
            project_root, project_name, task_id,
            result=f"El Job no se completó (estado '{job.status}'): {job.result}",
        )
        _update_task_file_state(tasks_dir, task_id, "TO_DO")
        return task_id

    # T-FB008-US14-02: la Task cerrada por el Developer pasa a REVIEW, no
    # a DONE directo — la entrada `dispatched` de `dispatch_queue.json`
    # se deja intacta a propósito (no se llama a ningún "mark_done"):
    # sigue siendo la única forma de saber qué Developer la cerró
    # (`_retained_developer_agent_ids`) hasta que el ciclo de Tester la
    # resuelva (PASS→DONE, FAIL→Task de corrección nueva).
    _update_task_file_state(tasks_dir, task_id, "REVIEW")
    return task_id


# ═══════════════════════════════════════════════════════════════════════════════
# T-FB008-US14-02: segundo nivel — Tasks en REVIEW asignadas a un Tester libre
# ═══════════════════════════════════════════════════════════════════════════════


def _annotate_task_with_correction_note(tasks_dir: Path, task_id: str, resumen: str, siguiente_paso: str) -> None:
    """Añade una sección `## Corrección pendiente` al fichero de
    `task_id` con el hallazgo del Tester — no existe ningún campo de
    frontmatter para esto en el esquema actual, texto simple en el
    cuerpo del fichero (mismo criterio que otras anotaciones de cierre
    del proyecto, p. ej. "Bugs encontrados"). Se sobreescribe en cada
    fallo (no acumula reintentos anteriores) — el Developer solo
    necesita el hallazgo más reciente."""
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
) -> None:
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
    queda anotada con el hallazgo y vuelve a `TO_DO` — el ciclo normal de
    `run_dispatch_cycle` la recogerá cuando alguien la marque `EN_DESARROLLO`
    de nuevo (mejor esfuerzo: nunca se pierde el hallazgo del Tester, ni
    se bloquea el resto del pipeline por un Developer caído)."""
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
        # Developer ya no disponible — queda anotada, vuelve a TO_DO para
        # que un humano/el ciclo normal la reencole cuando corresponda.
        _update_task_file_state(tasks_dir, task_item.id, "TO_DO")
        return

    runtime_instance = get_runtime_instance_for_agent(developer_agent.id)
    if runtime_instance is None:
        _update_task_file_state(tasks_dir, task_item.id, "TO_DO")
        return

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
        job = create_job(description, developer_agent, session)
        job.story_id = task_item.user_story
        dispatch_job(
            job,
            developer_agent,
            runtime_instance,
            timeout_seconds=AGENT_STEP_TIMEOUT_SECONDS,
            socket_name=socket_name,
        )
    except (JobCreationError, Exception):
        # Mismo criterio de mejor esfuerzo que el resto del ciclo: no
        # tumba el Dispatcher. La Task queda IN_PROGRESS con la nota de
        # corrección — se puede redespachar en un ciclo posterior.
        return

    if job.status == "completed":
        _update_task_file_state(tasks_dir, task_item.id, "REVIEW")


def run_review_dispatch_cycle(
    project_root: Path | str,
    project_name: str,
    session: DevelopmentSession,
    socket_name: str = DEFAULT_SOCKET_NAME,
) -> str | None:
    """Segundo nivel de REVIEW (T-FB008-US14-02, ciclo de FAIL rediseñado
    2026-08-17 — pipeline único, ver "PIPELINE OPERATIVO Y RECONCILIACIÓN":
    si hay al menos una Task en `state == "REVIEW"` y un Tester `idle`,
    despacha exactamente una verificación y procesa su veredicto
    (`RESULTADO: EXITO|FALLO`, `task_verdict.parse_task_verdict`):

    - `EXITO`: la Task pasa a `DONE`. El Developer que la había cerrado
      queda libre de nuevo (deja de aparecer en
      `_retained_developer_agent_ids`, porque ya no hay ninguna Task
      `REVIEW` asociada a su `agent_id`).
    - `FALLO`: la Task vuelve directamente al MISMO Developer que la
      cerró (`_redispatch_task_to_retained_developer`) — sin crear
      ninguna Task de corrección nueva. Decisión explícita del usuario,
      2026-08-17, sustituye el diseño anterior de T-FB008-US14-02 (Task
      de corrección nueva en `EN_DESARROLLO`, reparto normal): "esa
      orden va a la cola, pasa al dispatcher y este se la manda al mismo
      developer que está esperando, no se crea nueva task". La Task
      pasa a `IN_PROGRESS` (vuelve al ciclo de implementación, no queda
      colgada en `REVIEW`) con el resumen/siguiente paso del Tester
      como parte del Job. Si el Developer que la cerró ya no está
      disponible (runtime caído, agente ya no en la sesión), se trata
      como fallo de despacho — se reintenta en el siguiente ciclo, sin
      generar ninguna Task nueva ni perder el hallazgo del Tester (queda
      en la propia Task, sección `## Corrección pendiente`).

    Devuelve el `task_id` verificado este ciclo, o `None` si no había
    nada que hacer (sin Tasks en REVIEW, o sin Tester libre)."""
    tasks_dir = Path(project_root) / "02-backlog" / "tasks"
    backlog_dir = Path(project_root) / "02-backlog"
    graph = load_backlog(backlog_dir)

    review_tasks = sorted(
        (item for item in graph.items.values() if item.kind == "T" and item.state == "REVIEW"),
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

    task_path = next(iter(sorted(tasks_dir.glob(f"{task_item.id}-*.md"))), None)
    description = (
        f"Verifica la Task {task_item.id} (cerrada por el Developer, en REVIEW)."
    )
    if task_path is not None:
        description += f"\n\nFichero: {task_path.name}"

    try:
        job = create_job(description, tester_agent, session)
        job.story_id = task_item.user_story
        dispatch_job(
            job,
            tester_agent,
            runtime_instance,
            timeout_seconds=AGENT_STEP_TIMEOUT_SECONDS,
            socket_name=socket_name,
        )
    except (JobCreationError, Exception):
        # Mismo criterio que run_dispatch_cycle: un fallo de despacho de
        # ESTA verificación no bloquea el resto del ciclo — se reintenta
        # en el siguiente poll, la Task se queda en REVIEW.
        return None

    if job.status != "completed":
        return None

    resultado, resumen, siguiente_paso = parse_task_verdict(job.result)

    if resultado == VERDICT_PASSED:
        _update_task_file_state(tasks_dir, task_item.id, "DONE")
    else:
        # FALLO, o veredicto no parseable — se trata como fallo (criterio
        # de mejor esfuerzo: nunca deja la Task colgada en REVIEW sin
        # ningún camino hacia adelante). Vuelve directamente al mismo
        # Developer, sin crear Task nueva (decisión 2026-08-17).
        _redispatch_task_to_retained_developer(
            project_root, project_name, session, task_item, resumen, siguiente_paso,
            tasks_dir, socket_name,
        )

    return task_item.id


# ═══════════════════════════════════════════════════════════════════════════════
# T-FB008-US14-02: veredicto de User Story — sustituye la cola FIFO ciega de
# `architect_verdict_queue.py` por reparto vía este mismo Dispatcher,
# comprobando disponibilidad real del Arquitecto.
# ═══════════════════════════════════════════════════════════════════════════════


def story_is_fully_done(graph, story_id: str) -> bool:
    """`True` si TODAS las Tasks de `story_id` en el grafo están `DONE`
    (y existe al menos una) — criterio compartido por los dos puntos de
    disparo del veredicto de Arquitecto (`job_plan_dispatch.dispatch_plan`
    y `POST /jobs`, `api/routes.py`) para no disparar el veredicto tras
    un Job suelto mientras aún quedan Tasks de la misma Story sin cerrar
    (bug de diseño corregido en T-FB008-US14-02: antes disparaba tras
    CUALQUIER Job con `story_id`, sin comprobar el resto)."""
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
) -> str | None:
    """Tercer nivel (T-FB008-US14-02): si hay al menos una User Story en
    `state == "REVIEW"` y un Arquitecto `idle`, despacha su veredicto —
    sustituye el disparo ciego de `enqueue_architect_verdict`
    (`architect_verdict_queue.py`, cola FIFO que no comprobaba
    disponibilidad) por el mismo criterio "un agente libre a la vez" ya
    usado para Developer/Tester en este módulo.

    Llama a `dispatch_architect_verdict` (mismo módulo, más abajo) — el
    ciclo de veredicto completo (Job al Arquitecto + procesar
    APROBADO/RECHAZADO + promoción de US/Epic) queda encadenado dentro
    del propio Dispatcher, sin depender de un módulo aparte para saber
    "qué hacer" con el resultado (decisión explícita del usuario,
    2026-08-17: "este flujo de trabajo debe estar encadenado en el
    dispatcher" — el Dispatcher controla todo el pipeline, no solo el
    CUÁNDO de cada paso)."""
    backlog_dir = Path(project_root) / "02-backlog"
    graph = load_backlog(backlog_dir)

    review_stories = sorted(
        item.id for item in graph.items.values()
        if item.kind == "US" and item.state == "REVIEW"
    )
    if not review_stories:
        return None
    story_id = review_stories[0]

    architect_agent = next(
        (
            agent for agent in list_agents(session)
            if isinstance(agent, Agent) and agent.role == _ARQUITECTO_ROLE and agent.status == "idle"
        ),
        None,
    )
    if architect_agent is None:
        return None

    try:
        verdict_output = dispatch_architect_verdict(
            story_id, session, socket_name, reports_root, backlog_dir=backlog_dir
        )
    except Exception:
        return None

    # T-FB022-US15-04: mismo enganche que tenía el camino viejo
    # (`architect_verdict_queue._do_dispatch_verdict`) — encontrado
    # como regresión real durante este refactor: `trigger_architect_verdict`
    # dejó de llamar a `enqueue_architect_verdict` desde T-FB008-US14-02
    # (ahora solo marca la US en REVIEW), así que el disparo del Tester
    # de UI tras un veredicto aprobado había quedado sin ningún camino
    # vivo que lo alcanzara. Se reengancha aquí, el único disparador real.
    if verdict_output is not None:
        from brain.dispatcher.architect_verdict_queue import _maybe_enqueue_ui_tester
        from brain.dispatcher.job_plan_dispatch import _collect_story_reports

        root = (
            reports_root
            if reports_root
            else Path(__file__).resolve().parents[4] / "07-informes"
        )
        reports = _collect_story_reports(story_id, root)
        _maybe_enqueue_ui_tester(story_id, verdict_output, reports, session, socket_name, reports_root)

    return story_id


# ═══════════════════════════════════════════════════════════════════════════════
# T-FB008-US15-02 (2026-08-17, "PIPELINE OPERATIVO Y RECONCILIACIÓN"): el
# Dispatcher reparte el aterrizaje US→Tasks al Arquitecto — sustituye a la web
# llamando directamente y de forma síncrona a `POST /backlog/us/{id}/propose-tasks`.
# ═══════════════════════════════════════════════════════════════════════════════


def run_us_landing_dispatch_cycle(
    project_root: Path | str,
    project_name: str,
    session: DevelopmentSession,
    socket_name: str = DEFAULT_SOCKET_NAME,
) -> str | None:
    """Cuarto nivel: si hay al menos una User Story en `state == "EN_DISEÑO"`
    y un Arquitecto `idle`, ejecuta el aterrizaje US→Tasks
    (`propose_tasks_from_user_story`/`run_task_pipeline`, mismo mecanismo
    determinista que ya usa `POST /backlog/us/{us_id}/propose-tasks`) y
    transiciona la US a `TO_DO` si se escribió al menos una Task real.

    Nota de diseño: `propose_tasks_from_user_story` es determinista (sin
    `llm_generate`, genera Tasks por heurística de secciones de la propia
    US — verificado en `architect/propose_tasks.py`) — no despacha un Job
    real hacia el agente Arquitecto en tmux; el requisito de "Arquitecto
    `idle`" se mantiene igualmente como guardarraíl de disponibilidad
    (mismo criterio "un agente libre a la vez" que el resto de ciclos de
    este módulo), coherente con lo que la propia `US-FB008-15` describe
    como equivalente a `EN_DESARROLLO` para Developer.

    Devuelve el `story_id` aterrizado este ciclo, o `None` si no había
    nada que hacer (sin US en EN_DISEÑO, o sin Arquitecto libre)."""
    from brain.architect.propose_tasks import propose_tasks_from_user_story
    from brain.architect.review_user_story import review_user_story_for_gaps
    from brain.architect.task_pipeline import run_task_pipeline
    from brain.backlog.edit import set_item_state

    backlog_dir = Path(project_root) / "02-backlog"
    graph = load_backlog(backlog_dir)

    designing_stories = sorted(
        item.id for item in graph.items.values()
        if item.kind == "US" and item.state == "EN_DISEÑO"
    )
    if not designing_stories:
        return None
    story_id = designing_stories[0]

    architect_agent = next(
        (
            agent for agent in list_agents(session)
            if isinstance(agent, Agent) and agent.role == _ARQUITECTO_ROLE and agent.status == "idle"
        ),
        None,
    )
    if architect_agent is None:
        return None

    us_item = graph.items.get(story_id)
    if us_item is None:
        return None

    try:
        us_file_path = str(us_item.path)
        review = review_user_story_for_gaps(us_file_path)
        proposal = propose_tasks_from_user_story(review, us_item.epic, us_file_path)
        output_dir = str(backlog_dir / "tasks")
        pipeline_result = run_task_pipeline(proposal, output_dir=output_dir, auto_approve=False)
    except Exception:
        # Mismo criterio de mejor esfuerzo que el resto del Dispatcher: un
        # fallo del aterrizaje no bloquea el hilo de fondo — la US se
        # queda en EN_DISEÑO, se reintenta en el siguiente ciclo.
        return None

    if pipeline_result.approved_tasks:
        set_item_state(us_item.path, "TO_DO")
        return story_id

    # Sin Tasks aprobadas este ciclo (huecos detectados, autoauditoría
    # RECHAZADA) — la US se queda en EN_DISEÑO, no se pierde la señal;
    # un humano puede revisar `pipeline_result.validation`/`self_audit`
    # (mismo dato que ya expone `POST /backlog/us/{id}/propose-tasks`)
    # para resolver los huecos y dejar que el siguiente ciclo lo reintente.
    return None


def dispatch_architect_verdict(
    story_id: str,
    session: DevelopmentSession,
    socket_name: str,
    reports_root: Path | None = None,
    backlog_dir: Path | None = None,
) -> str | None:
    """Despacha un Job de veredicto concreto hacia el Arquitecto y
    encadena su procesamiento — movida aquí desde
    `architect_verdict_queue.py` (T-FB008-US14-02, refactor 2026-08-17):
    el Dispatcher pasa a poseer el ciclo completo de veredicto
    (despachar + interpretar + promocionar estado), no solo el momento
    en que se dispara. `architect_verdict_queue.py` (cola FIFO histórica,
    todavía en uso por `ui_tester_queue.py`) importa esta función desde
    aquí en vez de al revés, para no duplicar la lógica.

    Devuelve el `job.result` (texto del veredicto) si llegó a despachar
    y procesar el Job, o `None` si salió temprano (sin Arquitecto/
    runtime, o `JobCreationError`) — el llamador de la cola FIFO lo usa
    para decidir si encola al Tester de UI (`_maybe_enqueue_ui_tester`),
    que necesita saber si el veredicto fue APROBADO."""
    from brain.agents.arquitecto import ARQUITECTO_ROLE
    from brain.dispatcher.job_creation import JobCreationError, create_job
    from brain.dispatcher.job_dispatch import dispatch_job
    from brain.dispatcher.job_plan_dispatch import (
        _collect_story_reports,
        _process_verdict_result,
    )

    root = (
        reports_root
        if reports_root
        else Path(__file__).resolve().parents[4] / "07-informes"
    )
    reports = _collect_story_reports(story_id, root)

    architect_agent = next(
        (
            agent
            for agent in list_agents(session)
            if isinstance(agent, Agent) and agent.role == ARQUITECTO_ROLE
        ),
        None,
    )
    if architect_agent is None:
        return None

    runtime_instance = get_runtime_instance_for_agent(architect_agent.id)
    if runtime_instance is None:
        return None

    if reports:
        report_blocks = "\n\n---\n\n".join(reports)
        description = (
            f"Revisa el trabajo completado para la User Story {story_id}.\n\n"
            f"A continuación se incluyen los informes de cierre de cada Job "
            f"que trabajó en esta User Story. Emite tu veredicto en el "
            f"formato estructurado ESTADO:/JUSTIFICACIÓN:/"
            f"SIGUIENTE_PROMPT_PARA_WORKER:\n\n"
            f"{report_blocks}"
        )
    else:
        description = (
            f"Revisa el trabajo completado para la User Story {story_id}.\n\n"
            f"(No se encontraron informes de cierre para esta User Story. "
            f"Emite tu veredicto basándote en el contexto disponible.)"
        )

    try:
        job = create_job(description, architect_agent, session)
        dispatch_job(job, architect_agent, runtime_instance, socket_name=socket_name)
        _process_verdict_result(story_id, job.result, backlog_dir=backlog_dir)
    except JobCreationError:
        return None

    return job.result


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
        """Ejecuta un único ciclo de despacho de implementación (primer
        nivel) de forma síncrona, sin hilo — usado en tests deterministas
        que no quieren depender del temporizador real del polling."""
        return run_dispatch_cycle(
            self._project_root, self._project_name, self._session, self._socket_name
        )

    def run_review_once(self) -> str | None:
        """Ejecuta un único ciclo del segundo nivel (Tester verifica una
        Task en REVIEW) de forma síncrona — T-FB008-US14-02."""
        return run_review_dispatch_cycle(
            self._project_root, self._project_name, self._session, self._socket_name
        )

    def run_architect_verdict_once(self) -> str | None:
        """Ejecuta un único ciclo del tercer nivel (Arquitecto veredicta
        una User Story en REVIEW) de forma síncrona — T-FB008-US14-02."""
        return run_architect_verdict_dispatch_cycle(
            self._project_root, self._project_name, self._session, self._socket_name
        )

    def run_us_landing_once(self) -> str | None:
        """Ejecuta un único ciclo del aterrizaje US→Tasks (User Story en
        EN_DISEÑO) de forma síncrona — T-FB008-US15-02."""
        return run_us_landing_dispatch_cycle(
            self._project_root, self._project_name, self._session, self._socket_name
        )

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            # T-FB008-US14-02/T-FB008-US15-02: los cuatro niveles se
            # revisan en el mismo ciclo de polling — cada uno despacha
            # como máximo un item (mismo criterio "una unidad por ciclo"
            # ya vigente en `run_dispatch_cycle`), un fallo de cualquiera
            # no debe impedir que los otros se intenten este mismo ciclo.
            for cycle in (
                run_dispatch_cycle,
                run_review_dispatch_cycle,
                run_architect_verdict_dispatch_cycle,
                run_us_landing_dispatch_cycle,
            ):
                try:
                    cycle(
                        self._project_root, self._project_name, self._session, self._socket_name
                    )
                except Exception:
                    # Mismo criterio de "mejor esfuerzo" que `_notify` en
                    # `dispatch_plan`: un fallo inesperado de un ciclo no
                    # debe matar el hilo de fondo — se reintenta en el
                    # siguiente poll.
                    pass
            self._stop_event.wait(self._poll_interval_seconds)
