"""Tests unitarios de `atlas_forge.dispatcher.dispatch_queue` (T-AF008-US10-01),
sin pasar por HTTP — cubre el mecanismo de persistencia (fichero JSON
mutable por proyecto) y las transiciones de estado en aislamiento. Los
tests end-to-end vía `POST/GET/DELETE /backlog/...` viven en
`test_api_routes_dispatch_queue.py`."""

import pytest

from atlas_forge.dispatcher.dispatch_queue import (
    STATUS_AWAITING_TESTER,
    STATUS_COMPLETED,
    STATUS_DISPATCHED,
    STATUS_FAILED,
    STATUS_QUEUED,
    TaskAlreadyDispatchedError,
    TaskAlreadyQueuedError,
    TaskNotQueuedError,
    TaskNotTerminalError,
    QueueEntry,
    clear_completed,
    clear_history,
    dequeue_task,
    derive_effective_status,
    dispatch_queue_path,
    enqueue_task,
    get_queue,
    mark_completed,
    mark_dispatched,
    mark_failed,
    remove_entry,
)


def test_dispatch_queue_path_matches_architect_queue_state_directory(tmp_path):
    # Mismo directorio de estado por proyecto que `architect_queue_path`
    # (`.claude/state/<project_name saneado>/`), fichero distinto.
    path = dispatch_queue_path(tmp_path, "My Project")
    assert path == tmp_path / ".claude" / "state" / "my-project" / "dispatch_queue.json"


def test_get_queue_is_empty_list_when_file_does_not_exist(tmp_path):
    assert get_queue(tmp_path, "proj") == []


def test_enqueue_task_creates_a_queued_entry(tmp_path):
    entry = enqueue_task(
        tmp_path, "proj", task_id="T-AF999-US01-01", us_id="US-AF999-01", priority="Alta"
    )

    assert entry.task_id == "T-AF999-US01-01"
    assert entry.us_id == "US-AF999-01"
    assert entry.priority == "Alta"
    assert entry.status == STATUS_QUEUED
    assert entry.enqueued_at

    entries = get_queue(tmp_path, "proj")
    assert len(entries) == 1
    assert entries[0].task_id == "T-AF999-US01-01"


def test_enqueue_task_twice_raises_task_already_queued(tmp_path):
    enqueue_task(tmp_path, "proj", task_id="T-1", us_id="US-1", priority=None)

    with pytest.raises(TaskAlreadyQueuedError):
        enqueue_task(tmp_path, "proj", task_id="T-1", us_id="US-1", priority=None)


def test_reenqueue_after_failure_removes_terminal_history(tmp_path):
    # T-AF008-US10-04 (corrección): re-encolar una Task que falló (su
    # entrada quedó `failed`) debe eliminar la entrada histórica y dejar
    # solo la nueva — exactamente una entrada por `task_id`, sin acumular.
    enqueue_task(tmp_path, "proj", task_id="T-1", us_id="US-1", priority=None)
    mark_dispatched(tmp_path, "proj", "T-1", agent_id="a-1", agent_name="Developer-1")
    mark_failed(tmp_path, "proj", "T-1", result="Timeout")

    enqueue_task(tmp_path, "proj", task_id="T-1", us_id="US-1", priority=None)

    entries = get_queue(tmp_path, "proj")
    assert len(entries) == 1
    assert entries[0].status == STATUS_QUEUED
    assert entries[0].result is None


def test_reenqueue_after_completed_removes_terminal_history(tmp_path):
    # Ídem para una entrada `completed` previa (Task cerrada y reabierta).
    enqueue_task(tmp_path, "proj", task_id="T-1", us_id="US-1", priority=None)
    mark_dispatched(tmp_path, "proj", "T-1", agent_id="a-1", agent_name="Developer-1")
    mark_completed(tmp_path, "proj", "T-1", result="Veredicto EXITO")

    enqueue_task(tmp_path, "proj", task_id="T-1", us_id="US-1", priority=None)

    entries = get_queue(tmp_path, "proj")
    assert len(entries) == 1
    assert entries[0].status == STATUS_QUEUED


def test_dequeue_task_removes_a_queued_entry(tmp_path):
    enqueue_task(tmp_path, "proj", task_id="T-1", us_id="US-1", priority=None)

    dequeue_task(tmp_path, "proj", "T-1")

    assert get_queue(tmp_path, "proj") == []


def test_dequeue_task_raises_task_not_queued_when_never_enqueued(tmp_path):
    with pytest.raises(TaskNotQueuedError):
        dequeue_task(tmp_path, "proj", "T-nonexistent")


def test_dequeue_task_raises_task_already_dispatched_when_not_queued_anymore(tmp_path):
    enqueue_task(tmp_path, "proj", task_id="T-1", us_id="US-1", priority=None)
    mark_dispatched(tmp_path, "proj", "T-1", agent_id="a-1", agent_name="Developer-1")

    with pytest.raises(TaskAlreadyDispatchedError):
        dequeue_task(tmp_path, "proj", "T-1")

    # Y no se eliminó la entrada al fallar el intento de desencolar.
    entries = get_queue(tmp_path, "proj")
    assert len(entries) == 1
    assert entries[0].status == STATUS_DISPATCHED


def test_mark_dispatched_sets_agent_fields_and_status(tmp_path):
    enqueue_task(tmp_path, "proj", task_id="T-1", us_id="US-1", priority=None)

    mark_dispatched(tmp_path, "proj", "T-1", agent_id="a-1", agent_name="Developer-1")

    entries = get_queue(tmp_path, "proj")
    assert entries[0].status == STATUS_DISPATCHED
    assert entries[0].agent_id == "a-1"
    assert entries[0].agent_name == "Developer-1"
    assert entries[0].dispatched_at


def test_mark_dispatched_redispatch_after_failure_reuses_entry(tmp_path):
    # Decisión 2026-08-19 (reintento automático): una entrada `failed`
    # (Task que falló y volvió a TO_DEVELOP) se re-despacha reutilizando
    # la MISMA entrada -> vuelve a `dispatched` y limpia el resultado
    # previo, sin acumular una entrada nueva por reintento.
    enqueue_task(tmp_path, "proj", task_id="T-1", us_id="US-1", priority=None)
    mark_dispatched(tmp_path, "proj", "T-1", agent_id="a-1", agent_name="Developer-1")
    mark_failed(tmp_path, "proj", "T-1", result="Timeout esperando reporte del agente (>3600s).")

    mark_dispatched(tmp_path, "proj", "T-1", agent_id="a-2", agent_name="Developer-2")

    entries = get_queue(tmp_path, "proj")
    assert len(entries) == 1
    assert entries[0].status == STATUS_DISPATCHED
    assert entries[0].agent_id == "a-2"
    assert entries[0].result is None


def test_mark_failed_sets_result_and_status(tmp_path):
    enqueue_task(tmp_path, "proj", task_id="T-1", us_id="US-1", priority=None)
    mark_dispatched(tmp_path, "proj", "T-1", agent_id="a-1", agent_name="Developer-1")

    mark_failed(tmp_path, "proj", "T-1", result="El agente no completó la instrucción.")

    entries = get_queue(tmp_path, "proj")
    assert entries[0].status == STATUS_FAILED
    assert entries[0].result == "El agente no completó la instrucción."


def test_queue_survives_a_fresh_read_simulating_process_restart(tmp_path):
    # Requisito explícito de la Task: la cola debe ser consultable tras
    # un reinicio del proceso — simulado escribiendo con una "instancia"
    # lógica y leyendo con otra, sin ningún estado en memoria compartido
    # entre ambas llamadas (el módulo no mantiene ningún caché interno).
    enqueue_task(tmp_path, "proj", task_id="T-1", us_id="US-1", priority="Crítica")

    entries = get_queue(tmp_path, "proj")

    assert len(entries) == 1
    assert entries[0].task_id == "T-1"
    assert entries[0].priority == "Crítica"


