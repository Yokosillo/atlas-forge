from typing import Any

from brain.models import Agent

# Transiciones válidas del estado operativo v1 de Agent
# (ver 02-backlog/epics/FB-005-agent-manager.md, "Alcance v1"): idle,
# working, unavailable. El estado `paused` del modelo conceptual completo
# de la Epic se descarta explícitamente en v1 (sin consumidor identificado,
# ver "Diferido a v2" del propio Epic).
#
# `stopped` (T-FB016-US01-03, FB-016): detención intencional del agente
# por el desarrollador — distinto de `unavailable` (fallo NO solicitado,
# p. ej. el runtime muere por su cuenta). Alcanzable desde `idle` y desde
# `working` (detener un agente ocupado también debe ser posible), pero sin
# transición de vuelta a `idle`: un agente `stopped` no se "reanuda", debe
# relanzarse desde cero (mismo mecanismo de `register_agent`) — no
# confundir con `paused`, ya descartado arriba. Sin salida en v1 (criterio
# de aceptación explícito de la Task).
_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "idle": {"working", "unavailable", "stopped"},
    "working": {"idle", "unavailable", "stopped"},
    "unavailable": {"idle"},
    "stopped": set(),
}


class InvalidAgentTransitionError(ValueError):
    """La transición de estado operativo solicitada no está permitida en v1."""


def _transition(agent: Agent, target_status: str) -> None:
    allowed_targets = _ALLOWED_TRANSITIONS.get(agent.status, set())
    if target_status not in allowed_targets:
        raise InvalidAgentTransitionError(
            f"No se puede transicionar de '{agent.status}' a "
            f"'{target_status}'. Transiciones permitidas desde "
            f"'{agent.status}': {sorted(allowed_targets) or 'ninguna'}."
        )
    agent.status = target_status


def mark_working(agent: Agent) -> None:
    _transition(agent, "working")


def mark_idle(agent: Agent) -> None:
    _transition(agent, "idle")


def mark_unavailable(agent: Agent) -> None:
    _transition(agent, "unavailable")


def mark_stopped(agent: Agent) -> None:
    _transition(agent, "stopped")


def get_agent_state(agent: Agent) -> dict[str, Any]:
    """Consulta el estado operativo actual del agente."""
    return {
        "id": agent.id,
        "name": agent.name,
        "role": agent.role,
        "runtime_id": agent.runtime_id,
        "status": agent.status,
    }
