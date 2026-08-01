from brain.agents.registry import register_agent
from brain.core.session_lifecycle import list_agents
from brain.models import Agent, DevelopmentSession, Runtime
from brain.runtime import RuntimeInstance
from brain.tmux.manager import DEFAULT_SOCKET_NAME

# Prompt base de Developer (01-documentacion/04-agentes.md, "Agentes
# iniciales · Developer"): responsabilidad de implementar funcionalidades.
# No valida su propio trabajo — esa es responsabilidad de Critic.
#
# T-FB005-US01-03: mismo hueco real detectado en Critic, corregido aquí
# también — verificado explícitamente que existe `00-gobierno/developer.md`
# (no asumido) antes de añadir esta instrucción. Misma justificación de
# ruta relativa y condicional ("si existen") que `CRITIC_PROMPT` — ver su
# comentario para el detalle completo (proyectos sin `00-gobierno/`, como
# PROD-004-atlas-admin-portal, no deben recibir una instrucción de leer
# ficheros que no existen).
DEVELOPER_ROLE = "developer"
DEVELOPER_PROMPT = (
    "Eres el agente Developer de Factory Brain. Tu responsabilidad es "
    "implementar funcionalidades: escribir código, modificar "
    "documentación, crear tests, refactorizar y generar propuestas. "
    "No validas tu propio trabajo — esa responsabilidad corresponde al "
    "agente Critic. "
    "Antes de actuar, si existen en la raíz de este proyecto los ficheros "
    "00-gobierno/developer.md y 00-gobierno/METODOLOGIA.md, léelos "
    "primero y sigue el rol y protocolo que definen."
)


def _next_developer_name(session: DevelopmentSession) -> str:
    """Numeración incremental (`Developer-1`, `Developer-2`, ...) — esquema
    elegido, entre las alternativas consideradas (sufijo corto del
    `agent.id`, timestamp), porque es lo único legible de un vistazo en
    `GET /agents`/la lista de la TUI/app: un `agent.id` truncado
    (`Developer-a3f9`) identifica de forma única pero no dice nada sobre
    el ORDEN de lanzamiento, que es justo el dato útil para el
    desarrollador que lanzó varios Developer y quiere saber cuál es cuál
    ("el segundo que lancé", no "el que tiene id a3f9"). El número se
    calcula contando cuántos agentes con `DEVELOPER_ROLE` ya existen en
    `session` — no se persiste como contador aparte, así que si un
    Developer se detuviera y no se contara para el intervalo, el esquema
    seguiría siendo único (nunca se reutiliza el `agent.id`
    subyacente, solo el nombre visible), aunque pudiera repetir un número
    si el conteo cambia entre llamadas — aceptable para un nombre
    puramente informativo, no un identificador (`agent.id` sigue siendo el
    identificador real y único)."""
    existing_developer_count = sum(
        1
        for agent in list_agents(session)
        if isinstance(agent, Agent) and agent.role == DEVELOPER_ROLE
    )
    return f"Developer-{existing_developer_count + 1}"


def register_developer(
    session: DevelopmentSession,
    runtime: Runtime,
    project_path: str,
    socket_name: str = DEFAULT_SOCKET_NAME,
) -> tuple[Agent, RuntimeInstance]:
    """Registra un agente Developer NUEVO en `session` (T-FB005-US01-04):
    a diferencia de Critic (sigue con `register_agent_with_reuse`,
    reutilizado sin cambios), cada llamada crea un `Agent` y
    `RuntimeInstance` nuevos — nunca devuelve una instancia existente. El
    usuario necesita varios Developer trabajando en paralelo dentro de la
    misma sesión (límite real detectado en uso: antes, lanzar "Developer"
    dos veces devolvía siempre el mismo agente).

    `session_name_for` (`brain/runtime/generic.py`) ya construye el
    nombre de la sesión tmux a partir de `runtime.id` + `agent.id` (UUID
    único por instancia) — no necesita ningún cambio para evitar
    colisiones entre Developers distintos, verificado con test explícito.
    """
    name = _next_developer_name(session)
    return register_agent(
        name=name,
        role=DEVELOPER_ROLE,
        prompt=DEVELOPER_PROMPT,
        runtime=runtime,
        session=session,
        project_path=project_path,
        socket_name=socket_name,
    )
