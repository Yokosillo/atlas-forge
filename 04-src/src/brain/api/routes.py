"""Rutas HTTP de la API (T-FB016-US01-02 en adelante): cada endpoint es
una envoltura fina sobre una función de dominio ya existente, sin
reimplementar su validación — mismo principio ya fijado en
`02-backlog/epics/FB-016-api-backend.md` ("cada endpoint es una envoltura
fina... no se duplica lógica de validación"). Las excepciones de dominio
(`AgentLaunchError`, `SessionNotActiveError`, ...) se traducen a
`HTTPException` con el mismo mensaje ya construido por el dominio — nunca
un texto reinventado en esta capa."""

import json
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from brain.agents.lifecycle import InvalidAgentTransitionError
from brain.agents.liveness import refresh_agent_liveness
from brain.agents.stop import AgentRuntimeNotFoundError, stop_agent
from brain.api.events import jobs_hub, plans_hub
from brain.api.plan_registry import get_plan, get_plan_lock, list_plans, register_plan
from brain.backlog.detail import build_epic_detail, build_item_detail, is_epic_item_id
from brain.backlog.create import (
    BacklogValidationError as CreateBacklogValidationError,
    EpicAlreadyExistsError,
    EpicNotFoundError,
    InvalidEpicIdError,
    InvalidPriorityError as CreateInvalidPriorityError,
    InvalidTaskIdError,
    InvalidUserStoryIdError,
    TaskAlreadyExistsError,
    UserStoryAlreadyExistsError,
    UserStoryNotFoundError,
    create_epic,
    create_task,
    create_user_story,
)
from brain.backlog.edit import (
    BacklogValidationError,
    InvalidFieldValueError,
    set_item_priority,
    set_item_state,
)
from brain.backlog.promote import promote_backlog
from brain.backlog.dependency_graph import (
    analyze_epic_threads,
    format_thread_analysis_markdown,
    persist_thread_analysis,
)
from brain.architect.propose_user_stories import (
    load_epic_context,
    propose_user_stories_from_epic,
)
from brain.architect.propose_tasks import propose_tasks_from_user_story
from brain.architect.review_user_story import review_user_story_for_gaps
from brain.architect.task_pipeline import run_task_pipeline
from brain.architect.us_pipeline import run_us_pipeline
from brain.backlog.parser import load_backlog
from brain.backlog.report import build_backlog_report, priority_rank
from brain.core.session_lifecycle import SessionNotActiveError, list_agents
from brain.core.session_registry import focus_project_session, get_current_session
from brain.agents.agent_options import list_available_agent_options
from brain.agents.launch import (
    AgentLaunchError,
    launch_agent,
    launch_agent_with_initial_job,
)
from brain.dispatcher.job_cancellation import (
    JobCancellationRejectedError,
    request_cancellation,
)
from brain.dispatcher.dispatch_queue import (
    STATUS_QUEUED,
    TaskAlreadyDispatchedError,
    TaskAlreadyQueuedError,
    TaskNotQueuedError,
    dequeue_task,
    enqueue_task,
    get_queue,
)
from brain.dispatcher.job_creation import JobCreationError
from brain.dispatcher.job_dispatch import dispatch_job
from brain.dispatcher.job_history_registry import list_jobs_for_session
from brain.dispatcher.job_orchestration import create_and_record_job
from brain.dispatcher.job_plan_approval import present_plan_for_approval
from brain.dispatcher.job_report import write_job_report
from brain.dispatcher.job_plan_builder import (
    _pending_task_files_for_story,
    _read_task_title,
    build_job_plan_for_story,
    task_file_story_prefix,
)
from brain.dispatcher.job_plan_cancellation import (
    JobPlanCancellationRejectedError,
    request_cancellation as request_plan_cancellation,
)
from brain.dispatcher.job_plan_dispatch import (
    dispatch_plan,
    get_plan_progress,
    trigger_architect_verdict,
)
from brain.dispatcher.job_plan_lifecycle import InvalidJobPlanTransitionError
from brain.models import Agent, Job
from brain.models.backlog import ITEM_KIND_TASK, ITEM_KIND_USER_STORY
from brain.runtime.agent_runtime_registry import get_runtime_instance_for_agent
from brain.runtime.generic import extract_model_from_runtime, is_runtime_alive
from brain.agent_model import (
    get_active_model as agent_model_get_active_model,
    get_active_model_claude_code as agent_model_get_active_model_claude_code,
    get_available_model_entries as agent_model_get_available_model_entries,
    get_available_models as agent_model_get_available_models,
    set_active_model as agent_model_set_active_model,
)
from brain.model_preferences import (
    load_model_preferences,
    save_model_preferences,
)
from brain.system_preferences import (
    load_system_preferences,
    save_system_preferences,
)
from brain.tmux.manager import DEFAULT_SOCKET_NAME
from brain.tmux import capture_pane_lines
from brain.workspace.active_project import (
    ProjectNotDiscoveredError,
    get_active_project,
    select_active_project,
)
from brain.workspace.discovery import (
    discover_projects,
    invalidate_discovery_cache,
)
from brain.workspace.project_scripts import (
    MalformedScriptManifestError,
    discover_project_scripts,
    invalidate_project_scripts_cache,
    run_project_script,
)
from brain.workspace.generic_scripts import list_generic_scripts, run_generic_script
from brain.local_tools import ScribeUnavailableError, resumir_estado_backlog

router = APIRouter()

# Módulo-nivel (no parámetro del body HTTP: el socket tmux es un detalle de
# infraestructura del propio servidor, ningún cliente real debería
# controlarlo) — expuesto como variable, no inline, únicamente para que los
# tests puedan aislarse en un servidor tmux propio via monkeypatch, mismo
# patrón ya usado en test_launch_agent.py para los comandos de runtime.
_SOCKET_NAME = DEFAULT_SOCKET_NAME

# T-FB018-US02-04: la síntesis en prosa (T-FB018-US02-03) es una capa
# opcional dentro de la respuesta de `POST /scripts/backlog_status/run`.
# Se acota su timeout (menor que el por defecto de Scribe) para que un
# Ollama lento no cuelgue el endpoint: la capa es opcional, nunca una
# dependencia dura del resto de la respuesta.
_BACKLOG_PROSE_TIMEOUT_SECONDS = 15.0

# Mismo patrón que `_SOCKET_NAME` (T-FB016-US01-11): `None` en producción
# resuelve al directorio de trabajo real del proceso / ubicación por
# defecto de `brain.storage` (igual que `resolve_startup_session()` sin
# argumentos en `_lifespan`, `brain/api/app.py`) — expuestos como
# variables de módulo para que los tests puedan aislarse en un workspace
# y estado propios via monkeypatch, sin tocar el filesystem real del
# usuario.
_WORKSPACE_ROOT: Path | None = None
_STATE_DIR: Path | None = None

# T-FB008-US10-02: instancia del Dispatcher de fondo de la cola de
# despacho, arrancada en `_lifespan` (`brain/api/app.py`) — variable de
# módulo (mismo patrón que `_SOCKET_NAME`/`_STATE_DIR`) para que
# `GET /backlog/queue` (o cualquier endpoint futuro) pueda inspeccionar
# su estado si hiciera falta, y para que los tests puedan detenerlo
# explícitamente entre casos sin depender del recolector de basura.
_dispatch_queue_worker = None


def _resolve_workspace_root() -> Path:
    return _WORKSPACE_ROOT if _WORKSPACE_ROOT is not None else Path.cwd()


class LaunchAgentRequest(BaseModel):
    role: str
    runtime_type: str | None = None
    model_id: str | None = None
    model: str | None = None  # legacy: alias de model_id
    initial_job_description: str | None = None

    def resolved_runtime_type(self) -> str | None:
        """Resuelve el runtime_type: si se dio model_id/model catalogado, se
        infiere del catalogo; si el modelo no esta catalogado (p. ej. un
        modelo libre de OpenCode) o no se dio modelo, se usa el
        runtime_type explicito del request."""
        model = self.model_id or self.model
        if model:
            from brain.agent_model import resolve_runtime_for_model
            resolved = resolve_runtime_for_model(model)
            if resolved is not None:
                return resolved
        return self.runtime_type


    def resolved_model(self) -> str | None:
        return self.model_id or self.model


class CreateJobRequest(BaseModel):
    agent_id: str
    description: str
    previous_job_id: str | None = None
    # T-FB024-US15-01: Story a la que pertenece este Job suelto (sin pasar
    # por dispatch_plan). Si se informa, al completarse el Job dispara el
    # mismo ciclo de informe de cierre + veredicto automático que ya existe
    # para el flujo de Plan (ver `post_jobs`). Sin él, comportamiento
    # idéntico al actual.
    story_id: str | None = None


class CreateEpicRequest(BaseModel):
    # T-FB036-US02-01: campos sueltos del formulario "+ Nueva Epic"
    # (T-FB036-US02-04, todavía sin implementar) — `id` se valida en
    # servidor contra `EPIC_ID_PATTERN` (`brain.backlog.create`), nunca
    # solo en cliente.
    id: str
    title: str
    objetivo: str
    fase: str | None = None


class CreateUserStoryRequest(BaseModel):
    # T-FB036-US02-02: campos sueltos del formulario "+ Nueva User Story"
    # (T-FB036-US02-05, todavía sin implementar) — deliberadamente SIN
    # campo `epic_id`: la Epic padre viene siempre de la URL
    # (`POST /backlog/epic/{epic_id}/us`), nunca de un valor que el
    # cliente pudiera enviar en el body (criterio de aceptación explícito
    # de la Task).
    id: str
    title: str
    objetivo: str
    criterios_aceptacion: str
    priority: str | None = None


class CreateTaskRequest(BaseModel):
    # T-FB036-US02-03: campos sueltos del formulario "+ Nueva Task"
    # (T-FB036-US02-06, todavía sin implementar) — deliberadamente SIN
    # campo `epic_id`/`us_id`: `us_id` viene siempre de la URL
    # (`POST /backlog/us/{us_id}/task`) y `epic_id` se resuelve leyendo
    # el frontmatter de esa misma US (campo `epic`), nunca de un valor
    # que el cliente pudiera enviar en el body — evita la inconsistencia
    # de una Task declarando una Epic distinta a la de su US real
    # (criterio de aceptación explícito de la Task).
    id: str
    title: str
    objetivo: str
    descripcion: str
    criterios_aceptacion: str
    priority: str | None = None
    dependencies: list[str] | None = None


class LaunchDevelopmentRequest(BaseModel):
    agent_id: str


class CreatePlanRequest(BaseModel):
    goal: str


class SelectProjectRequest(BaseModel):
    # `Project.id` es literalmente `str(path)` (ver `discover_projects`,
    # `brain/workspace/discovery.py`) — un único campo cubre ambos nombres
    # que menciona la Descripción de la Task ("project_id o path"), sin
    # necesitar dos campos redundantes que pudieran discreparse entre sí.
    project_id: str


class RunScriptRequest(BaseModel):
    # T-FB018-US01-03: `message` es el único parámetro que necesita algún
    # script del catálogo (el genérico `commit`); los particulares y el
    # resto de genéricos (`push`, `changed_files`, `diff_stat`,
    # `language_stats`, `backlog_status`) se ejecutan sin él. Campo
    # opcional (default None): un cliente que solo hace un POST sin body
    # sigue funcionando como antes.
    message: str | None = None


def _serialize_project(project) -> dict:
    return {
        "id": project.id,
        "name": project.name,
        "path": project.path,
        "repository": project.repository,
        "workspace_id": project.workspace_id,
    }


