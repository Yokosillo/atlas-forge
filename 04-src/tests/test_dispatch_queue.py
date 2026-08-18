"""Tests unitarios de `brain.dispatcher.dispatch_queue` (T-FB008-US10-01),
sin pasar por HTTP — cubre el mecanismo de persistencia (fichero JSON
mutable por proyecto) y las transiciones de estado en aislamiento. Los
tests end-to-end vía `POST/GET/DELETE /backlog/...` viven en
`test_api_routes_dispatch_queue.py`."""

import pytest

from brain.dispatcher.dispatch_queue import (
    STATUS_DISPATCHED,
    STATUS_FAILED,
    STATUS_QUEUED,
    TaskAlreadyDispatchedError,
    TaskAlreadyQueuedError,
    TaskNotQueuedError,
    dequeue_task,
    dispatch_queue_path,
    enqueue_task,
    get_queue,
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
        tmp_path, "proj", task_id="T-FB999-US01-01", us_id="US-FB999-01", priority="Alta"
    )

    assert entry.task_id == "T-FB999-US01-01"
    assert entry.us_id == "US-FB999-01"
    assert entry.priority == "Alta"
    assert entry.status == STATUS_QUEUED
    assert entry.enqueued_at

    entries = get_queue(tmp_path, "proj")
    assert len(entries) == 1
    assert entries[0].task_id == "T-FB999-US01-01"


def test_enqueue_task_twice_raises_task_already_queued(tmp_path):
    enqueue_task(tmp_path, "proj", task_id="T-1", us_id="US-1", priority=None)

    with pytest.raises(TaskAlreadyQueuedError):
        enqueue_task(tmp_path, "proj", task_id="T-1", us_id="US-1", priority=None)


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
# migrate_queued_entries_to_state (T-FB008-US14-01, criterio de migración)
# ---------------------------------------------------------------------------


def _write_task_md(tasks_dir, task_id, us_id, state):
    tasks_dir.mkdir(parents=True, exist_ok=True)
    (tasks_dir / f"{task_id}.md").write_text(
        "---\n"
        f"id: {task_id}\ntype: task\ntitle: Task\nstate: {state}\n"
        f"dependencies: []\nepic: FB-999\nuser_story: {us_id}\npriority: Alta\n"
        "---\n\n"
        f"# {task_id}\n\n## Objetivo\n\nObjetivo.\n\n## Criterios de aceptación\n\n1. Y.\n",
        encoding="utf-8",
    )


def test_migrate_queued_entries_to_state_updates_task_still_in_todo(tmp_path):
    """Caso real de la migración: una Task se encoló ANTES de esta Task
    (entrada `queued` en el JSON) con el mecanismo antiguo — su fichero
    real sigue en `TODO`, nunca se escribió `EN_DESARROLLO`. La migración pone
    el fichero real al día sin perder la entrada JSON."""
    from brain.dispatcher.dispatch_queue import migrate_queued_entries_to_state

    backlog_dir = tmp_path / "02-backlog"
    _write_task_md(backlog_dir / "tasks", "T-FB999-US01-01", "US-FB999-01", "TODO")
    enqueue_task(tmp_path, "proj", task_id="T-FB999-US01-01", us_id="US-FB999-01", priority="Alta")

    migrated = migrate_queued_entries_to_state(tmp_path, "proj", backlog_dir)

    assert migrated == ["T-FB999-US01-01"]
    task_text = (backlog_dir / "tasks" / "T-FB999-US01-01.md").read_text(encoding="utf-8")
    assert "state: EN_DESARROLLO" in task_text
    # La entrada JSON no se toca — sigue como registro auxiliar.
    entries = get_queue(tmp_path, "proj")
    assert entries[0].status == STATUS_QUEUED


def test_migrate_queued_entries_to_state_is_idempotent(tmp_path):
    """Ejecutarlo dos veces no vuelve a tocar nada la segunda vez — la
    Task ya migrada está en `EN_DESARROLLO`, no en `TODO`."""
    from brain.dispatcher.dispatch_queue import migrate_queued_entries_to_state

    backlog_dir = tmp_path / "02-backlog"
    _write_task_md(backlog_dir / "tasks", "T-FB999-US01-01", "US-FB999-01", "TODO")
    enqueue_task(tmp_path, "proj", task_id="T-FB999-US01-01", us_id="US-FB999-01", priority="Alta")

    first = migrate_queued_entries_to_state(tmp_path, "proj", backlog_dir)
    second = migrate_queued_entries_to_state(tmp_path, "proj", backlog_dir)

    assert first == ["T-FB999-US01-01"]
    assert second == []


def test_migrate_queued_entries_to_state_skips_task_already_past_todo(tmp_path):
    """Una Task `queued` en el JSON cuyo fichero real ya no está en
    `TODO` (p. ej. el Dispatcher ya la despachó y el JSON quedó
    desincronizado, o alguien la movió a mano) no se toca — mismo
    criterio de "nunca revierte" que `promote_backlog`."""
    from brain.dispatcher.dispatch_queue import migrate_queued_entries_to_state

    backlog_dir = tmp_path / "02-backlog"
    _write_task_md(backlog_dir / "tasks", "T-FB999-US01-01", "US-FB999-01", "IN_PROGRESS")
    enqueue_task(tmp_path, "proj", task_id="T-FB999-US01-01", us_id="US-FB999-01", priority="Alta")

    migrated = migrate_queued_entries_to_state(tmp_path, "proj", backlog_dir)

    assert migrated == []
    task_text = (backlog_dir / "tasks" / "T-FB999-US01-01.md").read_text(encoding="utf-8")
    assert "state: IN_PROGRESS" in task_text


def test_migrate_queued_entries_to_state_returns_empty_for_empty_queue(tmp_path):
    from brain.dispatcher.dispatch_queue import migrate_queued_entries_to_state

    backlog_dir = tmp_path / "02-backlog"
    assert migrate_queued_entries_to_state(tmp_path, "proj", backlog_dir) == []
