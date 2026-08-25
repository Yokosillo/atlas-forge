"""Lógica central de recuperación de sesión (T-AF003-US02-01, US-AF003-02 ·
"Recuperar la sesión de desarrollo al reabrir Atlas Forge").

Capa de DOMINIO pura: modela el estado recuperable de una `DevelopmentSession`
(proyecto, agentes, historial de actividad) en forma portable y lo expone de
manera invocable programáticamente, SIN dependencias de infraestructura externa
(HTTP, persistencia/ficheros, I/O). La capa que persista `serialize_snapshot()`
a disco/BD y lo reconstruya al arrancar es responsabilidad de otro nivel.

## Decisiones de dominio (US-AF003-02)

- La sesión NO se destruye al cerrar el proceso: se marca como RECUPERABLE
  (`status` distinto de `closed`/`destroyed`).
- Al reabrir sobre el mismo proyecto, `is_recoverable` permite decidir si la
  sesión anterior puede reconstruirse (con sus agentes e historial).
- El historial de actividad (`ActivityEvent`) se conserva entre ejecuciones:
  es parte del snapshot portable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# Estados que marcan una sesión como NO recuperable (cerrada/destruida a
# propósito). Cualquier otro estado (creada/activa) la deja recuperable.
_NON_RECOVERABLE_STATUSES = frozenset({"closed", "destroyed", "finalized"})


@dataclass(frozen=True)
class AgentSnapshot:
    """Estado recuperable de un agente de la sesión (sin runtime/I-O)."""

    id: str
    name: str
    role: str
    status: str
    persistent: bool


@dataclass(frozen=True)
class ActivityEvent:
    """Un evento de actividad relevante de la sesión (para el historial)."""

    timestamp: str
    event: str
    detail: str = ""


@dataclass(frozen=True)
class SessionSnapshot:
    """Instantánea portable del estado recuperable de una sesión."""

    session_id: str
    project_id: str
    status: str
    created_at: str
    last_active_at: str
    agents: tuple[AgentSnapshot, ...] = field(default_factory=tuple)
    activity: tuple[ActivityEvent, ...] = field(default_factory=tuple)

    def is_recoverable(self) -> bool:
        """Una sesión es recuperable salvo que esté explícitamente cerrada/
        destruida. Es la decisión de dominio sobre la que la capa de arranque
        reconstruye o no la sesión al reabrir Atlas Forge."""
        return self.status not in _NON_RECOVERABLE_STATUSES

    def record_activity(self, event: str, detail: str = "", ts: str | None = None) -> "SessionSnapshot":
        """Devuelve una copia del snapshot con un evento de actividad añadido y
        `last_active_at` actualizado (inmutable)."""
        now = ts if ts is not None else datetime.now(timezone.utc).isoformat()
        return SessionSnapshot(
            session_id=self.session_id,
            project_id=self.project_id,
            status=self.status,
            created_at=self.created_at,
            last_active_at=now,
            agents=self.agents,
            activity=self.activity + (ActivityEvent(timestamp=now, event=event, detail=detail),),
        )


def _agent_to_snapshot(agent: Any) -> AgentSnapshot:
    """Extrae el estado recuperable de un `Agent` (o de un dict equivalente)
    sin tocar infraestructura."""
    if isinstance(agent, dict):
        return AgentSnapshot(
            id=str(agent.get("id", "")),
            name=str(agent.get("name", "")),
            role=str(agent.get("role", "")),
            status=str(agent.get("status", "idle")),
            persistent=bool(agent.get("persistent", False)),
        )
    return AgentSnapshot(
        id=getattr(agent, "id", ""),
        name=getattr(agent, "name", ""),
        role=getattr(agent, "role", ""),
        status=getattr(agent, "status", "idle"),
        persistent=bool(getattr(agent, "persistent", False)),
    )


def build_session_snapshot(
    session: Any,
    *,
    status: str | None = None,
    created_at: str | None = None,
    last_active_at: str | None = None,
) -> SessionSnapshot:
    """Construye el `SessionSnapshot` de una `DevelopmentSession` a partir de
    su estado en memoria (proyecto + agentes asignados). Función pura: no lee
    ni escribe disco ni llama a ningún servicio externo.

    `status`/`created_at`/`last_active_at` se derivan de la sesión si no se
    pasan; `last_active_at` cae a `created_at` si no hay actividad distinta."""
    now = datetime.now(timezone.utc).isoformat()
    s_status = status if status is not None else getattr(session, "status", "created")
    created = created_at if created_at is not None else getattr(session, "created_at", None) or now
    last_active = last_active_at if last_active_at is not None else created
    agents = tuple(_agent_to_snapshot(a) for a in getattr(session, "agents", []) or [])
    return SessionSnapshot(
        session_id=getattr(session, "id", ""),
        project_id=getattr(session, "project_id", ""),
        status=s_status,
        created_at=created,
        last_active_at=last_active,
        agents=agents,
    )


def is_recoverable(snapshot: SessionSnapshot) -> bool:
    """Atajo de `snapshot.is_recoverable()` para usos programáticos sin
    instanciar el modelo."""
    return snapshot.is_recoverable()


def serialize_snapshot(snapshot: SessionSnapshot) -> dict[str, Any]:
    """Convierte el snapshot a un dict portable (JSON-serializable) para que la
    capa de persistencia lo guarde. No hace I/O aquí."""
    return {
        "session_id": snapshot.session_id,
        "project_id": snapshot.project_id,
        "status": snapshot.status,
        "created_at": snapshot.created_at,
        "last_active_at": snapshot.last_active_at,
        "agents": [
            {
                "id": a.id,
                "name": a.name,
                "role": a.role,
                "status": a.status,
                "persistent": a.persistent,
            }
            for a in snapshot.agents
        ],
        "activity": [
            {"timestamp": e.timestamp, "event": e.event, "detail": e.detail}
            for e in snapshot.activity
        ],
    }


def deserialize_snapshot(data: dict[str, Any]) -> SessionSnapshot:
    """Reconstruye un `SessionSnapshot` desde el dict portable (salida de
    `serialize_snapshot`). Función pura: no lee disco."""
    return SessionSnapshot(
        session_id=str(data.get("session_id", "")),
        project_id=str(data.get("project_id", "")),
        status=str(data.get("status", "created")),
        created_at=str(data.get("created_at", "")),
        last_active_at=str(data.get("last_active_at", "")),
        agents=tuple(
            AgentSnapshot(
                id=str(a.get("id", "")),
                name=str(a.get("name", "")),
                role=str(a.get("role", "")),
                status=str(a.get("status", "idle")),
                persistent=bool(a.get("persistent", False)),
            )
            for a in (data.get("agents") or [])
        ),
        activity=tuple(
            ActivityEvent(
                timestamp=str(e.get("timestamp", "")),
                event=str(e.get("event", "")),
                detail=str(e.get("detail", "")),
            )
            for e in (data.get("activity") or [])
        ),
    )