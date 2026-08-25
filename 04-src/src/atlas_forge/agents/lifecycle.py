from typing import Any

from atlas_forge.models import Agent

# Transiciones válidas del estado operativo v1 de Agent
# (ver 02-backlog/epics/AF-005-agent-manager.md, "Alcance v1"): idle,
# working, unavailable. El estado `paused` del modelo conceptual completo
# de la Epic se descarta explícitamente en v1 (sin consumidor identificado,
# ver "Diferido a v2" del propio Epic).
#
# `stopped` (T-AF016-US01-03, AF-016): detención intencional del agente
# por el desarrollador — distinto de `unavailable` (fallo NO solicitado,
# p. ej. el runtime muere por su cuenta). Alcanzable desde `idle` y desde
# `working` (detener un agente ocupado también debe ser posible), pero sin
# transición de vuelta a `idle`: un agente `stopped` no se "reanuda", debe
# relanzarse desde cero (mismo mecanismo de `register_agent`) — no
# confundir con `paused`, ya descartado arriba. Sin salida en v1 (criterio
# de aceptación explícito de la Task).
#
# `limited` (T-AF024-US21-01, US-AF024-21): el agente Claude Code se
# quedó sin límite de sesión (patrón textual real en el pane, bloqueo
# total) — no elegible como `idle` para el Dispatcher mientras dura.
# Alcanzable desde `idle` y desde `working` (el límite puede golpear en
# cualquiera de los dos momentos). Vuelve a `idle` tras el ping automático
# del watcher una vez pasada la hora de reset (criterio 7 de la US: "deja
# de mostrarse en cuanto el agente vuelve a mostrar actividad normal") —
# nunca a `working` directamente, el ping solo le pide continuar, no
# hay forma de confirmar que retomó trabajo real hasta el siguiente ciclo
# normal de la aplicación. `unavailable`/`stopped` siguen alcanzables
# desde `limited`: el proceso tmux puede morir o detenerse a propósito
# igual que en cualquier otro estado.
#
# `failed` (T-AF008-US18-04, US-AF008-18): auto-liberación operativa de un
# agente que quedó `working` sin Job en vuelo (huérfano por re-despacho del
# mismo task_id o por reinicio/duplicado) y sin actividad reciente — el
# watcher `agents/stuck_working_watcher.py` lo marca `failed` con motivo
# consultable en `failure_reason`, desbloqueando la cola. A diferencia de
# `unavailable` (fallo del runtime), `failed` es un fallo de SUPERVISIÓN
# del ciclo operativo: el runtime puede seguir vivo. Vuelve a `idle` de
# forma automática cuando su runtime está vivo (RuntimeDeathWatcher) o por
# liberación manual; `stopped`/`unavailable` siguen alcanzables.
_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "idle": {"working", "unavailable", "stopped", "limited"},
    "working": {"idle", "unavailable", "stopped", "limited", "failed"},
    "unavailable": {"idle"},
    "stopped": set(),
    "limited": {"idle", "unavailable", "stopped"},
    "failed": {"idle", "unavailable", "stopped"},
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
    # T-AF008-US18-04: al recuperar un agente a `idle` se limpia el motivo
    # de fallo previo (si lo hubiera) — un agente operativo no debe seguir
    # exponiendo un fallo obsoleto.
    if getattr(agent, "failure_reason", None) is not None:
        agent.failure_reason = None


def mark_unavailable(agent: Agent) -> None:
    _transition(agent, "unavailable")


def mark_failed(agent: Agent, reason: str) -> None:
    """Transiciona `agent` a `failed` (T-AF008-US18-04) registrando el
    `failure_reason` consultable ANTES de la transición, para que si
    `_transition` lanza (origen no permitido) el agente no quede con un
    motivo de fallo obsoleto sin `status == "failed"` que lo respalde."""
    agent.failure_reason = reason
    _transition(agent, "failed")


def clear_failure(agent: Agent) -> None:
    """Limpia `failure_reason` al recuperar un agente `failed` a `idle` —
    un agente operativo no debe seguir exponiendo un motivo de fallo
    obsoleto."""
    agent.failure_reason = None


def mark_stopped(agent: Agent) -> None:
    _transition(agent, "stopped")


def mark_limited(agent: Agent, limited_until: str) -> None:
    """Transiciona `agent` a `limited` y registra `limited_until` (hora
    ISO 8601 de recuperación, ya calculada por el llamador —
    `atlas_forge.agents.session_limit`). El campo se fija ANTES de la
    transición para que, si `_transition` lanza (estado de origen no
    permitido), el agente no quede con un `limited_until` obsoleto sin
    `status == "limited"` que lo respalde."""
    agent.limited_until = limited_until
    _transition(agent, "limited")


def clear_session_limit(agent: Agent) -> None:
    """Transiciona `agent` de vuelta a `idle` tras el ping automático del
    watcher (T-AF024-US21-01, criterio 7) y limpia `limited_until` — un
    agente ya no limitado no debe seguir exponiendo una hora de
    recuperación obsoleta."""
    _transition(agent, "idle")
    agent.limited_until = None


def get_agent_state(agent: Agent) -> dict[str, Any]:
    """Consulta el estado operativo actual del agente."""
    return {
        "id": agent.id,
        "name": agent.name,
        "role": agent.role,
        "runtime_id": agent.runtime_id,
        "status": agent.status,
    }
