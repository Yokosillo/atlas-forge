from brain.agents.governance import (
    project_governance_instruction,
    project_identity_instruction,
)
from brain.agents.registry import register_agent_with_reuse
from brain.agents.roles import RoleConfig, register_role
from brain.models import Agent, DevelopmentSession, Runtime
from brain.runtime import RuntimeInstance
from brain.tmux.manager import DEFAULT_SOCKET_NAME

UX_ROLE = "ux"
UX_PROMPT = (
    "Eres el agente UX de Factory Brain. Tu responsabilidad es diseñar, "
    "antes de que exista ninguna Task de implementación, cómo debe "
    "funcionar un flujo o pantalla nueva (o un cambio grande sobre una "
    "existente) de la interfaz Web de Factory Brain — estados, "
    "transiciones, qué ve el usuario en cada paso, qué falta por decidir. "
    "No implementas código ni validas el trabajo del Developer — esas "
    "responsabilidades corresponden a Developer y Arquitecto "
    "respectivamente.\n"
    "\n"
    "Cuando termines tu trabajo, comunica el resultado de forma "
    "estructurada y sin ambigüedad, en texto plano, con estos tres campos "
    "(cada uno en su propia línea, precedido por el nombre entre guiones):\n"
    "- Resultado: 'éxito' o 'fallo'.\n"
    "- Resumen: qué diseñaste, de forma concisa.\n"
    "- Siguiente paso sugerido: una única acción recomendada para quien "
    "revise tu trabajo (normalmente el Arquitecto).\n"
    "\n"
    "Este protocolo de reporte es genérico de Factory Brain y no asume "
    "ningún formato de fichero, marcador ni carpeta propios de un proyecto "
    "concreto: si el proyecto que te emplea define su propia convención de "
    "entrega, te lo indicará explícitamente; en caso contrario, este es el "
    "formato que debes usar para que otro agente o un humano pueda leer tu "
    "reporte."
)


def build_ux_prompt(project_path: str) -> str:
    return (
        UX_PROMPT
        + project_identity_instruction(project_path)
        + project_governance_instruction(project_path, UX_ROLE)
    )


def register_ux(
    session: DevelopmentSession,
    runtime: Runtime,
    project_path: str,
    socket_name: str = DEFAULT_SOCKET_NAME,
) -> tuple[Agent, RuntimeInstance]:
    # Instancia única reutilizada (no una nueva por invocación), mismo
    # criterio que Arquitecto: UX se invoca sobre encargos puntuales, no en
    # paralelo simultáneo declarado en esta Epic (US-FB024-13) — a
    # diferencia de Developer, que sí necesita varias instancias a la vez.
    return register_agent_with_reuse(
        name="UX",
        role=UX_ROLE,
        prompt=build_ux_prompt(project_path),
        runtime=runtime,
        session=session,
        project_path=project_path,
        socket_name=socket_name,
    )


register_role(RoleConfig(
    role=UX_ROLE,
    governance_filename="UX.md",
    prompt=UX_PROMPT,
    prompt_builder=build_ux_prompt,
    register_fn=register_ux,
))
