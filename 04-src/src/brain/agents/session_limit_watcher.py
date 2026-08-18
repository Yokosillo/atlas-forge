"""Watcher de fondo que detecta cuándo un agente `claude-code` se queda
sin límite de sesión y le hace ping automáticamente pasada la hora de
reset (T-FB024-US21-01, US-FB024-21).

Mismo patrón arquitectónico que `dispatch_queue_worker.py`
(`DispatchQueueWorker`, T-FB008-US10-02): un hilo `daemon` DENTRO del
propio proceso `brain-api`, no un script externo — necesita
`list_agents`/`get_runtime_instance_for_agent` reales sobre la misma
`DevelopmentSession` en memoria, y mutar el `Agent` en memoria
directamente (`mark_limited`/`clear_session_limit`), igual que
`refresh_agent_liveness` hace con `mark_unavailable`.

## Por qué el ping es "texto real + Enter en llamada separada", no un
## Enter vacío

Verificado experimentalmente el mismo día del incidente que motivó esta
Task (2026-08-17): tras el reset de la sesión, un `Enter` vacío por sí
solo NO reactiva a Claude Code — hace falta enviarle texto real (un
mensaje pidiéndole continuar) seguido de un `Enter` en una invocación
`tmux send-keys` separada. `brain.tmux.manager.run_command` ya cumple
esto por construcción: internamente llama a `libtmux`'s `send_keys(cmd,
enter=True)`, que emite DOS invocaciones reales de `tmux send-keys` (una
con el texto, otra con `Enter` vía `pane.enter()`) — no una sola
combinada. No hace falta ninguna función nueva de bajo nivel para esto,
solo usar `run_command` tal cual, en vez de `send_keys_literal("Enter")`
a secas (que sí sería el Enter vacío insuficiente)."""

from __future__ import annotations

import threading
from datetime import datetime, timezone

from brain.agents.lifecycle import InvalidAgentTransitionError, clear_session_limit, mark_limited
from brain.agents.session_limit import detect_session_limit_block, should_ping_now
from brain.core.session_lifecycle import list_agents
from brain.models import Agent, DevelopmentSession
from brain.runtime.agent_runtime_registry import get_runtime_instance_for_agent
from brain.tmux.manager import DEFAULT_SOCKET_NAME, capture_pane_lines, run_command

DEFAULT_POLL_INTERVAL_SECONDS = 600.0  # 10 minutos, criterio explícito de la US.

_CLAUDE_CODE_RUNTIME_TYPE = "claude-code"

_STATUSES_ELIGIBLE_FOR_LIMIT_CHECK = {"idle", "working"}

# Mensaje real enviado al pane tras el reset — texto no vacío (criterio
# explícito, ver docstring del módulo), pidiendo continuar el trabajo en
# curso sin describirlo (el watcher no conoce el contenido del Job, solo
# que el agente estaba disponible antes de golpear el límite).
PING_MESSAGE = "Tu límite de sesión ya se ha reiniciado. Continúa con el trabajo en el que estabas."


def _resolve_pane_text(agent: Agent, socket_name: str) -> str | None:
    runtime_instance = get_runtime_instance_for_agent(agent.id)
    if runtime_instance is None or runtime_instance.runtime.type != _CLAUDE_CODE_RUNTIME_TYPE:
        return None
    try:
        lines = capture_pane_lines(runtime_instance.session_name, socket_name=socket_name)
    except Exception:
        # Mismo criterio de "mejor esfuerzo" que el resto de watchers de
        # fondo (`DispatchQueueWorker._run_loop`): un pane no capturable
        # ahora mismo (sesión en transición, tmux ocupado) no debe tumbar
        # el ciclo completo, solo se salta este agente.
        return None
    return "\n".join(lines)


