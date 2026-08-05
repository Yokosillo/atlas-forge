from brain.agents.governance import project_governance_instruction
from brain.agents.registry import register_agent
from brain.agents.roles import RoleConfig, register_role
from brain.core.session_lifecycle import list_agents
from brain.models import Agent, DevelopmentSession, Runtime
from brain.runtime import RuntimeInstance
from brain.tmux.manager import DEFAULT_SOCKET_NAME

DEVELOPER_ROLE = "developer"
MAX_SIMULTANEOUS_DEVELOPERS = 3
DEVELOPER_PROMPT = (
    "Eres el agente Developer de Factory Brain. Tu responsabilidad es "
    "implementar funcionalidades: escribir código, modificar "
    "documentación, crear tests, refactorizar y generar propuestas. "
    "No validas tu propio trabajo — esa responsabilidad corresponde al "
    "agente Critic.\n"
    "\n"
    "Cuando termines tu trabajo, comunica el resultado de forma "
    "estructurada y sin ambigüedad, en texto plano, con estos tres campos "
    "(cada uno en su propia línea, precedido por el nombre entre guiones):\n"
    "- Resultado: 'éxito' o 'fallo'.\n"
    "- Resumen: qué implementaste, de forma concisa.\n"
    "- Siguiente paso sugerido: una única acción recomendada para quien "
    "revise tu trabajo (normalmente el Critic).\n"
    "\n"
    "Este protocolo de reporte es genérico de Factory Brain y no asume "
    "ningún formato de fichero, marcador ni carpeta propios de un proyecto "
    "concreto: si el proyecto que te emplea define su propia convención de "
    "entrega, te lo indicará explícitamente; en caso contrario, este es el "
    "formato que debes usar para que otro agente o un humano pueda leer tu "
    "reporte."
)


def build_developer_prompt(project_path: str) -> str:
    """CAPA 2 — prompt en dos capas para Developer: rol base
    (`DEVELOPER_PROMPT`) + gobierno específico del proyecto si aplica
    (`project_governance_instruction`, solo si existen
    `00-gobierno/developer.md` y `00-gobierno/METODOLOGIA.md` en
    `project_path`). La decisión de incluir la capa de gobierno se toma
    AQUÍ en Python, antes de construir el string final — el agente solo
    recibe la instrucción ya decidida."""
    return DEVELOPER_PROMPT + project_governance_instruction(
        project_path, DEVELOPER_ROLE
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

    T-FB022-US06-02: rechaza explícitamente un intento de superar
    `MAX_SIMULTANEOUS_DEVELOPERS` en `session` con feedback claro — no
    falla en silencio.
    """
    existing = sum(
        1
        for agent in list_agents(session)
        if isinstance(agent, Agent) and agent.role == DEVELOPER_ROLE
    )
    if existing >= MAX_SIMULTANEOUS_DEVELOPERS:
        raise RuntimeError(
            f"No se puede lanzar otro Developer: ya hay "
            f"{existing} Developer(s) activos en la sesión (máximo "
            f"{MAX_SIMULTANEOUS_DEVELOPERS}). Detén alguno antes de "
            f"lanzar uno nuevo."
        )

    name = _next_developer_name(session)
    return register_agent(
        name=name,
        role=DEVELOPER_ROLE,
        prompt=build_developer_prompt(project_path),
        runtime=runtime,
        session=session,
        project_path=project_path,
        socket_name=socket_name,
    )


register_role(RoleConfig(
    role=DEVELOPER_ROLE,
    governance_filename="developer.md",
    prompt=DEVELOPER_PROMPT,
    prompt_builder=build_developer_prompt,
    register_fn=register_developer,
))
