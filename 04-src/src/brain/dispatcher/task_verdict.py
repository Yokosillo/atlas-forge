"""Formato estructurado de veredicto del Tester sobre una Task individual
(T-FB008-US14-02).

Mismo patrón que `architect_verdict.py` (dos estados en vez de tres: el
Tester no tiene la variante "con observaciones", solo pasa/falla con
evidencia — ver `agents/tester.py`)."""

from __future__ import annotations

import re

VERDICT_PASSED = "EXITO"
VERDICT_FAILED = "FALLO"

VALID_TASK_VERDICTS = {VERDICT_PASSED, VERDICT_FAILED}

_RESULTADO_PATTERN = re.compile(
    r"^RESULTADO:\s*(EXITO|FALLO)\s*$",
    re.MULTILINE,
)


def parse_task_verdict(agent_output: str) -> tuple[str, str, str]:
    """Extrae (resultado, resumen, siguiente_paso) de la salida del
    Tester sobre una Task.

    Formato esperado (ver `TESTER_PROMPT`, `agents/tester.py`):

        RESULTADO: [EXITO | FALLO]
        RESUMEN:
        <evidencia concreta, puede ocupar varias líneas>
        SIGUIENTE_PASO:
        <acción recomendada, puede ocupar varias líneas hasta el final>

    En caso de no poder parsear, devuelve ("", agent_output, "")."""
    status_match = _RESULTADO_PATTERN.search(agent_output)
    if status_match is None:
        return "", agent_output, ""

    resultado = status_match.group(1)
    rest = agent_output[status_match.end():]

    resumen = ""
    siguiente_paso = ""

    resumen_match = re.search(r"^RESUMEN:\s*\n", rest, re.MULTILINE)
    paso_match = re.search(r"^SIGUIENTE_PASO:\s*\n", rest, re.MULTILINE)

    if resumen_match and paso_match:
        resumen = rest[resumen_match.end():paso_match.start()].strip()
        siguiente_paso = rest[paso_match.end():].strip()
    elif resumen_match:
        resumen = rest[resumen_match.end():].strip()
    elif paso_match:
        siguiente_paso = rest[paso_match.end():].strip()
    else:
        resumen = rest.strip()

    return resultado, resumen, siguiente_paso


TASK_VERDICT_PROMPT_INSTRUCTION = (
    "Cuando termines de verificar una Task, comunica tu resultado de "
    "forma estructurada y parseable, con este formato exacto (sin "
    "desviarte):\n"
    "\n"
    "RESULTADO: [EXITO | FALLO]\n"
    "RESUMEN:\n"
    "<qué criterios pasaron, cuáles fallaron, con evidencia concreta "
    "(logs de test, valores reales, casos reproducibles)>\n"
    "SIGUIENTE_PASO:\n"
    "<si RESULTADO es FALLO: describe exactamente qué falta o qué se "
    "rompe, acotado al problema — se usará como base de una Task de "
    "corrección nueva. Si RESULTADO es EXITO: '(sin correcciones "
    "pendientes)'>\n"
    "\n"
    "Reglas:\n"
    "- RESULTADO debe ser exactamente una de las dos opciones, en "
    "mayúsculas.\n"
    "- EXITO: todos los criterios de aceptación de la Task se cumplen.\n"
    "- FALLO: al menos un criterio no se cumple, o hay una regresión "
    "real — SIGUIENTE_PASO señala exactamente qué falta.\n"
    "- SIGUIENTE_PASO debe ser siempre la última sección del mensaje.\n"
    "- Nunca dejes el mensaje sin SIGUIENTE_PASO, aunque el resultado "
    "sea EXITO."
)
