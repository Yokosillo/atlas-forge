"""Detección y parseo del aviso de límite de sesión de Claude Code
(T-FB024-US21-01, US-FB024-21).

Solo el bloqueo TOTAL ("You've hit your session limit") transiciona el
estado operativo del agente — es el único caso en que el Dispatcher
realmente le despacharía trabajo que fallaría. El aviso previo ("You've
used N% of your session limit", sin haber llegado aún al límite) se
ignora deliberadamente (decisión de producto, 2026-08-17): el agente
sigue operativo, y exponerlo como si ya estuviera limitado produciría un
falso "no disponible" mientras todavía puede trabajar.

Dos variantes reales verificadas en producción el mismo día:
    "You've hit your session limit · resets 1:30am (UTC)"
    "You've used 92% of your session limit · resets 8am (UTC) · /upgrade to keep …"

Ambas comparten el sufijo "resets <hora> (UTC)" — el parseo de hora es
común a las dos, aunque solo la primera variante dispara la transición de
estado."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

# "resets 1:30am (UTC)" / "resets 8am (UTC)" — minutos opcionales, am/pm
# pegado a la hora (sin espacio, formato real visto), mayúsculas/minúsculas
# indiferentes por si Claude Code cambia el casing en una versión futura.
_RESET_TIME_PATTERN = re.compile(
    r"resets\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)\s*\(UTC\)", re.IGNORECASE
)

_SESSION_LIMIT_HIT_PATTERN = re.compile(
    r"You(?:'|’)ve hit your session limit", re.IGNORECASE
)

# Margen tras la hora de reset antes de hacer ping (criterio explícito de
# la Task/US: "para evitar reintentar justo en el segundo exacto y
# toparse con el límite todavía no liberado del todo").
PING_MARGIN_MINUTES = 1


def parse_reset_time(pane_text: str, *, now: datetime) -> datetime | None:
    """Extrae la hora de reset de `pane_text` (p. ej. "resets 1:30am
    (UTC)") como `datetime` UTC completo, o `None` si no hay coincidencia.

    Claude Code solo comunica hora del día, sin fecha — se resuelve contra
    `now` (siempre UTC, pasado explícito por el llamador para tests
    deterministas): si la hora resultante ya quedó en el pasado hoy
    mismo, se asume que es la ocurrencia de MAÑANA (el aviso siempre
    anuncia un reset futuro, nunca uno que ya pasó en el momento en que
    Claude Code lo mostró por primera vez) — evita interpretar
    "resets 1:30am" visto a las 23:00 como si ya hubiera pasado hace
    horas."""
    match = _RESET_TIME_PATTERN.search(pane_text)
    if match is None:
        return None

    hour = int(match.group(1))
    minute = int(match.group(2)) if match.group(2) else 0
    meridiem = match.group(3).lower()

    if hour == 12:
        hour = 0
    if meridiem == "pm":
        hour += 12

    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now - timedelta(minutes=1):
        # Ya pasó "hoy" con margen — es el reset de mañana. El margen de
        # 1 minuto evita reinterpretar como "de mañana" el mismo instante
        # que este watcher podría estar comprobando justo al filo.
        candidate += timedelta(days=1)
    return candidate


def detect_session_limit_block(pane_text: str, *, now: datetime | None = None) -> datetime | None:
    """Si `pane_text` contiene el patrón de BLOQUEO TOTAL (no el aviso
    previo de porcentaje), devuelve la hora de reset como `datetime` UTC;
    `None` si no hay bloqueo o no se pudo parsear la hora."""
    if now is None:
        now = datetime.now(timezone.utc)
    if not _SESSION_LIMIT_HIT_PATTERN.search(pane_text):
        return None
    return parse_reset_time(pane_text, now=now)


def should_ping_now(reset_at: datetime, *, now: datetime | None = None) -> bool:
    """`True` si ya pasó `reset_at` + `PING_MARGIN_MINUTES` respecto a
    `now` (criterio explícito: nunca justo en el segundo exacto)."""
    if now is None:
        now = datetime.now(timezone.utc)
    return now >= reset_at + timedelta(minutes=PING_MARGIN_MINUTES)
