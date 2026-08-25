"""Decisión PURA de relanzamiento automático de un runtime caído
(T-AF004-US04-02, US-AF004-04 · "Detectar y recuperar automáticamente un
runtime caído"): ante un runtime muerto, decidir si se reintenta el
relanzamiento — con un límite de reintentos CONSECUTIVOS configurable
(default 3) — y registrar el resultado, reutilizando `RecoveryRetryTracker`
(T-AF023-US02-01) como contador puro.

Capa de dominio pura: NO depende de tmux, HTTP ni I/O. La ejecución del
relanzamiento (launcher) y la comprobación de vida se inyectan como
callables, de modo que la decisión es testeable de forma determinista.

Semántica por ciclo (un agente cuyo runtime se comprobó):

- `alive=True` -> `record_success` (resetea el contador; un relanzamiento
  con éxito previo devuelve el runtime a vivo y esto se observa aquí).
- `alive=False` y `should_retry()` -> intenta el `relaunch` y registra el
  intento; si se alcanza el límite, el contador pasa a `failed`.
- `alive=False` y límite superado -> no reintenta más (el runtime queda en
  `failed`), sin marcar al agente silenciosamente: se invoca `on_failed`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from atlas_forge.agents.recovery import (
    DEFAULT_MAX_CONSECUTIVE_RETRIES,
    RETRY_STATUS_FAILED,
    RecoveryRetryTracker,
)


@dataclass
class RuntimeRelaunchTrackers:
    """Estado por agente del ciclo de reintentos: un `RecoveryRetryTracker`
    por `agent.id`, con `max_retries` configurable (default 3)."""

    max_retries: int = DEFAULT_MAX_CONSECUTIVE_RETRIES
    trackers: dict[str, RecoveryRetryTracker] = field(default_factory=dict)

    def tracker_for(self, agent_id: str) -> RecoveryRetryTracker:
        return self.trackers.setdefault(
            agent_id, RecoveryRetryTracker(max_retries=self.max_retries)
        )


def decide_auto_relaunch(
    agent_id: str,
    *,
    alive: bool,
    trackers: RuntimeRelaunchTrackers,
    relaunch: Callable[[], bool] | None = None,
    on_failed: Callable[[], None] | None = None,
) -> str:
    """Un paso de decisión puro para el runtime de `agent_id`.

    - `alive=True` -> resetea el contador (`ok`).
    - `alive=False` y el contador permite reintentar -> ejecuta `relaunch`
      (si se aporta) y registra el fallo del ciclo; devuelve `recovering` o
      `failed` (si este intento agota el límite).
    - `alive=False` y límite superado -> devuelve `failed`, invoca
      `on_failed` (marcar al agente/avisar) y NO reintenta.

    Devuelve el `status` resultante del `RecoveryRetryTracker`
    (`ok`/`recovering`/`failed`)."""
    tracker = trackers.tracker_for(agent_id)
    if alive:
        tracker.record_success()
        return tracker.status
    if tracker.should_retry():
        if relaunch is not None:
            relaunch()
        tracker.record_failure("runtime caído; relanzamiento intentado")
        return tracker.status
    if on_failed is not None:
        on_failed()
    return RETRY_STATUS_FAILED


def max_retries_of(trackers: RuntimeRelaunchTrackers) -> int:
    """Expone el límite configurado (para observación/tests)."""
    return trackers.max_retries