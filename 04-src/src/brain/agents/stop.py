"""Detener un agente lanzado a propósito (T-FB016-US01-03): capacidad de
dominio que hoy no existía en ninguna interfaz, aunque su mecanismo de
bajo nivel (`stop_runtime`/`is_runtime_alive`, `brain.runtime.generic`) ya
estaba implementado desde FB-004, sin ningún consumidor hasta ahora."""

from brain.agents.lifecycle import mark_stopped
from brain.models import Agent
from brain.runtime.agent_runtime_registry import get_runtime_instance_for_agent
from brain.runtime.generic import stop_runtime
from brain.tmux.manager import DEFAULT_SOCKET_NAME


class AgentRuntimeNotFoundError(ValueError):
    """El agente no tiene ningún `RuntimeInstance` registrado — nunca se
    lanzó, o el registro se perdió (p. ej. reinicio del proceso)."""


def stop_agent(agent: Agent, socket_name: str = DEFAULT_SOCKET_NAME) -> None:
    """Detiene la sesión tmux real del agente y transiciona `agent` a
    `stopped` — nunca a `unavailable`, reservado para fallos no
    solicitados por el desarrollador (distinción explícita de esta Task).

    Resuelve el `RuntimeInstance` del agente vía
    `get_runtime_instance_for_agent` (T-FB002-US03-00); si no hay ninguno
    registrado, lanza `AgentRuntimeNotFoundError` sin tocar el estado del
    agente — no hay ninguna sesión real que detener.

    La sesión tmux se detiene ANTES de transicionar el estado: si
    `stop_runtime` fallara, `agent` no quedaría marcado `stopped` sin que
    la sesión real lo esté de verdad (evita un estado de dominio que
    mienta sobre la realidad de la infraestructura)."""
    runtime_instance = get_runtime_instance_for_agent(agent.id)
    if runtime_instance is None:
        raise AgentRuntimeNotFoundError(
            f"El agente '{agent.name}' no tiene ningún runtime registrado "
            "— no hay ninguna sesión que detener."
        )

    stop_runtime(runtime_instance, socket_name=socket_name)
    mark_stopped(agent)
