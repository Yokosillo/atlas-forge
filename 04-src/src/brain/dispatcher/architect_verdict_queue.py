"""Cola FIFO de veredictos hacia el Arquitecto (T-FB022-US07-01):
garantiza que dos Jobs de Developer que se completan casi simultáneamente no
envíen sus veredictos al Arquitecto en paralelo — el segundo espera en cola
hasta que el primero termina, sin solapar contexto entre Tasks distintas.

El Arquitecto nunca tiene más de un Job de veredicto en curso a la vez,
coherente con la decisión de que es un rol reactivo de contexto pesado por
Task (ver FB-022, Contexto).

Uso:
    from brain.dispatcher.architect_verdict_queue import (
        enqueue_architect_verdict,
        get_verdict_queue_status,
    )

    enqueue_architect_verdict(story_id, session, socket_name)
    # ... inmediatamente en cola si el worker ya está procesando otro.
    status = get_verdict_queue_status()
    # {"active": "US-FB022-10", "waiting": ["US-FB022-11"]}
    # "active" es None si no hay veredicto en curso.
"""

from __future__ import annotations

import queue
import threading
from pathlib import Path
from typing import Any


class VerdictQueueState:
    """Estado consultable de la cola de veredictos, protegida por Lock."""

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


class _ArchitectVerdictQueue:
    """Cola FIFO con un único worker daemon que procesa los veredictos uno
    detrás de otro, sin solapamiento."""

    def __init__(self) -> None:
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._state = VerdictQueueState()
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
                name="verdict-queue-worker",
            )
            self._worker.start()
            self._started = True

    def enqueue(
        self,
        story_id: str,
        session: Any,
        socket_name: str,
        reports_root: Path | None,
    ) -> None:
        """Encola una petición de veredicto. El worker arranca en el primer
        `enqueue` si aún no lo ha hecho."""
        self.start()
        self._state.add_waiting(story_id)
        self._queue.put(
            {
                "story_id": story_id,
                "session": session,
                "socket_name": socket_name,
                "reports_root": reports_root,
            }
        )

    def get_status(self) -> dict[str, Any]:
        return self._state.snapshot()

    def reset_for_testing(self) -> None:
        """Restaura la cola a su estado inicial para aislamiento entre tests.

        Drena todos los items pendientes y reinicia el estado — el worker
        daemon sigue vivo (no se puede matar sin más), pero la cola queda
        vacía y con active=None, lista para el siguiente test."""
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except queue.Empty:
                break
        self._state = VerdictQueueState()

    def _process_queue(self) -> None:
        while True:
            item = self._queue.get()
            story_id: str = item["story_id"]
            session: Any = item["session"]
            socket_name: str = item["socket_name"]
            reports_root: Path | None = item["reports_root"]

            self._state.move_to_active(story_id)

            try:
                _do_dispatch_verdict(story_id, session, socket_name, reports_root)
            except Exception:
                pass
            finally:
                self._state.clear_active()

            self._queue.task_done()


_instance = _ArchitectVerdictQueue()


def enqueue_architect_verdict(
    story_id: str,
    session: Any,
    socket_name: str = "default",
    reports_root: Path | None = None,
) -> None:
    """API pública de la cola FIFO de veredictos.

    Encola la petición y retorna inmediatamente — el worker daemon procesa
    los veredictos uno detrás de otro en orden de llegada.

    Si el Arquitecto no está presente en `session` o no tiene runtime
    registrado, el veredicto se descarta silenciosamente cuando el worker
    intente procesarlo — mismo comportamiento que `trigger_architect_verdict`
    antes de la cola.
    """
    _instance.enqueue(story_id, session, socket_name, reports_root)


def get_verdict_queue_status() -> dict[str, Any]:
    """Estado actual de la cola de veredictos.

    Devuelve:
        {"active": <story_id o None>, "waiting": [<story_id>, ...]}
    """
    return _instance.get_status()


# ═══════════════════════════════════════════════════════════════════════════════
# Despacho real (ejecutado por el worker de la cola, nunca directamente)
# ═══════════════════════════════════════════════════════════════════════════════


def _do_dispatch_verdict(
    story_id: str,
    session: Any,
    socket_name: str,
    reports_root: Path | None = None,
) -> None:
    """Despacha un Job de veredicto concreto hacia el Arquitecto y procesa
    su resultado. Invocado exclusivamente por el worker daemon de la cola.

    Lógica extraída de `trigger_architect_verdict` (T-FB022-US05-02), sin
    cambios — la cola solo añade serialización externa, no modifica el
    contrato de despacho.
    """
    from brain.agents.arquitecto import ARQUITECTO_ROLE
    from brain.core.session_lifecycle import list_agents
    from brain.dispatcher.job_creation import JobCreationError, create_job
    from brain.dispatcher.job_dispatch import dispatch_job
    from brain.dispatcher.job_plan_dispatch import (
        _collect_story_reports,
        _process_verdict_result,
    )
    from brain.models import Agent
    from brain.runtime.agent_runtime_registry import get_runtime_instance_for_agent

    root = (
        reports_root
        if reports_root
        else Path(__file__).resolve().parents[4] / "07-informes"
    )
    reports = _collect_story_reports(story_id, root)

    architect_agent = next(
        (
            agent
            for agent in list_agents(session)
            if isinstance(agent, Agent) and agent.role == ARQUITECTO_ROLE
        ),
        None,
    )
    if architect_agent is None:
        return

    runtime_instance = get_runtime_instance_for_agent(architect_agent.id)
    if runtime_instance is None:
        return

    if reports:
        report_blocks = "\n\n---\n\n".join(reports)
        description = (
            f"Revisa el trabajo completado para la User Story {story_id}.\n\n"
            f"A continuación se incluyen los informes de cierre de cada Job "
            f"que trabajó en esta User Story. Emite tu veredicto en el "
            f"formato estructurado ESTADO:/JUSTIFICACIÓN:/"
            f"SIGUIENTE_PROMPT_PARA_WORKER:\n\n"
            f"{report_blocks}"
        )
    else:
        description = (
            f"Revisa el trabajo completado para la User Story {story_id}.\n\n"
            f"(No se encontraron informes de cierre para esta User Story. "
            f"Emite tu veredicto basándote en el contexto disponible.)"
        )

    try:
        job = create_job(description, architect_agent, session)
        dispatch_job(job, architect_agent, runtime_instance, socket_name=socket_name)
        _process_verdict_result(story_id, job.result)
    except JobCreationError:
        pass
