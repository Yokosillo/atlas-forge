"""Cola FIFO de veredictos hacia el Arquitecto (T-AF022-US07-01):
garantiza que dos Jobs de Developer que se completan casi simultáneamente no
envíen sus veredictos al Arquitecto en paralelo — el segundo espera en cola
hasta que el primero termina, sin solapar contexto entre Tasks distintas.

El Arquitecto nunca tiene más de un Job de veredicto en curso a la vez,
coherente con la decisión de que es un rol reactivo de contexto pesado por
Task (ver AF-022, Contexto).

**Estado tras T-AF008-US14-02 (refactor 2026-08-17):** el disparo real del
veredicto en producción ya no pasa por `enqueue_architect_verdict` —
`trigger_architect_verdict` (`job_plan_dispatch.py`) solo marca la User
Story en `state: REVIEW`, y es `dispatch_queue_worker.run_architect_verdict_dispatch_cycle`
(polling del Dispatcher, mismo criterio "un agente libre a la vez" que ya
usa para Developer/Tester) quien la asigna a un Arquitecto libre y ejecuta
el ciclo completo (`dispatch_queue_worker.dispatch_architect_verdict`,
que esta misma cola importa y delega en vez de duplicar). Esta cola FIFO
sigue viva solo para `ui_tester_queue.py` (serialización del Job de
Tester de UI) y para compatibilidad de los tests de integración
existentes — el Dispatcher es quien posee el ciclo de veredicto de
principio a fin, no esta cola.

Uso (ruta histórica, todavía funcional):
    from atlas_forge.dispatcher.architect_verdict_queue import (
        enqueue_architect_verdict,
        get_verdict_queue_status,
    )

    enqueue_architect_verdict(story_id, session, socket_name)
    # ... inmediatamente en cola si el worker ya está procesando otro.
    status = get_verdict_queue_status()
    # {"active": "US-AF022-10", "waiting": ["US-AF022-11"]}
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
    backlog_dir: Path | None = None,
) -> None:
    """Despacha un Job de veredicto concreto hacia el Arquitecto y procesa
    su resultado. Invocado exclusivamente por el worker daemon de esta
    cola FIFO histórica (todavía en uso indirecto vía
    `ui_tester_queue.py` para el Tester de UI, `T-AF022-US15-04`).

    Refactor 2026-08-17 (T-AF008-US14-02, "el flujo de trabajo debe
    estar encadenado en el dispatcher"): la lógica real de despacho +
    interpretar el veredicto + promoción de estado vive ahora en
    `dispatch_queue_worker.dispatch_architect_verdict` — el Dispatcher
    de polling pasa a poseer el ciclo completo. Esta función queda como
    delegación fina para no duplicar esa lógica en dos módulos."""
    from atlas_forge.dispatcher.dispatch_queue_worker import dispatch_architect_verdict
    from atlas_forge.dispatcher.job_plan_dispatch import _collect_story_reports

    verdict_output = dispatch_architect_verdict(
        story_id, session, socket_name, reports_root, backlog_dir=backlog_dir
    )
    if verdict_output is None:
        return

    root = (
        reports_root
        if reports_root
        else Path(__file__).resolve().parents[4] / "07-informes"
    )
    reports = _collect_story_reports(story_id, root)
    _maybe_enqueue_ui_tester(story_id, verdict_output, reports, session, socket_name, reports_root)


def _maybe_enqueue_ui_tester(
    story_id: str,
    verdict_output: str,
    reports: list[str],
    session: Any,
    socket_name: str,
    reports_root: Path | None,
) -> None:
    """T-AF022-US15-04: si el veredicto fue aprobado (con o sin
    observaciones) y la User Story toca `10-web/` (heurística sobre los
    informes de cierre ya leídos — ver `story_scope.py` para la
    justificación de diseño), encola un Job de Tester de UI.

    Se ejecuta tras `_process_verdict_result`, en el mismo hilo del
    worker de la cola de veredictos — nunca bloquea el flujo de cierre de
    la US (criterio de aceptación 4): `enqueue_ui_tester_job` solo
    encola y retorna, el Job de Tester real lo procesa un worker daemon
    DISTINTO en segundo plano."""
    from atlas_forge.dispatcher.architect_verdict import (
        VERDICT_APPROVED,
        VERDICT_APPROVED_WITH_NOTES,
        parse_verdict,
    )
    from atlas_forge.dispatcher.story_scope import story_touches_web
    from atlas_forge.dispatcher.ui_tester_queue import enqueue_ui_tester_job

    if not verdict_output:
        return

    estado, _justificacion, _siguiente_prompt = parse_verdict(verdict_output)
    if estado not in (VERDICT_APPROVED, VERDICT_APPROVED_WITH_NOTES):
        return

    if not story_touches_web(reports):
        return

    enqueue_ui_tester_job(story_id, session, socket_name, reports_root)
