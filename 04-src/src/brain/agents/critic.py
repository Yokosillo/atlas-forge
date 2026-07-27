from brain.agents.registry import register_agent_with_reuse
from brain.models import Agent, DevelopmentSession, Runtime
from brain.runtime import RuntimeInstance
from brain.tmux.manager import DEFAULT_SOCKET_NAME

# Prompt base de Critic (01-documentacion/04-agentes.md, "Agentes
# iniciales · Critic"): responsabilidad de revisar el trabajo de otros
# agentes. No implementa funcionalidades — eso es Developer.
CRITIC_ROLE = "critic"
CRITIC_PROMPT = (
    "Eres el agente Critic de Factory Brain. Tu responsabilidad es "
    "revisar el trabajo realizado por otros agentes: revisión técnica, "
    "búsqueda de defectos, validación funcional y arquitectónica, e "
    "identificación de riesgos. No implementas funcionalidades — esa "
    "responsabilidad corresponde al agente Developer."
)


def register_critic(
    session: DevelopmentSession,
    runtime: Runtime,
    project_path: str,
    socket_name: str = DEFAULT_SOCKET_NAME,
) -> tuple[Agent, RuntimeInstance]:
    """Registra el agente Critic en `session`, con su rol y prompt fijos.

    Reutiliza `register_agent_with_reuse` (T-FB005-US01-02): si ya existe
    un Critic asignado a `session`, se devuelve tal cual sin relanzar su
    runtime desde cero.
    """
    return register_agent_with_reuse(
        name="Critic",
        role=CRITIC_ROLE,
        prompt=CRITIC_PROMPT,
        runtime=runtime,
        session=session,
        project_path=project_path,
        socket_name=socket_name,
    )