def test_two_different_projects_have_independent_queues(tmp_path):
    enqueue_task(tmp_path, "proj-a", task_id="T-a", us_id="US-a", priority=None)
    enqueue_task(tmp_path, "proj-b", task_id="T-b", us_id="US-b", priority=None)

    assert [e.task_id for e in get_queue(tmp_path, "proj-a")] == ["T-a"]
    assert [e.task_id for e in get_queue(tmp_path, "proj-b")] == ["T-b"]


# ---------------------------------------------------------------------------
# migrate_queued_entries_to_state (T-AF008-US14-01, criterio de migración)
# ---------------------------------------------------------------------------


def _write_task_md(tasks_dir, task_id, us_id, state):
    tasks_dir.mkdir(parents=True, exist_ok=True)
    (tasks_dir / f"{task_id}.md").write_text(
        "---\n"
        f"id: {task_id}\ntype: task\ntitle: Task\nstate: {state}\n"
        f"dependencies: []\nepic: AF-999\nuser_story: {us_id}\npriority: Alta\n"
        "---\n\n"
        f"# {task_id}\n\n## Objetivo\n\nObjetivo.\n\n## Criterios de aceptación\n\n1. Y.\n",
        encoding="utf-8",
    )


def test_migrate_queued_entries_to_state_updates_task_still_in_to_do(tmp_path):
    """Caso real de la migración: una Task se encoló ANTES de esta Task
    (entrada `queued` en el JSON) con el mecanismo antiguo — su fichero
    real sigue en `TODO`, nunca se escribió `TO_DEVELOP`. La migración pone
    el fichero real al día sin perder la entrada JSON."""
    from atlas_forge.dispatcher.dispatch_queue import migrate_queued_entries_to_state

    backlog_dir = tmp_path / "02-backlog"
    _write_task_md(backlog_dir / "tasks", "T-AF999-US01-01", "US-AF999-01", "READY")
    enqueue_task(tmp_path, "proj", task_id="T-AF999-US01-01", us_id="US-AF999-01", priority="Alta")

    migrated = migrate_queued_entries_to_state(tmp_path, "proj", backlog_dir)

    assert migrated == ["T-AF999-US01-01"]
    task_text = (backlog_dir / "tasks" / "T-AF999-US01-01.md").read_text(encoding="utf-8")
    assert "state: TO_DEVELOP" in task_text
    # La entrada JSON no se toca — sigue como registro auxiliar.
    entries = get_queue(tmp_path, "proj")
    assert entries[0].status == STATUS_QUEUED


def test_migrate_queued_entries_to_state_is_idempotent(tmp_path):
    """Ejecutarlo dos veces no vuelve a tocar nada la segunda vez — la
    Task ya migrada está en `TO_DEVELOP`, no en `TODO`."""
    from atlas_forge.dispatcher.dispatch_queue import migrate_queued_entries_to_state

    backlog_dir = tmp_path / "02-backlog"
    _write_task_md(backlog_dir / "tasks", "T-AF999-US01-01", "US-AF999-01", "READY")
    enqueue_task(tmp_path, "proj", task_id="T-AF999-US01-01", us_id="US-AF999-01", priority="Alta")

    first = migrate_queued_entries_to_state(tmp_path, "proj", backlog_dir)
    second = migrate_queued_entries_to_state(tmp_path, "proj", backlog_dir)

    assert first == ["T-AF999-US01-01"]
    assert second == []


def test_migrate_queued_entries_to_state_skips_task_already_past_todo(tmp_path):
    """Una Task `queued` en el JSON cuyo fichero real ya no está en
    `TODO` (p. ej. el Dispatcher ya la despachó y el JSON quedó
    desincronizado, o alguien la movió a mano) no se toca — mismo
    criterio de "nunca revierte" que `promote_backlog`."""
    from atlas_forge.dispatcher.dispatch_queue import migrate_queued_entries_to_state

    backlog_dir = tmp_path / "02-backlog"
    _write_task_md(backlog_dir / "tasks", "T-AF999-US01-01", "US-AF999-01", "IN_PROGRESS")
    enqueue_task(tmp_path, "proj", task_id="T-AF999-US01-01", us_id="US-AF999-01", priority="Alta")

    migrated = migrate_queued_entries_to_state(tmp_path, "proj", backlog_dir)

    assert migrated == []
    task_text = (backlog_dir / "tasks" / "T-AF999-US01-01.md").read_text(encoding="utf-8")
    assert "state: IN_PROGRESS" in task_text


def test_migrate_queued_entries_to_state_returns_empty_for_empty_queue(tmp_path):
    from atlas_forge.dispatcher.dispatch_queue import migrate_queued_entries_to_state

    backlog_dir = tmp_path / "02-backlog"
    assert migrate_queued_entries_to_state(tmp_path, "proj", backlog_dir) == []


# ---------------------------------------------------------------------------
# T-AF008-US10-04: la cola debe reflejar el estado REAL de la Task —
# `mark_completed`, `derive_effective_status`, `reconcile_dispatch_queue_entries`.
# ---------------------------------------------------------------------------


def _entry(task_id, status, agent_id=None, agent_name=None):
    return QueueEntry(
        task_id=task_id, us_id="US-1", priority=None, status=status,
        enqueued_at="2026-01-01T00:00:00", agent_id=agent_id, agent_name=agent_name,
    )


def test_mark_completed_terminalizes_a_dispatched_entry(tmp_path):
    enqueue_task(tmp_path, "proj", task_id="T-1", us_id="US-1", priority=None)
    mark_dispatched(tmp_path, "proj", "T-1", agent_id="a-1", agent_name="Developer-1")

    mark_completed(tmp_path, "proj", "T-1", result="Veredicto EXITO del Tester.")

    entries = get_queue(tmp_path, "proj")
    assert entries[0].status == STATUS_COMPLETED
    assert entries[0].result == "Veredicto EXITO del Tester."
    assert entries[0].agent_id == "a-1"


def test_mark_completed_does_not_touch_queued_or_failed_entries(tmp_path):
    # Una entrada aún `queued` (no tomada por el Dispatcher) o ya `failed`
    # no se toca — `completed` solo terminaliza una entrada que pudiera
    # mostrar "en curso".
    enqueue_task(tmp_path, "proj", task_id="T-1", us_id="US-1", priority=None)
    mark_completed(tmp_path, "proj", "T-1")
    assert get_queue(tmp_path, "proj")[0].status == STATUS_QUEUED

    mark_dispatched(tmp_path, "proj", "T-1", agent_id="a-1", agent_name="Developer-1")
    mark_failed(tmp_path, "proj", "T-1", result="x")
    mark_completed(tmp_path, "proj", "T-1")
    assert get_queue(tmp_path, "proj")[0].status == STATUS_FAILED


def test_derive_effective_status_queued_stays_queued():
    assert derive_effective_status(_entry("T-1", STATUS_QUEUED), "TO_DEVELOP") == STATUS_QUEUED


def test_derive_effective_status_queued_done_is_completed_not_pendiente():
    # T-AF008-US10-04 (corrección): una Task `DONE` con entrada `queued`
    # residual (cerrada fuera del pipeline, nunca despachada por esta
    # cola) no se muestra como "Pendiente" para siempre.
    assert derive_effective_status(_entry("T-1", STATUS_QUEUED), "DONE") == STATUS_COMPLETED
    # Una Task `READY`/inexistente con entrada `queued` residual tampoco
    # puede seguir mostrándose como pendiente — es una huérfana.
    assert derive_effective_status(_entry("T-1", STATUS_QUEUED), "READY") == STATUS_FAILED
    assert derive_effective_status(_entry("T-1", STATUS_QUEUED), None) == STATUS_FAILED


