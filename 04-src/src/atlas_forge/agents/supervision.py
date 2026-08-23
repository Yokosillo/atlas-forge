"""Estado de supervisión del agente (T-AF023-US01-02): expone si un agente
está `vivo`, `colgado` o `detenido` según la detección de inactividad de
T-AF023-US01-01 (`detect_agent_activity`), además de su estado funcional
(`idle`/`working`/...).

El estado de supervisión se calcula PERezosamente al consultar (mismo patrón
que `refresh_agent_liveness` en `atlas_forge/agents/liveness.py`): se resuelve la
fuente de actividad del runtime (para OpenCode, el mtime del log interno
`~/.local/share/opencode/log/opencode.log`; para el resto, sin fuente
determinada se reporta `vivo` — no se puede declarar un cuelgue sin fuente)
y se alimenta `detect_agent_activity` con un historial acotado de lecturas.

## Relación con el estado funcional

Es ORTOGONAL al estado funcional (`status`): no lo modifica ni participa en el
flujo del pipeline ni del Dispatcher. Solo se calcula para exponerlo en
`GET /agents`. Un agente `stopped`/`unavailable`, o cuyo runtime ya no está
vivo, se reporta `detenido`.
"""

from __future__ import annotations

import time
from pathlib import Path

from atlas_forge.agents.inactivity import (
    DEFAULT_INACTIVITY_THRESHOLD_SECONDS,
    VERDICT_HUNG,
    detect_agent_activity,
)
from atlas_forge.models import Agent
from atlas_forge.runtime.agent_runtime_registry import get_runtime_instance_for_agent
from atlas_forge.runtime.generic import is_runtime_alive
from atlas_forge.tmux.manager import DEFAULT_SOCKET_NAME

# Vocabulario del estado de supervisión (T-AF023-US01-02).
SUPERVISION_ALIVE = "vivo"
SUPERVISION_HUNG = "colgado"
SUPERVISION_STOPPED = "detenido"

# Historial acotado de lecturas de última actividad que se conservan por
# agente para la detección de cuelgue (T-AF023-US01-01 usa 3 lecturas
# consecutivas sin cambio; se guarda un margen para no perder el caso).
_MAX_ACTIVITY_HISTORY = 8

# Fuente de actividad de OpenCode (T-AF023-US01-01): el mtime del log interno
# avanza cuando el agente produce actividad; un mtime congelado superando el
# umbral en varias lecturas indica un cuelgue.
_OPENCODE_LOG_PATH = (
    Path.home() / ".local" / "share" / "opencode" / "log" / "opencode.log"
)


def compute_supervision_state(
    agent: Agent,
    activity_history: list[float],
    threshold_seconds: float = DEFAULT_INACTIVITY_THRESHOLD_SECONDS,
    now: float | None = None,
) -> str:
    """Estado de supervisión determinista a partir del agente y de su historial
    de timestamps de última actividad observados entre lecturas.

    - `detenido`: agente `stopped`/`unavailable` (detenido o caído).
    - `colgado`: la detección de T-AF023-US01-01 reporta cuelgue (varias
      lecturas seguidas sin actividad superando el umbral).
    - `vivo`: en cualquier otro caso (actividad reciente o procesando).

    No toca `agent.status` (ortogonal). `now` inyectable para tests
    deterministas."""
    if agent.status in ("stopped", "unavailable"):
        return SUPERVISION_STOPPED
    verdict = detect_agent_activity(
        activity_history, threshold_seconds=threshold_seconds, now=now
    )
    if verdict == VERDICT_HUNG:
        return SUPERVISION_HUNG
    return SUPERVISION_ALIVE


def resolve_runtime_last_activity(
    runtime_instance, socket_name: str = DEFAULT_SOCKET_NAME
) -> float | None:
    """Resuelve el timestamp (epoch segundos) de la última actividad del
    runtime real de `runtime_instance`, o `None` si no hay fuente determinada.

    - OpenCode: mtime del log interno `~/.local/share/opencode/log/opencode.log`
      (avanza con la actividad real del agente).
    - Resto de runtimes (Claude Code, ...): sin mecanismo determinado — `None`
      (no se declara un cuelgue sin fuente; se reporta `vivo`).

    Defensivo: cualquier error de I/O devuelve `None` (no aborta la consulta)."""
    runtime_type = getattr(getattr(runtime_instance, "runtime", None), "type", None)
    if runtime_type != "opencode":
        return None
    try:
        if _OPENCODE_LOG_PATH.is_file():
            return _OPENCODE_LOG_PATH.stat().st_mtime
    except OSError:
        return None
    return None


def refresh_agent_supervision(
    agent: Agent, socket_name: str = DEFAULT_SOCKET_NAME
) -> Agent:
    """Calcula (perezosamente) y almacena `agent.supervision_status` al
    consultar — mismo patrón que `refresh_agent_liveness`. Devuelve el mismo
    `agent` (mutado in-place) para poder encadenar la llamada.

    Registra la última actividad observada en `agent.activity_history` (acotado)
    y decide `vivo`/`colgado`/`detenido`. No altera el estado funcional."""
    if agent.status in ("stopped", "unavailable"):
        agent.supervision_status = SUPERVISION_STOPPED
        return agent

    runtime_instance = get_runtime_instance_for_agent(agent.id)
    if runtime_instance is None:
        agent.supervision_status = SUPERVISION_STOPPED
        return agent

    session_name = getattr(runtime_instance, "session_name", None)
    if session_name is None or not is_runtime_alive(
        runtime_instance, socket_name=socket_name
    ):
        # Runtime muerto (sin sesión tmux, o servidor headless sin responder)
        # -> detenido/caído.
        agent.supervision_status = SUPERVISION_STOPPED
        return agent

    activity = resolve_runtime_last_activity(runtime_instance, socket_name)
    if activity is not None:
        # Se registra el timestamp observado en CADA lectura (aunque repita el
        # anterior): `detect_agent_activity` necesita las lecturas consecutivas
        # con el mismo valor para declarar un cuelgue. Historial acotado.
        agent.activity_history = (list(agent.activity_history) + [activity])[-_MAX_ACTIVITY_HISTORY:]

    agent.supervision_status = compute_supervision_state(
        agent, agent.activity_history, now=time.time()
    )
    return agent
