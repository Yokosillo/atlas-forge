"""Historial mínimo de Jobs despachados por agente/sesión (T-FB008-US03-02,
punto 1 de la Descripción): de dónde se obtiene el conteo de Jobs
consecutivos que necesita `should_invoke_scribe_by_job_count`
(T-FB008-US03-01).

## Decisión: registro nuevo, no extender `DevelopmentSession`

Se evaluaron dos opciones:
- Extender `DevelopmentSession` con un contador por agente. Se descarta:
  ese modelo es un dato de dominio ya usado por `session_lifecycle.py`,
  `session_registry.py`, y las pantallas Dashboard/Agentes de la TUI
  (US-FB002-02/03/04) — añadir un campo que solo el Dispatcher necesita
  aumentaría la superficie de un modelo ya estable sin beneficio para
  esos otros consumidores.
- Un registro nuevo, específico del Dispatcher, en memoria de proceso.
  Elegido: mismo patrón ya establecido en este proyecto para
  `_SessionRegistry` (`brain/core/session_registry.py`) — un contador
  indexado por `(session_id, agent_id)`, con el mismo ciclo de vida que
  la sesión de desarrollo real del proceso (vive mientras el proceso
  vive; se resetea explícitamente en tests, igual que
  `_reset_registry_for_tests` de `session_registry.py`).

"Consecutivos" se interpreta como "despachados a ese agente sin que la
sesión se haya cerrado y reabierto" — no hay lógica de "romper la racha"
por otro evento en v1 (no existe todavía ningún evento intermedio
relevante, como un cambio de rol o una pausa de sesión, que deba
resetear el conteo — `paused` es un estado v2 no alcanzable todavía, ver
`session_lifecycle.py`). El conteo se resetea a 0 tras cada disparo de
Scribe por conteo (`should_invoke_scribe_by_job_count`): igual que la
compresión periódica de contexto que motivó este mecanismo (ver
`scribe_trigger.py`) cuenta turnos desde la última compactación, no
turnos totales de la sesión.
"""


class _JobCountRegistry:
    def __init__(self) -> None:
        self._counts: dict[tuple[str, str], int] = {}

    def record_dispatch(self, session_id: str, agent_id: str) -> None:
        """Registra que se ha despachado un Job a `agent_id` dentro de
        `session_id`, incrementando su conteo consecutivo."""
        key = (session_id, agent_id)
        self._counts[key] = self._counts.get(key, 0) + 1

    def get_consecutive_count(self, session_id: str, agent_id: str) -> int:
        """Conteo de Jobs despachados consecutivamente a `agent_id`
        dentro de `session_id` desde el último reseteo (arranque, o
        último disparo de Scribe por conteo)."""
        return self._counts.get((session_id, agent_id), 0)

    def reset_count(self, session_id: str, agent_id: str) -> None:
        """Resetea el conteo consecutivo tras un disparo de Scribe por
        conteo — la racha empieza de nuevo desde ese punto."""
        self._counts[(session_id, agent_id)] = 0


_registry = _JobCountRegistry()


def record_job_dispatch(session_id: str, agent_id: str) -> None:
    _registry.record_dispatch(session_id, agent_id)


def get_consecutive_job_count(session_id: str, agent_id: str) -> int:
    return _registry.get_consecutive_count(session_id, agent_id)


def reset_consecutive_job_count(session_id: str, agent_id: str) -> None:
    _registry.reset_count(session_id, agent_id)


def _reset_registry_for_tests() -> None:
    """Reinicia el registro interno. Uso exclusivo de la suite de tests
    (mismo patrón que `session_registry._reset_registry_for_tests`), para
    que cada test parta de un estado limpio sin depender del orden de
    ejecución de otros tests."""
    global _registry
    _registry = _JobCountRegistry()
