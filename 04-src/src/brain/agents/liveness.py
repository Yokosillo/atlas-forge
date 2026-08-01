"""Verificación PEREZOSA (T-FB016-US01-07) de que el runtime real de un
agente sigue vivo, antes de reportar su estado. No es un monitor activo
en segundo plano ni requiere polling continuo — se comprueba
`is_runtime_alive` en el momento de cada consulta (`GET /agents`, y el
equivalente que use la TUI tras T-FB016-US01-06), mismo criterio de
simplicidad ya aplicado en el resto de FB-004 v1 ("basta con verificar en
el momento de cada consulta"). Si en el futuro hiciera falta detectar la
caída sin que nadie consulte entretanto, eso sería una Task de polling
continuo aparte — deliberadamente no implementada aquí para no
comprometerla sin que nadie la haya pedido todavía.

Cierra un hueco real: si el proceso tmux de un agente muere solo (crash,
OOM, `tmux kill-session` manual accidental fuera de `stop_agent`), el
agente seguía reportándose `idle`/`working` indefinidamente en cualquier
interfaz, porque nada comprobaba la infraestructura real al consultar."""

from brain.agents.lifecycle import mark_unavailable
from brain.models import Agent
from brain.runtime.agent_runtime_registry import get_runtime_instance_for_agent
from brain.runtime.generic import is_runtime_alive
from brain.tmux.manager import DEFAULT_SOCKET_NAME

# Estados desde los que un agente puede caer a `unavailable` sin que
# nadie lo pidiera — mismo conjunto que ya admite esa transición en
# `_ALLOWED_TRANSITIONS` (`brain/agents/lifecycle.py`). `stopped` se
# excluye explícitamente aquí, no solo porque la tabla de transiciones ya
# lo rechazaría (`"stopped": set()`, `InvalidAgentTransitionError`): un
# agente `stopped` con su runtime ya detenido a propósito no representa
# ningún fallo que reportar — comprobarlo evita depender de que la
# excepción se dispare y haya que capturarla en cada llamador.
_STATUSES_THAT_CAN_BECOME_UNAVAILABLE = {"idle", "working"}


def refresh_agent_liveness(agent: Agent, socket_name: str = DEFAULT_SOCKET_NAME) -> Agent:
    """Comprueba si el runtime real de `agent` sigue vivo y, si no lo
    está y `agent` no fue detenido a propósito (`stopped`), lo transiciona
    a `unavailable` en el momento de esta llamada.

    Casos que NO transicionan nada (se devuelve `agent` sin tocar):
    - `agent.status == "stopped"` — detención intencional, no un fallo.
    - `agent.status == "unavailable"` — ya refleja el fallo, no hay
      transición `unavailable -> unavailable` que aplicar de nuevo.
    - no hay ningún `RuntimeInstance` registrado para `agent` — mismo
      criterio que `stop_agent`/`AgentRuntimeNotFoundError`, pero aquí no
      se lanza excepción: una consulta de estado nunca debe fallar por
      esto, simplemente no hay nada que verificar.
    - `is_runtime_alive` devuelve `True` — el runtime sigue vivo de
      verdad, no hay nada que corregir.

    Devuelve siempre el mismo `agent` recibido (mutado in-place si
    corresponde), para poder encadenar la llamada en el punto de consulta."""
    if agent.status not in _STATUSES_THAT_CAN_BECOME_UNAVAILABLE:
        return agent

    runtime_instance = get_runtime_instance_for_agent(agent.id)
    if runtime_instance is None:
        return agent

    if not is_runtime_alive(runtime_instance, socket_name=socket_name):
        mark_unavailable(agent)

    return agent
