import uuid

from atlas_forge.core.session_lifecycle import assign_agent, list_agents
from atlas_forge.agents.roles import is_persistent_role
from atlas_forge.models import Agent, DevelopmentSession, Runtime
from atlas_forge.runtime import (
    RuntimeInstance,
    register_runtime_instance_for_agent,
    session_name_for,
    start_runtime,
)
from atlas_forge.tmux.manager import DEFAULT_SOCKET_NAME


# Estados en los que un agente existente SI es reutilizable (T-AF005-US01-06):
# solo se reutiliza el runtime ya vivo; un agente `stopped`/`unavailable` se
# trata como si no existiera y se lanza uno nuevo desde cero.
_REUSABLE_STATUSES = {"idle", "working"}


def register_agent(
    name: str,
    role: str,
    prompt: str,
    runtime: Runtime,
    session: DevelopmentSession,
    project_path: str,
    socket_name: str = DEFAULT_SOCKET_NAME,
) -> tuple[Agent, RuntimeInstance]:
    """Registra un agente genérico: crea el `Agent`, lanza su runtime
    (T-AF004-US01-02/US02-01) en `project_path`, y lo asigna a `session`
    (T-AF003-US01-02).

    No asume ningún rol concreto (Developer/Arquitecto/otro futuro) — recibe
    `role` y `prompt` como parámetros, tal como pide la Task. Las
    especializaciones concretas (`agents/developer.py`, `agents/arquitecto.py`)
    fijan el `role`/`prompt` y llaman a esta función.

    El agente se crea en estado `idle` y su runtime queda vivo, listo para
    recibir trabajo.

    Registra la asociación `agent.id` → `runtime_instance` en
    `agent_runtime_registry` (T-AF002-US03-00), consultable después con
    `get_runtime_instance_for_agent` — necesaria para que `dispatch_job`
    (T-AF002-US03-01) pueda recuperar el runtime de un agente ya lanzado.
    """
    agent = Agent(
        id=str(uuid.uuid4()),
        name=name,
        role=role,
        prompt=prompt,
        runtime_id=runtime.id,
        status="idle",
        # T-AF023-US03-01: el flag persistent se decide por rol, no por
        # instancia — se asigna en el punto de creación del Agent.
        persistent=is_persistent_role(role),
    )

    runtime_instance = start_runtime(runtime, agent, project_path, socket_name=socket_name)

    assign_agent(session, agent)
    register_runtime_instance_for_agent(agent.id, runtime_instance)

    return agent, runtime_instance


def register_agent_with_reuse(
    name: str,
    role: str,
    prompt: str,
    runtime: Runtime,
    session: DevelopmentSession,
    project_path: str,
    socket_name: str = DEFAULT_SOCKET_NAME,
) -> tuple[Agent, RuntimeInstance]:
    """Registra un agente de rol fijo (`role`) en `session`, reutilizando
    uno ya existente si lo hay.

    Patrón compartido por las especializaciones de rol único por sesión
    (Developer, Arquitecto, y futuros roles fijos análogos): si ya existe un
    `Agent` con ese `role` asignado a `session` y **sigue vivo**, se
    devuelve tal cual sin volver a registrar ni relanzar su runtime desde
    cero — la sesión tmux ya viva sigue siendo la misma. Si no existe, o el
    que existe está detenido (`stopped`/`unavailable`), delega en
    `register_agent` para el registro completo con un runtime nuevo.

    Extraído a partir de T-AF005-US01-02 (Developer) para no duplicar este
    bloque de búsqueda en cada especialización de rol (T-AF005-US02-01,
    Arquitecto, lo reutiliza tal cual).

    ## Solo se reutiliza un agente vivo (T-AF005-US01-06)

    Bug real corregido: antes de este cambio, la búsqueda por `role` no
    comprobaba el `status`, así que si el Arquitecto estaba `stopped` se
    devolvía tal cual (con su runtime muerto) en lugar de relanzarlo. Ahora
    solo se reutiliza si el agente encontrado está `idle` o
    `working`; si está `stopped`/`unavailable` se trata como si no
    existiera y se crea una instancia nueva con `register_agent` (mismo
    patrón que `register_developer`, que siempre crea instancia nueva).

    ## Decisión: sustituir, no convivir (documentada el 2026-08-02)

    El `Agent` anterior (`stopped`) se **sustituye** por el nuevo en
    `session.agents` (no conviven ambos con el mismo `role`) por un
    consumidor real del dominio: `dispatch.dispatch_plan._find_agent_by_role`
    (`dispatcher/job_plan_dispatch.py`) resuelve el agente destinatario de
    un paso con `next(...)` sobre `list_agents(session)` filtrando por
    `role`. Si convivieran un Arquitecto `stopped` (más antiguo, primero en la
    lista) y uno `idle` nuevo, ese `next` devolvería siempre al `stopped` y
    el despacho usaría su runtime muerto. Sustituyendo se garantiza que el
    primero (y único) agente con ese `role` es siempre el vivo, coherente
    con la premisa de rol único por sesión que motiva la reutilización
    aquí. El histórico de Jobs no depende de `session.agents` (se indexa
    por `session_id` y referencia `agent_id` como string en
    `job_history_registry`), así que sustituir no borra histórico.
    """
    existing_agent = next(
        (
            agent
            for agent in list_agents(session)
            if isinstance(agent, Agent) and agent.role == role
        ),
        None,
    )
    if existing_agent is not None and existing_agent.status in _REUSABLE_STATUSES:
        existing_session_name = session_name_for(runtime, existing_agent, project_path)
        return existing_agent, RuntimeInstance(
            runtime=runtime, session_name=existing_session_name
        )

    if existing_agent is not None:
        # Existe pero está `stopped`/`unavailable` -> se sustituye (decisión
        # documentada arriba), nunca se conviven dos agentes con el mismo rol.
        session.agents.remove(existing_agent)

    return register_agent(
        name=name,
        role=role,
        prompt=prompt,
        runtime=runtime,
        session=session,
        project_path=project_path,
        socket_name=socket_name,
    )
