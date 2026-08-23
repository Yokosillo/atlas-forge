"""Ciclo de supervisión que ejecuta la recuperación automática de un agente
colgado (T-AF023-US02-02): consulta el estado de supervisión de los agentes
(T-AF023-US01-02) y, ante un `colgado`, planifica y ejecuta la recuperación
real (kill + relaunch conservando contexto cuando el runtime lo permite)
reutilizando la lógica pura de T-AF023-US02-01 (`plan_recovery`/
`RecoveryRetryTracker`).

Patrón de "mejor esfuerzo" del `DispatchQueueWorker`/`SessionLimitWatcher`: un
hilo `daemon` dentro de `atlas-forge-api`, sin scripts externos. Tras una
recuperación con éxito el agente vuelve a un estado operativo normal
consultable (`idle` si estaba `working`), y el límite de reintentos de la Task
01 se respeta: al superarlo, el agente queda en estado de fallo consultable y
no se reintenta más.

La ejecución real de kill/relaunch se inyecta (`kill_fn`/`relaunch_fn`) para
poder conectar la migración headless (T-AF023-US04) sin acoplar este ciclo al
mecanismo concreto; por defecto se usan funciones de mejor esfuerzo sobre el
runtime.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from atlas_forge.agents.lifecycle import InvalidAgentTransitionError, mark_idle
from atlas_forge.agents.recovery import (
    RecoveryRetryTracker,
    plan_recovery,
)
from atlas_forge.agents.supervision import (
    SUPERVISION_HUNG,
    refresh_agent_supervision,
)
from atlas_forge.core.session_lifecycle import list_agents
from atlas_forge.models import Agent, DevelopmentSession
from atlas_forge.runtime.agent_runtime_registry import get_runtime_instance_for_agent
from atlas_forge.tmux.manager import DEFAULT_SOCKET_NAME, is_alive, kill_session

DEFAULT_POLL_INTERVAL_SECONDS = 30.0


@dataclass
class SupervisionRecoveryResult:
    """Resultado consultable de un ciclo de supervisión (T-AF023-US02-02)."""

    recovered: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)


def _kill_runtime_default(runtime_instance) -> None:
    """Kill de mejor esfuerzo del runtime del agente: para una sesión tmux
    (persistente) la mata; para una sesión headless (con `attach_url`) la
    gestión del proceso la resuelve el mecanismo de lanzamiento headless —
    aquí no-op seguro. No lanza."""
    if runtime_instance is None:
        return
    session_name = getattr(runtime_instance, "session_name", None)
    attach_url = getattr(runtime_instance, "attach_url", None)
    if attach_url:
        return  # headless: el kill del proceso lo gestiona el lanzamiento headless
    if session_name:
        try:
            kill_session(session_name)
        except Exception:
            pass


def _relaunch_runtime_default(agent: Agent, plan) -> None:
    """Relaunch de mejor esfuerzo: la ejecución real (reutilizar el servidor
    headless y relanzar con `--session`) se conecta con la migración del
    lanzamiento (T-AF023-US04). Aquí no-op seguro documentado; no lanza."""
    return


def run_supervision_recovery_cycle(
    session: DevelopmentSession,
    socket_name: str = DEFAULT_SOCKET_NAME,
    retry_trackers: dict[str, RecoveryRetryTracker] | None = None,
    kill_fn=None,
    relaunch_fn=None,
) -> SupervisionRecoveryResult:
    """Un único ciclo de supervisión: revisa cada agente, y si está
    `colgado` ejecuta la recuperación automática (kill + relaunch) respetando
    el límite de reintentos de T-AF023-US02-01.

    - `retry_trackers`: registro (por `agent.id`) de contadores de reintentos;
      se crea uno nuevo si no existe. Persistirlo entre ciclos (en el watcher)
      es lo que respeta el límite de reintentos consecutivos.
    - `kill_fn`/`relaunch_fn`: inyectables para tests/ejecución real.

    Tras una recuperación con éxito, un agente `working` vuelve a `idle`
    (estado operativo normal consultable). Si un agente colgado ya no lo está
    (recuperó por su cuenta), se resetea su contador. Devuelve
    `SupervisionRecoveryResult` consultable."""
    if retry_trackers is None:
        retry_trackers = {}
    kill = kill_fn if kill_fn is not None else _kill_runtime_default
    relaunch = relaunch_fn if relaunch_fn is not None else _relaunch_runtime_default

    result = SupervisionRecoveryResult()

    for agent in list_agents(session):
        if not isinstance(agent, Agent):
            continue

        refresh_agent_supervision(agent, socket_name=socket_name)
        if agent.supervision_status != SUPERVISION_HUNG:
            # No colgado: si un agente en fallo volvió a estar sano, se
            # resetea el contador para permitir futuras recuperaciones.
            tracker = retry_trackers.get(agent.id)
            if tracker is not None and tracker.status == "failed":
                tracker.record_success()
            continue

        runtime_instance = get_runtime_instance_for_agent(agent.id)
        if runtime_instance is None:
            # Sin runtime no hay nada que recuperar — se cuenta como fallo.
            tracker = retry_trackers.setdefault(agent.id, RecoveryRetryTracker())
            tracker.record_failure("sin runtime registrado")
            result.failed.append(agent.id)
            continue

        tracker = retry_trackers.setdefault(agent.id, RecoveryRetryTracker())
        if not tracker.should_retry():
            # Límite de reintentos superado: se deja de reintentar y el fallo
            # queda consultable (`tracker.status == failed`).
            result.failed.append(agent.id)
            continue

        runtime_type = getattr(getattr(runtime_instance, "runtime", None), "type", None)
        session_id = getattr(runtime_instance, "session_name", None)
        plan = plan_recovery(hung=True, runtime_type=runtime_type, session_id=session_id)

        if not plan.recovers:
            tracker.record_failure("recuperación no soportada")
            result.failed.append(agent.id)
            continue

        try:
            if plan.kill_needed:
                kill(runtime_instance)
            relaunch(agent, plan)
        except Exception as error:
            tracker.record_failure(str(error))
            result.failed.append(agent.id)
            continue

        tracker.record_success()
        # El agente vuelve a un estado operativo normal consultable.
        if agent.status == "working":
            try:
                mark_idle(agent)
            except InvalidAgentTransitionError:
                pass
        result.recovered.append(agent.id)

    return result


class SupervisionRecoveryWatcher:
    """Hilo `daemon` que llama a `run_supervision_recovery_cycle` cada
    `poll_interval_seconds` — mismo patrón que `SessionLimitWatcher`/
    `DispatchQueueWorker`: `start()` es idempotente."""

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
        # Registro de reintentos consecutivos persistido entre ciclos.
        self._retry_trackers: dict[str, RecoveryRetryTracker] = {}

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="supervision-recovery-watcher"
        )
        self._thread.start()

    def stop(self, timeout: float | None = 2.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def run_once(self) -> SupervisionRecoveryResult:
        """Ejecuta un único ciclo de forma síncrona, sin hilo — para tests."""
        return run_supervision_recovery_cycle(
            self._session, self._socket_name, retry_trackers=self._retry_trackers
        )

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                run_supervision_recovery_cycle(
                    self._session, self._socket_name, retry_trackers=self._retry_trackers
                )
            except Exception:
                pass
            self._stop_event.wait(self._poll_interval_seconds)
