"""Detener un agente lanzado a propósito (T-FB016-US01-03): capacidad de
dominio que hoy no existía en ninguna interfaz, aunque su mecanismo de
bajo nivel (`stop_runtime`/`is_runtime_alive`, `brain.runtime.generic`) ya
estaba implementado desde FB-004, sin ningún consumidor hasta ahora.

T-FB024-US12-02: para Developer, "detener" pasó de pausar (`stopped`
residual, ocupando cupo para siempre) a eliminar el `Agent` por completo
de `session.agents` — decisión de producto explícita del usuario
(2026-08-15, ver la Task para el contexto completo del bug que la
motivó). Arquitecto NO cambia: sigue pausando a `stopped`, nunca se
elimina, porque es una instancia única reutilizada por diseño
(`register_agent_with_reuse`, distinto de Developer que siempre crea
instancias nuevas). El resto de roles (comportamiento por defecto)
también sigue pausando — esta excepción es exclusiva de
`DEVELOPER_ROLE`."""

from brain.agents.developer import DEVELOPER_ROLE
from brain.agents.lifecycle import mark_stopped
from brain.models import Agent, DevelopmentSession
from brain.runtime.agent_runtime_registry import get_runtime_instance_for_agent
from brain.runtime.generic import stop_runtime
from brain.tmux.manager import DEFAULT_SOCKET_NAME


class AgentRuntimeNotFoundError(ValueError):
    """El agente no tiene ningún `RuntimeInstance` registrado — nunca se
    lanzó, o el registro se perdió (p. ej. reinicio del proceso)."""


def stop_agent(
    agent: Agent,
    session: DevelopmentSession,
    socket_name: str = DEFAULT_SOCKET_NAME,
) -> None:
    """Detiene la sesión tmux real del agente.

    Para la mayoría de roles (incluido Arquitecto), transiciona `agent` a
    `stopped` — nunca a `unavailable`, reservado para fallos no
    solicitados por el desarrollador (distinción explícita de
    T-FB016-US01-03) — y `agent` permanece en `session.agents`,
    reutilizable/consultable como una instancia pausada.

    Para `DEVELOPER_ROLE` (T-FB024-US12-02, decisión de producto): en vez
    de pausar, `agent` se retira por completo de `session.agents` — deja
    de existir, libera su plaza del límite de Developer simultáneos de
    inmediato (`_next_developer_name`/`register_developer`,
    `agents/developer.py`, ya cuentan sobre `session.agents` en el
    instante de la llamada, sin cambios adicionales necesarios). El
    objeto `Agent` en memoria Python se marca igualmente `stopped` antes
    de salir de la lista (coherente para cualquier referencia que ya lo
    tuviera capturado, p. ej. la propia respuesta HTTP de la ruta que
    invoca esta función), pero ya no es alcanzable vía `list_agents`
    después de esta llamada.

    Resuelve el `RuntimeInstance` del agente vía
    `get_runtime_instance_for_agent` (T-FB002-US03-00); si no hay ninguno
    registrado, lanza `AgentRuntimeNotFoundError` sin tocar el estado del
    agente — no hay ninguna sesión real que detener.

    La sesión tmux se detiene ANTES de transicionar el estado/eliminar de
    `session.agents`: si `stop_runtime` fallara, `agent` no quedaría
    marcado `stopped` ni eliminado sin que la sesión real lo esté de
    verdad (evita un estado de dominio que mienta sobre la realidad de la
    infraestructura)."""
    runtime_instance = get_runtime_instance_for_agent(agent.id)
    if runtime_instance is None:
        raise AgentRuntimeNotFoundError(
            f"El agente '{agent.name}' no tiene ningún runtime registrado "
            "— no hay ninguna sesión que detener."
        )

    stop_runtime(runtime_instance, socket_name=socket_name)
    mark_stopped(agent)

    if agent.role == DEVELOPER_ROLE:
        session.agents.remove(agent)
