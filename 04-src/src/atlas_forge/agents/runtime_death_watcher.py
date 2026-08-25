"""Watcher de fondo que detecta la muerte inesperada de un runtime
(T-AF004-US04-01, US-AF004-04): reacciona proactivamente (sin esperar a que
alguien consulte `GET /agents`) ante un crash/OOM/kill manual del proceso del
runtime de un agente, distinguiéndolo de una parada solicitada.

Mismo patrón que `SessionLimitWatcher` (`agents/session_limit_watcher.py`) y
`PersistentAgentWatcher`: un hilo `daemon` DENTRO del proceso `atlas-forge-api`,
no un script externo — necesita `list_agents` real sobre la `DevelopmentSession`
en memoria.

En cada ciclo se comprueba el runtime de cada agente del session activo y se
marca `unavailable` (vía `mark_unavailable`) a los que murieron sin mediar
`stop`. Se EXCLUYEN los agentes en `stopped` (parada intencional, no un fallo)
— mismo criterio que `_STATUSES_THAT_CAN_BECOME_UNAVAILABLE` de
`agents/liveness.py`.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

from atlas_forge.agents.lifecycle import mark_idle, mark_unavailable
from atlas_forge.agents.recovery import DEFAULT_MAX_CONSECUTIVE_RETRIES
from atlas_forge.agents.runtime_relaunch import (
    RuntimeRelaunchTrackers,
    decide_auto_relaunch,
)
from atlas_forge.core.session_lifecycle import list_agents
from atlas_forge.models import DevelopmentSession
from atlas_forge.runtime.agent_runtime_registry import (
    get_runtime_instance_for_agent,
    register_runtime_instance_for_agent,
)
from atlas_forge.runtime.generic import is_runtime_alive, start_runtime
from atlas_forge.tmux.manager import DEFAULT_SOCKET_NAME

DEFAULT_POLL_INTERVAL_SECONDS = 30.0

# Estados que pueden pasar a `unavailable` ante un runtime caído: un agente en
# `stopped` NO se reporta como caído (parada solicitada, no fallo).
_STATUSES_THAT_CAN_BECOME_UNAVAILABLE = {"idle", "working", "limited"}
# T-AF004-US04-04: un agente `unavailable` (runtime caído) vuelve a operativo
# (`idle`) cuando su runtime se recupera (is_runtime_alive=True).
# T-AF008-US18-04: lo mismo aplica a un agente `failed` por auto-liberación
# ("working sin Job en vuelo") cuyo runtime sigue VIVO — el fallo es del ciclo
# operativo, no del proceso; recuperado el pane (vivo) el agente vuelve a
# `idle` sin intervención manual. `failure_reason` se limpia al transicionar
# a `idle` (mark_idle).
_STATUS_THAT_CAN_RECOVER = {"unavailable", "failed"}


def _default_alive_check(agent: Any, socket_name: str) -> bool:
    """Comprueba si el runtime real de `agent` sigue vivo. Si no hay ningún
    `RuntimeInstance` registrado, se considera vivo (nada que verificar) —
    mismo criterio que `refresh_agent_liveness`."""
    runtime_instance = get_runtime_instance_for_agent(agent.id)
    if runtime_instance is None:
        return True
    return is_runtime_alive(runtime_instance, socket_name=socket_name)


def _relaunch_runtime(agent: Any, session: DevelopmentSession, socket_name: str) -> bool:
    """Relanza el runtime de `agent` en la misma sesión tmux determinista
    (T-AF004-US04-02): reutiliza `start_runtime` (que deriva el nombre de
    sesión con `session_name_for`) y registra el `RuntimeInstance` nuevo en el
    registro (`agent_runtime_registry`). Devuelve `True` si el relanzamiento
    se lanzó sin error. Sin `RuntimeInstance` registrado no hay nada que
    relanzar -> `False` (el intento cuenta como fallido del contador)."""
    runtime_instance = get_runtime_instance_for_agent(agent.id)
    if runtime_instance is None:
        return False
    try:
        new_instance = start_runtime(
            runtime_instance.runtime,
            agent,
            str(session.project_id),
            socket_name=socket_name,
        )
        register_runtime_instance_for_agent(agent.id, new_instance)
        return True
    except Exception:
        return False


def run_runtime_death_cycle(
    session: DevelopmentSession,
    socket_name: str = DEFAULT_SOCKET_NAME,
    *,
    alive_check: Callable[[Any, str], bool] | None = None,
    relaunch: Callable[[Any, str], bool] | None = None,
    retry_policy: RuntimeRelaunchTrackers | None = None,
    notify: Callable[[str, str], None] | None = None,
    notified_failed: set[str] | None = None,
) -> list[str]:
    """Un ciclo de detección proactiva + recuperación + relanzamiento.

    Detección/recuperación (T-AF004-US04-01/-04):
    - Para cada agente cuyo estado puede pasar a `unavailable` (excluye
      `stopped`), si su runtime murió lo marca `unavailable`.
    - Para cada agente `unavailable` cuyo runtime se ha recuperado
      (`is_runtime_alive=True`), lo devuelve a `idle` (operativo).

    Relanzamiento automático (T-AF004-US04-02): si se aporta `relaunch`, ante
    un runtime muerto (detectado o ya `unavailable`) se decide reintentar el
    relanzamiento con el límite de `retry_policy` (`RuntimeRelaunchTrackers`,
    default 3). Un runtime vivo resetea el contador; al agotarse el límite se
    deja de reintentar (estado `failed` del contador), sin descartar al agente
    en silencio (sigue `unavailable`, visible).

    Notificación (T-AF004-US04-03): cuando un runtime agota los reintentos y
    pasa a `failed`, se invoca `notify(agent_id, last_error)` UNA vez por
    episodio de fallo (rastreado en `notified_failed`; al recuperarse el
    agente se rehabilita para un futuro fallo). Esto materializa el aviso
    visible al desarrollador sin repetir la alerta en cada ciclo.

    Devuelve la lista de `agent.id` que cambiaron de estado en este ciclo
    (marcados `unavailable` o recuperados a `idle`).

    `alive_check`/`relaunch`/`notify` son inyectables — permiten a los tests
    simular la muerte, la recuperación, el relanzamiento y la notificación sin
    depender de un tmux real."""
    check = alive_check if alive_check is not None else _default_alive_check
    trackers = retry_policy if retry_policy is not None else RuntimeRelaunchTrackers()
    notified = notified_failed if notified_failed is not None else set()
    changed: list[str] = []
    for agent in list_agents(session):
        status = getattr(agent, "status", None)
        if status == "stopped":
            continue
        if check(agent, socket_name):
            # Runtime operativo: si hay retry conectado, un relanzamiento con
            # éxito previo se observa aquí -> se resetea el contador.
            if relaunch is not None:
                decide_auto_relaunch(agent.id, alive=True, trackers=trackers)
            # Al recuperarse, se rehabilita el aviso para un futuro fallo.
            notified.discard(agent.id)
            if status in _STATUS_THAT_CAN_RECOVER:
                mark_idle(agent)
                changed.append(agent.id)
            continue
        # Runtime muerto: decisión de relanzamiento automático (también para
        # agentes ya `unavailable` de ciclos previos — siguen sin ser
        # `stopped`, así que se les puede reintentar el relanzamiento).
        if relaunch is not None:

            def _on_failed():
                # Idempotente: si el agente ya es `unavailable` (marcado en un
                # ciclo previo), `mark_unavailable` lanzaría una transición
                # inválida — solo se marca si aún no lo está.
                if getattr(agent, "status", None) != "unavailable":
                    mark_unavailable(agent)

            result = decide_auto_relaunch(
                agent.id,
                alive=False,
                trackers=trackers,
                relaunch=lambda: relaunch(agent, socket_name),
                on_failed=_on_failed,
            )
            if result == "failed" and agent.id not in notified:
                # T-AF004-US04-03: notificación visible del fallo (una vez por
                # episodio), con el último error del contador.
                error = trackers.tracker_for(agent.id).last_error or "runtime caído"
                if notify is not None:
                    notify(agent.id, error)
                notified.add(agent.id)
        if status in _STATUSES_THAT_CAN_BECOME_UNAVAILABLE:
            mark_unavailable(agent)
            changed.append(agent.id)
    return changed


class RuntimeDeathWatcher:
    """Hilo `daemon` que llama a `run_runtime_death_cycle` cada
    `poll_interval_seconds` mientras esté vivo. Mismo criterio de
    idempotencia que `SessionLimitWatcher`: `start()` no lanza un segundo hilo
    si ya hay uno vivo."""

    def __init__(
        self,
        session: DevelopmentSession,
        socket_name: str = DEFAULT_SOCKET_NAME,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        *,
        project_root: str | None = None,
        project_name: str | None = None,
        alive_check: Callable[[Any, str], bool] | None = None,
        relaunch: Callable[[Any, str], bool] | None = None,
        max_retries: int = DEFAULT_MAX_CONSECUTIVE_RETRIES,
        notify: Callable[[str, str], None] | None = None,
    ) -> None:
        self._session = session
        self._socket_name = socket_name
        self._poll_interval_seconds = poll_interval_seconds
        self._alive_check = alive_check
        # T-AF004-US04-03: eventos de runtime `failed` (notificación visible y
        # consultable). `_failed_events` acumula las notificaciones emitidas
        # ({agent_id, agent_name, error}); `_notified_failed` evita re-notificar
        # el mismo episodio en cada ciclo (se rehabilita al recuperarse).
        self._failed_events: list[dict] = []
        self._notified_failed: set[str] = set()
        self._project_root = project_root
        self._project_name = project_name
        # T-AF004-US04-02: relanzamiento automático conectado por defecto
        # (reusa `start_runtime` sobre la misma sesión determinista); se
        # puede desactivar pasando `relaunch=None` (p. ej. en tests).
        self._relaunch = (
            (lambda agent, sn: _relaunch_runtime(agent, self._session, sn))
            if relaunch is None
            else relaunch
        )
        self._retry_policy: RuntimeRelaunchTrackers = RuntimeRelaunchTrackers(
            max_retries=max_retries
        )
        self._notify = notify
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def failed_events(self) -> list[dict]:
        """Eventos de runtime `failed` notificados (consultable): lista de
        `{agent_id, agent_name, error, ts}` — la notificación visible de
        T-AF004-US04-03."""
        return list(self._failed_events)

    def poll_interval_seconds(self) -> float:
        """El intervalo de polling configurado (T-AF004-US04-05: configurable,
        no hardcodeado)."""
        return self._poll_interval_seconds

    def _notify_runtime_failed(self, agent_id: str, error: str) -> None:
        """Notificación visible de un runtime `failed`: registra el evento en
        memoria (`_failed_events`) y, si se dispone del proyecto, lo persiste
        en el `reconciliation_log.jsonl` (canal consultable)."""
        agent_name = ""
        for agent in list_agents(self._session):
            if agent.id == agent_id:
                agent_name = getattr(agent, "name", "") or agent_id
                break
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).isoformat()
        event = {"agent_id": agent_id, "agent_name": agent_name, "error": error, "ts": ts}
        self._failed_events.append(event)
        if self._project_root and self._project_name:
            from atlas_forge.core.reconciliation_log import append_runtime_failed_log
            try:
                append_runtime_failed_log(
                    self._project_root, self._project_name,
                    agent_id=agent_id, agent_name=agent_name, error=error, ts=ts,
                )
            except Exception:
                pass

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="runtime-death-watcher"
        )
        self._thread.start()

    def stop(self, timeout: float | None = 2.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def _cycle_kwargs(self) -> dict:
        notify = self._notify if self._notify is not None else self._notify_runtime_failed
        return {
            "alive_check": self._alive_check,
            "relaunch": self._relaunch,
            "retry_policy": self._retry_policy,
            "notify": notify,
            "notified_failed": self._notified_failed,
        }

    def run_once(self) -> list[str]:
        """Ejecuta un único ciclo de forma síncrona, sin hilo — usado en
        tests deterministas que no quieren depender del temporizador real."""
        return run_runtime_death_cycle(
            self._session, self._socket_name, **self._cycle_kwargs()
        )

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                run_runtime_death_cycle(
                    self._session, self._socket_name, **self._cycle_kwargs()
                )
            except Exception:
                # Mismo criterio de "mejor esfuerzo" que el resto de watchers:
                # un fallo inesperado de un ciclo no debe matar el hilo.
                pass
            self._stop_event.wait(self._poll_interval_seconds)