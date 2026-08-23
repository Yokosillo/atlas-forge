from atlas_forge.agents.governance import (
    project_governance_instruction,
    project_identity_instruction,
)
from atlas_forge.agents.registry import register_agent_with_reuse
from atlas_forge.agents.roles import RoleConfig, register_role
from atlas_forge.models import Agent, DevelopmentSession, Runtime
from atlas_forge.runtime import RuntimeInstance
from atlas_forge.tmux.manager import DEFAULT_SOCKET_NAME

AUDITOR_OSS_ROLE = "auditor_oss"
AUDITOR_OSS_PROMPT = (
    "Eres el agente Auditor-OSS de Atlas Forge. Tu responsabilidad es "
    "evaluar Atlas Forge como lo haría un maintainer senior de "
    "proyectos open source de referencia — imagen pública del "
    "repositorio (qué percibe un desarrollador que lo descubre por "
    "primera vez en GitHub) y auditoría de UX+Producto de la interfaz "
    "web ya construida, navegando y ejerciendo su superficie real contra "
    "el backend real, no solo leyendo código. No implementas código ni "
    "diseñas flujos nuevos — esas responsabilidades corresponden a "
    "Developer y UX respectivamente.\n"
    "\n"
    "Cuando termines tu trabajo, comunica el resultado de forma "
    "estructurada y sin ambigüedad, en texto plano, con estos tres campos "
    "(cada uno en su propia línea, precedido por el nombre entre guiones):\n"
    "- Resultado: 'éxito' o 'fallo'.\n"
    "- Resumen: qué auditaste y qué encontraste, de forma concisa.\n"
    "- Siguiente paso sugerido: una única acción recomendada para quien "
    "revise tu trabajo (normalmente el Arquitecto).\n"
    "\n"
    "Este protocolo de reporte es genérico de Atlas Forge y no asume "
    "ningún formato de fichero, marcador ni carpeta propios de un proyecto "
    "concreto: si el proyecto que te emplea define su propia convención de "
    "entrega, te lo indicará explícitamente; en caso contrario, este es el "
    "formato que debes usar para que otro agente o un humano pueda leer tu "
    "reporte."
)


def build_auditor_oss_prompt(project_path: str) -> str:
    return (
        AUDITOR_OSS_PROMPT
        + project_identity_instruction(project_path)
        + project_governance_instruction(project_path, AUDITOR_OSS_ROLE)
    )


def register_auditor_oss(
    session: DevelopmentSession,
    runtime: Runtime,
    project_path: str,
    socket_name: str = DEFAULT_SOCKET_NAME,
) -> tuple[Agent, RuntimeInstance]:
    # Instancia única reutilizada, mismo criterio que UX (T-AF024-US13-01)
    # y Arquitecto: Auditor-OSS se invoca sobre encargos puntuales
    # ("lanzable puntualmente desde la web", `00-gobierno/AUDITOR-OSS.md`),
    # no en paralelo simultáneo declarado en esta Epic — sin motivo real
    # para desviarse del criterio ya aplicado a UX.
    return register_agent_with_reuse(
        name="Auditor-OSS",
        role=AUDITOR_OSS_ROLE,
        prompt=build_auditor_oss_prompt(project_path),
        runtime=runtime,
        session=session,
        project_path=project_path,
        socket_name=socket_name,
    )


register_role(RoleConfig(
    role=AUDITOR_OSS_ROLE,
    governance_filename="AUDITOR-OSS.md",
    prompt=AUDITOR_OSS_PROMPT,
    prompt_builder=build_auditor_oss_prompt,
    register_fn=register_auditor_oss,
    persistent=True,
))
