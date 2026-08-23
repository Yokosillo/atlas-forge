"""Cola FIFO de Jobs de Tester de UI (T-AF022-US15-04, US-AF022-15):
cuando el Arquitecto aprueba una User Story cuyo alcance toca `10-web/`
(`story_scope.story_touches_web`), se encola automáticamente un Job hacia
el agente Tester con instrucción de navegar la web real (Puppeteer) y
ampliar la suite de `10-web/tests/`.

Mismo patrón arquitectónico que `architect_verdict_queue.py` (cola FIFO,
un único worker daemon, nunca bloquea al llamador) — reutilizado
literalmente como referencia de diseño (ver criterio de aceptación 1 de
la Task, "documentado con su justificación de diseño"): cola SEPARADA en
vez de extender la del Arquitecto, porque el Tester de UI y el veredicto
del Arquitecto son flujos independientes con destinatarios distintos (un
agente Tester, no un Arquitecto) — mezclarlos en la misma cola acoplaría
dos conceptos sin necesidad (un veredicto rechazado nunca debe esperar
detrás de un Job de Tester de UI en curso, y viceversa)."""

from __future__ import annotations

import queue
import threading
from pathlib import Path
from typing import Any


class UiTesterQueueState:
    """Estado consultable de la cola, protegida por Lock — mismo diseño
    que `VerdictQueueState`."""

    def __init__(self) -> None:
        self.waiting_story_ids: list[str] = []
        self.active_story_id: str | None = None
        self._lock = threading.Lock()

    def add_waiting(self, story_id: str) -> None:
        with self._lock:
            self.waiting_story_ids.append(story_id)

    def move_to_active(self, story_id: str) -> None:
        with self._lock:
            self.waiting_story_ids.remove(story_id)
            self.active_story_id = story_id

    def clear_active(self) -> None:
        with self._lock:
            self.active_story_id = None

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "active": self.active_story_id,
                "waiting": list(self.waiting_story_ids),
            }


class _UiTesterQueue:
    """Cola FIFO con un único worker daemon — mismo mecanismo que
    `_ArchitectVerdictQueue`."""

    def __init__(self) -> None:
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._state = UiTesterQueueState()
        self._worker: threading.Thread | None = None
        self._started = False
        self._start_lock = threading.Lock()

    def start(self) -> None:
        with self._start_lock:
            if self._started:
                return
            self._worker = threading.Thread(
                target=self._process_queue,
                daemon=True,
                name="ui-tester-queue-worker",
            )
            self._worker.start()
            self._started = True

    def enqueue(
        self,
        story_id: str,
        session: Any,
        socket_name: str,
        reports_root: Path | None,
        tasks_dir: Path | None,
    ) -> None:
        self.start()
        self._state.add_waiting(story_id)
        self._queue.put(
            {
                "story_id": story_id,
                "session": session,
                "socket_name": socket_name,
                "reports_root": reports_root,
                "tasks_dir": tasks_dir,
            }
        )

    def get_status(self) -> dict[str, Any]:
        return self._state.snapshot()

    def reset_for_testing(self) -> None:
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except queue.Empty:
                break
        self._state = UiTesterQueueState()

    def _process_queue(self) -> None:
        while True:
            item = self._queue.get()
            story_id: str = item["story_id"]
            session: Any = item["session"]
            socket_name: str = item["socket_name"]
            reports_root: Path | None = item["reports_root"]
            tasks_dir: Path | None = item["tasks_dir"]

            self._state.move_to_active(story_id)

            try:
                _do_dispatch_ui_tester(story_id, session, socket_name, reports_root, tasks_dir)
            except Exception:
                pass
            finally:
                self._state.clear_active()

            self._queue.task_done()


_instance = _UiTesterQueue()


def enqueue_ui_tester_job(
    story_id: str,
    session: Any,
    socket_name: str = "default",
    reports_root: Path | None = None,
    tasks_dir: Path | None = None,
) -> None:
    """API pública de la cola FIFO de Jobs de Tester de UI.

    Encola la petición y retorna inmediatamente (criterio de aceptación
    4: "el disparo no bloquea ni retrasa el flujo normal de cierre de la
    US") — el worker daemon la procesa en segundo plano.

    Si el Tester no está presente en `session` o no tiene runtime
    registrado, el Job se descarta silenciosamente cuando el worker
    intente procesarlo — mismo comportamiento que
    `enqueue_architect_verdict` cuando no hay Arquitecto lanzado."""
    _instance.enqueue(story_id, session, socket_name, reports_root, tasks_dir)


def get_ui_tester_queue_status() -> dict[str, Any]:
    return _instance.get_status()


# ═══════════════════════════════════════════════════════════════════════════════
# Despacho real (ejecutado por el worker de la cola, nunca directamente)
# ═══════════════════════════════════════════════════════════════════════════════


def _do_dispatch_ui_tester(
    story_id: str,
    session: Any,
    socket_name: str,
    reports_root: Path | None = None,
    tasks_dir: Path | None = None,
) -> None:
    """Despacha el Job de Tester de UI para `story_id`. Invocado
    exclusivamente por el worker daemon de la cola."""
    from atlas_forge.agents.tester import TESTER_ROLE
    from atlas_forge.core.session_lifecycle import list_agents
    from atlas_forge.dispatcher.job_creation import JobCreationError, create_job
    from atlas_forge.dispatcher.job_dispatch import dispatch_job
    from atlas_forge.dispatcher.ui_tester_input import build_ui_tester_job_description
    from atlas_forge.models import Agent
    from atlas_forge.runtime.agent_runtime_registry import get_runtime_instance_for_agent

    tester_agent = next(
        (
            agent
            for agent in list_agents(session)
            if isinstance(agent, Agent) and agent.role == TESTER_ROLE
        ),
        None,
    )
    if tester_agent is None:
        return

    runtime_instance = get_runtime_instance_for_agent(tester_agent.id)
    if runtime_instance is None:
        return

    description = build_ui_tester_job_description(
        story_id, reports_root=reports_root, tasks_dir=tasks_dir,
    )

    try:
        job = create_job(description, tester_agent, session)
        job.story_id = story_id
        dispatch_job(job, tester_agent, runtime_instance, socket_name=socket_name)
    except JobCreationError:
        pass
