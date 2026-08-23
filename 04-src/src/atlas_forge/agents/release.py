"""Liberar un agente caído o detenido (T-AF005-US01-09): retira de
`session.agents` a un agente `unavailable` (su proceso murió fuera de
atlas_forge: crash, OOM, kill manual) o `stopped` (detenido a propósito),
liberando su plaza del límite de Developers simultáneos sin intentar matar
su runtime.

`stop_agent` no sirve para este caso (ver `atlas_forge/agents/stop.py`): exige un
runtime vivo — `get_runtime_instance_for_agent` lanza
`AgentRuntimeNotFoundError` si no hay registro, y `stop_runtime` falla
sobre una sesión tmux ya muerta. Un agente caído no tiene nada que matar:
solo hace falta retirarlo de la sesión para que su slot deje de contar.

No se intenta ninguna transición de estado (`_transition`): el agente ya
está en un estado terminal (`unavailable`/`stopped`) y permanece así en el
objeto Python tras salir de la lista — la acción es puramente estructural
(retirar de `session.agents`)."""

from atlas_forge.models import Agent, DevelopmentSession

# Estados liberables: el agente ya no mantiene un runtime vivo real, no hay
# nada que matar — solo se retira de la sesión. `idle`/`working`/`limited`
# se rechazan porque están vivos: para liberar a un agente vivo existe
# "Detener" (`stop_agent`).
RELEASABLE_STATUSES = frozenset({"unavailable", "stopped"})


class AgentReleaseError(ValueError):
    """El agente no se puede liberar porque sigue vivo (idle/working/limited)."""


def release_agent(agent: Agent, session: DevelopmentSession) -> None:
    """Retira `agent` de `session.agents` si su estado es liberable
    (`unavailable`/`stopped`), liberando su plaza del límite de Developers
    simultáneos. Lanza `AgentReleaseError` si el agente está activo
    (`idle`/`working`/`limited`) — a un agente vivo no se le libera, se le
    detiene con `stop_agent`.

    No toca el runtime real (ya está muerto o detenido) ni el registro de
    liveness: una vez fuera de `session.agents`, `list_agents`/`GET /agents`
    dejan de consultarlo y `refresh_agent_liveness` nunca vuelve a marcar
    nada sobre él."""
    if agent.status not in RELEASABLE_STATUSES:
        raise AgentReleaseError(
            f"No se puede liberar el agente '{agent.name}': su estado es "
            f"'{agent.status}', solo se libera un agente "
            f"{'/'.join(sorted(RELEASABLE_STATUSES))}. Para detener un "
            f"agente activo usa la acción 'Detener'."
        )
    session.agents.remove(agent)
