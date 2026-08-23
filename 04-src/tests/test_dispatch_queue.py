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
    QueueEntry,
    clear_history,
    dequeue_task,
    derive_effective_status,
    dispatch_queue_path,
    enqueue_task,
    get_queue,
    mark_completed,
    mark_dispatched,
    mark_failed,
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


def test_reconcile_reverts_in_progress_orphan_to_ready(tmp_path):
    """T-AF008-US10-05, criterio 1: una entrada `dispatched` huérfana
    (Task IN_PROGRESS, Job en vuelo perdido — sin reporte localizable) se
    revierte a `READY` en el fichero real y la entrada queda `failed` con
    el motivo, dejando la plaza libre para re-despachar."""
    backlog_dir = tmp_path / "02-backlog"
    _write_task_md(backlog_dir / "tasks", "T-AF999-US01-01", "US-AF999-01", "IN_PROGRESS")
    enqueue_task(tmp_path, "proj", task_id="T-AF999-US01-01", us_id="US-AF999-01", priority="Alta")
    mark_dispatched(tmp_path, "proj", "T-AF999-US01-01", agent_id="a-1", agent_name="Developer-1")

    from atlas_forge.dispatcher.dispatch_queue import reconcile_dispatch_queue_entries
    reconciled = reconcile_dispatch_queue_entries(tmp_path, "proj", backlog_dir)

    assert reconciled == ["T-AF999-US01-01"]
    task_text = (backlog_dir / "tasks" / "T-AF999-US01-01.md").read_text(encoding="utf-8")
    assert "state: READY" in task_text
    entry = get_queue(tmp_path, "proj")[0]
    assert entry.status == STATUS_FAILED
    assert "reencolada manualmente" in entry.result


def test_reconcile_in_progress_orphan_writes_reconciliation_log(tmp_path):
    """Criterio 4: la reconciliación de una huérfana queda registrada en
    `reconciliation_log.jsonl` con el motivo `dispatched_orphan_reconciled`."""
    backlog_dir = tmp_path / "02-backlog"
    _write_task_md(backlog_dir / "tasks", "T-AF999-US01-01", "US-AF999-01", "IN_PROGRESS")
    enqueue_task(tmp_path, "proj", task_id="T-AF999-US01-01", us_id="US-AF999-01", priority="Alta")
    mark_dispatched(tmp_path, "proj", "T-AF999-US01-01", agent_id="a-1", agent_name="Developer-1")

    from atlas_forge.dispatcher.dispatch_queue import reconcile_dispatch_queue_entries
    reconcile_dispatch_queue_entries(tmp_path, "proj", backlog_dir)

    import json
    log_path = tmp_path / ".claude" / "state" / "proj" / "reconciliation_log.jsonl"
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["reason"] == "dispatched_orphan_reconciled"
    assert entry["task_id"] == "T-AF999-US01-01"
    assert entry["target_state"] == "READY"


def test_reconcile_in_progress_orphan_with_auto_reenqueue_to_develop(tmp_path):
    """Criterio 3 + preferencia automática: con `auto_reenqueue_orphaned`
    activa, la Task huérfana vuelve a `TO_DEVELOP` — el siguiente
    `run_dispatch_cycle` la despacha a un Developer idle sin intervención."""
    backlog_dir = tmp_path / "02-backlog"
    _write_task_md(backlog_dir / "tasks", "T-AF999-US01-01", "US-AF999-01", "IN_PROGRESS")
    enqueue_task(tmp_path, "proj", task_id="T-AF999-US01-01", us_id="US-AF999-01", priority="Alta")
    mark_dispatched(tmp_path, "proj", "T-AF999-US01-01", agent_id="a-1", agent_name="Developer-1")

    from atlas_forge.dispatcher.dispatch_queue import reconcile_dispatch_queue_entries
    reconciled = reconcile_dispatch_queue_entries(
        tmp_path, "proj", backlog_dir, auto_reenqueue_orphaned=True
    )

    assert reconciled == ["T-AF999-US01-01"]
    task_text = (backlog_dir / "tasks" / "T-AF999-US01-01.md").read_text(encoding="utf-8")
    assert "state: TO_DEVELOP" in task_text
    entry = get_queue(tmp_path, "proj")[0]
    assert entry.status == STATUS_FAILED
    assert "reencolada automáticamente" in entry.result


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
