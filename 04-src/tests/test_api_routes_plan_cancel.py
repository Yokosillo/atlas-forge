"""Tests de T-FB016-US01-17: `POST /plans/{plan_id}/cancel`, exponiendo
`job_plan_cancellation.request_cancellation` (T-FB008-US08-01) vía HTTP —
la pieza que cierra US-FB008-08 por completo, mismo patrón que
T-FB016-US01-15 cerró US-FB008-05."""

import threading
import time
import uuid
from pathlib import Path

import libtmux
import pytest
from fastapi.testclient import TestClient

import brain.api.routes as routes_module
from brain.api import create_app
from brain.api.plan_registry import _reset_registry_for_tests as _reset_plan_registry
from brain.api.plan_registry import register_plan
from brain.core import resolve_startup_session
from brain.core.session_registry import _reset_registry_for_tests
from brain.dashboard import launch_agent
from brain.dispatcher.job_cancellation_registry import (
    _reset_registry_for_tests as _reset_job_cancellation,
)
from brain.dispatcher.job_history_registry import _reset_registry_for_tests as _reset_job_history
from brain.dispatcher.job_plan_cancellation_registry import (
    _reset_registry_for_tests as _reset_plan_cancellation,
)
from brain.models import JobPlan, JobPlanStep
from brain.runtime import is_runtime_alive, stop_runtime
from brain.workspace import discover_projects, select_active_project

_COOPERATIVE_AGENT_SCRIPT = str(
    Path(__file__).parent / "fixtures" / "cooperative_agent_sim.sh"
)


@pytest.fixture(autouse=True)
def _clean_registries():
    _reset_registry_for_tests()
    _reset_job_history()
    _reset_plan_registry()
    _reset_job_cancellation()
    _reset_plan_cancellation()
    yield
    _reset_registry_for_tests()
    _reset_job_history()
    _reset_plan_registry()
    _reset_job_cancellation()
    _reset_plan_cancellation()


@pytest.fixture(autouse=True)
def _no_real_runtime(monkeypatch):
    import brain.runtime.claude_code as claude_code_module
    import brain.runtime.opencode as opencode_module

    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_COMMAND", "sleep")
    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_ARGS", ["5"])
    monkeypatch.setattr(opencode_module, "DEFAULT_OPENCODE_COMMAND", "sleep")
    monkeypatch.setattr(opencode_module, "DEFAULT_OPENCODE_AUTONOMY_FLAG", "5")
    monkeypatch.setattr(opencode_module, "DEFAULT_OPENCODE_ARGS", ["5"])


@pytest.fixture
def isolated_socket(monkeypatch):
    name = f"brain-test-{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(routes_module, "_SOCKET_NAME", name)
    try:
        yield name
    finally:
        try:
            libtmux.Server(socket_name=name).kill()
        except Exception:
            pass


def _make_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()


def _active_project_and_session(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    _make_git_repo(workspace / "project-a")
    state_dir = tmp_path / "state"

    discovered = discover_projects(workspace)
    select_active_project(discovered[0], discovered=discovered, state_dir=state_dir)
    monkeypatch.setattr(
        routes_module, "get_active_project", lambda **_kwargs: discovered[0]
    )

    session = resolve_startup_session(workspace_root=workspace, state_dir=state_dir)
    assert session is not None
    return discovered[0], session


def _launch_cooperative_developer(
    tmp_path: Path, session, isolated_socket: str, monkeypatch, extra_env: str = ""
):
    import brain.runtime.claude_code as claude_code_module

    monkeypatch.setattr(
        claude_code_module, "DEFAULT_CLAUDE_CODE_COMMAND", f"{extra_env} bash".strip()
    )
    monkeypatch.setattr(
        claude_code_module, "DEFAULT_CLAUDE_CODE_ARGS", [_COOPERATIVE_AGENT_SCRIPT]
    )
    return launch_agent(
        "developer", "claude-code", None, session, str(tmp_path), socket_name=isolated_socket
    )


def test_post_plan_cancel_on_a_real_plan_with_pending_steps_cancels_it(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """Criterio de aceptación: 'POST /plans/{plan_id}/cancel sobre un plan
    real con pasos pendientes lo cancela, verificado con tmux real.'
    También cierra el criterio central que dejó pendiente T-FB008-US08-01:
    la respuesta HTTP de este endpoint refleja el plan ya `cancelled`, no
    un estado intermedio obsoleto — mismo detalle de condición de carrera
    ya encontrado y corregido en T-FB016-US01-15 para Job."""
    _project, session = _active_project_and_session(tmp_path, monkeypatch)
    agent, runtime_instance = _launch_cooperative_developer(
        tmp_path, session, isolated_socket, monkeypatch, extra_env="SIM_DELAY=10"
    )

    plan = JobPlan(
        goal="FB999-US01",
        steps=[
            JobPlanStep(description="paso 1", mechanism="agent", agent_role="developer"),
            JobPlanStep(description="paso 2", mechanism="agent", agent_role="developer"),
        ],
        status="proposed",
    )
    plan_id = register_plan(plan)

    client = TestClient(create_app())
    approve_thread = threading.Thread(
        target=client.post, args=(f"/plans/{plan_id}/approve",)
    )

    started_at = time.monotonic()
    approve_thread.start()

    deadline = time.monotonic() + 5.0
    while plan.steps[0].status != "running" and time.monotonic() < deadline:
        time.sleep(0.02)
    assert plan.steps[0].status == "running"

    cancel_response = client.post(f"/plans/{plan_id}/cancel")
    approve_thread.join(timeout=5.0)
    elapsed = time.monotonic() - started_at

    assert cancel_response.status_code == 200
    body = cancel_response.json()
    assert body["status"] == "cancelled"
    assert body["steps"][0]["status"] == "cancelled"
    assert body["steps"][1]["status"] == "pending"

    assert not approve_thread.is_alive()
    assert plan.status == "cancelled"
    assert agent.status == "idle"
    # Muy por debajo del delay simulado del agente (10s).
    assert elapsed < 5.0

    assert is_runtime_alive(runtime_instance, socket_name=isolated_socket) is True

    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_post_plan_cancel_returns_400_if_plan_is_not_approved() -> None:
    plan = JobPlan(goal="FB999-US01", status="proposed")
    plan_id = register_plan(plan)

    client = TestClient(create_app())
    response = client.post(f"/plans/{plan_id}/cancel")

    assert response.status_code == 400
    assert "approved" in response.json()["detail"]


def test_post_plan_cancel_returns_400_if_plan_is_blocked() -> None:
    plan = JobPlan(goal="FB999-US01", status="blocked")
    plan_id = register_plan(plan)

    client = TestClient(create_app())
    response = client.post(f"/plans/{plan_id}/cancel")

    assert response.status_code == 400


def test_post_plan_cancel_returns_404_for_unknown_plan_id() -> None:
    client = TestClient(create_app())

    response = client.post("/plans/does-not-exist/cancel")

    assert response.status_code == 404
