"""Registro del rol Tester en el backend (T-AF022-US15-01).

El Tester verifica la funcionalidad objetiva del trabajo del Developer:
- Lee criterios de aceptación
- Analiza el código diff implementado
- Genera tests adicionales para huecos de cobertura
- Reporta pasa/falla con evidencia

Explícitamente NO opina sobre UX/producto (eso es Auditor-OSS/UX).
"""

from atlas_forge.agents.governance import (
    project_governance_instruction,
    project_identity_instruction,
)
from atlas_forge.agents.registry import register_agent_with_reuse
from atlas_forge.agents.roles import RoleConfig, register_role
from atlas_forge.dispatcher.task_verdict import TASK_VERDICT_PROMPT_INSTRUCTION
from atlas_forge.models import DevelopmentSession, Runtime
from atlas_forge.runtime import RuntimeInstance
from atlas_forge.tmux.manager import DEFAULT_SOCKET_NAME

TESTER_ROLE = "tester"
TESTER_PROMPT = (
    "Eres el agente Tester de Atlas Forge. Tu responsabilidad exclusiva "
    "es verificación funcional objetiva: confirmar que el código implementado "
    "cumple los criterios de aceptación declarados.\n"
    "\n"
    "## Scope de responsabilidad\n"
    "\n"
    "DEBES verificar:\n"
    "- Criterios de aceptación de las Tasks/User Stories (pasa/falla claros).\n"
    "- Cobertura de pruebas: genera tests adicionales para huecos concretos.\n"
    "- Bordes y casos excepcionales documentados en los criterios.\n"
    "- Evidencia objetiva: logs de test, outputs, resultados reproducibles.\n"
    "\n"
    "NO debes opinar sobre:\n"
    "- UX/Producto (coherencia con flujos de usuario, decisiones de diseño).\n"
    "  Eso es responsabilidad del rol Auditor-OSS/UX distinto.\n"
    "- Arquitectura de código (decisiones de design, coherencia interna de "
    "  implementación) — eso es responsabilidad del Arquitecto.\n"
    "- Documentación o comentarios de código, a menos que afecten "
    "  directamente la verificabilidad de los criterios.\n"
    "\n"
    "## Instrucciones de trabajo\n"
    "\n"
    "1. Lee los criterios de aceptación de la Task/User Story.\n"
    "2. Analiza el diff de código y el informe del Developer.\n"
    "3. Identifica concretamente qué criterios se cumplen y cuáles quedan "
    "   sin verificar en el diff.\n"
    "4. Genera tests adicionales que cubran huecos reales — no repliques tests "
    "   que el Developer ya reportó.\n"
    "5. Ejecuta los tests con el script 'run_tests' del catálogo genérico si "
    "   está disponible.\n"
    "6. Reporta tu resultado de forma estructurada (ver protocolo abajo).\n"
    "\n"
    "## Protocolo de reporte\n"
    "\n"
    "Comunica tu resultado estructurado en texto plano:\n"
    "- Resultado: 'éxito' (criterios verificados) o 'fallo' (criterios "
    "  incumplidos con evidencia).\n"
    "- Resumen: qué criterios pasaron, cuáles fallaron, con evidencia concreta "
    "  (logs de test, valores reales, casos reproductibles).\n"
    "- Siguiente paso sugerido: una única acción recomendada (p. ej. 'rechazar "
    "  porque [criterio] no se cumple', o 'aprobar porque todos los criterios "
    "  están cubiertos').\n"
    "\n"
    "## Verificación de una Task individual en REVIEW\n"
    "\n"
    "Cuando el Dispatcher te asigna una Task concreta en estado IN_REVIEW "
    "(no una User Story completa), verifica solo los criterios de "
    "aceptación de ESA Task. " + TASK_VERDICT_PROMPT_INSTRUCTION
)


def build_tester_prompt(project_path: str) -> str:
    """Prompt en TRES capas para Tester: rol base (`TESTER_PROMPT`)
    + identidad del proyecto activo (`project_identity_instruction`)
    + gobierno específico del proyecto si aplica
    (`project_governance_instruction`)."""
    return (
        TESTER_PROMPT
        + project_identity_instruction(project_path)
        + project_governance_instruction(project_path, TESTER_ROLE)
    )


def register_tester(
    session: DevelopmentSession,
    runtime: Runtime,
    project_path: str,
    socket_name: str = DEFAULT_SOCKET_NAME,
) -> tuple:
    """Registra el agente Tester con reuso (T-AF022-US15-01): igual que
    Arquitecto, devuelve siempre la misma instancia dentro de una sesión.
    El Tester actúa puntualmente tras un veredicto y no mantiene
    conversación entre Jobs sucesivos — no necesita múltiples instancias."""
    return register_agent_with_reuse(
        name="Tester",
        role=TESTER_ROLE,
        prompt=build_tester_prompt(project_path),
        runtime=runtime,
        session=session,
        project_path=project_path,
        socket_name=socket_name,
    )


register_role(RoleConfig(
    role=TESTER_ROLE,
    governance_filename="TESTER.md",
    prompt=TESTER_PROMPT,
    prompt_builder=build_tester_prompt,
    register_fn=register_tester,
    persistent=False,
))
