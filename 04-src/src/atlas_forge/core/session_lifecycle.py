from typing import Any

from atlas_forge.models import DevelopmentSession

# Transiciones válidas del ciclo de vida v1 de DevelopmentSession
# (ver 02-backlog/epics/AF-003-development-session.md, "Alcance v1").
# `paused` pertenece al ciclo de vida completo (v2, US-AF003-03) y no es
# un estado alcanzable todavía.
_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "created": {"active"},
    "active": {"closed"},
    "closed": set(),
}


class InvalidSessionTransitionError(ValueError):
    """La transición de estado solicitada no está permitida en v1."""


def _transition(session: DevelopmentSession, target_status: str) -> None:
    allowed_targets = _ALLOWED_TRANSITIONS.get(session.status, set())
    if target_status not in allowed_targets:
        raise InvalidSessionTransitionError(
            f"No se puede transicionar de '{session.status}' a "
            f"'{target_status}'. Transiciones permitidas desde "
            f"'{session.status}': {sorted(allowed_targets) or 'ninguna'}."
        )
    session.status = target_status


def activate(session: DevelopmentSession) -> None:
    _transition(session, "active")


def close(session: DevelopmentSession) -> None:
    _transition(session, "closed")


def get_session_state(session: DevelopmentSession) -> dict[str, Any]:
    """Consulta el estado actual de la sesión y su contenido."""
    return {
        "id": session.id,
        "project_id": session.project_id,
        "status": session.status,
        "agents": list(session.agents),
    }


class SessionNotActiveError(ValueError):
    """No se puede asignar un agente a una sesión que no está `active`."""


def assign_agent(session: DevelopmentSession, agent: Any) -> None:
    """Asigna `agent` a `session`, solo si esta está `active`.

    No duplica un agente ya asignado a la misma sesión (comparación por
    igualdad, sin asumir ningún atributo concreto del agente — el modelo
    `Agent` pertenece a AF-005, Epic posterior a esta Task).
    """
    if session.status != "active":
        raise SessionNotActiveError(
            f"No se puede asignar un agente a una sesión en estado "
            f"'{session.status}'. La sesión debe estar 'active'."
        )
    if agent not in session.agents:
        session.agents.append(agent)


def list_agents(session: DevelopmentSession) -> list[Any]:
    """Consulta los agentes actualmente asignados a `session`."""
    return list(session.agents)