def test_derive_effective_status_in_progress_is_dispatched():
    assert derive_effective_status(_entry("T-1", STATUS_DISPATCHED), "IN_PROGRESS") == STATUS_DISPATCHED


def test_derive_effective_status_in_review_is_awaiting_tester():
    # Criterio 2: una Task IN_REVIEW aparece como "esperando al Tester",
    # nunca como "En curso" — el Developer que la cerró queda identificado.
    assert derive_effective_status(_entry("T-1", STATUS_DISPATCHED), "IN_REVIEW") == STATUS_AWAITING_TESTER


def test_derive_effective_status_done_is_completed_not_en_curso():
    # Criterio 1: una Task DONE nunca aparece como "En curso".
    assert derive_effective_status(_entry("T-1", STATUS_DISPATCHED), "DONE") == STATUS_COMPLETED
    # Y una entrada ya terminalizada permanece completed aunque el estado
    # real diverga.
    assert derive_effective_status(_entry("T-1", STATUS_COMPLETED), "IN_PROGRESS") == STATUS_COMPLETED


def test_derive_effective_status_ready_orphan_is_not_en_curso():
    # Criterio 3: una Task READY/TO_DEVELOP con entrada `dispatched`
    # residual (huérfana de reinicio) no aparece como "En curso".
    assert derive_effective_status(_entry("T-1", STATUS_DISPATCHED), "READY") == STATUS_FAILED
    assert derive_effective_status(_entry("T-1", STATUS_DISPATCHED), "TO_DEVELOP") == STATUS_FAILED
    # Task que ya no existe en el backlog: tampoco puede estar "en curso".
    assert derive_effective_status(_entry("T-1", STATUS_DISPATCHED), None) == STATUS_FAILED


def test_derive_effective_status_failed_stays_failed():
    assert derive_effective_status(_entry("T-1", STATUS_FAILED), "IN_PROGRESS") == STATUS_FAILED


def test_reconcile_marks_done_entry_completed(tmp_path):
    backlog_dir = tmp_path / "02-backlog"
    _write_task_md(backlog_dir / "tasks", "T-AF999-US01-01", "US-AF999-01", "DONE")
    enqueue_task(tmp_path, "proj", task_id="T-AF999-US01-01", us_id="US-AF999-01", priority="Alta")
    mark_dispatched(tmp_path, "proj", "T-AF999-US01-01", agent_id="a-1", agent_name="Developer-1")

    from atlas_forge.dispatcher.dispatch_queue import reconcile_dispatch_queue_entries
    reconciled = reconcile_dispatch_queue_entries(tmp_path, "proj", backlog_dir)

    assert reconciled == ["T-AF999-US01-01"]
    assert get_queue(tmp_path, "proj")[0].status == STATUS_COMPLETED


def test_reconcile_marks_ready_orphan_entry_failed(tmp_path):
    backlog_dir = tmp_path / "02-backlog"
    _write_task_md(backlog_dir / "tasks", "T-AF999-US01-01", "US-AF999-01", "READY")
    enqueue_task(tmp_path, "proj", task_id="T-AF999-US01-01", us_id="US-AF999-01", priority="Alta")
    mark_dispatched(tmp_path, "proj", "T-AF999-US01-01", agent_id="a-1", agent_name="Developer-1")

    from atlas_forge.dispatcher.dispatch_queue import reconcile_dispatch_queue_entries
    reconciled = reconcile_dispatch_queue_entries(tmp_path, "proj", backlog_dir)

    assert reconciled == ["T-AF999-US01-01"]
    entry = get_queue(tmp_path, "proj")[0]
    assert entry.status == STATUS_FAILED
    assert "huérfana" in entry.result


def test_reconcile_queued_done_entry_completed(tmp_path):
    # T-AF008-US10-04 (corrección): una entrada `queued` cuya Task real ya
    # está `DONE` (cerrada fuera del pipeline) se terminaliza a `completed`
    # al arrancar — no se queda "Pendiente" para siempre.
    backlog_dir = tmp_path / "02-backlog"
    _write_task_md(backlog_dir / "tasks", "T-AF999-US01-01", "US-AF999-01", "DONE")
    enqueue_task(tmp_path, "proj", task_id="T-AF999-US01-01", us_id="US-AF999-01", priority="Alta")

    from atlas_forge.dispatcher.dispatch_queue import reconcile_dispatch_queue_entries
    reconciled = reconcile_dispatch_queue_entries(tmp_path, "proj", backlog_dir)

    assert reconciled == ["T-AF999-US01-01"]
    assert get_queue(tmp_path, "proj")[0].status == STATUS_COMPLETED


def test_reconcile_queued_ready_orphan_entry_failed(tmp_path):
    # T-AF008-US10-04 (corrección): una entrada `queued` cuya Task real ya
    # volvió a `READY` (revertida/desencolada por otra vía) es una huérfana
    # y se terminaliza a `failed` al arrancar.
    backlog_dir = tmp_path / "02-backlog"
    _write_task_md(backlog_dir / "tasks", "T-AF999-US01-01", "US-AF999-01", "READY")
    enqueue_task(tmp_path, "proj", task_id="T-AF999-US01-01", us_id="US-AF999-01", priority="Alta")

    from atlas_forge.dispatcher.dispatch_queue import reconcile_dispatch_queue_entries
    reconciled = reconcile_dispatch_queue_entries(tmp_path, "proj", backlog_dir)

    assert reconciled == ["T-AF999-US01-01"]
    entry = get_queue(tmp_path, "proj")[0]
    assert entry.status == STATUS_FAILED
    assert "huérfana" in entry.result


def test_reconcile_leaves_queued_to_develop_untouched(tmp_path):
    # Una entrada `queued` con su estado real normal (`TO_DEVELOP`, que es
    # lo que escribe el enqueue) NO se reconcilia — sigue siendo una
    # entrada pendiente legítima.
    backlog_dir = tmp_path / "02-backlog"
    _write_task_md(backlog_dir / "tasks", "T-AF999-US01-01", "US-AF999-01", "TO_DEVELOP")
    enqueue_task(tmp_path, "proj", task_id="T-AF999-US01-01", us_id="US-AF999-01", priority="Alta")

    from atlas_forge.dispatcher.dispatch_queue import reconcile_dispatch_queue_entries
    reconciled = reconcile_dispatch_queue_entries(tmp_path, "proj", backlog_dir)

    assert reconciled == []
    assert get_queue(tmp_path, "proj")[0].status == STATUS_QUEUED


def test_reconcile_leaves_in_review_untouched(tmp_path):
    # Criterio T-AF008-US10-05: una Task IN_REVIEW se deja intacta — el
    # ciclo de revisión (`run_review_dispatch_cycle`) la re-despacha sola
    # cada poll; revertirla descartaría el trabajo ya cerrado por el
    # Developer. (IN_PROGRESS sin reporte SÍ es huérfana y se reconcilia;
    # ver tests siguientes.)
    backlog_dir = tmp_path / "02-backlog"
    _write_task_md(backlog_dir / "tasks", "T-AF999-US01-01", "US-AF999-01", "IN_REVIEW")
    enqueue_task(tmp_path, "proj", task_id="T-AF999-US01-01", us_id="US-AF999-01", priority="Alta")
    mark_dispatched(tmp_path, "proj", "T-AF999-US01-01", agent_id="a-1", agent_name="Developer-1")

    from atlas_forge.dispatcher.dispatch_queue import reconcile_dispatch_queue_entries
    reconciled = reconcile_dispatch_queue_entries(tmp_path, "proj", backlog_dir)

    assert reconciled == []
    assert get_queue(tmp_path, "proj")[0].status == STATUS_DISPATCHED


