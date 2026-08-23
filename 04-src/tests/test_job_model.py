import pytest

from atlas_forge.dispatcher import (
    InvalidJobTransitionError,
    get_job_state,
    mark_completed,
    mark_failed,
    mark_running,
)
from atlas_forge.models import Job


def _make_job(status: str = "created") -> Job:
    return Job(
        id="j1",
        session_id="s1",
        agent_id="a1",
        description="test description",
        status=status,
    )


def test_job_construction_is_created_with_empty_result() -> None:
    job = _make_job()

    assert job.id == "j1"
    assert job.session_id == "s1"
    assert job.agent_id == "a1"
    assert job.description == "test description"
    assert job.status == "created"
    assert job.result == ""


def test_mark_running_transitions_from_created() -> None:
    job = _make_job(status="created")

    mark_running(job)

    assert job.status == "running"


def test_mark_completed_transitions_from_running_and_registers_result() -> None:
    job = _make_job(status="running")

    mark_completed(job, result="the implementation result")

    assert job.status == "completed"
    assert job.result == "the implementation result"


def test_mark_failed_transitions_from_running_and_registers_reason() -> None:
    job = _make_job(status="running")

    mark_failed(job, reason="agent crashed")

    assert job.status == "failed"
    assert job.result == "agent crashed"


def test_mark_running_rejected_from_completed() -> None:
    job = _make_job(status="completed")

    with pytest.raises(InvalidJobTransitionError):
        mark_running(job)

    assert job.status == "completed"


def test_mark_completed_rejected_from_created() -> None:
    # No se puede saltar directamente created -> completed sin pasar por running.
    job = _make_job(status="created")

    with pytest.raises(InvalidJobTransitionError):
        mark_completed(job, result="skip attempt")

    assert job.status == "created"
    # La transición inválida no debe dejar mutado el resultado: la validación
    # ocurre antes de tocar `job.result`, no después.
    assert job.result == ""


def test_mark_failed_rejected_from_created() -> None:
    # No se puede saltar directamente created -> failed sin pasar por running.
    job = _make_job(status="created")

    with pytest.raises(InvalidJobTransitionError):
        mark_failed(job, reason="skip attempt")

    assert job.status == "created"
    # Misma garantía que mark_completed: sin mutación de `job.result` en un
    # rechazo de transición.
    assert job.result == ""


def test_get_job_state_for_freshly_created_job() -> None:
    job = _make_job()

    state = get_job_state(job)

    assert state == {
        "id": "j1",
        "session_id": "s1",
        "agent_id": "a1",
        "description": "test description",
        "status": "created",
        "result": "",
    }


def test_get_job_state_for_completed_job_returns_registered_result() -> None:
    job = _make_job(status="running")
    mark_completed(job, result="final output")

    state = get_job_state(job)

    assert state["status"] == "completed"
    assert state["result"] == "final output"
