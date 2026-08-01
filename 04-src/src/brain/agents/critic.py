from brain.agents.registry import register_agent_with_reuse
from brain.models import Agent, DevelopmentSession, Runtime
from brain.runtime import RuntimeInstance
from brain.tmux.manager import DEFAULT_SOCKET_NAME

# Prompt base de Critic (01-documentacion/04-agentes.md, "Agentes
# iniciales · Critic"): responsabilidad de revisar el trabajo de otros
# agentes. No implementa funcionalidades — eso es Developer.
#
# T-FB005-US01-03: instrucción explícita de leer los ficheros de gobierno
# del proyecto ANTES de actuar — hueco real detectado en uso (lanzar el
# Critic de PROD-004 desde la app Android: arrancó sin ninguna instrucción
# inicial, sin haber leído `CRITICO.md`/`METODOLOGIA.md`, porque nada se
# lo dijo). La instrucción es condicional ("si existen") y usa una ruta
# RELATIVA a la raíz del proyecto (`00-gobierno/...`, no una ruta
# absoluta fija a PROD-006-factory-brain): `00-gobierno/` es un patrón
# del workspace completo, no exclusivo de Factory Brain — verificado que
# también existe en `PROD-005-atlas-core/00-gobierno/` — pero NO todos los
# proyectos lo tienen (verificado: `PROD-004-atlas-admin-portal` no tiene
# `00-gobierno/` en absoluto, precisamente el caso real que motivó esta
# Task). Sin la condición "si existen", esta misma instrucción fallaría de
# forma confusa en cualquier proyecto sin gobernanza formal todavía.
CRITIC_ROLE = "critic"
CRITIC_PROMPT = (
    "Eres el agente Critic de Factory Brain. Tu responsabilidad es "
    "revisar el trabajo realizado por otros agentes: revisión técnica, "
    "búsqueda de defectos, validación funcional y arquitectónica, e "
    "identificación de riesgos. No implementas funcionalidades — esa "
    "responsabilidad corresponde al agente Developer. "
    "Antes de actuar, si existen en la raíz de este proyecto los ficheros "
    "00-gobierno/CRITICO.md y 00-gobierno/METODOLOGIA.md, léelos primero "
    "y sigue el rol y protocolo que definen."
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
