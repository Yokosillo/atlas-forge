from brain.agents.registry import register_agent_with_reuse
from brain.models import Agent, DevelopmentSession, Runtime
from brain.runtime import RuntimeInstance
from brain.tmux.manager import DEFAULT_SOCKET_NAME

# Prompt base de Developer (01-documentacion/04-agentes.md, "Agentes
# iniciales · Developer"): responsabilidad de implementar funcionalidades.
# No valida su propio trabajo — esa es responsabilidad de Critic.
DEVELOPER_ROLE = "developer"
DEVELOPER_PROMPT = (
    "Eres el agente Developer de Factory Brain. Tu responsabilidad es "
    "implementar funcionalidades: escribir código, modificar "
    "documentación, crear tests, refactorizar y generar propuestas. "
    "No validas tu propio trabajo — esa responsabilidad corresponde al "
    "agente Critic."
)


def register_developer(
    session: DevelopmentSession,
    runtime: Runtime,
    project_path: str,
    socket_name: str = DEFAULT_SOCKET_NAME,
) -> tuple[Agent, RuntimeInstance]:
    """Registra el agente Developer en `session`, con su rol y prompt fijos.

    Reutiliza `register_agent_with_reuse`: si ya existe un Developer
    asignado a `session` (segunda tarea dentro de la misma sesión), se
    devuelve tal cual sin relanzar su runtime desde cero.
    """
    return register_agent_with_reuse(
        name="Developer",
        role=DEVELOPER_ROLE,
        prompt=DEVELOPER_PROMPT,
        runtime=runtime,
        session=session,
        project_path=project_path,
        socket_name=socket_name,
    )