def test_reconcile_does_not_revert_dispatched_in_progress_without_report(tmp_path):
    """T-AF022-US20-01, criterio 1: una entrada `dispatched` cuya Task está
    `IN_PROGRESS` NO se revierte aunque su `report_file` aún no exista en
    disco — el fichero es el destino del informe que el agente escribirá al
    terminar, y su ausencia transitoria es lo normal (reproduce la ventana de
    despacho que causó decenas de falsos positivos el 2026-08-24). El residuo
    de Job huérfano REAL (agente ya inexistente) lo limpia la función
    dedicada del worker (`_reconcile_orphaned_agent_entries`, T-AF008-US18-05)."""
    backlog_dir = tmp_path / "02-backlog"
    _write_task_md(backlog_dir / "tasks", "T-AF999-US01-01", "US-AF999-01", "IN_PROGRESS")
    enqueue_task(tmp_path, "proj", task_id="T-AF999-US01-01", us_id="US-AF999-01", priority="Alta")
    mark_dispatched(tmp_path, "proj", "T-AF999-US01-01", agent_id="a-1", agent_name="Developer-1")

    from atlas_forge.dispatcher.dispatch_queue import reconcile_dispatch_queue_entries
    reconciled = reconcile_dispatch_queue_entries(tmp_path, "proj", backlog_dir)

    assert reconciled == []
    task_text = (backlog_dir / "tasks" / "T-AF999-US01-01.md").read_text(encoding="utf-8")
    assert "state: IN_PROGRESS" in task_text
    entry = get_queue(tmp_path, "proj")[0]
    assert entry.status == STATUS_DISPATCHED
    assert entry.result is None


def test_reconcile_does_not_log_reverted_for_dispatched_in_progress_without_report(tmp_path):
    """T-AF022-US20-01, criterio 3: la reconciliación de una entrada
    `dispatched` en la ventana (sin reporte aún) NO registra
    `dispatched_orphan_reconciled → READY` en el log."""
    backlog_dir = tmp_path / "02-backlog"
    _write_task_md(backlog_dir / "tasks", "T-AF999-US01-01", "US-AF999-01", "IN_PROGRESS")
    enqueue_task(tmp_path, "proj", task_id="T-AF999-US01-01", us_id="US-AF999-01", priority="Alta")
    mark_dispatched(tmp_path, "proj", "T-AF999-US01-01", agent_id="a-1", agent_name="Developer-1")

    from atlas_forge.dispatcher.dispatch_queue import reconcile_dispatch_queue_entries
    reconcile_dispatch_queue_entries(tmp_path, "proj", backlog_dir)

    import json
    from pathlib import Path as _Path
    log_path = tmp_path / ".claude" / "state" / "proj" / "reconciliation_log.jsonl"
    assert not _Path(log_path).exists()

    lines = get_queue(tmp_path, "proj")
    assert lines[0].status == STATUS_DISPATCHED


def test_reconcile_does_not_revert_dispatched_in_progress_even_with_auto_reenqueue(tmp_path):
    """T-AF022-US20-01: la preferencia `auto_reenqueue_orphaned` no debe
    revolver una entrada `dispatched` en la ventana (sin reporte aún) — el
    guard "si hay entrada dispatched, no se revierte" es el de seguridad
    principal y aplica con cualquier valor de la preferencia."""
    backlog_dir = tmp_path / "02-backlog"
    _write_task_md(backlog_dir / "tasks", "T-AF999-US01-01", "US-AF999-01", "IN_PROGRESS")
    enqueue_task(tmp_path, "proj", task_id="T-AF999-US01-01", us_id="US-AF999-01", priority="Alta")
    mark_dispatched(tmp_path, "proj", "T-AF999-US01-01", agent_id="a-1", agent_name="Developer-1")

    from atlas_forge.dispatcher.dispatch_queue import reconcile_dispatch_queue_entries
    reconciled = reconcile_dispatch_queue_entries(
        tmp_path, "proj", backlog_dir, auto_reenqueue_orphaned=True
    )

    assert reconciled == []
    task_text = (backlog_dir / "tasks" / "T-AF999-US01-01.md").read_text(encoding="utf-8")
    assert "state: IN_PROGRESS" in task_text
    assert get_queue(tmp_path, "proj")[0].status == STATUS_DISPATCHED


def test_reconcile_reverts_in_progress_without_dispatched_real_orphan(tmp_path):
    """T-AF022-US20-01, criterio 2 (+ T-AF022-US18-01): una task IN_PROGRESS
    SIN entrada `dispatched`, SIN reporte, SIN `_inflight` (protegida) es una
    huérfana REAL (caso T-AF023-US03-01) y SÍ se revierte a
    READY/TO_DEVELOP — la detección de huérfanas reales no se debilita."""
    backlog_dir = tmp_path / "02-backlog"
    _write_task_md(backlog_dir / "tasks", "T-AF999-US01-01", "US-AF999-01", "IN_PROGRESS")
    # NOTA: sin enqueue ni mark_dispatched — no hay entrada en la cola.

    from atlas_forge.dispatcher.dispatch_queue import reconcile_orphaned_in_progress_tasks
    reconciled = reconcile_orphaned_in_progress_tasks(tmp_path, "proj", backlog_dir)

    assert reconciled == ["T-AF999-US01-01"]
    task_text = (backlog_dir / "tasks" / "T-AF999-US01-01.md").read_text(encoding="utf-8")
    assert "state: READY" in task_text

    import json
    from pathlib import Path as _Path
    log_path = tmp_path / ".claude" / "state" / "proj" / "reconciliation_log.jsonl"
    entry = json.loads(_Path(log_path).read_text(encoding="utf-8").strip().splitlines()[0])
    assert entry["reason"] == "dispatched_orphan_reconciled"
    assert entry["target_state"] == "READY"


def test_reconcile_in_progress_real_orphan_respects_protected_and_auto_reenqueue(tmp_path):
    """La huérfana real respeta `protected_task_ids` (_inflight) y la
    preferencia `auto_reenqueue_orphaned` (TO_DEVELOP si activa)."""
    backlog_dir = tmp_path / "02-backlog"
    _write_task_md(backlog_dir / "tasks", "T-AF999-US01-01", "US-AF999-01", "IN_PROGRESS")
    _write_task_md(backlog_dir / "tasks", "T-AF999-US01-02", "US-AF999-01", "IN_PROGRESS")

    from atlas_forge.dispatcher.dispatch_queue import reconcile_orphaned_in_progress_tasks

    # Con auto_reenqueue False y `protected` para la segunda task:
    reconciled = reconcile_orphaned_in_progress_tasks(
        tmp_path, "proj", backlog_dir,
        auto_reenqueue_orphaned=False,
        protected_task_ids={"T-AF999-US01-02"},
    )

    assert reconciled == ["T-AF999-US01-01"]
    text1 = (backlog_dir / "tasks" / "T-AF999-US01-01.md").read_text(encoding="utf-8")
    assert "state: READY" in text1
    text2 = (backlog_dir / "tasks" / "T-AF999-US01-02.md").read_text(encoding="utf-8")
    assert "state: IN_PROGRESS" in text2  # protegida: no se toca.

    # Con la preferencia activa, la real revierte a TO_DEVELOP.
    from pathlib import Path as _Path
    backlog_dir2 = tmp_path / "backlog2"
    _write_task_md(backlog_dir2 / "tasks", "T-AF999-US01-03", "US-AF999-01", "IN_PROGRESS")
    reconciled2 = reconcile_orphaned_in_progress_tasks(
        tmp_path, "proj", backlog_dir2, auto_reenqueue_orphaned=True
    )
    assert reconciled2 == ["T-AF999-US01-03"]
    text3 = (backlog_dir2 / "tasks" / "T-AF999-US01-03.md").read_text(encoding="utf-8")
    assert "state: TO_DEVELOP" in text3


