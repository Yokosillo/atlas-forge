"""Capa de gobierno específico de proyecto (T-FB005-US01-05).

El rol de cada agente (Arquitecto, Developer) se define en dos capas, AMBAS
construidas por Factory Brain antes de arrancar el proceso, nunca por
decisión del propio agente (01-documentacion/04-agentes.md, "Rol base vs.
gobierno específico de proyecto"):

1. Rol base: `ARQUITECTO_PROMPT`/`DEVELOPER_PROMPT` (`agents/arquitecto.py`,
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


def project_identity_instruction(project_path: str) -> str:
    """Instrucción explícita con el nombre y la ruta del proyecto activo
    (T-FB005-US01-07): el `cwd` real del proceso ya arranca en
    `project_path` (`create_session`), pero el TEXTO del prompt nunca
    decía qué proyecto era — solo genérico ("en la raíz de este
    proyecto"), obligando al agente a inferirlo con `pwd`/`git remote`
    por su cuenta. Mismo criterio que el resto del prompt en dos capas:
    Factory Brain construye el contexto en Python, el agente nunca lo
    infiere.

    El nombre se resuelve puntualmente aquí a partir de `project_path`
    (`Path(project_path).name`, mismo criterio que `Project.name` en
    `workspace/discovery.py` y que `session_name_for`,
    `runtime/generic.py`) en vez de exigir que `Project`/`Project.name`
    viaje explícito por toda la cadena `launch_agent` →
    `register_agent_for_role` → `build_<rol>_prompt` — evaluado y
    descartado: encadenar un parámetro nuevo por 4+ funciones intermedias
    que hoy solo pasan `project_path` (verificado antes de escribir esta
    Task) introduciría más acoplamiento que resolver el nombre aquí, en
    el único punto que realmente lo necesita, con la misma fuente de
    verdad que ya usan `FB-030`/`FB-031` para el mismo dato.

    Siempre presente, nunca condicional — a diferencia de
    `project_governance_instruction` (que sí depende de si el proyecto
    declara gobierno propio), la identidad del proyecto activo aplica
    siempre que hay un `project_path` real, así que no hay decisión
    "incluir o no" que tomar aquí."""
    project_name = Path(project_path).name if project_path else project_path
    return (
        f"\n\nEstás trabajando en el proyecto '{project_name}' "
        f"(ruta: {project_path}). Todo tu trabajo debe realizarse dentro "
        "de este proyecto."
    )


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