def run_session_limit_cycle(
    session: DevelopmentSession,
    socket_name: str = DEFAULT_SOCKET_NAME,
    now: datetime | None = None,
) -> list[str]:
    """Un único ciclo: revisa el pane de cada agente `claude-code`
    `idle`/`working`, detecta el patrón de bloqueo total, y:

    - si no estaba ya `limited`, lo marca `limited` con la hora de reset
      (criterios 1-2).
    - si ya estaba `limited` y ya pasó la hora de reset + margen, envía el
      ping real y lo devuelve a `idle` (criterio 5); si el patrón de
      límite sigue presente tras leerlo, no reintenta en bucle dentro de
      este mismo ciclo — se reintenta en el siguiente (criterio 6, mismo
      principio que `run_dispatch_cycle`).
    - si un agente `limited` ya NO muestra el patrón (recuperó actividad
      normal por su cuenta, sin necesitar el ping), limpia el estado
      igualmente (criterio 7).

    Devuelve la lista de `agent.id` a los que se les envió el ping en
    este ciclo (uso principal: tests deterministas)."""
    if now is None:
        now = datetime.now(timezone.utc)

    pinged: list[str] = []

    for agent in list_agents(session):
        if not isinstance(agent, Agent):
            continue

        pane_text = _resolve_pane_text(agent, socket_name)
        if pane_text is None:
            continue

        if agent.status in _STATUSES_ELIGIBLE_FOR_LIMIT_CHECK:
            reset_at = detect_session_limit_block(pane_text, now=now)
            if reset_at is not None:
                mark_limited(agent, reset_at.isoformat())
            continue

        if agent.status == "limited":
            # Fuente de verdad: `agent.limited_until`, ya calculado y
            # fijado en el ciclo que detectó el bloqueo — NUNCA se
            # re-parsea la hora del pane contra el `now` de este ciclo.
            # `detect_session_limit_block`/`parse_reset_time` asumen que
            # una hora ya pasada respecto a `now` es la ocurrencia de
            # MAÑANA (para el primer aviso, que siempre anuncia un reset
            # futuro) — reaplicar esa heurística aquí, con `now` ya
            # avanzado más allá del reset real, reinterpretaría el
            # mismísimo reset ya ocurrido como si fuera el de mañana,
            # dejando al agente "limited" para siempre (bug real
            # detectado por `test_watcher_pings_and_clears_status_once_reset_time_plus_margin_has_passed`
            # durante el desarrollo de esta Task).
            reset_at = datetime.fromisoformat(agent.limited_until) if agent.limited_until else None
            if reset_at is None:
                clear_session_limit(agent)
                continue

            still_blocked = detect_session_limit_block(pane_text, now=now) is not None
            if not still_blocked:
                # Ya no muestra el patrón — recuperó actividad normal por
                # su cuenta (criterio 7), sin necesitar el ping.
                clear_session_limit(agent)
                continue

            if not should_ping_now(reset_at, now=now):
                continue

            runtime_instance = get_runtime_instance_for_agent(agent.id)
            if runtime_instance is None:
                continue

            run_command(runtime_instance.session_name, PING_MESSAGE, socket_name=socket_name)
            pinged.append(agent.id)
            try:
                clear_session_limit(agent)
            except InvalidAgentTransitionError:
                # Defensivo: si algo externo ya lo transicionó fuera de
                # `limited` entre la comprobación y aquí (p. ej. detenido
                # a propósito a mitad de ciclo), no hay nada que limpiar.
                pass

    return pinged


class SessionLimitWatcher:
    """Hilo `daemon` que llama a `run_session_limit_cycle` cada
    `poll_interval_seconds` mientras esté vivo. Mismo criterio de
    idempotencia que `DispatchQueueWorker`/`launch_architect_queue_watcher`:
    `start()` no lanza un segundo hilo si ya hay uno vivo."""

    def __init__(
        self,
        session: DevelopmentSession,
        socket_name: str = DEFAULT_SOCKET_NAME,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    ) -> None:
        self._session = session
        self._socket_name = socket_name
        self._poll_interval_seconds = poll_interval_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="session-limit-watcher"
        )
        self._thread.start()

    def stop(self, timeout: float | None = 2.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def run_once(self) -> list[str]:
        """Ejecuta un único ciclo de forma síncrona, sin hilo — usado en
        tests deterministas que no quieren depender del temporizador
        real del polling."""
        return run_session_limit_cycle(self._session, self._socket_name)

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                run_session_limit_cycle(self._session, self._socket_name)
            except Exception:
                # Mismo criterio de "mejor esfuerzo" que
                # `DispatchQueueWorker._run_loop`: un fallo inesperado de
                # un ciclo no debe matar el hilo de fondo.
                pass
            self._stop_event.wait(self._poll_interval_seconds)
