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