def test_reconcile_leaves_in_progress_with_live_report_untouched(tmp_path):
    """Criterio 2: una Task IN_PROGRESS cuyo reporte de Job en vuelo sigue
    existiendo (no se toca — el Job sigue legítimamente vivo; no duplicar
    trabajo)."""
    backlog_dir = tmp_path / "02-backlog"
    _write_task_md(backlog_dir / "tasks", "T-AF999-US01-01", "US-AF999-01", "IN_PROGRESS")
    enqueue_task(tmp_path, "proj", task_id="T-AF999-US01-01", us_id="US-AF999-01", priority="Alta")
    mark_dispatched(tmp_path, "proj", "T-AF999-US01-01", agent_id="a-1", agent_name="Developer-1")
    from atlas_forge.dispatcher.dispatch_queue import set_entry_report_file
    report_file = tmp_path / "atlas-forge-job-live.txt"
    report_file.write_text("reporte en vuelo", encoding="utf-8")
    set_entry_report_file(tmp_path, "proj", "T-AF999-US01-01", report_file)

    from atlas_forge.dispatcher.dispatch_queue import reconcile_dispatch_queue_entries
    reconciled = reconcile_dispatch_queue_entries(tmp_path, "proj", backlog_dir)

    assert reconciled == []
    assert get_queue(tmp_path, "proj")[0].status == STATUS_DISPATCHED
    task_text = (backlog_dir / "tasks" / "T-AF999-US01-01.md").read_text(encoding="utf-8")
    assert "state: IN_PROGRESS" in task_text


def test_set_entry_report_file_persists_on_dispatched_entry(tmp_path):
    from atlas_forge.dispatcher.dispatch_queue import set_entry_report_file

    enqueue_task(tmp_path, "proj", task_id="T-AF999-US01-01", us_id="US-AF999-01", priority="Alta")
    # No hace nada si la entrada no está `dispatched` (mejor esfuerzo).
    set_entry_report_file(tmp_path, "proj", "T-AF999-US01-01", "/tmp/noop.txt")
    assert get_queue(tmp_path, "proj")[0].report_file is None

    mark_dispatched(tmp_path, "proj", "T-AF999-US01-01", agent_id="a-1", agent_name="Developer-1")
    set_entry_report_file(tmp_path, "proj", "T-AF999-US01-01", "/tmp/atlas-forge-job-abc.txt")
    assert get_queue(tmp_path, "proj")[0].report_file == "/tmp/atlas-forge-job-abc.txt"


def test_reconcile_marks_missing_task_entry_failed(tmp_path):
    backlog_dir = tmp_path / "02-backlog"
    (backlog_dir / "tasks").mkdir(parents=True)
    enqueue_task(tmp_path, "proj", task_id="T-AF999-US01-99", us_id="US-AF999-01", priority="Alta")
    mark_dispatched(tmp_path, "proj", "T-AF999-US01-99", agent_id="a-1", agent_name="Developer-1")

    from atlas_forge.dispatcher.dispatch_queue import reconcile_dispatch_queue_entries
    reconciled = reconcile_dispatch_queue_entries(tmp_path, "proj", backlog_dir)

    assert reconciled == ["T-AF999-US01-99"]
    assert get_queue(tmp_path, "proj")[0].status == STATUS_FAILED


def test_reconcile_empty_queue_returns_empty(tmp_path):
    from atlas_forge.dispatcher.dispatch_queue import reconcile_dispatch_queue_entries
    assert reconcile_dispatch_queue_entries(tmp_path, "proj", tmp_path / "02-backlog") == []


def test_mark_failed_sets_finished_at(tmp_path):
    """T-AF036-US17-01: `mark_failed` registra `finished_at` en la entrada."""
    enqueue_task(tmp_path, "proj", task_id="T-1", us_id="US-1", priority=None)
    mark_dispatched(tmp_path, "proj", "T-1", agent_id="a-1", agent_name="Developer-1")

    mark_failed(tmp_path, "proj", "T-1", result="falló")

    entries = get_queue(tmp_path, "proj")
    assert entries[0].status == STATUS_FAILED
    assert entries[0].finished_at is not None


def test_mark_completed_sets_finished_at(tmp_path):
    """T-AF036-US17-01: `mark_completed` registra `finished_at` en la entrada."""
    enqueue_task(tmp_path, "proj", task_id="T-2", us_id="US-2", priority=None)
    mark_dispatched(tmp_path, "proj", "T-2", agent_id="a-1", agent_name="Developer-1")

    mark_completed(tmp_path, "proj", "T-2", result="ok")

    entries = get_queue(tmp_path, "proj")
    assert entries[0].status == STATUS_COMPLETED
    assert entries[0].finished_at is not None


def test_old_record_without_finished_at_reads_as_none(tmp_path):
    """T-AF036-US17-01: compatibilidad hacia atrás — un registro existente
    sin `finished_at` (persistido antes de este campo) se lee como `None`."""
    from atlas_forge.dispatcher.dispatch_queue import dispatch_queue_path
    import json

    path = dispatch_queue_path(tmp_path, "proj")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            [
                {
                    "task_id": "T-legacy",
                    "us_id": None,
                    "priority": None,
                    "status": STATUS_COMPLETED,
                    "enqueued_at": "2026-01-01T00:00:00+00:00",
                    "agent_id": None,
                    "agent_name": None,
                    "result": "ok",
                    "dispatched_at": "2026-01-01T00:01:00+00:00",
                    "dispatch_reason": None,
                    "report_file": None,
                }
            ]
        ),
        encoding="utf-8",
    )

    entries = get_queue(tmp_path, "proj")
    assert entries[0].status == STATUS_COMPLETED
    assert entries[0].finished_at is None


def test_record_with_finished_at_reads_without_error(tmp_path):
    """T-AF036-US17-11 (bug en vivo): reproduce el HTTP 500 de
    `GET /backlog/queue` — `TypeError: QueueEntry.__init__() got an
    unexpected keyword argument 'finished_at'`. Un JSON de cola persistido
    con `finished_at` (escrito por `mark_completed`/`mark_failed` en
    `T-AF036-US17-01`) debe leerse sin error: `QueueEntry` declara
    `finished_at`, así que `get_queue` devuelve la entrada completa y la
    capa HTTP responde 200, no 500."""
    import json

    from atlas_forge.dispatcher.dispatch_queue import dispatch_queue_path

    path = dispatch_queue_path(tmp_path, "proj")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            [
                {
                    "task_id": "T-af036",
                    "us_id": "US-AF036-17",
                    "priority": "Crítica",
                    "status": STATUS_COMPLETED,
                    "enqueued_at": "2026-08-20T10:00:00+00:00",
                    "agent_id": "dev-1",
                    "agent_name": "Developer-1",
                    "result": "ok",
                    "dispatched_at": "2026-08-20T10:01:00+00:00",
                    "dispatch_reason": "encaja directo",
                    "report_file": None,
                    "finished_at": "2026-08-21T09:30:00+00:00",
                }
            ]
        ),
        encoding="utf-8",
    )

    entries = get_queue(tmp_path, "proj")

    assert len(entries) == 1
    assert entries[0].status == STATUS_COMPLETED
    assert entries[0].finished_at == "2026-08-21T09:30:00+00:00"
    assert entries[0].task_id == "T-af036"