@router.get("/project")
def get_project() -> dict:
    """Proyecto activo (`brain.workspace.active_project`, FB-001) — 404
    explícito si no hay ninguno seleccionado todavía.

    Usa `_STATE_DIR` (T-FB016-US01-11), no el valor por defecto de
    `get_active_project`: antes de esta Task no había ninguna forma de
    aislar este endpoint del filesystem real del usuario en tests
    (`~/.local/share/brain/`), inconsistencia que se hizo visible al
    aislar `POST /project` en su propio estado de test — ambos deben leer
    y escribir la misma ubicación, sea la real (`_STATE_DIR=None`, valor
    por defecto en producción) o una aislada de test."""
    project = get_active_project(state_dir=_STATE_DIR)
    if project is None:
        raise HTTPException(status_code=404, detail="No hay ningún proyecto activo.")

    return _serialize_project(project)


@router.get("/projects")
def get_projects() -> list[dict]:
    """Repositorios Git descubiertos en el workspace (T-FB016-US01-11),
    candidatos a proyecto activo — mismo `discover_projects` (FB-001) que
    ya usa `WorkspaceScreen` de la TUI, sobre el mismo `workspace_root`
    por defecto (directorio de trabajo del proceso) que usa
    `resolve_startup_session` en `_lifespan` (`brain/api/app.py`), para
    que la lista aquí coincida con la que ese arranque ya resolvió."""
    return [
        _serialize_project(project)
        for project in discover_projects(_resolve_workspace_root(), state_dir=_STATE_DIR)
    ]


@router.post("/project")
def post_project(body: SelectProjectRequest) -> dict:
    """Selecciona un proyecto de `GET /projects` como activo
    (`select_active_project`, FB-001) y le da el foco de sesión de
    desarrollo del proceso (T-FB029-US01-02, `focus_project_session`):
    si el proyecto ya tenía una sesión viva la reutiliza tal cual
    (mismo `session.id`, mismos agentes, sin relanzar nada); si no, la
    crea igual que el arranque del proceso (`resolve_startup_session`).

    ## Qué pasa con los agentes de la sesión anterior (FB-029)

    Nada: los agentes del proyecto que pierde el foco no se tocan ni se
    detienen. Siguen vivos en su propia sesión (`_SessionRegistry`,
    `brain.core.session_registry`) y vuelven a ser alcanzables por
    `GET /agents`/`POST /agents/{id}/stop` en cuanto su proyecto
    recupera el foco — ya no hace falta detenerlos para evitarlo, porque
    dejaron de quedar huérfanos: antes de esta Epic solo existía una
    sesión global, así que un agente de un proyecto sin foco quedaba
    fuera de `session.agents` de la única sesión existente; con el
    registro multi-sesión de FB-029 cada proyecto tiene su propia sesión
    viva en paralelo, alcanzable por su `project_id`. Comportamiento
    anterior (detener explícitamente cada agente no `stopped` antes de
    descartar la sesión) documentado y sustituido por esta Epic — ver
    `02-backlog/epics/FB-016-api-backend.md`, sección "Cambio de
    proyecto activo en caliente", y `02-backlog/epics/FB-029-sesiones-proyecto-simultaneas.md`.
    """
    discovered = discover_projects(_resolve_workspace_root(), state_dir=_STATE_DIR)
    selected = next(
        (project for project in discovered if project.id == body.project_id), None
    )
    if selected is None:
        raise HTTPException(
            status_code=400,
            detail=f"El proyecto '{body.project_id}' no pertenece a la lista de "
            "repositorios descubiertos.",
        )

    try:
        select_active_project(selected, discovered=discovered, state_dir=_STATE_DIR)
    except ProjectNotDiscoveredError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    # T-FB001-US01-06: al cambiar de proyecto activo se invalidan las cachés
    # TTL de discovery (proyectos y scripts), para que el catálogo del nuevo
    # proyecto se refleje sin esperar al TTL anterior (y para que un
    # ida-y-vuelta A→B→A dentro del TTL no sirva la caché vieja de A).
    invalidate_discovery_cache()
    invalidate_project_scripts_cache()

    focus_project_session(selected.id)

    return _serialize_project(selected)


# ------------------------------------------------------------------ FB-025
# Acciones transversales de proyecto (US-FB025-01 a US-FB025-07).
# Despachan Jobs al Arquitecto, scripts deterministas, o invocaciones
# headless de opencode/Scribe desde un solo clic en la web, sin pasar por
# el modo conversacional del Arquitecto.


@router.post("/project/actions/{action_id}")
def post_project_action(action_id: str) -> dict:
    """Despacha una acción transversal de proyecto.

    Acciones disponibles:
    - `documentar`, `analizar-arquitectura`, `sugerir-ideas`: despacha un
      Job al Arquitecto. Requiere sesión activa con un Arquitecto lanzado.
    - `auditar-ux` (T-FB024-US13-03): despacha un Job a la instancia de UX
      ya lanzada. Requiere sesión activa con un UX lanzado — si no hay
      ninguno, informa explícitamente en vez de fallar en silencio.
    - `testear`: ejecuta `pytest` determinista. No requiere sesión.
    - `indexar`: Scribe index_documents. No requiere sesión.

    Bloqueante: la respuesta HTTP llega cuando la acción termina."""
    from brain.actions.transversal import ACCIONES_DISPONIBLES, dispatch_action

    if action_id not in ACCIONES_DISPONIBLES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Acción desconocida: '{action_id}'. "
                f"Acciones disponibles: {', '.join(ACCIONES_DISPONIBLES)}."
            ),
        )

    _AGENT_ACTIONS = frozenset({"documentar", "analizar-arquitectura", "sugerir-ideas"})
    if action_id in _AGENT_ACTIONS:
        session = get_current_session()
        if session is None:
            raise HTTPException(
                status_code=404,
                detail="No hay ninguna sesión de desarrollo activa.",
            )

    try:
        result = dispatch_action(action_id, socket_name=_SOCKET_NAME)
    except RuntimeError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except ProjectNotDiscoveredError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except JobCreationError as error:
        # Defensa en profundidad (T-FB024-US13-03): `_find_agent_by_role`
        # ya excluye agentes no `idle` antes de llegar aquí, pero un 500
        # crudo por un agente en estado inesperado sigue siendo peor que
        # un 400 explícito si algún camino nuevo llegara a esta excepción.
        raise HTTPException(status_code=400, detail=str(error)) from error

    return result


@router.get("/session")
def get_session() -> dict:
    """Sesión de desarrollo activa de este proceso — 404 explícito si
    todavía no se ha arrancado ninguna (criterio de aceptación de la
    Task)."""
    session = get_current_session()
    if session is None:
        raise HTTPException(
            status_code=404, detail="No hay ninguna sesión de desarrollo activa."
        )

    return {
        "id": session.id,
        "project_id": session.project_id,
        "status": session.status,
    }


def _serialize_agent(agent: Agent) -> dict:
    """Serializa `agent` incluyendo su preferencia de runtime/modelo
    (T-FB005-US05-01, criterio de aceptación: "consultar el agente
    muestra el runtime/modelo asociado"). `runtime_id` ya existía en
    `Agent` — sin cambios de modelo necesarios, confirmado que el
    mecanismo de `Runtime` ya cubre la necesidad (ver
    `runtime/generic.py`, `extract_model_from_runtime`). `model` se
    resuelve desde el `RuntimeInstance` real asociado al agente
    (`get_runtime_instance_for_agent`, T-FB002-US03-00) — `None`
    explícito si el agente nunca llegó a registrar un runtime (no debería
    ocurrir en la práctica, todo agente pasa por `register_agent`, pero
    se maneja sin excepción por si acaso) o si el runtime no tiene un
    modelo asociado (Claude Code hoy, o OpenCode sin `model` indicado)."""
    runtime_instance = get_runtime_instance_for_agent(agent.id)
    model = (
        extract_model_from_runtime(runtime_instance.runtime)
        if runtime_instance is not None
        else None
    )
    session_name = (
        runtime_instance.session_name if runtime_instance is not None else None
    )
    return {
        "id": agent.id,
        "name": agent.name,
        "role": agent.role,
        "status": agent.status,
        "runtime_id": agent.runtime_id,
        "model": model,
        "session_name": session_name,
        "last_command_at": getattr(agent, "last_command_at", None) or None,
    }


@router.get("/agents")
def get_agents() -> list[dict]:
    """Lista de agentes lanzados en la sesión activa y su estado
    (reutiliza `list_agents`, FB-005). 404 si no hay sesión activa — sin
    sesión no hay agentes que consultar, mismo criterio que `GET
    /session`.

    Antes de devolver cada agente, `refresh_agent_liveness`
    (T-FB016-US01-07) comprueba de forma perezosa si su runtime real
    sigue vivo — si murió sin que nadie lo pidiera (no estaba `stopped`),
    se transiciona a `unavailable` en este mismo momento, para que ningún
    cliente vea `idle`/`working` de un proceso que ya no existe."""
    session = get_current_session()
    if session is None:
        raise HTTPException(
            status_code=404, detail="No hay ninguna sesión de desarrollo activa."
        )

    return [
        _serialize_agent(refresh_agent_liveness(agent, socket_name=_SOCKET_NAME))
        for agent in list_agents(session)
    ]


@router.get("/agents/options")
def get_agents_options() -> list[dict]:
    """Catalogo de combinaciones rol/modelo disponibles (T-FB022-US11-01):
    producto cartesiano de roles x modelos habilitados, con el runtime
    resuelto internamente del catalogo. No requiere sesion activa.

    El filtro que excluia Critic + OpenCode (T-FB016-US01-19) se eliminó
    junto con el rol `critic` (FB-022): ya no existe esa combinación que
    ocultar."""
    return [
        {
            "agent_role": option.agent_role,
            "model_id": option.model_id,
            "model_name": option.model_name,
            "runtime_type": option.runtime_type,
            "runtime_name": option.runtime_name,
            "supports_model": option.supports_model,
        }
        for option in list_available_agent_options()
    ]


@router.post("/agents", status_code=201)
def post_agents(body: LaunchAgentRequest) -> dict:
    """Lanza un agente (mismo mecanismo que la TUI, `launch_agent` de
    `brain.agents.launch`, FB-005), sin reimplementar su validación.
    `project_path` se resuelve del proyecto activo (FB-001) en vez de
    pedirlo al cliente — el dominio ya lo conoce, no tiene sentido que
    cada cliente HTTP tenga que resolverlo por su cuenta.

    Cualquier rechazo de `launch_agent` (`AgentLaunchError`) o de sesión
    no activa (`SessionNotActiveError`) se traduce a 400 con el mismo
    mensaje de motivo ya construido por el dominio — criterio de
    aceptación explícito de la Task, nunca un texto reinventado aquí.

    Si `initial_job_description` viene informado (T-FB016-US01-16, expone
    T-FB008-US06-01), el lanzamiento encadena el despacho del Job inicial
    en el mismo paso (`launch_agent_with_initial_job`) y la respuesta 201
    incluye tanto los datos del agente como los del Job despachado (o su
    fallo: si el despacho falla por timeout/runtime, el agente sigue
    registrado e `idle`, `job.status == "failed"` con el motivo en
    `job.result`). Sin el campo, la respuesta es idéntica a la actual
    (solo datos del agente)."""
    session = get_current_session()
    if session is None:
        raise HTTPException(
            status_code=404, detail="No hay ninguna sesión de desarrollo activa."
        )

    project = get_active_project(state_dir=_STATE_DIR)
    if project is None:
        raise HTTPException(status_code=404, detail="No hay ningún proyecto activo.")

    try:
        runtime_type = body.resolved_runtime_type()
        if runtime_type is None:
            raise HTTPException(
                status_code=400,
                detail="Se requiere 'runtime_type' o 'model_id'/'model' para lanzar un agente.",
            )

        model = body.resolved_model()
        if body.initial_job_description is None:
            agent, _runtime_instance = launch_agent(
                body.role,
                runtime_type,
                model,
                session,
                project.path,
                socket_name=_SOCKET_NAME,
            )
            return _serialize_agent(agent)

        agent, _runtime_instance, job = launch_agent_with_initial_job(
            body.role,
            runtime_type,
            model,
            session,
            project.path,
            initial_job_description=body.initial_job_description,
            socket_name=_SOCKET_NAME,
        )
    except (
        AgentLaunchError,
        SessionNotActiveError,
        JobCreationError,
        RuntimeError,
    ) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    jobs_hub.publish({"event": "job_status", **_serialize_job(job)})

    return {"agent": _serialize_agent(agent), "job": _serialize_job(job)}


