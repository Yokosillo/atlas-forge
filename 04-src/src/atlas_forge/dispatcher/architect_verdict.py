"""Formato estructurado de veredicto del Arquitecto (T-AF022-US05-01).

Reemplaza el prompt de texto libre de `agents/arquitecto.py` por un formato
parseable con tres estados: APROBADO, APROBADO_CON_OBSERVACIONES,
RECHAZADO, con justificación y siguiente prompt accionable para el
Developer.
"""

from __future__ import annotations

import re

VERDICT_APPROVED = "APROBADO"
VERDICT_APPROVED_WITH_NOTES = "APROBADO_CON_OBSERVACIONES"
VERDICT_REJECTED = "RECHAZADO"

VALID_VERDICTS = {VERDICT_APPROVED, VERDICT_APPROVED_WITH_NOTES, VERDICT_REJECTED}

_ESTADO_PATTERN = re.compile(
    r"^ESTADO:\s*(APROBADO(?:_CON_OBSERVACIONES)?|RECHAZADO)\s*$",
    re.MULTILINE,
)


def parse_verdict(agent_output: str) -> tuple[str, str, str]:
    """Extrae (estado, justificacion, siguiente_prompt) de la salida del
    Arquitecto.

    El formato esperado es el definido en `00-gobierno/ARQUITECTO.md` y
    en el prompt del agente:

        ESTADO: [APROBADO | APROBADO_CON_OBSERVACIONES | RECHAZADO]
        JUSTIFICACIÓN:
        <justificación, puede ocupar varias líneas>
        SIGUIENTE_PROMPT_PARA_WORKER:
        <prompt concreto, puede ocupar varias líneas hasta el final>

    Devuelve una tupla (estado, justificacion, siguiente_prompt). En caso
    de no poder parsear, devuelve ("", agent_output, "").
    """
    status_match = _ESTADO_PATTERN.search(agent_output)
    if status_match is None:
        return "", agent_output, ""

    estado = status_match.group(1)

    rest = agent_output[status_match.end() :]

    justificacion = ""
    siguiente_prompt = ""

    just_match = re.search(r"^JUSTIFICACIÓN:\s*\n", rest, re.MULTILINE)
    prompt_match = re.search(r"^SIGUIENTE_PROMPT_PARA_WORKER:\s*\n", rest, re.MULTILINE)

    if just_match and prompt_match:
        justificacion = rest[just_match.end() : prompt_match.start()].strip()
        siguiente_prompt = rest[prompt_match.end() :].strip()
    elif just_match:
        justificacion = rest[just_match.end() :].strip()
    elif prompt_match:
        siguiente_prompt = rest[prompt_match.end() :].strip()
    else:
        justificacion = rest.strip()

    return estado, justificacion, siguiente_prompt


VERDICT_PROMPT_INSTRUCTION = (
    "Cuando termines tu revisión, comunica el veredicto de forma "
    "estructurada y parseable, con este formato exacto (sin desviarte):\n"
    "\n"
    "ESTADO: [APROBADO | APROBADO_CON_OBSERVACIONES | RECHAZADO]\n"
    "JUSTIFICACIÓN:\n"
    "<explica el motivo de tu decisión, de forma concisa (2-4 líneas)>\n"
    "SIGUIENTE_PROMPT_PARA_WORKER:\n"
    "<prompt concreto y accionable para el Developer — autocontenido, "
    "el Developer no tiene acceso al resto de tu razonamiento>\n"
    "\n"
    "Reglas:\n"
    "- ESTADO debe ser exactamente una de las tres opciones, en mayúsculas.\n"
    "- APROBADO: el trabajo cumple los criterios de aceptación.\n"
    "- APROBADO_CON_OBSERVACIONES: el trabajo es correcto pero hay mejoras "
    "no bloqueantes — el siguiente prompt ya las incorpora.\n"
    "- RECHAZADO: hay un problema real (no cumple criterios, rompe algo, "
    "falta una prueba esencial) — el siguiente prompt señala exactamente "
    "qué falta, acotado al problema.\n"
    "- SIGUIENTE_PROMPT_PARA_WORKER debe ser siempre la última sección del "
    "mensaje — todo lo que vaya después se interpreta como el prompt para "
    "el Developer.\n"
    "- Nunca dejes el mensaje sin SIGUIENTE_PROMPT_PARA_WORKER, aunque "
    "el estado sea RECHAZADO."
)