def test_mixed_legacy_and_finished_at_entries_read(tmp_path):
    """T-AF036-US17-11: escenario real tras el fix — el fichero de cola
    contiene entradas MEZCLADAS: algunas legacy sin `finished_at` y otras
    recién terminalizadas con `finished_at`. `get_queue` debe leer todas sin
    error (cada `QueueEntry(**entry)` acepta y omite `finished_at`)."""
    import json

    from atlas_forge.dispatcher.dispatch_queue import dispatch_queue_path

    path = dispatch_queue_path(tmp_path, "proj")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            [
                {
                    "task_id": "T-legacy",
                    "us_id": None,
                    "priority": None,
                    "status": STATUS_COMPLETED,
                    "enqueued_at": "2026-01-01T00:00:00+00:00",
                    "agent_id": None,
                    "agent_name": None,
                    "result": "ok",
                    "dispatched_at": "2026-01-01T00:01:00+00:00",
                    "dispatch_reason": None,
                    "report_file": None,
                },
                {
                    "task_id": "T-new",
                    "us_id": "US-AF036-17",
                    "priority": "Crítica",
                    "status": STATUS_FAILED,
                    "enqueued_at": "2026-08-20T10:00:00+00:00",
                    "agent_id": "dev-1",
                    "agent_name": "Developer-1",
                    "result": "falló",
                    "dispatched_at": "2026-08-20T10:01:00+00:00",
                    "dispatch_reason": "encaja directo",
                    "report_file": None,
                    "finished_at": "2026-08-21T09:30:00+00:00",
                },
            ]
        ),
        encoding="utf-8",
    )

    entries = get_queue(tmp_path, "proj")

    assert len(entries) == 2
    by_id = {e.task_id: e for e in entries}
    assert by_id["T-legacy"].finished_at is None
    assert by_id["T-new"].finished_at == "2026-08-21T09:30:00+00:00"
    assert {e.status for e in entries} == {STATUS_COMPLETED, STATUS_FAILED}


def test_clear_history_removes_terminal_entries_and_keeps_active(tmp_path):
    """T-AF036-US17-02: `clear_history` borra `completed`/`failed` y conserva
    `queued`/`dispatched`, devolviendo el número de borradas."""
    enqueue_task(tmp_path, "proj", task_id="T-1", us_id="US-1", priority=None)  # queued
    enqueue_task(tmp_path, "proj", task_id="T-2", us_id="US-2", priority=None)  # queued -> dispatched
    enqueue_task(tmp_path, "proj", task_id="T-3", us_id="US-3", priority=None)  # queued -> completed
    enqueue_task(tmp_path, "proj", task_id="T-4", us_id="US-4", priority=None)  # queued -> failed

    mark_dispatched(tmp_path, "proj", "T-2", agent_id="a", agent_name="D")
    mark_dispatched(tmp_path, "proj", "T-3", agent_id="a", agent_name="D")
    mark_completed(tmp_path, "proj", "T-3", result="ok")
    mark_dispatched(tmp_path, "proj", "T-4", agent_id="a", agent_name="D")
    mark_failed(tmp_path, "proj", "T-4", result="fail")

    removed = clear_history(tmp_path, "proj")

    assert removed == 2
    entries = get_queue(tmp_path, "proj")
    assert {e.task_id for e in entries} == {"T-1", "T-2"}


def test_clear_history_is_idempotent_when_no_terminal_entries(tmp_path):
    """T-AF036-US17-02: sin entradas terminales, devuelve 0 y no borra nada."""
    enqueue_task(tmp_path, "proj", task_id="T-1", us_id="US-1", priority=None)
    mark_dispatched(tmp_path, "proj", "T-1", agent_id="a", agent_name="D")

    assert clear_history(tmp_path, "proj") == 0
    entries = get_queue(tmp_path, "proj")
    assert [e.task_id for e in entries] == ["T-1"]
    assert entries[0].status == STATUS_DISPATCHED


def test_clear_completed_removes_only_completed_and_keeps_rest(tmp_path):
    """T-AF042-US07-01: `clear_completed` borra SOLO las entradas
    `completed`, conservando `failed`/`queued`/`dispatched`."""
    enqueue_task(tmp_path, "proj", task_id="T-1", us_id="US-1", priority=None)  # queued
    enqueue_task(tmp_path, "proj", task_id="T-2", us_id="US-2", priority=None)  # dispatched
    enqueue_task(tmp_path, "proj", task_id="T-3", us_id="US-3", priority=None)  # failed
    enqueue_task(tmp_path, "proj", task_id="T-4", us_id="US-4", priority=None)  # completed
    enqueue_task(tmp_path, "proj", task_id="T-5", us_id="US-5", priority=None)  # completed

    mark_dispatched(tmp_path, "proj", "T-2", agent_id="a", agent_name="D")
    mark_dispatched(tmp_path, "proj", "T-3", agent_id="a", agent_name="D")
    mark_failed(tmp_path, "proj", "T-3", result="fail")
    mark_dispatched(tmp_path, "proj", "T-4", agent_id="a", agent_name="D")
    mark_completed(tmp_path, "proj", "T-4", result="ok")
    mark_dispatched(tmp_path, "proj", "T-5", agent_id="a", agent_name="D")
    mark_completed(tmp_path, "proj", "T-5", result="ok")

    removed = clear_completed(tmp_path, "proj")

    assert removed == 2
    by_id = {e.task_id: e.status for e in get_queue(tmp_path, "proj")}
    assert by_id == {"T-1": "queued", "T-2": "dispatched", "T-3": "failed"}


def test_clear_completed_is_idempotent_when_no_completed_entries(tmp_path):
    """T-AF042-US07-01: sin entradas `completed`, devuelve 0 y no borra nada."""
    enqueue_task(tmp_path, "proj", task_id="T-1", us_id="US-1", priority=None)
    enqueue_task(tmp_path, "proj", task_id="T-2", us_id="US-2", priority=None)
    mark_dispatched(tmp_path, "proj", "T-2", agent_id="a", agent_name="D")
    mark_failed(tmp_path, "proj", "T-2", result="fail")

    assert clear_completed(tmp_path, "proj") == 0
    assert {e.task_id for e in get_queue(tmp_path, "proj")} == {"T-1", "T-2"}


def test_remove_entry_removes_only_the_terminal_entry_and_keeps_the_rest(tmp_path):
    """T-AF036-US17-07: `remove_entry` borra SOLO la entrada terminal de
    `task_id` y conserva el resto de la cola (completed + failed + en curso)."""
    enqueue_task(tmp_path, "proj", task_id="T-1", us_id="US-1", priority=None)  # completed
    enqueue_task(tmp_path, "proj", task_id="T-2", us_id="US-2", priority=None)  # failed
    enqueue_task(tmp_path, "proj", task_id="T-3", us_id="US-3", priority=None)  # queued (en curso)
    mark_dispatched(tmp_path, "proj", "T-1", agent_id="a", agent_name="D")
    mark_completed(tmp_path, "proj", "T-1", result="ok")
    mark_dispatched(tmp_path, "proj", "T-2", agent_id="a", agent_name="D")
    mark_failed(tmp_path, "proj", "T-2", result="fail")

    removed = remove_entry(tmp_path, "proj", "T-1")

    assert removed is True
    by_id = {e.task_id: e.status for e in get_queue(tmp_path, "proj")}
    assert by_id == {"T-2": "failed", "T-3": "queued"}


def test_remove_entry_removes_a_failed_entry_too(tmp_path):
    """T-AF036-US17-07: `failed` es terminal y también se borra por esta vía."""
    enqueue_task(tmp_path, "proj", task_id="T-1", us_id="US-1", priority=None)
    mark_dispatched(tmp_path, "proj", "T-1", agent_id="a", agent_name="D")
    mark_failed(tmp_path, "proj", "T-1", result="fail")

    assert remove_entry(tmp_path, "proj", "T-1") is True
    assert get_queue(tmp_path, "proj") == []


