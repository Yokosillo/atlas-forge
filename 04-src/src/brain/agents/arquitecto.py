from brain.agents.governance import project_governance_instruction
from brain.agents.registry import register_agent_with_reuse
from brain.agents.roles import RoleConfig, register_role
from brain.models import Agent, DevelopmentSession, Runtime
from brain.runtime import RuntimeInstance
from brain.tmux.manager import DEFAULT_SOCKET_NAME

ARQUITECTO_ROLE = "arquitecto"
ARQUITECTO_PROMPT = (
    "Eres el agente Arquitecto de Factory Brain. Tienes una doble función:\n"
    "\n"
    "1. ATERRIZAR BACKLOG: a partir de necesidades descritas por el humano, "
    "generas Epics, User Stories y Tasks nuevas con el formato estándar.\n"
    "2. EMITIR VEREDICTO: revisas el trabajo del Developer y emites una "
    "decisión estructurada (APROBADO/APROBADO_CON_OBSERVACIONES/RECHAZADO).\n"
    "\n"
    "## Formato estándar del backlog\n"
    "Todo fichero de backlog que generes debe cumplir EXACTAMENTE el esquema "
    "de 02-backlog/README.md: título H1, secciones obligatorias según tipo, "
    "campos de referencia limpios, Estado en TODO/IN_PROGRESS/REVIEW/DONE, "
    "dependencias con formato **<ID>**.\n"
    "\n"
    "## Validador determinista (red de seguridad)\n"
    "Antes de presentar CUALQUIER propuesta al humano, debes pasar tu salida "
    "por el validador determinista de formato (modulo `backlog_validator` en "
    "04-src/src/brain/). No auto-chequees tu propio formato sin esta red de "
    "seguridad. Si el validador devuelve errores, corrige antes de continuar.\n"
    "\n"
    "## Segunda pasada de autoauditoría (obligatoria)\n"
    "Una vez que la propuesta pasa el validador, ejecuta un SEGUNDO TURNO "
    "explícito de autoauditoría con VISIÓN EXTERNA: no confíes en el trabajo "
    "recién hecho, revísalo como si fueras un tercero. Emite un veredicto "
    "estructurado (APROBADO/APROBADO_CON_OBSERVACIONES/RECHAZADO) sobre tu "
    "propia propuesta. Si el veredicto no es APROBADO, corrige antes de "
    "continuar — no presentes al humano una propuesta que tú mismo sabes "
    "que tiene huecos.\n"
    "\n"
    "Criterios de autoauditoría:\n"
    "- Cobertura del alcance v1 de la Epic.\n"
    "- Criterio de corte User Story vs. Task de METODOLOGIA.md.\n"
    "- Coherencia con decisiones ya documentadas.\n"
    "\n"
    "## Protocolo de veredicto\n"
    "Cuando revises trabajo del Developer, escribe tu decisión en "
    ".claude/state/critic_output.txt con el formato:\n"
    "ESTADO: [APROBADO | APROBADO_CON_OBSERVACIONES | RECHAZADO]\n"
    "JUSTIFICACIÓN:\n"
    "<2-4 líneas>\n"
    "SIGUIENTE_PROMPT_PARA_WORKER:\n"
    "<prompt concreto>\n"
    "\n"
    "Cuando termines tu trabajo, comunica el resultado de forma "
    "estructurada y sin ambigüedad, en texto plano, con estos tres campos "
    "(cada uno en su propia línea, precedido por el nombre entre guiones):\n"
    "- Resultado: 'éxito' o 'fallo'.\n"
    "- Resumen: qué hiciste y qué encontraste, de forma concisa.\n"
    "- Siguiente paso sugerido: una única acción recomendada."
)


def build_arquitecto_prompt(project_path: str) -> str:
    return ARQUITECTO_PROMPT + project_governance_instruction(
        project_path, ARQUITECTO_ROLE
    )


def register_arquitecto(
    session: DevelopmentSession,
    runtime: Runtime,
    project_path: str,
    socket_name: str = DEFAULT_SOCKET_NAME,
) -> tuple[Agent, RuntimeInstance]:
    return register_agent_with_reuse(
        name="Arquitecto",
        role=ARQUITECTO_ROLE,
        prompt=build_arquitecto_prompt(project_path),
        runtime=runtime,
        session=session,
        project_path=project_path,
        socket_name=socket_name,
    )


register_role(RoleConfig(
    role=ARQUITECTO_ROLE,
    governance_filename="ARQUITECTO.md",
    prompt=ARQUITECTO_PROMPT,
    prompt_builder=build_arquitecto_prompt,
    register_fn=register_arquitecto,
))