def _find_agent_by_id(session, agent_id: str) -> Agent | None:
    return next(
        (
            agent
            for agent in list_agents(session)
            if isinstance(agent, Agent) and agent.id == agent_id
        ),
        None,
    )


@router.post("/agents/{agent_id}/stop")
def post_agent_stop(agent_id: str) -> dict:
    """Detiene el agente `agent_id` de la sesión activa (`stop_agent`,
    T-FB016-US01-03): detiene su sesión tmux real. Para la mayoría de
    roles (incluido Arquitecto) lo transiciona a `stopped` — nunca a
    `unavailable` — y permanece consultable en `GET /agents` después. Para
    Developer (T-FB024-US12-02, decisión de producto), en cambio, el
    `Agent` se elimina por completo de la sesión: deja de listarse en
    `GET /agents` y libera de inmediato su plaza del límite de Developer
    simultáneos — ver docstring de `stop_agent` para el detalle completo.
    La respuesta siempre devuelve el estado del agente justo tras la
    acción (con `status: stopped` también en el caso Developer, aunque ya
    no sea consultable después)."""
    session = get_current_session()
    if session is None:
        raise HTTPException(
            status_code=404, detail="No hay ninguna sesión de desarrollo activa."
        )

    agent = _find_agent_by_id(session, agent_id)
    if agent is None:
        raise HTTPException(
            status_code=404, detail=f"No existe ningún agente con id '{agent_id}'."
        )

    try:
        stop_agent(agent, session, socket_name=_SOCKET_NAME)
    except (AgentRuntimeNotFoundError, InvalidAgentTransitionError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    return _serialize_agent(agent)


@router.get("/agents/{agent_id}/pane")
def get_agent_pane(agent_id: str) -> dict:
    """Contenido actual del pane de tmux del agente `agent_id` de la sesión
    activa (T-FB016-US01-12). Reutiliza `capture_pane_lines` sin reimplementar:
    devuelve el contenido visual CRUDO de la sesión real del runtime — no es
    una consola interactiva, es una vista de solo lectura del estado actual
    (incluye cualquier señal visual de "esperando prompt" que OpenCode muestre
    en su TUI, sin interpretarla semánticamente). 404 explícito si no hay
    sesión activa, si el agente no existe en ella, o si el agente no tiene un
    runtime registrado del que capturar pane."""
    session = get_current_session()
    if session is None:
        raise HTTPException(
            status_code=404, detail="No hay ninguna sesión de desarrollo activa."
        )

    agent = _find_agent_by_id(session, agent_id)
    if agent is None:
        raise HTTPException(
            status_code=404, detail=f"No existe ningún agente con id '{agent_id}'."
        )

    runtime_instance = get_runtime_instance_for_agent(agent.id)
    if runtime_instance is None:
        raise HTTPException(
            status_code=404,
            detail=f"No hay ningún runtime registrado para el agente '{agent_id}'.",
        )

    # Agente `stopped`: la sesión tmux ya se mató (ver `stop_agent`) —
    # capturar un pane inexistente lanzaría un AttributeError (500). Se
    # devuelve un 404 limpio con el motivo, mismo estilo de detalle que el
    # resto de endpoints.
    if not is_runtime_alive(runtime_instance, socket_name=_SOCKET_NAME):
        raise HTTPException(
            status_code=404,
            detail=f"El agente '{agent_id}' no tiene una sesión tmux viva que mostrar.",
        )

    content = capture_pane_lines(
        runtime_instance.session_name, socket_name=_SOCKET_NAME
    )
    return {"agent_id": agent_id, "content": "\n".join(content)}


@router.get("/agents/{agent_id}/model")
def get_agent_model(agent_id: str) -> dict:
    """Modelo activo actual del agente `agent_id`, leido de la barra de
    estado de OpenCode via `get_active_model` (T-FB004-US05-01).

    Devuelve `{agent_id, model: str | null}`. El valor `null` indica:
    runtime no OpenCode, sesion muerta, patrón no encontrado o cualquier
    fallo de lectura del pane — nunca un error HTTP (la ausencia de dato
    es un dato en si mismo). 404 solo si no hay sesion activa o el agente
    no existe en ella."""
    session = get_current_session()
    if session is None:
        raise HTTPException(
            status_code=404, detail="No hay ninguna sesión de desarrollo activa."
        )
    agent = _find_agent_by_id(session, agent_id)
    if agent is None:
        raise HTTPException(
            status_code=404, detail=f"No existe ningún agente con id '{agent_id}'."
        )
    model = agent_model_get_active_model(agent_id, socket_name=_SOCKET_NAME)
    return {"agent_id": agent_id, "model": model}


@router.get("/agents/{agent_id}/status-model")
def get_agent_status_model(agent_id: str) -> dict:
    """Modelo activo real del agente `agent_id`, leído bajo demanda vía
    `/status` del pane (T-FB024-US11-05, `get_active_model_claude_code`)
    — a diferencia de `GET /agents/{id}/model` (OpenCode, lectura pasiva
    de la barra de estado), esta ruta interactúa activamente con el pane
    (envía `/status` + Enter, espera, captura, cierra con Escape).

    Por eso, y por decisión de producto ya cerrada (nunca automático, solo
    bajo demanda explícita del humano — ver `agent_model.py`), esta ruta:
    - Devuelve `400` explícito si el agente está `working` — nunca se
      interactúa con el pane de un agente trabajando activamente
      (criterio de aceptación 2 de la Task), no solo cuando se dispara
      automáticamente.
    - Solo tiene sentido para agentes Claude Code; para cualquier otro
      runtime `get_active_model_claude_code` ya devuelve `None` sin
      fallar (mismo criterio del resto de endpoints de modelo: la
      ausencia de dato es un dato en sí mismo, no un error HTTP).

    Devuelve `{agent_id, model: str | null}`. 404 solo si no hay sesión
    activa o el agente no existe en ella."""
    session = get_current_session()
    if session is None:
        raise HTTPException(
            status_code=404, detail="No hay ninguna sesión de desarrollo activa."
        )
    agent = _find_agent_by_id(session, agent_id)
    if agent is None:
        raise HTTPException(
            status_code=404, detail=f"No existe ningún agente con id '{agent_id}'."
        )
    if agent.status == "working":
        raise HTTPException(
            status_code=400,
            detail=(
                f"No se puede consultar el modelo del agente '{agent.name}': "
                "está 'working'. Consultar el modelo requiere interactuar "
                "con su pane (/status), lo que interrumpiría su trabajo en "
                "curso — espera a que quede 'idle' antes de consultar."
            ),
        )
    model = agent_model_get_active_model_claude_code(agent_id, socket_name=_SOCKET_NAME)
    return {"agent_id": agent_id, "model": model}


@router.put("/agents/{agent_id}/model")
def put_agent_model(agent_id: str, body: dict) -> dict:
    """Cambia el modelo activo del agente `agent_id` via
    `set_active_model` (T-FB004-US05-01). Recibe `{"model": "<id>"}` en el
    cuerpo. Solo para agentes OpenCode en ejecucion — si el runtime no lo
    soporta o la sesion tmux no esta viva, devuelve 400 con el motivo
    (nunca 500). No modifica el estado del agente (sigue `idle`/`working`).

    Devuelve `{agent_id, model, changed: true|false}`."""
    session = get_current_session()
    if session is None:
        raise HTTPException(
            status_code=404, detail="No hay ninguna sesión de desarrollo activa."
        )
    agent = _find_agent_by_id(session, agent_id)
    if agent is None:
        raise HTTPException(
            status_code=404, detail=f"No existe ningún agente con id '{agent_id}'."
        )

    model_name = body.get("model") if isinstance(body, dict) else None
    if not isinstance(model_name, str) or not model_name.strip():
        raise HTTPException(
            status_code=400,
            detail="El campo 'model' es obligatorio (cadena no vacía).",
        )

    # Verificar que el runtime es OpenCode antes de intentar el cambio
    # (get_active_model ya lo comprueba internamente, pero aquí damos un
    # 400 explicito con el motivo de dominio en vez de un false silencioso).
    rt = get_runtime_instance_for_agent(agent.id)
    if rt is None:
        raise HTTPException(
            status_code=400,
            detail=f"El agente '{agent_id}' no tiene un runtime registrado.",
        )
    if rt.runtime.type != "opencode":
        raise HTTPException(
            status_code=400,
            detail=f"El agente '{agent_id}' no usa OpenCode — no admite cambio de modelo.",
        )

    changed = agent_model_set_active_model(
        agent_id, model_name.strip(), socket_name=_SOCKET_NAME
    )
    return {"agent_id": agent_id, "model": model_name.strip(), "changed": changed}


@router.get("/agents/{agent_id}/available-models")
def get_agent_available_models(agent_id: str) -> dict:
    """Modelos disponibles para el agente `agent_id`, con indicador de si
    el agente admite cambio de modelo (runtime OpenCode). La lista se lee
    del catalogo de configuracion (`models.yml`, T-FB022-US09) — no es un
    array fijo de codigo ni se interroga al binario de OpenCode.

    Devuelve `{agent_id, supports_model: bool, models: [{id, name, runtime}]}`.
    404 solo si no hay sesion activa o el agente no existe."""
    session = get_current_session()
    if session is None:
        raise HTTPException(
            status_code=404, detail="No hay ninguna sesión de desarrollo activa."
        )
    agent = _find_agent_by_id(session, agent_id)
    if agent is None:
        raise HTTPException(
            status_code=404, detail=f"No existe ningún agente con id '{agent_id}'."
        )

    rt = get_runtime_instance_for_agent(agent.id)
    supports = rt is not None and rt.runtime.type == "opencode"
    return {
        "agent_id": agent_id,
        "supports_model": supports,
        "models": agent_model_get_available_model_entries() if supports else [],
    }


@router.get("/models/preferences")
def get_models_preferences() -> dict:
    """Preferencias de modelos: catalogo completo con habilitado/deshabilitado
    y defaults por rol (T-FB022-US10-01).

    Devuelve `{models: [{id, name, runtime, enabled}], defaults: {role: model_id}}`.
    No requiere sesion activa. `enabled` se resuelve asi:
    - `enabled_model_ids` vacio = todos habilitados.
    - `enabled_model_ids` con IDs = solo esos habilitados."""
    catalog = agent_model_get_available_model_entries()
    prefs = load_model_preferences(state_dir=_STATE_DIR)
    enabled_ids = prefs["enabled_model_ids"]
    all_enabled = not enabled_ids  # lista vacia = todos habilitados

    models_with_status = []
    for entry in catalog:
        models_with_status.append({
            "id": entry["id"],
            "name": entry["name"],
            "runtime": entry["runtime"],
            "enabled": all_enabled or entry["id"] in enabled_ids,
        })

    return {
        "models": models_with_status,
        "defaults": prefs["default_model_by_role"],
    }


class UpdateModelsPreferencesRequest(BaseModel):
    enabled_model_ids: list[str] | None = None
    default_model_by_role: dict[str, str] | None = None


@router.put("/models/preferences")
def put_models_preferences(body: UpdateModelsPreferencesRequest) -> dict:
    """Actualiza las preferencias de modelos (T-FB022-US10-01).
    Recibe `{enabled_model_ids: [...], default_model_by_role: {...}}`.
    Ambos campos son opcionales — solo se actualiza lo enviado."""
    current = load_model_preferences(state_dir=_STATE_DIR)

    if body.enabled_model_ids is not None:
        current["enabled_model_ids"] = body.enabled_model_ids
    if body.default_model_by_role is not None:
        current["default_model_by_role"] = body.default_model_by_role

    save_model_preferences(current, state_dir=_STATE_DIR)
    return current


@router.get("/system/preferences")
def get_system_preferences() -> dict:
    """Preferencias de sistema (US-FB024-12): catálogo abierto de valores
    operativos configurables desde la web en vez de constantes fijas en
    código (hoy solo `max_simultaneous_developers`). No requiere sesión
    activa, mismo criterio que `GET /models/preferences`."""
    return load_system_preferences(state_dir=_STATE_DIR)


class UpdateSystemPreferencesRequest(BaseModel):
    max_simultaneous_developers: int | None = None


@router.put("/system/preferences")
def put_system_preferences(body: UpdateSystemPreferencesRequest) -> dict:
    """Actualiza las preferencias de sistema (US-FB024-12). Recibe
    `{max_simultaneous_developers: <int>}`. Rechaza con 400 un valor
    inválido (0, negativo, no numérico ya lo rechaza FastAPI/Pydantic al
    parsear el body) sin persistir un estado que rompería
    `register_developer` (criterio de aceptación explícito: nunca
    persistir un límite que dejaría el sistema en un estado roto)."""
    current = load_system_preferences(state_dir=_STATE_DIR)

    if body.max_simultaneous_developers is not None:
        if body.max_simultaneous_developers < 1:
            raise HTTPException(
                status_code=400,
                detail=(
                    "max_simultaneous_developers debe ser un entero mayor "
                    f"que 0 (recibido: {body.max_simultaneous_developers})."
                ),
            )
        current["max_simultaneous_developers"] = body.max_simultaneous_developers

    save_system_preferences(current, state_dir=_STATE_DIR)
    return current


def _find_job_by_id(session, job_id: str) -> Job | None:
    return next(
        (job for job in list_jobs_for_session(session.id) if job.id == job_id),
        None,
    )


def _serialize_job(job: Job) -> dict:
    return {
        "id": job.id,
        "session_id": job.session_id,
        "agent_id": job.agent_id,
        "description": job.description,
        "status": job.status,
        "result": job.result,
    }


@router.post("/jobs", status_code=201)
def post_jobs(body: CreateJobRequest) -> dict:
    """Crea y despacha un Job real (`create_and_record_job` + `dispatch_job`,
    US-FB008-01/02), sin reimplementar su validación ni su mecanismo de
    encadenamiento — mismo resultado que si se hubiera despachado desde la
    TUI (criterio de aceptación explícito). Bloqueante: la respuesta HTTP
    solo llega cuando el Job ya terminó (`completed`/`failed`), igual que
    `dispatch_job` ya es síncrono en el resto del dominio.

    `previous_job_id` (opcional) resuelve un `Job` ya existente del
    histórico de la sesión para encadenar su resultado como entrada del
    nuevo Job (`create_job(..., previous_job=...)`, US-FB008-02) — mismo
    mecanismo que `JobsScreen` usa hoy para encadenar Developer → Critic.

    Publica en `WS /ws/jobs` (T-FB016-US01-05) el evento `created` antes
    de despachar, y el evento final (`completed`/`failed`) después —
    `dispatch_job` en sí no conoce a sus observadores (ver
    `brain.api.events` para la justificación de no tocar el dominio).
    `dispatch_job` nunca propaga una excepción por un fallo de despacho
    (timeout esperando al agente, etc.): captura el fallo internamente y
    deja `job.status == "failed"` con el motivo en `job.result` — no hay
    ningún `try/except` que envolver aquí para ese caso, el estado final
    ya es correcto por construcción, se publica y se devuelve tal cual."""
    session = get_current_session()
    if session is None:
        raise HTTPException(
            status_code=404, detail="No hay ninguna sesión de desarrollo activa."
        )

    agent = _find_agent_by_id(session, body.agent_id)
    if agent is None:
        raise HTTPException(
            status_code=404, detail=f"No existe ningún agente con id '{body.agent_id}'."
        )

    previous_job = None
    if body.previous_job_id is not None:
        previous_job = _find_job_by_id(session, body.previous_job_id)
        if previous_job is None:
            raise HTTPException(
                status_code=404,
                detail=f"No existe ningún Job con id '{body.previous_job_id}' "
                "en el histórico de la sesión.",
            )

    runtime_instance = get_runtime_instance_for_agent(agent.id)
    if runtime_instance is None:
        raise HTTPException(
            status_code=400,
            detail=f"El agente '{agent.name}' no tiene un runtime registrado "
            "— debe estar lanzado antes de despachar un Job.",
        )

    try:
        job = create_and_record_job(
            body.description, agent, session, previous_job=previous_job
        )
    except JobCreationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    if body.story_id is not None:
        job.story_id = body.story_id

    jobs_hub.publish({"event": "job_status", **_serialize_job(job)})

    dispatch_job(job, agent, runtime_instance, socket_name=_SOCKET_NAME)

    # T-FB024-US15-01: mismo ciclo de informe de cierre + veredicto
    # automático que ya dispara `dispatch_plan` al completar todos sus
    # pasos (ver `_dispatch_agent_step`/`trigger_architect_verdict` en
    # `job_plan_dispatch.py`), ahora también para un Job suelto creado
    # directamente con `POST /jobs` cuando viene asociado a una Story. Sin
    # `story_id`, comportamiento idéntico al actual (nada de esto se
    # ejecuta). Un Job `cancelled` no se reporta — mismo criterio que
    # `_dispatch_agent_step` ("un paso cancelado no tiene información útil
    # que persistir").
    if job.story_id and job.status in ("completed", "failed"):
        try:
            write_job_report(job)
        except Exception:
            pass
        try:
            trigger_architect_verdict(job.story_id, session, socket_name=_SOCKET_NAME)
        except Exception:
            pass

    jobs_hub.publish({"event": "job_status", **_serialize_job(job)})

    return _serialize_job(job)


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    """Estado y resultado de un Job del histórico de la sesión activa —
    404 si no hay sesión activa o si `job_id` no existe en ese histórico."""
    session = get_current_session()
    if session is None:
        raise HTTPException(
            status_code=404, detail="No hay ninguna sesión de desarrollo activa."
        )

    job = _find_job_by_id(session, job_id)
    if job is None:
        raise HTTPException(
            status_code=404, detail=f"No existe ningún Job con id '{job_id}'."
        )

    return _serialize_job(job)


@router.get("/jobs")
def get_jobs() -> list[dict]:
    """Histórico de Jobs de la sesión activa — mismo origen de datos que
    consulta la pantalla Jobs de la TUI (`list_jobs_for_session`,
    T-FB002-US03-03), no duplicado. 404 si no hay sesión activa."""
    session = get_current_session()
    if session is None:
        raise HTTPException(
            status_code=404, detail="No hay ninguna sesión de desarrollo activa."
        )

    return [_serialize_job(job) for job in list_jobs_for_session(session.id)]


_CANCEL_CONFIRMATION_TIMEOUT_SECONDS = 5.0
_CANCEL_CONFIRMATION_POLL_INTERVAL_SECONDS = 0.05


@router.post("/jobs/{job_id}/cancel")
def post_job_cancel(job_id: str) -> dict:
    """Cancela el Job `job_id` en curso (T-FB016-US01-15, expone
    `request_cancellation`, T-FB008-US05-01): localiza el Job en el
    histórico de la sesión activa (404 si no existe o no pertenece a
    ella), señaliza su cancelación (`threading.Event` por Job,
    `job_cancellation_registry`) y devuelve el estado ya actualizado.

    Esta petición corre en un hilo del threadpool DISTINTO al de la
    petición `POST /jobs` original que despachó el Job (FastAPI atiende
    cada endpoint síncrono en su propio hilo) — es precisamente esa
    concurrencia entre hilos la que hace útil este endpoint: `dispatch_job`
    (bloqueado dentro de esa otra petición, en `_wait_for_report`) detecta
    la señal en su siguiente ciclo de polling y transiciona el Job a
    `cancelled` desde SU PROPIO hilo (nunca este, evita que dos hilos
    escriban `job.status` a la vez). Señalizar no es instantáneo desde el
    punto de vista de este endpoint: `_wait_for_report` solo comprueba el
    evento una vez por `poll_interval_seconds` del despacho en curso, así
    que tras señalizar se espera (mismo patrón de polling breve, acotado a
    `_CANCEL_CONFIRMATION_TIMEOUT_SECONDS`) a que `job.status` dependa de
    esa transición real antes de responder — para devolver de verdad "el
    estado actualizado" (criterio de aceptación de la Task), no una
    fotografía tomada antes de que el otro hilo la aplique.

    400 explícito (mensaje ya construido por el dominio, sin reinventarlo
    aquí) si el Job no está `running` — ya terminó o nunca se despachó."""
    session = get_current_session()
    if session is None:
        raise HTTPException(
            status_code=404, detail="No hay ninguna sesión de desarrollo activa."
        )

    job = _find_job_by_id(session, job_id)
    if job is None:
        raise HTTPException(
            status_code=404, detail=f"No existe ningún Job con id '{job_id}'."
        )

    try:
        request_cancellation(job)
    except JobCancellationRejectedError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    deadline = time.monotonic() + _CANCEL_CONFIRMATION_TIMEOUT_SECONDS
    while job.status == "running" and time.monotonic() < deadline:
        time.sleep(_CANCEL_CONFIRMATION_POLL_INTERVAL_SECONDS)

    return _serialize_job(job)


@router.post("/plans", status_code=201)
def post_plans(body: CreatePlanRequest) -> dict:
    """Solicita al Arquitecto un plan para `goal` (identificador de User
    Story), reutilizando `build_job_plan_for_story` (T-FB008-US04-01) sin
    reimplementar la heurística de desglose. No despacha ningún Job
    todavía — el plan se presenta en estado `proposed`, tal como ya
    garantiza el propio dominio (criterio de aceptación explícito de
    US-FB008-04, reconfirmado aquí).

    US-FB008-04 ya existe en este momento de la implementación de
    Factory Brain, así que este endpoint no devuelve nunca 501 en la
    práctica — el fallback explícito que pedía la Descripción de esta
    Task ("Dispatcher-crítico todavía no implementado") solo aplicaría si
    `build_job_plan_for_story` no estuviera disponible para importar, lo
    cual haría fallar el arranque de la app entera antes de llegar aquí,
    no este endpoint en particular. No se introduce un `try/except
    ImportError` especulativo para un escenario que no puede darse ya
    con el import fijo de arriba."""
    plan = build_job_plan_for_story(body.goal)
    plan_id = register_plan(plan)

    progress = get_plan_progress(plan)
    plans_hub.publish({"event": "plan_progress", "plan_id": plan_id, **progress})

    return {"plan_id": plan_id, **progress}


@router.get("/plans")
def get_plans() -> list[dict]:
    """Lista todos los planes registrados en el proceso (T-FB016-US01-14):
    corrige la asimetría real con `GET /jobs` — antes de esta Task solo
    existía `GET /plans/{plan_id}` (uno concreto, si ya se conocía su id).
    Sin esto, un cliente que pierde la referencia al `plan_id` actual (la
    app cerrada y matada en segundo plano, o la TUI que nunca lo tuvo en
    primer lugar — ver T-FB016-US01-18) no tenía forma de descubrir qué
    plan seguía `proposed`/`approved` sin pedirle uno nuevo al Arquitecto,
    arriesgando duplicar trabajo.

    Ningún plan se elimina de la lista tras decidirse — un plan ya
    `approved`/`rejected`/`blocked`/`cancelled` sigue apareciendo con su
    estado final (criterio de aceptación explícito), mismo criterio que
    `GET /jobs` ya aplica a su histórico."""
    return [
        {"plan_id": plan_id, **get_plan_progress(plan)} for plan_id, plan in list_plans()
    ]


def _get_plan_or_404(plan_id: str):
    plan = get_plan(plan_id)
    if plan is None:
        raise HTTPException(
            status_code=404, detail=f"No existe ningún plan con id '{plan_id}'."
        )
    return plan


def _settle_plan_decision(plan_id: str, plan, approved: bool) -> tuple[dict, bool]:
    """Sección crítica de la decisión (T-FB016-US01-08): protegida por el
    `Lock` de `plan_id` para que "leer `plan.status` + transicionar" sea
    atómico frente a dos peticiones casi simultáneas en hilos distintos
    (ver docstring de módulo de `brain.api.plan_registry`).

    Devuelve `(progress_dict, did_transition_now)`:
    - Si `plan.status` ya no es `proposed` (ya fijado por una petición
      anterior, incluida otra que "ganó la carrera" hace microsegundos),
      NO se reintenta transicionar — se devuelve el estado ya fijado tal
      cual, `did_transition_now=False`. Nunca un error genérico ni una
      transición silenciosa (criterio de aceptación explícito): el propio
      payload de respuesta refleja el estado real, con
      `already_decided=True` explícito para que el cliente distinga este
      caso de una decisión que él mismo acaba de provocar.
    - Si sigue `proposed`, se transiciona dentro del lock y se devuelve
      `did_transition_now=True` — la única petición que puede haber
      ganado, de entre cualquier número de llamadas concurrentes."""
    lock = get_plan_lock(plan_id)
    with lock:
        if plan.status != "proposed":
            progress = get_plan_progress(plan)
            return {"plan_id": plan_id, "already_decided": True, **progress}, False

        present_plan_for_approval(plan, approved=approved)
        progress = get_plan_progress(plan)
        return {"plan_id": plan_id, "already_decided": False, **progress}, True


@router.post("/plans/{plan_id}/approve")
def post_plan_approve(plan_id: str) -> dict:
    """Aprueba el plan completo (`present_plan_for_approval` +
    `dispatch_plan`, T-FB008-US04-02/03) — sin aprobación por paso
    individual, mismo criterio que la TUI tendría si expusiera esto.
    Bloqueante: despacha el plan entero antes de responder.

    ## Progreso por paso en `WS /ws/plans` (T-FB017-US04-03)

    Antes de esta Task, solo se publicaba el progreso antes y después de
    la secuencia COMPLETA — nunca durante, pese a que el docstring previo
    de este mismo endpoint afirmaba lo contrario (verificado leyendo el
    código real). `dispatch_plan` (dominio) ahora acepta un callback
    opcional `on_step_status_changed`, invocado cada vez que el estado de
    un paso cambia — aquí se pasa un lambda que publica el progreso
    completo (`get_plan_progress`) en `plans_hub`, mismo formato de evento
    que ya usan el resto de publicaciones de este endpoint. El dominio no
    conoce `plans_hub` en ningún momento (mismo principio ya fijado en
    `brain/api/events.py`) — solo invoca una función genérica.

    Idempotente (T-FB016-US01-08): dos llamadas casi simultáneas para el
    mismo `plan_id` producen un único despacho real — la sección crítica
    de `_settle_plan_decision` garantiza que solo una de ellas transiciona
    `proposed -> approved` y por tanto solo una llega a invocar
    `dispatch_plan`; el resto recibe el estado ya fijado
    (`already_decided=True`) sin re-despachar nada."""
    session = get_current_session()
    if session is None:
        raise HTTPException(
            status_code=404, detail="No hay ninguna sesión de desarrollo activa."
        )

    plan = _get_plan_or_404(plan_id)

    try:
        result, did_transition_now = _settle_plan_decision(plan_id, plan, approved=True)
    except InvalidJobPlanTransitionError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    plans_hub.publish({"event": "plan_progress", **result})

    if not did_transition_now:
        return result

    def _publish_step_progress(dispatched_plan) -> None:
        plans_hub.publish(
            {
                "event": "plan_progress",
                "plan_id": plan_id,
                "already_decided": False,
                **get_plan_progress(dispatched_plan),
            }
        )

    dispatch_plan(
        plan, session, socket_name=_SOCKET_NAME, on_step_status_changed=_publish_step_progress
    )

    progress = get_plan_progress(plan)
    result = {"plan_id": plan_id, "already_decided": False, **progress}
    plans_hub.publish({"event": "plan_progress", **result})

    return result


@router.post("/plans/{plan_id}/reject")
def post_plan_reject(plan_id: str) -> dict:
    """Rechaza el plan completo (`present_plan_for_approval`,
    T-FB008-US04-02) — no se despacha ningún Job de este plan.

    Idempotente (T-FB016-US01-08), mismo mecanismo que `post_plan_approve`:
    una llamada tras el plan ya `approved`/`rejected` no cambia el estado
    ya fijado, devuelve ese estado con `already_decided=True`."""
    plan = _get_plan_or_404(plan_id)

    try:
        result, _did_transition_now = _settle_plan_decision(plan_id, plan, approved=False)
    except InvalidJobPlanTransitionError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    plans_hub.publish({"event": "plan_progress", **result})

    return result


@router.get("/plans/{plan_id}")
def get_plan_endpoint(plan_id: str) -> dict:
    """Consulta el progreso de un plan ya construido — no forma parte del
    listado explícito de la Descripción de esta Task, pero es necesario
    para que un cliente pueda releer el estado de un `plan_id` ya emitido
    sin depender solo del WebSocket (misma simetría que `GET
    /jobs/{job_id}` frente a `WS /ws/jobs`)."""
    plan = _get_plan_or_404(plan_id)
    return {"plan_id": plan_id, **get_plan_progress(plan)}


@router.post("/plans/{plan_id}/cancel")
def post_plan_cancel(plan_id: str) -> dict:
    """Cancela el plan `plan_id` en curso (T-FB016-US01-17, expone
    `job_plan_cancellation.request_cancellation`, T-FB008-US08-01):
    localiza el plan (404 si no existe), invoca la cancelación de dominio
    y devuelve el progreso ya actualizado (incluye qué pasos llegaron a
    `completed` antes de cancelar, vía `get_plan_progress`, sin cambios).

    Mismo patrón que `post_plan_reject`: no comprueba sesión activa — el
    mecanismo de dominio (`request_cancellation`) no la necesita (opera
    solo sobre el objeto `plan`), y los planes no se indexan por sesión en
    ningún registro (a diferencia de `Job`, ver `job_history_registry`) —
    `plan_registry` es un registro global por `plan_id`, no por sesión.

    400 explícito (mensaje ya construido por el dominio) si el plan no
    está `approved`, o si no le quedan pasos pendientes de despachar.

    ## Por qué SÍ hace falta esperar confirmación tras señalizar (decidido
    ## con evidencia, no por simetría automática con T-FB016-US01-15)

    `request_cancellation` (`job_plan_cancellation.py`) ya resuelve
    INTERNAMENTE, antes de devolver el control, las dos ventanas de
    carrera entre "señalizar" y "hay un Job real que cancelar" (Job del
    paso aún no registrado como activo del plan, o registrado pero aún no
    `running`) — mediante su propio polling acotado
    (`_CANCELLATION_RETRY_TIMEOUT_SECONDS`). Pero esa función retorna en
    cuanto el `Event` del Job individual queda señalizado con éxito
    (`job_cancellation.request_cancellation` no lanza) — NO espera a que
    `_wait_for_report`, en el hilo de `dispatch_plan`/`dispatch_job`,
    detecte esa señal en su siguiente ciclo de polling y aplique de
    verdad `transition_job_plan(plan, "cancelled")`. Esa ventana final
    persiste exactamente igual que en `POST /jobs/{job_id}/cancel`
    (verificado con un test que reproduce sin ella la misma falla que
    motivó el fix allí: `plan.status` seguía `approved` justo después de
    señalizar) — mismo fix: polling breve acotado tras invocar el
    dominio, hasta que `plan.status` deje de ser `approved`."""
    plan = _get_plan_or_404(plan_id)

    try:
        request_plan_cancellation(plan)
    except JobPlanCancellationRejectedError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    deadline = time.monotonic() + _CANCEL_CONFIRMATION_TIMEOUT_SECONDS
    while plan.status == "approved" and time.monotonic() < deadline:
        time.sleep(_CANCEL_CONFIRMATION_POLL_INTERVAL_SECONDS)

    progress = get_plan_progress(plan)
    result = {"plan_id": plan_id, **progress}
    plans_hub.publish({"event": "plan_progress", **result})

    return result


@router.get("/backlog")
def get_backlog() -> dict:
    """Informe estructurado del `02-backlog/` del proyecto activo
    (T-FB020-US01-01): envoltura fina de `build_backlog_report`
    (T-FB018-US02-02) — mismo dict que ya usa `POST
    /scripts/backlog_status/run` en su campo `data`, expuesto ahora
    también como lectura directa (`GET`, sin ejecutar nada). 404 explícito
    si no hay proyecto activo, mismo criterio que `GET /scripts`."""
    project = get_active_project(state_dir=_STATE_DIR)
    if project is None:
        raise HTTPException(status_code=404, detail="No hay ningún proyecto activo.")

    backlog_path = Path(project.path) / "02-backlog"
    return build_backlog_report(backlog_path)


def _active_project_or_404():
    project = get_active_project(state_dir=_STATE_DIR)
    if project is None:
        raise HTTPException(status_code=404, detail="No hay ningún proyecto activo.")
    return project


def _load_active_backlog_graph(project):
    backlog_path = Path(project.path) / "02-backlog"
    return load_backlog(backlog_path)


@router.get("/backlog/queue")
def get_dispatch_queue() -> dict:
    """Estado completo de la cola de despacho (T-FB008-US10-01): qué
    Tasks están `queued`/`dispatched`/`failed`, en qué orden por
    prioridad (`Crítica` > `Alta` > `Media` > `Baja`/sin prioridad,
    reutilizando `priority_rank` de `brain.backlog.report` — mismo
    criterio de orden que el resto del backlog, sin un segundo cálculo
    paralelo). Base del criterio 6 de `US-FB008-10` ("consultable desde
    la pantalla Backlog sin necesitar la pantalla Plan ni Agentes").

    Declarada ANTES de `GET /backlog/{item_id}` a propósito: FastAPI
    resuelve las rutas en orden de declaración, y `/backlog/queue`
    coincidiría con el parámetro `item_id="queue"` de esa ruta genérica
    si se declarara después — mismo motivo por el que
    `/backlog/{story_id}/launch-development` (con segmento fijo tras el
    parámetro) no tiene este problema, pero un segmento fijo SIN
    parámetro adicional antes sí lo tiene."""
    project = _active_project_or_404()
    entries = get_queue(project.path, project.name)

    # Solo las `queued` se ordenan por prioridad (es el orden que le
    # importa al Dispatcher, `T-FB008-US10-02`, para decidir cuál sacar
    # primero) — las `dispatched`/`failed` ya no compiten por orden de
    # despacho, se listan en su propio orden de inserción (histórico).
    queued = sorted(
        (e for e in entries if e.status == STATUS_QUEUED),
        key=lambda e: (priority_rank(e.priority), e.task_id),
    )
    dispatched = [e for e in entries if e.status != STATUS_QUEUED]

    def _serialize(entry) -> dict:
        return {
            "task_id": entry.task_id,
            "us_id": entry.us_id,
            "priority": entry.priority,
            "status": entry.status,
            "enqueued_at": entry.enqueued_at,
            "agent_id": entry.agent_id,
            "agent_name": entry.agent_name,
            "result": entry.result,
            "dispatched_at": entry.dispatched_at,
        }

    return {
        "queued": [_serialize(e) for e in queued],
        "dispatched": [_serialize(e) for e in dispatched if e.status != "failed"],
        "failed": [_serialize(e) for e in dispatched if e.status == "failed"],
    }


def _find_task_item(graph, task_id: str):
    item = graph.items.get(task_id)
    if item is not None and item.kind == ITEM_KIND_TASK:
        return item
    return None


@router.post("/backlog/{task_id}/enqueue", status_code=201)
def post_enqueue_task(task_id: str) -> dict:
    """Marca la Task `task_id` (debe estar en estado `TODO`) como
    encolada para desarrollo (T-FB008-US10-01, criterio de aceptación 1
    de `US-FB008-10`) — sin pasar por el flujo de Plan/aprobación.

    404 si `task_id` no existe como Task en el backlog del proyecto
    activo; 400 si existe pero no está en `TODO` (no tiene sentido
    encolar algo ya `DONE`/`IN_PROGRESS`/`REVIEW`); 409 si ya estaba
    encolada (evita duplicados silenciosos ante un doble clic)."""
    project = _active_project_or_404()
    graph = _load_active_backlog_graph(project)

    item = _find_task_item(graph, task_id)
    if item is None:
        raise HTTPException(
            status_code=404,
            detail=f"No existe ninguna Task con id '{task_id}' en el backlog activo.",
        )
    if item.state != "TODO":
        raise HTTPException(
            status_code=400,
            detail=f"La Task '{task_id}' no está en estado 'TODO' (estado real: '{item.state}') — no se puede encolar.",
        )

    try:
        entry = enqueue_task(
            project.path,
            project.name,
            task_id=item.id,
            us_id=item.user_story,
            priority=item.priority,
        )
    except TaskAlreadyQueuedError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error

    return {
        "task_id": entry.task_id,
        "us_id": entry.us_id,
        "priority": entry.priority,
        "status": entry.status,
        "enqueued_at": entry.enqueued_at,
    }


@router.post("/backlog/{us_id}/enqueue-all", status_code=201)
def post_enqueue_all_tasks(us_id: str) -> dict:
    """Encola de una sola llamada todas las Tasks `TODO` de la User
    Story `us_id` (T-FB008-US10-01, criterio de aceptación 2 de
    `US-FB008-10`) — equivalente funcional al lote que hoy ofrece un
    Plan, pero sin el paso de aprobación explícita.

    Filtra por el campo `item.user_story` real de cada Task (el valor
    del `user_story:` del frontmatter YAML, T-FB008-US04-05), NUNCA por
    prefijo del propio `task_id` — confirmado en `T-FB036-US01-04` que
    esa convención de nombre de fichero no es universal en el backlog
    real (hay Tasks reales cuyo id no coincide con su `user_story`
    verdadero).

    404 si `us_id` no existe como User Story en el backlog activo.
    Idempotente ante Tasks ya encoladas: las salta en vez de fallar toda
    la llamada por una ya en cola (un `enqueue-all` repetido sobre una
    Story parcialmente encolada no debe romperse)."""
    project = _active_project_or_404()
    graph = _load_active_backlog_graph(project)

    us_item = graph.items.get(us_id)
    if us_item is None or us_item.kind != ITEM_KIND_USER_STORY:
        raise HTTPException(
            status_code=404,
            detail=f"No existe ninguna User Story con id '{us_id}' en el backlog activo.",
        )

    pending_tasks = [
        item
        for item in graph.items.values()
        if item.kind == ITEM_KIND_TASK and item.user_story == us_id and item.state == "TODO"
    ]

    enqueued = []
    skipped_already_queued = []
    for item in pending_tasks:
        try:
            entry = enqueue_task(
                project.path,
                project.name,
                task_id=item.id,
                us_id=item.user_story,
                priority=item.priority,
            )
            enqueued.append(entry.task_id)
        except TaskAlreadyQueuedError:
            skipped_already_queued.append(item.id)

    return {
        "us_id": us_id,
        "enqueued": enqueued,
        "skipped_already_queued": skipped_already_queued,
    }


@router.delete("/backlog/{task_id}/enqueue")
def delete_dequeue_task(task_id: str) -> dict:
    """Retira `task_id` de la cola antes de que el Dispatcher
    (`T-FB008-US10-02`) la haya tomado (T-FB008-US10-01, criterio de
    aceptación 7 de `US-FB008-10`) — sin ningún efecto secundario, mismo
    criterio de reversibilidad que "Cancelar" en el flujo de Plan
    existente.

    404 si `task_id` nunca se encoló (nada que desencolar); 409 si la
    entrada existe pero ya no está `queued` (el Dispatcher ya la tomó —
    desencolar algo ya despachado/fallido no tiene efecto real, se
    señala explícito en vez de responder 200 en silencio)."""
    project = _active_project_or_404()
    try:
        dequeue_task(project.path, project.name, task_id)
    except TaskNotQueuedError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except TaskAlreadyDispatchedError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error

    return {"task_id": task_id, "dequeued": True}


def _resolve_editable_item(graph, item_id: str):
    """Resuelve `item_id` contra el grafo para los endpoints de edición
    en línea de `US-FB036-08`. Devuelve 404 si no existe como User
    Story/Task, y 400 explícito si es una Epic — `priority`/`state` de
    Epic quedan fuera por completo (`priority` no existe en su esquema,
    `state` cambia solo por promoción automática, nunca desde aquí;
    T-FB036-US08-01, criterio de aceptación 5)."""
    if is_epic_item_id(item_id):
        raise HTTPException(
            status_code=400,
            detail=f"'{item_id}' es una Epic — su prioridad/estado no se edita desde aquí (el estado de Epic solo cambia por promoción automática).",
        )
    item = graph.items.get(item_id)
    if item is None:
        raise HTTPException(
            status_code=404,
            detail=f"No existe ninguna User Story ni Task con id '{item_id}' en el backlog activo.",
        )
    return item


@router.put("/backlog/{item_id}/priority")
def put_backlog_item_priority(item_id: str, body: dict) -> dict:
    """Cambia el campo `priority` del fichero real de una User Story/Task
    (T-FB036-US08-01) desde su línea de título en el listado raíz, sin
    desplegar el detalle — reutiliza `brain.backlog.edit.set_item_priority`,
    que valida con el validador determinista antes de persistir.

    Body: `{"priority": "Alta" | "Media" | "Baja" | "Crítica" | null}`.
    400 si el valor no pertenece al conjunto cerrado, o si el contenido
    resultante no pasa el validador — `detail` verbatim del validador en
    este último caso (criterio de aceptación 3 de la Task)."""
    project = _active_project_or_404()
    graph = _load_active_backlog_graph(project)
    item = _resolve_editable_item(graph, item_id)

    new_priority = body.get("priority")
    try:
        set_item_priority(item.path, new_priority)
    except InvalidFieldValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except BacklogValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    return {"item_id": item_id, "priority": new_priority}


@router.put("/backlog/{item_id}/state")
def put_backlog_item_state(item_id: str, body: dict) -> dict:
    """Cambia el campo `state` del fichero real de una User Story/Task
    (T-FB036-US08-01) desde su línea de título, sin desplegar el
    detalle — reutiliza `brain.backlog.edit.set_item_state`, que valida
    con el validador determinista antes de persistir.

    Si el nuevo estado es `DONE` y el item es una User Story, dispara la
    promoción automática ya existente (`promote_backlog`,
    `promote_states.py`) por si esta Story deja a su Epic con todos los
    hijos `DONE` — criterio de aceptación 2 de `US-FB036-08` y de la
    propia Task, reutilizando el mecanismo sin duplicarlo.

    Body: `{"state": "TODO" | "IN_PROGRESS" | "REVIEW" | "DONE"}`. 400 si
    el valor no pertenece al conjunto cerrado, o si el contenido
    resultante no pasa el validador — `detail` verbatim en este caso."""
    project = _active_project_or_404()
    backlog_path = Path(project.path) / "02-backlog"
    graph = load_backlog(backlog_path)
    item = _resolve_editable_item(graph, item_id)

    new_state = body.get("state")
    try:
        set_item_state(item.path, new_state)
    except InvalidFieldValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except BacklogValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    promoted_epics: list[str] = []
    if new_state == "DONE" and item.kind == ITEM_KIND_USER_STORY:
        promotion = promote_backlog(backlog_path)
        promoted_epics = promotion.promoted_epics

    return {"item_id": item_id, "state": new_state, "promoted_epics": promoted_epics}


@router.post("/backlog/epic", status_code=201)
def post_backlog_epic(body: CreateEpicRequest) -> dict:
    """Crea una Epic nueva desde cero (T-FB036-US02-01, US-FB036-02):
    escribe `02-backlog/epics/{id}-{slug(title)}.md` a partir de campos
    sueltos, pasando por el mismo validador determinista que usa el
    Arquitecto (`brain.backlog.create.create_epic`) antes de persistir —
    precondición de backend para el formulario "+ Nueva Epic"
    (`T-FB036-US02-04`, todavía sin implementar).

    Declarada ANTES de `GET /backlog/{item_id}` a propósito (mismo
    criterio que `POST /backlog/{task_id}/enqueue`/`PUT /backlog/{item_id}/priority`
    más arriba): `epic` como segmento fijo tras `/backlog/`, nunca
    capturado por la ruta con `{item_id}` variable.

    400 si `id` no tiene formato `FB-\\d{3,}` (validado en servidor,
    nunca solo en cliente — criterio de aceptación explícito) o si el
    contenido generado no pasa el validador determinista (`detail`
    verbatim). 409 si ya existe un fichero `{id}*.md` en `epics/` — no
    sobreescribe. 201 con `{id, title, path}` del fichero creado, para
    que el frontend pueda expandir la Epic recién creada sin un fetch
    adicional."""
    project = _active_project_or_404()
    backlog_path = Path(project.path) / "02-backlog"

    try:
        path = create_epic(backlog_path, body.id, body.title, body.objetivo, body.fase)
    except InvalidEpicIdError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except EpicAlreadyExistsError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except CreateBacklogValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    return {"id": body.id, "title": body.title, "path": str(path)}


@router.post("/backlog/epic/{epic_id}/us", status_code=201)
def post_backlog_epic_user_story(epic_id: str, body: CreateUserStoryRequest) -> dict:
    """Crea una User Story nueva dentro de la Epic `epic_id`
    (T-FB036-US02-02, US-FB036-02): escribe
    `02-backlog/user-stories/{id}-{slug(title)}.md` a partir de campos
    sueltos, pasando por el mismo validador determinista que usa el
    Arquitecto (`brain.backlog.create.create_user_story`) antes de
    persistir — precondición de backend para el formulario "+ Nueva User
    Story" (`T-FB036-US02-05`, todavía sin implementar).

    `epic_id` viene SIEMPRE de la URL, nunca de un campo del body — no
    existe ningún `epic_id` en `CreateUserStoryRequest` (criterio de
    aceptación explícito: "el `epic_id` del fichero creado coincide
    siempre con el de la URL, nunca con un valor distinto que el cliente
    pudiera enviar en el body").

    404 si `epic_id` no tiene ningún fichero de Epic real en `epics/`
    (mismo criterio de glob y mismo mensaje que ya usa
    `POST /backlog/epic/{epic_id}/propose-stories` más abajo — no tiene
    sentido crear una US bajo una Epic inexistente). 400 si `id` no tiene
    formato `US-FBNNN-nn`, si `priority` no pertenece al conjunto cerrado
    (ni es `null`), o si el contenido generado no pasa el validador
    determinista (`detail` verbatim en los tres casos). 409 si ya existe
    un fichero `{id}*.md` en `user-stories/` — no sobreescribe. 201 con
    `{id, title, epic_id, path}` del fichero creado."""
    project = _active_project_or_404()
    backlog_path = Path(project.path) / "02-backlog"

    try:
        path = create_user_story(
            backlog_path,
            epic_id,
            body.id,
            body.title,
            body.objetivo,
            body.criterios_aceptacion,
            body.priority,
        )
    except EpicNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except InvalidUserStoryIdError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except CreateInvalidPriorityError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except UserStoryAlreadyExistsError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except CreateBacklogValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    return {"id": body.id, "title": body.title, "epic_id": epic_id, "path": str(path)}


@router.post("/backlog/us/{us_id}/task", status_code=201)
def post_backlog_us_task(us_id: str, body: CreateTaskRequest) -> dict:
    """Crea una Task nueva dentro de la User Story `us_id`
    (T-FB036-US02-03, US-FB036-02): escribe
    `02-backlog/tasks/{id}-{slug(title)}.md` a partir de campos sueltos,
    pasando por el mismo validador determinista que usa el Arquitecto
    (`brain.backlog.create.create_task`) antes de persistir —
    precondición de backend para el formulario "+ Nueva Task"
    (`T-FB036-US02-06`, todavía sin implementar).

    `us_id` viene SIEMPRE de la URL, nunca de un campo del body — no
    existe ningún `us_id` en `CreateTaskRequest`, mismo criterio ya
    aplicado a `epic_id` en `POST /backlog/epic/{epic_id}/us`.
    `epic_id` NUNCA se pide al cliente en absoluto (ni en URL ni en
    body): se resuelve leyendo el frontmatter de la propia US
    encontrada (`create_task`), evitando que una Task declare una Epic
    distinta a la de su US real. Caso borde explícito (ya documentado en
    la especificación UX, sección "Casos borde"): si la US es huérfana
    (sin `epic` en su frontmatter), la Task se crea igualmente con
    `epic_id: null` en la respuesta — no bloquea la creación.

    404 si `us_id` no tiene ningún fichero de User Story real en
    `user-stories/`. 400 si `id` no tiene formato `T-FBNNN-USnn-mm`, si
    `priority` no pertenece al conjunto cerrado (ni es `null`), o si el
    contenido generado (incluidas `dependencies`, si se envían) no pasa
    el validador determinista (`detail` verbatim en los tres casos). 409
    si ya existe un fichero `{id}*.md` en `tasks/` — no sobreescribe.
    201 con `{id, title, us_id, epic_id, path}` del fichero creado."""
    project = _active_project_or_404()
    backlog_path = Path(project.path) / "02-backlog"

    try:
        path, epic_id = create_task(
            backlog_path,
            us_id,
            body.id,
            body.title,
            body.objetivo,
            body.descripcion,
            body.criterios_aceptacion,
            body.priority,
            body.dependencies,
        )
    except UserStoryNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except InvalidTaskIdError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except CreateInvalidPriorityError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except TaskAlreadyExistsError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except CreateBacklogValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    return {
        "id": body.id,
        "title": body.title,
        "us_id": us_id,
        "epic_id": epic_id,
        "path": str(path),
    }


@router.get("/backlog/{item_id}")
def get_backlog_item(item_id: str) -> dict:
    """Detalle de una Epic/User Story/Task concreta del `02-backlog/` del
    proyecto activo (T-FB020-US01-01), sin reimplementar el parseo de
    Markdown: reusa `load_backlog` (T-FB018-US02-01) para el grafo ya
    calculado y `brain.backlog.detail` para extraer las secciones
    convencionales (objetivo/historia, criterios de aceptación) del
    fichero de `item_id` — parseo de texto simple por encabezados `##`,
    igual de determinista que el resto del parser.

    Un `item_id` con forma `FB-xxx` (p. ej. `FB-020`) se resuelve como
    Epic (no es un nodo de `BacklogGraph` — vive en
    `02-backlog/epics/`); cualquier otro se busca como Task/User Story en
    el grafo. 404 explícito con `detail` si no existe en ninguno de los
    dos casos — nunca un error genérico ni un 500 (criterio de aceptación
    explícito de la Task)."""
    project = get_active_project(state_dir=_STATE_DIR)
    if project is None:
        raise HTTPException(status_code=404, detail="No hay ningún proyecto activo.")

    backlog_path = Path(project.path) / "02-backlog"
    graph = load_backlog(backlog_path)

    if is_epic_item_id(item_id):
        detail = build_epic_detail(backlog_path, graph, item_id)
    else:
        detail = build_item_detail(graph, item_id)

    if detail is None:
        # Un `item_id` cuyo fichero existe pero no siguió la convención de
        # `## Estado`/`## Dependencias` no llega a `graph.items` (se reporta
        # en `graph.errors`, mismo criterio que `GET /backlog`) — el 404
        # sigue siendo el código correcto (el item no es consultable), pero
        # el motivo real del fallo de parseo es más útil que "no existe".
        parse_error = next(
            (error for error in graph.errors if error.item_id == item_id), None
        )
        detail_message = (
            f"El item de backlog '{item_id}' no se pudo cargar: {parse_error.reason}."
            if parse_error is not None
            else f"No existe ningún item de backlog con id '{item_id}'."
        )
        raise HTTPException(status_code=404, detail=detail_message)

    return detail


def _job_plan_builder_story_id(story_id: str) -> str:
    """Convierte el `story_id` de `GET /backlog/{item_id}` (p. ej.
    `US-FB020-01`) al formato que espera `_pending_task_files_for_story`/
    `build_job_plan_for_story` (`job_plan_builder.py`): SIN el prefijo
    `US-`, con el número de Story pegado tras `US` (`FB020-US01`) — el
    mismo prefijo literal que ya usan los nombres reales de fichero de
    Task en `02-backlog/tasks/` (`T-FB020-US01-01-...md`, NO
    `T-US-FB020-01-...md`). Verificado directamente contra el `02-backlog/`
    real de este proyecto y contra `test_job_plan_builder.py` (que
    construye sus Tasks de prueba con `story_id = "FB999-US01"`, nunca
    `"US-FB999-01"`) — sin esta conversión, `_pending_task_files_for_story`
    nunca encuentra ningún fichero real, aunque la Story sí tenga Tasks
    `TODO` (el 400 de 'sin Tasks pendientes' se dispararía siempre,
    incorrectamente).

    Delega en `task_file_story_prefix` (`job_plan_builder.py`), el mismo
    normalizador que ya usan `_pending_task_files_for_story`,
    `_mark_story_tasks_done` y `read_acceptance_criteria` (T-FB022-US13-01B):
    un único criterio de conversión `story_id` → prefijo de fichero, sin
    lógica duplicada."""
    return task_file_story_prefix(story_id)


def _build_launch_development_description(story_id: str, story_detail: dict, tasks_dir: Path) -> str:
    """`description` del Job de "lanzar desarrollo de una User Story"
    (T-FB020-US02-01): objetivo/historia real de la US (ya resuelto por
    `build_item_detail`, `GET /backlog/{item_id}`) + títulos de sus Tasks
    `TODO`, reutilizando `_pending_task_files_for_story`/`_read_task_title`
    (`brain.dispatcher.job_plan_builder`) tal cual — mismo mecanismo ya
    usado por `build_job_plan_for_story` para encontrar las Tasks
    pendientes de una Story, sin reimplementar esa búsqueda aquí."""
    lines = [f"Lanzar desarrollo de {story_id}."]
    objetivo = story_detail.get("objetivo")
    if objetivo:
        lines.append(f"\nObjetivo: {objetivo}")

    task_titles = []
    for task_path in _pending_task_files_for_story(
        _job_plan_builder_story_id(story_id), tasks_dir
    ):
        text = task_path.read_text(encoding="utf-8")
        task_titles.append(_read_task_title(text, fallback=task_path.stem))

    lines.append("\nTasks pendientes:")
    lines.extend(f"- {title}" for title in task_titles)

    return "\n".join(lines)


@router.post("/backlog/{story_id}/launch-development", status_code=201)
def post_launch_development(story_id: str, body: LaunchDevelopmentRequest) -> dict:
    """Lanza el desarrollo de la User Story `story_id` con contexto ya
    resuelto (T-FB020-US02-01): construye la `description` del Job
    concatenando el objetivo/historia real de la US (mismo contenido que
    `GET /backlog/{item_id}`, T-FB020-US01-01) y los títulos de sus Tasks
    en `TODO` (reutilizando `_pending_task_files_for_story`/
    `_read_task_title` de `job_plan_builder.py` tal cual — no un segundo
    mecanismo de búsqueda de Tasks pendientes), y despacha con el mismo
    motor ya existente (`create_and_record_job`/`dispatch_job`,
    FB-005/FB-008) — no un despachador paralelo. El Job resultante es
    indistinguible de uno creado por `POST /jobs` normal desde
    `GET /jobs` (mismo criterio de aceptación explícito): mismo
    mecanismo, sin tabla/campo propio.

    Una User Story sin ninguna Task `TODO` (todas `DONE`, o ninguna
    creada todavía) responde 400 con `detail` explícito, SIN llegar a
    invocar `create_and_record_job`/`dispatch_job` — nunca se despacha un
    Job vacío (criterio de aceptación explícito). `story_id` inexistente
    en el backlog responde 404, mismo patrón que `GET /backlog/{item_id}`.
    Un `agent_id` inválido (no pertenece a la sesión, no está `idle`, sin
    runtime registrado) reutiliza exactamente la misma validación que
    `POST /jobs` — no se duplica aquí."""
    session = get_current_session()
    if session is None:
        raise HTTPException(
            status_code=404, detail="No hay ninguna sesión de desarrollo activa."
        )

    project = get_active_project(state_dir=_STATE_DIR)
    if project is None:
        raise HTTPException(status_code=404, detail="No hay ningún proyecto activo.")

    backlog_path = Path(project.path) / "02-backlog"
    graph = load_backlog(backlog_path)

    story_detail = build_item_detail(graph, story_id)
    if story_detail is None or story_detail.get("kind") != ITEM_KIND_USER_STORY:
        raise HTTPException(
            status_code=404,
            detail=f"No existe ninguna User Story con id '{story_id}' en el backlog.",
        )

    tasks_dir = backlog_path / "tasks"
    pending_tasks = _pending_task_files_for_story(
        _job_plan_builder_story_id(story_id), tasks_dir
    )
    if not pending_tasks:
        raise HTTPException(
            status_code=400,
            detail=f"La User Story {story_id} no tiene Tasks pendientes; "
            "no se lanza un Job vacío.",
        )

    agent = _find_agent_by_id(session, body.agent_id)
    if agent is None:
        raise HTTPException(
            status_code=404, detail=f"No existe ningún agente con id '{body.agent_id}'."
        )

    runtime_instance = get_runtime_instance_for_agent(agent.id)
    if runtime_instance is None:
        raise HTTPException(
            status_code=400,
            detail=f"El agente '{agent.name}' no tiene un runtime registrado "
            "— debe estar lanzado antes de despachar un Job.",
        )

    description = _build_launch_development_description(story_id, story_detail, tasks_dir)

    try:
        job = create_and_record_job(description, agent, session)
    except JobCreationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    jobs_hub.publish({"event": "job_status", **_serialize_job(job)})

    dispatch_job(job, agent, runtime_instance, socket_name=_SOCKET_NAME)

    jobs_hub.publish({"event": "job_status", **_serialize_job(job)})

    return _serialize_job(job)


# ------------------------------------------------------------------ FB-026
# Análisis de hilos de desarrollo de una Epic (US-FB026-01 a US-FB026-04):
# construye el grafo de dependencias, calcula niveles topológicos, agrupa
# en hilos, detecta cruces, genera recomendación de reparto y persiste el
# informe en `07-informes/<Epic-id>/`.


@router.post("/backlog/epic/{epic_id}/analyze-threads")
def post_analyze_epic_threads(epic_id: str, num_agents: int = 2) -> dict:
    """Ejecuta el análisis determinista de hilos de desarrollo para una
    Epic: grafo de dependencias, niveles topológicos, agrupación en hilos
    paralelizables, detección de cruces y recomendación de reparto entre
    agentes.

    `num_agents` (query param, default 2) es el número de agentes
    disponibles para la recomendación de reparto — configurable, nunca
    fijo (corrección 2026-08-06, auditoría de cierre de Fase 1.0: el
    valor estaba hardcodeado sin posibilidad de override, contradiciendo
    el criterio de aceptación de la Epic FB-026).

    No despacha un Job al Arquitecto — el análisis es determinista (mismo
    criterio que `testear` en FB-025), ya implementado en
    `brain.backlog.dependency_graph`. El informe se persiste en
    `07-informes/<epic_id>/` con identificador único por ejecución (no se
    sobrescribe)."""
    if num_agents < 1:
        raise HTTPException(
            status_code=400,
            detail="'num_agents' debe ser al menos 1.",
        )
    project = get_active_project(state_dir=_STATE_DIR)
    if project is None:
        raise HTTPException(status_code=404, detail="No hay ningún proyecto activo.")

    backlog_path = Path(project.path) / "02-backlog"
    graph = load_backlog(backlog_path)

    if epic_id not in graph.items or not is_epic_item_id(epic_id):
        raise HTTPException(
            status_code=404,
            detail=f"No existe ninguna Epic con id '{epic_id}' en el backlog.",
        )

    try:
        analysis = analyze_epic_threads(graph, epic_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    if len(analysis.threads) == 0:
        raise HTTPException(
            status_code=400,
            detail=f"La Epic '{epic_id}' no tiene Tasks con dependencias "
                    "analizables en el backlog.",
        )

    report_path = persist_thread_analysis(analysis, num_agents=num_agents)

    markdown = format_thread_analysis_markdown(analysis, num_agents=num_agents)

    threads_data = []
    for thread in analysis.threads:
        threads_data.append({
            "id": thread.id,
            "start_level": thread.start_level,
            "task_count": len(thread.tasks),
            "tasks": [t.id for t in thread.tasks],
        })

    crosses_data = [
        {
            "from_task": c.from_task,
            "from_thread": c.from_thread,
            "to_task": c.to_task,
            "to_thread": c.to_thread,
        }
        for c in analysis.crosses
    ]

    return {
        "epic": epic_id,
        "num_tasks": sum(len(t.tasks) for t in analysis.threads),
        "num_threads": len(analysis.threads),
        "num_crosses": len(analysis.crosses),
        "num_agents": num_agents,
        "threads": threads_data,
        "crosses": crosses_data,
        "missing_refs": list(analysis.missing_refs),
        "report_path": str(report_path),
        "markdown": markdown,
    }


# ------------------------------------------------------------------ FB-022
# Pipeline Epic→User Story: carga el fichero real de Epic desde disco,
# genera propuesta de User Stories a partir de su alcance v1 y ejecuta
# el pipeline completo (validacion + autoauditoria).


@router.post("/backlog/epic/{epic_id}/propose-stories")
def post_propose_stories(epic_id: str) -> dict:
    project = get_active_project(state_dir=_STATE_DIR)
    if project is None:
        raise HTTPException(status_code=404, detail="No hay ningun proyecto activo.")

    epic_path = Path(project.path) / "02-backlog" / "epics"
    candidates = list(epic_path.glob(f"{epic_id}*.md"))
    if not candidates:
        raise HTTPException(
            status_code=404,
            detail=f"No existe ningun fichero de Epic con id '{epic_id}'.",
        )

    epic_context = load_epic_context(str(candidates[0]))
    proposal = propose_user_stories_from_epic(epic_context)

    output_dir = str(Path(project.path) / "02-backlog" / "user-stories")
    pipeline_result = run_us_pipeline(
        proposal,
        output_dir=output_dir,
        auto_approve=False,
    )

    stories_data = []
    for story in proposal.stories:
        stories_data.append({
            "id": story.id,
            "title": story.title,
            "epic_id": story.epic_id,
            "description": story.description,
            "criteria": story.criteria,
            "priority": story.priority,
        })

    return {
        "epic": epic_id,
        "num_stories": len(proposal.stories),
        "stories": stories_data,
        "notes": proposal.notes,
        "validation_valid": pipeline_result.validation.valid,
        "validation_errors": pipeline_result.validation.errors,
        "self_audit": (
            {
                "status": pipeline_result.self_audit.status,
                "justification": pipeline_result.self_audit.justification,
                "suggestions": pipeline_result.self_audit.suggestions,
            }
            if pipeline_result.self_audit
            else None
        ),
    }


@router.post("/backlog/us/{us_id}/propose-tasks")
def post_propose_tasks(us_id: str) -> dict:
    project = get_active_project(state_dir=_STATE_DIR)
    if project is None:
        raise HTTPException(status_code=404, detail="No hay ningun proyecto activo.")

    us_path = Path(project.path) / "02-backlog" / "user-stories"
    candidates = list(us_path.glob(f"{us_id}*.md"))
    if not candidates:
        raise HTTPException(
            status_code=404,
            detail=f"No existe ningun fichero de User Story con id '{us_id}'.",
        )

    us_file_path = str(candidates[0])
    review = review_user_story_for_gaps(us_file_path)

    epic_id = us_id.split("-US")[0] if "-US" in us_id else us_id.split("-")[0]

    proposal = propose_tasks_from_user_story(review, epic_id, us_file_path)

    output_dir = str(Path(project.path) / "02-backlog" / "tasks")
    pipeline_result = run_task_pipeline(
        proposal,
        output_dir=output_dir,
        auto_approve=False,
    )

    tasks_data = []
    for task in proposal.tasks:
        tasks_data.append({
            "id": task.id,
            "title": task.title,
            "epic_id": task.epic_id,
            "us_id": task.us_id,
            "objective": task.objective,
            "description": task.description,
            "criteria": task.criteria,
            "priority": task.priority,
            "dependencies": task.dependencies,
        })

    return {
        "us_id": us_id,
        "epic_id": epic_id,
        "num_tasks": len(proposal.tasks),
        "tasks": tasks_data,
        "notes": proposal.notes,
        "validation_valid": pipeline_result.validation.valid,
        "validation_errors": pipeline_result.validation.errors,
        "self_audit": (
            {
                "status": pipeline_result.self_audit.status,
                "justification": pipeline_result.self_audit.justification,
                "suggestions": pipeline_result.self_audit.suggestions,
            }
            if pipeline_result.self_audit
            else None
        ),
    }


def _serialize_script(script) -> dict:
    return {
        "id": script.id,
        "name": script.name,
        "command": script.command,
        "description": script.description,
        "origin": "particular",
    }


def _serialize_generic_script(script) -> dict:
    return {
        "id": script.id,
        "name": script.name,
        "command": None,
        "description": script.description,
        "origin": "generic",
    }


@router.get("/scripts")
def get_scripts() -> list[dict]:
    """Catálogo combinado de scripts del proyecto activo (T-FB018-US01-03):
    genéricos (`list_generic_scripts`, T-FB018-US01-01) + particulares
    (`discover_project_scripts`, T-FB001-US03-01), distinguibles por el
    cliente mediante el campo `origin` (`"generic"`/`"particular"`) — no
    fusionados en una lista indistinguible, porque `commit` necesita un
    parámetro (`message`) que los particulares no tienen.

    Un proyecto sin scripts particulares sigue mostrando el catálogo
    genérico con normalidad (criterio de aceptación explícito: "no depende
    de que existan ambos") — el catálogo genérico es fijo e igual para
    cualquier proyecto del workspace. `MalformedScriptManifestError`
    (manifiesto presente pero roto) se traduce a 400 con el mismo mensaje
    ya construido por el dominio, nunca un 500 genérico.

    `get_active_project(state_dir=_STATE_DIR)`, no el valor por defecto
    implícito — mismo bug ya corregido una vez en `GET /project`
    (T-FB016-US01-11)."""
    project = get_active_project(state_dir=_STATE_DIR)
    if project is None:
        raise HTTPException(status_code=404, detail="No hay ningún proyecto activo.")

    try:
        scripts = discover_project_scripts(project.path)
    except MalformedScriptManifestError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    generic = [_serialize_generic_script(script) for script in list_generic_scripts()]
    particular = [_serialize_script(script) for script in scripts]
    return generic + particular


@router.post("/scripts/{script_id}/run")
def post_script_run(script_id: str, request: RunScriptRequest | None = None) -> dict:
    """Ejecuta el script catalogado `script_id` del proyecto activo y
    devuelve su resultado completo (`success`, `exit_code`, `stdout`,
    `stderr`, `error_message`).

    T-FB018-US01-03: resuelve `script_id` contra AMBOS catálogos — si
    pertenece al catálogo genérico (T-FB018-US01-01) delega en
    `run_generic_script`, si no en `run_project_script` (T-FB001-US03-02).
    `message` (body opcional) es el parámetro que necesita el genérico
    `commit`; el resto de scripts se ejecutan sin parámetros adicionales.

    T-FB018-US02-04: para `backlog_status` (T-FB018-US02-02), además de la
    salida estructurada en `stdout` (el JSON del informe), la respuesta
    incluye `data` (el informe ya parseado como dict, para que el cliente
    pueda presentarlo con formato — tabla de conteo por Epic, lista de
    Tasks listas, cadena de mayor apalancamiento) y `prose` (la capa
    opcional de síntesis en prosa de T-FB018-US02-03, cuando Scribe/Ollama
    está disponible — si no, `null` y la respuesta no pierde nada). Para el
    resto de scripts ambos campos son `null`.

    A diferencia de `POST /agents`/`POST /jobs`, este endpoint nunca
    traduce un fallo a un código HTTP de error — tanto `run_generic_script`
    como `run_project_script` devuelven un `ScriptRunResult` con toda la
    información del fallo (`script_id` desconocido, script que falla,
    timeout, manifiesto roto) de forma estructurada; convertir eso a una
    `HTTPException` perdería la salida/motivo detallado que el criterio de
    aceptación exige mostrar. El único 404 real de este endpoint es la
    ausencia de sesión activa — no encontrar el script en sí es un
    resultado válido de `ScriptRunResult`, no un error de la petición
    HTTP. Mismo motivo que `get_scripts` para pasar `state_dir=_STATE_DIR`
    explícito."""
    project = get_active_project(state_dir=_STATE_DIR)
    if project is None:
        raise HTTPException(status_code=404, detail="No hay ningún proyecto activo.")

    generic_ids = {script.id for script in list_generic_scripts()}
    if script_id in generic_ids:
        params = {}
        if request is not None and request.message:
            params["message"] = request.message
        result = run_generic_script(script_id, project.path, **params)
    else:
        result = run_project_script(script_id, project.path)

    data: dict | None = None
    prose: str | None = None
    if script_id == "backlog_status" and result.success:
        # T-FB018-US02-04: el informe estructurado ya calculado (JSON en
        # stdout) se expone parseado para que el cliente lo presente con
        # formato, y la capa opcional de síntesis en prosa (T-FB018-US02-03)
        # se incluye cuando está disponible — nunca una dependencia dura: si
        # Scribe/Ollama no está disponible, `prose` es `null` y el resto de
        # la respuesta no cambia.
        try:
            data = json.loads(result.stdout)
        except (json.JSONDecodeError, TypeError):
            data = None
        if data is not None and not data.get("empty"):
            try:
                prose = resumir_estado_backlog(
                    json.dumps(data, ensure_ascii=False),
                    timeout_seconds=_BACKLOG_PROSE_TIMEOUT_SECONDS,
                )
            except ScribeUnavailableError:
                prose = None

    return {
        "success": result.success,
        "exit_code": result.exit_code,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "error_message": result.error_message,
        "data": data,
        "prose": prose,
    }