def test_remove_entry_raises_when_task_not_queued(tmp_path):
    """T-AF036-US17-07: 404 — `task_id` sin ninguna entrada no borra nada y
    lanza `TaskNotQueuedError`."""
    enqueue_task(tmp_path, "proj", task_id="T-1", us_id="US-1", priority=None)

    with pytest.raises(TaskNotQueuedError):
        remove_entry(tmp_path, "proj", "T-desconocida")

    assert {e.task_id for e in get_queue(tmp_path, "proj")} == {"T-1"}


def test_remove_entry_raises_when_entry_not_terminal(tmp_path):
    """T-AF036-US17-07: 409 — una entrada en curso (`queued`/`dispatched`)
    no es borrable por esta vía y lanza `TaskNotTerminalError`."""
    enqueue_task(tmp_path, "proj", task_id="T-1", us_id="US-1", priority=None)
    enqueue_task(tmp_path, "proj", task_id="T-2", us_id="US-2", priority=None)
    mark_dispatched(tmp_path, "proj", "T-2", agent_id="a", agent_name="D")

    with pytest.raises(TaskNotTerminalError):
        remove_entry(tmp_path, "proj", "T-1")
    with pytest.raises(TaskNotTerminalError):
        remove_entry(tmp_path, "proj", "T-2")

    assert {e.task_id for e in get_queue(tmp_path, "proj")} == {"T-1", "T-2"}


# ---------------------------------------------------------------------------
# T-AF022-US18-01: reconciliar tasks IN_PROGRESS huérfanas SIN entrada JSON
# (cierra el hueco de `reconcile_dispatch_queue_entries`, que solo recorre
# entradas con presencia en la cola — el caso real T-AF023-US03-01).
# ---------------------------------------------------------------------------


def _write_us_md(user_stories_dir, us_id, state):
    user_stories_dir.mkdir(parents=True, exist_ok=True)
    (user_stories_dir / f"{us_id}.md").write_text(
        "---\n"
        f"id: {us_id}\ntype: user_story\ntitle: User Story\nstate: {state}\n"
        f"dependencies: []\nepic: AF-999\npriority: Alta\nversion: 0.1\n"
        "---\n\n"
        f"# {us_id}\n\n## Historia\n\nHistoria.\n\n## Criterios de aceptación\n\n1. Y.\n",
        encoding="utf-8",
    )


def _read_state(file_path):
    import re

    text = file_path.read_text(encoding="utf-8")
    match = re.search(r"^state:\s*(\S+)$", text, re.MULTILINE)
    return match.group(1) if match else None


def test_reconcile_orphaned_reverts_in_progress_without_entry_to_ready(tmp_path):
    """Criterio 1 (caso real T-AF023-US03-01): una Task IN_PROGRESS SIN
    entrada en `dispatch_queue.json` (ni `dispatched` ni reporte) es una
    huérfana real y se revierte a `READY` (preferencia por defecto) en su
    fichero real, desbloqueando la cadena para que las dependientes se
    vuelvan elegibles."""
    from atlas_forge.dispatcher.dispatch_queue import reconcile_orphaned_in_progress_tasks

    backlog_dir = tmp_path / "02-backlog"
    _write_task_md(backlog_dir / "tasks", "T-AF999-US01-01", "US-AF999-01", "IN_PROGRESS")

    reconciled = reconcile_orphaned_in_progress_tasks(tmp_path, "proj", backlog_dir)

    assert reconciled == ["T-AF999-US01-01"]
    assert _read_state(backlog_dir / "tasks" / "T-AF999-US01-01.md") == "READY"


def test_reconcile_orphaned_auto_reenqueue_to_develop(tmp_path):
    """Criterio 2: con `auto_reenqueue_orphaned` activa, la huérfana real
    vuelve a `TO_DEVELOP` — el siguiente `run_dispatch_cycle` la despacha
    sola a un Developer idle, sin intervención humana."""
    from atlas_forge.dispatcher.dispatch_queue import reconcile_orphaned_in_progress_tasks

    backlog_dir = tmp_path / "02-backlog"
    _write_task_md(backlog_dir / "tasks", "T-AF999-US01-01", "US-AF999-01", "IN_PROGRESS")

    reconciled = reconcile_orphaned_in_progress_tasks(
        tmp_path, "proj", backlog_dir, auto_reenqueue_orphaned=True
    )

    assert reconciled == ["T-AF999-US01-01"]
    assert _read_state(backlog_dir / "tasks" / "T-AF999-US01-01.md") == "TO_DEVELOP"


def test_reconcile_orphaned_respects_dispatched_in_progress(tmp_path):
    """Criterio 2 + criterio 7: una Task IN_PROGRESS CON entrada
    `dispatched` (Job legítimo en vuelo) NO se revierte — no duplicar
    trabajo ni descartar nada."""
    from atlas_forge.dispatcher.dispatch_queue import reconcile_orphaned_in_progress_tasks

    backlog_dir = tmp_path / "02-backlog"
    _write_task_md(backlog_dir / "tasks", "T-AF999-US01-01", "US-AF999-01", "IN_PROGRESS")
    enqueue_task(tmp_path, "proj", task_id="T-AF999-US01-01", us_id="US-AF999-01", priority="Alta")
    mark_dispatched(tmp_path, "proj", "T-AF999-US01-01", agent_id="a-1", agent_name="Developer-1")

    reconciled = reconcile_orphaned_in_progress_tasks(tmp_path, "proj", backlog_dir)

    assert reconciled == []
    assert _read_state(backlog_dir / "tasks" / "T-AF999-US01-01.md") == "IN_PROGRESS"


def test_reconcile_orphaned_respects_live_report(tmp_path):
    """Criterio 7: una Task IN_PROGRESS cuyo reporte de Job en vuelo sigue
    existiendo (vía cualquier entrada con `report_file` localizable) NO se
    revierte."""
    from atlas_forge.dispatcher.dispatch_queue import (
        reconcile_orphaned_in_progress_tasks,
        set_entry_report_file,
    )

    backlog_dir = tmp_path / "02-backlog"
    _write_task_md(backlog_dir / "tasks", "T-AF999-US01-01", "US-AF999-01", "IN_PROGRESS")
    enqueue_task(tmp_path, "proj", task_id="T-AF999-US01-01", us_id="US-AF999-01", priority="Alta")
    mark_dispatched(tmp_path, "proj", "T-AF999-US01-01", agent_id="a-1", agent_name="Developer-1")
    report_file = tmp_path / "atlas-forge-job-live.txt"
    report_file.write_text("reporte en vuelo", encoding="utf-8")
    set_entry_report_file(tmp_path, "proj", "T-AF999-US01-01", report_file)

    reconciled = reconcile_orphaned_in_progress_tasks(tmp_path, "proj", backlog_dir)

    assert reconciled == []
    assert _read_state(backlog_dir / "tasks" / "T-AF999-US01-01.md") == "IN_PROGRESS"


def test_reconcile_orphaned_skips_user_story(tmp_path):
    """Criterio 2: una User Story IN_PROGRESS no se toca — su estado deriva
    de sus Tasks; esta función solo reconcilia Tasks (`kind == "T"`)."""
    from atlas_forge.dispatcher.dispatch_queue import reconcile_orphaned_in_progress_tasks

    backlog_dir = tmp_path / "02-backlog"
    _write_us_md(backlog_dir / "user-stories", "US-AF999-01", "IN_PROGRESS")

    reconciled = reconcile_orphaned_in_progress_tasks(tmp_path, "proj", backlog_dir)

    assert reconciled == []
    assert _read_state(backlog_dir / "user-stories" / "US-AF999-01.md") == "IN_PROGRESS"


