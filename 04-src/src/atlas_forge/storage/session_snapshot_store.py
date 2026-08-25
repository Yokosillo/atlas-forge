"""Persistencia del snapshot recuperable de sesión (T-AF003-US02-02,
US-AF003-02 · "Recuperar la sesión de desarrollo al reabrir Atlas Forge").

Guarda/lee el dict portable que produce
`atlas_forge.core.session_recovery.serialize_snapshot` en
`<project_id>/.claude/state/<sanitize_session_name_part(basename)>/session_snapshot.json`
— la misma raíz de estado por proyecto que ya usan
`dispatch_queue.json`/`reconciliation_log.jsonl`, así que el snapshot
sobrevive a reinicios del proceso y a cambios de máquina sin depender del
estado en memoria.

Esta capa NO contiene lógica de dominio: solo serializa/deserializa el
dict ya preparado por `serialize_snapshot`/`deserialize_snapshot`. Un fallo
de I/O aquí no debe tumbar al llamador (los puntos de conexión lo tratan
como "mejor esfuerzo").
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from atlas_forge.runtime import sanitize_session_name_part

_SNAPSHOT_FILENAME = "session_snapshot.json"


def session_snapshot_path(project_id: str | Path) -> Path:
    """Ruta del fichero de snapshot de la sesión de `project_id`.

    `project_id` es el path real del proyecto activo (convención AF-001:
    `Project.id == str(path)`); el directorio de estado se deriva del
    basename del path con la misma sanitización que el resto de la raíz
    de estado por proyecto."""
    p = Path(project_id)
    dirname = sanitize_session_name_part(p.name)
    return p / ".claude" / "state" / dirname / _SNAPSHOT_FILENAME


def save_session_snapshot(project_id: str | Path, data: dict[str, Any]) -> None:
    """Persiste el dict portable del snapshot de la sesión de `project_id`.

    Escribe el fichero completo (sobreeescritura), creando el directorio de
    estado si no existe — mismo criterio que `save_active_project`. Solo
    escribe el `data` que el llamador ya preparó con
    `serialize_snapshot`; no hay decisión de negocio aquí."""
    path = session_snapshot_path(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_session_snapshot(project_id: str | Path) -> dict[str, Any] | None:
    """Lee el snapshot persistido de `project_id`.

    Devuelve `None` si no existe fichero (o está vacío) — el llamador decide
    entonces el comportamiento por defecto (sin recuperación). Devuelve el
    dict raw, sin interpretar: la reconstrucción a `SessionSnapshot` la hace
    la capa de dominio (`deserialize_snapshot`)."""
    path = session_snapshot_path(project_id)
    if not path.is_file():
        return None
    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        return None
    return json.loads(raw)