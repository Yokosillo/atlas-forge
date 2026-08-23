"""Tests de T-AF023-US02-01: lógica pura de recuperación de un agente colgado
con límite de reintentos consecutivos y estado consultable. Deterministas, sin
infraestructura."""

from atlas_forge.agents.recovery import (
    ACTION_NONE,
    ACTION_RELAUNCH,
    ACTION_RELAUNCH_PRESERVING_CONTEXT,
    DEFAULT_MAX_CONSECUTIVE_RETRIES,
    RETRY_STATUS_FAILED,
    RETRY_STATUS_OK,
    RETRY_STATUS_RECOVERING,
    RecoveryPlan,
    RecoveryRetryTracker,
    plan_recovery,
)


# ── plan_recovery (decisión pura) ───────────────────────────────────────────


def test_no_hang_means_no_recovery() -> None:
    plan = plan_recovery(hung=False, runtime_type="opencode", session_id="s1")
    assert plan.action == ACTION_NONE
    assert not plan.kill_needed
    assert not plan.recovers


def test_opencode_preserves_context_with_session() -> None:
    plan = plan_recovery(hung=True, runtime_type="opencode", session_id="sess-1")
    assert plan.action == ACTION_RELAUNCH_PRESERVING_CONTEXT
    assert plan.kill_needed
    assert plan.session_id == "sess-1"
    assert "--session" in plan.relaunch_args
    assert "sess-1" in plan.relaunch_args
    assert "--auto" in plan.relaunch_args


def test_opencode_without_session_relaunches_without_context() -> None:
    plan = plan_recovery(hung=True, runtime_type="opencode")
    assert plan.action == ACTION_RELAUNCH
    assert plan.kill_needed


def test_non_opencode_relaunches_without_context() -> None:
    for rt in ("claude-code", "codex"):
        plan = plan_recovery(hung=True, runtime_type=rt)
        assert plan.action == ACTION_RELAUNCH
        assert plan.kill_needed


# ── RecoveryRetryTracker (límite de reintentos) ─────────────────────────────


def test_default_max_retries_is_three() -> None:
    assert DEFAULT_MAX_CONSECUTIVE_RETRIES == 3
    assert RecoveryRetryTracker().max_retries == 3


def test_recovery_stops_after_max_consecutive_failures() -> None:
    tracker = RecoveryRetryTracker(max_retries=3)
    assert tracker.status == RETRY_STATUS_OK
    assert tracker.should_retry()

    tracker.record_failure("err1")
    assert tracker.status == RETRY_STATUS_RECOVERING
    assert tracker.should_retry()

    tracker.record_failure("err2")
    assert tracker.status == RETRY_STATUS_RECOVERING
    assert tracker.should_retry()

    tracker.record_failure("err3")
    # Se superó el límite: estado de fallo consultable, no se reintenta más.
    assert tracker.status == RETRY_STATUS_FAILED
    assert not tracker.should_retry()
    assert tracker.last_error == "err3"


def test_success_resets_consecutive_counter() -> None:
    tracker = RecoveryRetryTracker(max_retries=3)
    tracker.record_failure("e1").record_failure("e2")
    assert tracker.status == RETRY_STATUS_RECOVERING

    tracker.record_success()
    assert tracker.status == RETRY_STATUS_OK
    assert tracker.consecutive_retries == 0
    assert tracker.last_error is None
    assert tracker.should_retry()


def test_custom_max_retries_is_configurable() -> None:
    tracker = RecoveryRetryTracker(max_retries=1)
    tracker.record_failure()
    assert tracker.status == RETRY_STATUS_FAILED
    assert not tracker.should_retry()