def test_reconcile_orphaned_writes_reconciliation_log(tmp_path):
    """Criterio 5: la reconciliación de la huérfana real queda registrada en
    `reconciliation_log.jsonl` con el motivo `dispatched_orphan_reconciled`."""
    import json

    from atlas_forge.dispatcher.dispatch_queue import reconcile_orphaned_in_progress_tasks

    backlog_dir = tmp_path / "02-backlog"
    _write_task_md(backlog_dir / "tasks", "T-AF999-US01-01", "US-AF999-01", "IN_PROGRESS")

    reconcile_orphaned_in_progress_tasks(tmp_path, "proj", backlog_dir)

    log_path = tmp_path / ".claude" / "state" / "proj" / "reconciliation_log.jsonl"
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["reason"] == "dispatched_orphan_reconciled"
    assert entry["task_id"] == "T-AF999-US01-01"
    assert entry["target_state"] == "READY"


def test_reconcile_orphaned_is_idempotent(tmp_path):
    """Tras revertir la huérfana a `READY`, una segunda ejecución no vuelve
    a tocar nada (la task ya no está `IN_PROGRESS`)."""
    from atlas_forge.dispatcher.dispatch_queue import reconcile_orphaned_in_progress_tasks

    backlog_dir = tmp_path / "02-backlog"
    _write_task_md(backlog_dir / "tasks", "T-AF999-US01-01", "US-AF999-01", "IN_PROGRESS")

    first = reconcile_orphaned_in_progress_tasks(tmp_path, "proj", backlog_dir)
    second = reconcile_orphaned_in_progress_tasks(tmp_path, "proj", backlog_dir)

    assert first == ["T-AF999-US01-01"]
    assert second == []


def test_reconcile_orphaned_composes_with_dispatch_queue_reconcile(tmp_path):
    """Criterio de composición: ambas funciones pueden convivir — una Task
    con entrada `dispatched` + reporte vivo es resuelta por la de cola (se
    conserva intacta por la de huérfanas), y una Task IN_PROGRESS sin
    entrada es resuelta por la de huérfanas."""
    from atlas_forge.dispatcher.dispatch_queue import (
        reconcile_dispatch_queue_entries,
        reconcile_orphaned_in_progress_tasks,
    )

    backlog_dir = tmp_path / "02-backlog"
    # Huérfana real: IN_PROGRESS sin entrada -> la revierte la nueva función.
    _write_task_md(backlog_dir / "tasks", "T-AF999-US01-01", "US-AF999-01", "IN_PROGRESS")
    # Legítima: IN_PROGRESS con entrada dispatched + reporte vivo -> intacta.
    _write_task_md(backlog_dir / "tasks", "T-AF999-US01-02", "US-AF999-01", "IN_PROGRESS")
    enqueue_task(tmp_path, "proj", task_id="T-AF999-US01-02", us_id="US-AF999-01", priority="Alta")
    mark_dispatched(tmp_path, "proj", "T-AF999-US01-02", agent_id="a-1", agent_name="Developer-1")
    report_file = tmp_path / "atlas-forge-job-live2.txt"
    report_file.write_text("en vuelo", encoding="utf-8")
    from atlas_forge.dispatcher.dispatch_queue import set_entry_report_file

    set_entry_report_file(tmp_path, "proj", "T-AF999-US01-02", report_file)

    # La reconciliación de cola deja intacta la legítima (reporte vivo).
    assert reconcile_dispatch_queue_entries(tmp_path, "proj", backlog_dir) == []
    # La de huérfanas revierte la sin-entrada y respeta la legítima.
    orphaned = reconcile_orphaned_in_progress_tasks(tmp_path, "proj", backlog_dir)

    assert orphaned == ["T-AF999-US01-01"]
    assert _read_state(backlog_dir / "tasks" / "T-AF999-US01-01.md") == "READY"
    assert _read_state(backlog_dir / "tasks" / "T-AF999-US01-02.md") == "IN_PROGRESS"


def test_reconcile_orphaned_empty_backlog_returns_empty(tmp_path):
    """Mejor esfuerzo: sin backlog (directorio inexistente/vacío) no lanza y
    devuelve `[]`."""
    from atlas_forge.dispatcher.dispatch_queue import reconcile_orphaned_in_progress_tasks

    assert reconcile_orphaned_in_progress_tasks(tmp_path, "proj", tmp_path / "no-backlog") == []


def test_reconcile_periodic_respects_protected_inflight_task(tmp_path):
    """T-AF022-US18-02 (regresión observada en vivo): la reconciliación
    periódica NO debe marcar `failed` un Job recién despachado cuyo
    `report_file` aún no existe — el fichero de reporte solo se crea cuando
    el agente TERMINA de escribir su informe. Antes del fix, una tarea que
    acababa de coger un Developer pasaba a `failed` a los pocos segundos
    (mensaje "Job en vuelo perdido tras reinicio") y se re-despachaba,
    duplicando trabajo mientras el agente seguía completándola."""
    from atlas_forge.dispatcher.dispatch_queue import (
        reconcile_dispatch_queue_entries,
        reconcile_orphaned_in_progress_tasks,
    )
    from atlas_forge.dispatcher.dispatch_queue import set_entry_report_file

    backlog_dir = tmp_path / "02-backlog"
    _write_task_md(backlog_dir / "tasks", "T-AF999-US01-01", "US-AF999-01", "IN_PROGRESS")
    enqueue_task(tmp_path, "proj", task_id="T-AF999-US01-01", us_id="US-AF999-01", priority="Alta")
    mark_dispatched(tmp_path, "proj", "T-AF999-US01-01", agent_id="a-1", agent_name="Developer-1")
    # `dispatch_job_send` ya registró la ruta del reporte, pero el agente aún
    # está trabajando: el fichero NO existe todavía (estado NORMAL en vuelo).
    pending_report = tmp_path / "atlas-forge-job-pendiente.txt"
    set_entry_report_file(tmp_path, "proj", "T-AF999-US01-01", pending_report)
    assert not pending_report.exists()

    # El worker vigila esta task en su registro `_inflight` en memoria.
    protected = {"T-AF999-US01-01"}

    assert reconcile_dispatch_queue_entries(
        tmp_path, "proj", backlog_dir, protected_task_ids=protected
    ) == []
    assert reconcile_orphaned_in_progress_tasks(
        tmp_path, "proj", backlog_dir, protected_task_ids=protected
    ) == []

    entry = get_queue(tmp_path, "proj")[0]
    assert entry.status == STATUS_DISPATCHED
    assert _read_state(backlog_dir / "tasks" / "T-AF999-US01-01.md") == "IN_PROGRESS"


def test_reconcile_periodic_still_reverts_unprotected_in_progress(tmp_path):
    """La protección de task_ids en vuelo no anula la reconciliación de
    huérfanas reales: una Task IN_PROGRESS sin protección y sin reporte
    localizable sigue revertiéndose (comportamiento vigente para reinicios
    reales y colas huérfanas)."""
    from atlas_forge.dispatcher.dispatch_queue import reconcile_orphaned_in_progress_tasks

    backlog_dir = tmp_path / "02-backlog"
    _write_task_md(backlog_dir / "tasks", "T-AF999-US01-99", "US-AF999-01", "IN_PROGRESS")

    reconciled = reconcile_orphaned_in_progress_tasks(tmp_path, "proj", backlog_dir)

    assert reconciled == ["T-AF999-US01-99"]
    assert _read_state(backlog_dir / "tasks" / "T-AF999-US01-99.md") == "READY"
