"""Lógica PURA de recuperación de un agente colgado (T-AF023-US02-01): decidir
y planificar la recuperación (matar → relanzar conservando el contexto cuando
el runtime lo permite, OpenCode con `--session <id>`), con límite de reintentos
consecutivos y estado consultable del resultado.

Capa de dominio pura: no depende de HTTP, persistencia ni tmux directo — es
testeable de forma determinista. La ejecución real de kill/relaunch se conecta
en la Task T-AF023-US02-02.

Se apoya en:
- la señal de "colgado" de US-AF023-01 (T-AF023-US01-01/02);
- el mecanismo headless de OpenCode (T-AF023-US04-01) para el relanzamiento
  con `--session <id>` (conserva el contexto de la sesión).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Límite por defecto de reintentos CONSECUTIVOS (documentado en el código):
# tras este número de fallos seguidos se deja de reintentar automáticamente y
# el agente queda en un estado de fallo consultable — nunca se reintenta de
# forma indefinida. Configurable por parámetro/instancia.
DEFAULT_MAX_CONSECUTIVE_RETRIES = 3

# Acciones de recuperación posibles (vocabulario canónico de la Task).
ACTION_NONE = "none"
ACTION_RELAUNCH_PRESERVING_CONTEXT = "relaunch_preserving_context"
ACTION_RELAUNCH = "relaunch"

# Estados consultables del contador de reintentos.
RETRY_STATUS_OK = "ok"
RETRY_STATUS_RECOVERING = "recovering"
RETRY_STATUS_FAILED = "failed"

# Runtimes que admiten relanzamiento conservando el contexto de la sesión
# (vía `opencode run --session <id>` del mecanismo headless, T-AF023-US04-01).
_CONTEXT_PRESERVING_RUNTIMES = {"opencode"}


@dataclass(frozen=True)
class RecoveryPlan:
    """Plan de recuperación para un agente colgado (decisión pura).

    - `action`: `none` (sin recuperación), `relaunch_preserving_context`
      (matar + relanzar conservando la sesión), o `relaunch` (matar +
      relanzar sin conservar contexto).
    - `kill_needed`: si la recuperación requiere matar el proceso primero.
    - `session_id`: id de sesión a conservar en el relanzamiento (OpenCode).
    - `relaunch_args`: argumentos del comando de relanzamiento (incluye
      `--session`/`--auto` cuando aplica)."""

    action: str = ACTION_NONE
    kill_needed: bool = False
    session_id: str | None = None
    relaunch_args: tuple[str, ...] = ()

    @property
    def recovers(self) -> bool:
        return self.action in (ACTION_RELAUNCH_PRESERVING_CONTEXT, ACTION_RELAUNCH)


def plan_recovery(
    hung: bool,
    runtime_type: str | None,
    session_id: str | None = None,
) -> RecoveryPlan:
    """Plan de recuperación puro a partir de la señal de "colgado" (`hung`) y
    del runtime del agente:

    - `hung` falso -> `action="none"`, sin matar nada.
    - runtime `opencode`: relanzar CONSERVANDO el contexto con
      `--session <id>` (si se dispone de `session_id`); sin `session_id`, se
      relanza sin contexto.
    - resto de runtimes: relanzar sin conservar contexto (no hay mecanismo
      de sesión equivalente).

    No ejecuta nada — solo decide y planifica."""
    if not hung:
        return RecoveryPlan(action=ACTION_NONE, kill_needed=False)

    if runtime_type in _CONTEXT_PRESERVING_RUNTIMES:
        if session_id:
            return RecoveryPlan(
                action=ACTION_RELAUNCH_PRESERVING_CONTEXT,
                kill_needed=True,
                session_id=session_id,
                # Relanzamiento conservando la sesión (mecanismo headless de
                # T-AF023-US04-01, sin modal de permisos interactivo). La URL
                # de attach concreta la resuelve la ejecución (Task 02).
                relaunch_args=("--session", session_id, "--auto"),
            )
        return RecoveryPlan(action=ACTION_RELAUNCH, kill_needed=True)

    return RecoveryPlan(action=ACTION_RELAUNCH, kill_needed=True)


@dataclass
class RecoveryRetryTracker:
    """Contador de reintentos consecutivos de recuperación (estado consultable).

    - `max_retries`: límite configurable (por defecto 3).
    - `consecutive_retries`: fallos seguidos registrados.
    - `status`: `ok` (recuperado/operativo), `recovering` (reintentando),
      o `failed` (se superó el límite; no se reintenta más).
    - `last_error`: motivo del último fallo (consultable).

    Pura y determinista; no depende de infraestructura."""

    max_retries: int = DEFAULT_MAX_CONSECUTIVE_RETRIES
    consecutive_retries: int = 0
    status: str = RETRY_STATUS_OK
    last_error: str | None = None

    def should_retry(self) -> bool:
        """`True` si aún no se superó el límite de reintentos consecutivos."""
        return self.consecutive_retries < self.max_retries

    def record_failure(self, error: str | None = None) -> "RecoveryRetryTracker":
        """Registra un intento fallido: incrementa el contador; si se alcanza
        el límite, el estado pasa a `failed` (deja de reintentar). Devuelve el
        propio tracker para encadenar."""
        self.consecutive_retries += 1
        self.last_error = error
        self.status = (
            RETRY_STATUS_FAILED
            if self.consecutive_retries >= self.max_retries
            else RETRY_STATUS_RECOVERING
        )
        return self

    def record_success(self) -> "RecoveryRetryTracker":
        """Registra una recuperación con éxito: resetea el contador y el estado
        a `ok`."""
        self.consecutive_retries = 0
        self.last_error = None
        self.status = RETRY_STATUS_OK
        return self
