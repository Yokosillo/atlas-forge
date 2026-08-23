"""Vigilancia periódica PROACTIVA de los agentes persistentes de una sesión
activa (T-AF023-US05-01, US-AF023-05).

`refresh_agent_liveness` (T-AF016-US01-07) solo se ejecuta al consultar
(`GET /agents`). Este watcher ejecuta la misma comprobación de forma
periódica, SIN depender de una consulta previa: si el proceso/sesión tmux
real de un agente persistente (Arquitecto y otros con `persistent=true`,
US-AF023-03) desapareció (crash, OOM, kill manual), el agente pasa a
`unavailable` en memoria aunque nadie haya llamado a `GET /agents`.

Deliberadamente NO relanza automáticamente (eso es US-AF023-02): esta Task
solo detecta y deja constancia, usando el mismo estado `unavailable` que
`refresh_agent_liveness`.

Mismo patrón arquitectónico que `SessionLimitWatcher`
(`session_limit_watcher.py`, T-AF024-US21-01) y `DispatchQueueWorker`
(`dispatch_queue_worker.py`, T-AF008-US10-02): un hilo `daemon` DENTRO del
proceso `atlas-forge-api`, con un ciclo de "mejor esfuerzo" que nunca tumba el
hilo por un fallo puntual.
"""

from __future__ import annotations

import threading

from atlas_forge.agents.liveness import refresh_agent_liveness
from atlas_forge.core.reconciliation_log import append_unreachable_agent_log
from atlas_forge.core.session_lifecycle import list_agents
from atlas_forge.models import Agent, DevelopmentSession
from atlas_forge.tmux.manager import DEFAULT_SOCKET_NAME

DEFAULT_POLL_INTERVAL_SECONDS = 60.0


def run_persistent_agent_cycle(
    session: DevelopmentSession,
    socket_name: str = DEFAULT_SOCKET_NAME,
    project_root: str | None = None,
    project_name: str | None = None,
) -> list[str]:
    """Un único ciclo: comprueba la operatividad real (liveness) de cada
    agente PERSISTENTE (`agent.persistent is True`) de `session` vía
    `refresh_agent_liveness`, sin necesitar una consulta previa.

    Devuelve la lista de `agent.id` cuyo estado quedó `unavailable` en este
    ciclo (proceso/sesión real desaparecido) — el estado consultable de
    inalcanzable que exige el criterio 2. Los agentes no persistentes no se
    comprueban aquí (bajo demanda, no objeto de esta vigilancia).

    Si se indican `project_root`/`project_name` (T-AF023-US05-02), cada
    agente que pasa a `unavailable` en este ciclo queda además registrado en
    el `reconciliation_log.jsonl` (motivo `persistent_agent_unreachable`) —
    constancia visible en un canal consultable por un humano sin abrir la
    web/TUI. Deliberadamente NO relanza nada (solo detección y constancia)."""
    became_unavailable: list[str] = []
    for agent in list_agents(session):
        if not isinstance(agent, Agent):
            continue
        if not getattr(agent, "persistent", False):
            continue
        before = agent.status
        refresh_agent_liveness(agent, socket_name=socket_name)
        if agent.status == "unavailable" and before != "unavailable":
            became_unavailable.append(agent.id)
            if project_root is not None and project_name is not None:
                try:
                    append_unreachable_agent_log(
                        project_root, project_name,
                        agent_id=agent.id,
                        agent_name=agent.name,
                        reason="proceso/sesión persistente real desaparecido (liveness)",
                    )
                except Exception:
                    # Mejor esfuerzo: un fallo de escritura del log no debe
                    # tumbar el ciclo ni impedir marcar el agente.
                    pass
    return became_unavailable


class PersistentAgentWatcher:
    """Hilo `daemon` que llama a `run_persistent_agent_cycle` cada
    `poll_interval_seconds` mientras esté vivo. Mismo criterio de
    idempotencia que `SessionLimitWatcher`/`DispatchQueueWorker`:
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
            target=self._run_loop, daemon=True, name="persistent-agent-watcher"
        )
        self._thread.start()

    def stop(self, timeout: float | None = 2.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def run_once(self) -> list[str]:
        """Ejecuta un único ciclo de forma síncrona, sin hilo — usado en
        tests deterministas que no quieren depender del temporizador real
        del polling."""
        return run_persistent_agent_cycle(self._session, self._socket_name)

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                run_persistent_agent_cycle(self._session, self._socket_name)
            except Exception:
                # Mismo criterio de "mejor esfuerzo" que el resto de
                # watchers de fondo: un fallo puntual no mata el hilo.
                pass
            self._stop_event.wait(self._poll_interval_seconds)
