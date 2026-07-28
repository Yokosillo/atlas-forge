import uuid

from brain.core.session_lifecycle import assign_agent, list_agents
from brain.models import Agent, DevelopmentSession, Runtime
from brain.runtime import (
    RuntimeInstance,
    register_runtime_instance_for_agent,
    session_name_for,
    start_runtime,
)
from brain.tmux.manager import DEFAULT_SOCKET_NAME


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
    (T-FB004-US01-02/US02-01) en `project_path`, y lo asigna a `session`
    (T-FB003-US01-02).

    No asume ningún rol concreto (Developer/Critic/otro futuro) — recibe
    `role` y `prompt` como parámetros, tal como pide la Task. Las
    especializaciones concretas (`agents/developer.py`, `agents/critic.py`)
    fijan el `role`/`prompt` y llaman a esta función.

    El agente se crea en estado `idle` y su runtime queda vivo, listo para
    recibir trabajo.

    Registra la asociación `agent.id` → `runtime_instance` en
    `agent_runtime_registry` (T-FB002-US03-00), consultable después con
    `get_runtime_instance_for_agent` — necesaria para que `dispatch_job`
    (T-FB002-US03-01) pueda recuperar el runtime de un agente ya lanzado.
    """
    agent = Agent(
        id=str(uuid.uuid4()),
        name=name,
        role=role,
        prompt=prompt,
        runtime_id=runtime.id,
        status="idle",
    )

    runtime_instance = start_runtime(
        runtime, agent, project_path, socket_name=socket_name
    )

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
    (Developer, Critic, y futuros roles fijos análogos): si ya existe un
    `Agent` con ese `role` asignado a `session`, se devuelve tal cual sin
    volver a registrar ni relanzar su runtime desde cero — la sesión tmux
    ya viva sigue siendo la misma. Si no existe, delega en `register_agent`
    para el registro completo.

    Extraído a partir de T-FB005-US01-02 (Developer) para no duplicar este
    bloque de búsqueda en cada especialización de rol (T-FB005-US02-01,
    Critic, lo reutiliza tal cual).
    """
    existing_agent = next(
        (
            agent
            for agent in list_agents(session)
            if isinstance(agent, Agent) and agent.role == role
        ),
        None,
    )
    if existing_agent is not None:
        existing_session_name = session_name_for(runtime, existing_agent)
        return existing_agent, RuntimeInstance(
            runtime=runtime, session_name=existing_session_name
        )

    return register_agent(
        name=name,
        role=role,
        prompt=prompt,
        runtime=runtime,
        session=session,
        project_path=project_path,
        socket_name=socket_name,
    )
