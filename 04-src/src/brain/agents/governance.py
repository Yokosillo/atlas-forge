"""Capa de gobierno específico de proyecto (T-FB005-US01-05).

El rol de cada agente (Critic, Developer) se define en dos capas, AMBAS
construidas por Factory Brain antes de arrancar el proceso, nunca por
decisión del propio agente (01-documentacion/04-agentes.md, "Rol base vs.
gobierno específico de proyecto"):

1. Rol base: `CRITIC_PROMPT`/`DEVELOPER_PROMPT` (`agents/critic.py`,
   `agents/developer.py`) — completo y autosuficiente, con protocolo de
   reporte genérico. Funciona para cualquier proyecto.
2. Gobierno específico del proyecto: este módulo. Si el proyecto activo
   declara `00-gobierno/<rol>.md` + `00-gobierno/METODOLOGIA.md`, se añade
   una instrucción EXPLÍCITA de leerlos. La decisión de incluir o no esta
   capa se toma AQUÍ, en Python, con una comprobación determinista de
   existencia de ficheros en disco — nunca como condición textual dentro
   del prompt ("si existen, léelos") que el agente tendría que
   autoevaluar.
"""

from pathlib import Path

from brain.agents.roles import get_governance_filename_for_role

GOVERNANCE_DIRNAME = "00-gobierno"
METODOLOGIA_FILENAME = "METODOLOGIA.md"


def project_has_governance(project_path: str, role: str) -> bool:
    """Determina, de forma determinista (existencia real de ficheros en
    disco, comprobada por Factory Brain), si el proyecto activo declara
    capa de gobierno específico para `role`: deben existir
    `00-gobierno/<rol>.md` Y `00-gobierno/METODOLOGIA.md` en
    `project_path`.

    La decisión de incluir o no la capa de gobierno se toma AQUÍ en
    Python, ANTES de construir el string final del prompt — nunca se
    delega en una condición textual que el agente deba autoevaluar.
    """
    governance_dir = Path(project_path) / GOVERNANCE_DIRNAME
    governance_filename = get_governance_filename_for_role(role)
    if governance_filename is None:
        return False
    role_file = governance_dir / governance_filename
    metodologia_file = governance_dir / METODOLOGIA_FILENAME
    return role_file.exists() and metodologia_file.exists()


def project_governance_instruction(project_path: str, role: str) -> str:
    """Construye la capa de gobierno específico del proyecto: instrucción
    explícita de leer `00-gobierno/<rol>.md` y
    `00-gobierno/METODOLOGIA.md`, SOLO si ambos ficheros existen
    (`project_has_governance`). Devuelve "" si no aplica, para que el
    prompt final sea exactamente el rol base (sin degradar al agente en un
    proyecto sin gobernanza formal).
    """
    if not project_has_governance(project_path, role):
        return ""
    governance_filename = get_governance_filename_for_role(role)
    if governance_filename is None:
        return ""
    return (
        "Este proyecto declara un gobierno específico propio. Antes de "
        f"actuar, lee los ficheros 00-gobierno/{governance_filename} y "
        "00-gobierno/METODOLOGIA.md en la raíz de este proyecto y sigue el "
        "rol y protocolo que definen."
    )
