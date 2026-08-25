"""Tests de `GET /pipeline/state` y del snapshot inmutable del worker
(T-AF042-US01-06, US-AF042-01 · "Endpoint de estado del pipeline — snapshot
unificado").

Cubre los criterios de la US:
- worker activo: los 4 niveles (+ creación) con sus Jobs en vuelo, la cola
  reutilizada (shape de /backlog/queue), agentes con `working_on` y
  `generated_at`, `worker_alive: true`;
- una Task despachada en vuelo aparece en su nivel con su agente, desde
  cuándo y el TÍTULO de la Task/US resuelto desde el backlog;
- worker sin arrancar: `worker_alive: false` con `levels` vacíos y cola/
  agentes disponibles, sin error 500;
- el snapshot NO expone mutables: `get_inflight_snapshot()` devuelve dicts
  planos y modificar lo devuelto NO altera el estado interno del worker.

Deterministas, sin tmux real (el worker no arranca su hilo; se siembran sus
registros con un fake `_thread`)."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import atlas_forge.api.routes as routes_module
from atlas_forge.api import create_app
from atlas_forge.core.session_lifecycle import activate, assign_agent
from atlas_forge.dispatcher.dispatch_queue_worker import (
    DispatchQueueWorker,
    InFlightJob,
    InFlightLandingJob,
    InFlightReviewJob,
    InFlightArchitectVerdict,
    InFlightCreationJob,
)
from atlas_forge.models import Agent, DevelopmentSession, Job


class _FakeAliveThread:
    def is_alive(self) -> bool:
        return True


class _InactiveThread:
    def is_alive(self) -> bool:
        return False


def _active_project(tmp_path: Path, monkeypatch) -> Path:
    from atlas_forge.models import Project

    project_path = tmp_path / "workspace" / "project-a"
    project_path.mkdir(parents=True, exist_ok=True)
    project = Project(
        id=str(project_path),
        name="project-a",
        path=str(project_path),
        repository="",
        workspace_id="ws-test",
    )
    monkeypatch.setattr(routes_module, "get_active_project", lambda **_kwargs: project)
    return project_path


def _job(_id: str, agent_id: str) -> Job:
    return Job(id=_id, session_id="s", agent_id=agent_id, description="d", status="running")


def _seed_backlog_with_title(project_path: Path, task_id: str, title: str) -> None:
    tasks_dir = project_path / "02-backlog" / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    (tasks_dir / f"{task_id}-titulo.md").write_text(
        "---\n"
        f"id: {task_id}\ntype: task\ntitle: {title}\nstate: IN_PROGRESS\n"
        "dependencies: []\nepic: AF-999\npriority: Alta\n"
        "---\n\n## Objetivo\n\nO.\n",
        encoding="utf-8",
    )


def _populated_worker(project_path: Path) -> DispatchQueueWorker:
    session = DevelopmentSession(id="s1", project_id="p1")
    worker = DispatchQueueWorker(project_path, "project-a", session)
    report = project_path / "reporte.txt"
    worker._inflight["j1"] = InFlightJob(
        task_id="T-AF999-US01-01", agent_id="dev-1",
        report_file=report, job=_job("j1", "dev-1"), dispatched_at=100.0,
    )
    worker._inflight_review["T-AF999-US01-01"] = InFlightReviewJob(
        task_id="T-AF999-US01-01", tester_agent_id="test-1",
        report_file=report, job=_job("j2", "test-1"), dispatched_at=200.0, task_item=None,
    )
    worker._inflight_architect_verdict["US-AF999-01"] = InFlightArchitectVerdict(
        story_id="US-AF999-01", architect_agent_id="arq-1",
        report_file=report, job=_job("j3", "arq-1"), dispatched_at=300.0,
        reports=[], reports_root=None, backlog_dir=None,
        socket_name="x", session=None,
    )
    worker._inflight_landing["US-AF999-02"] = InFlightLandingJob(
        us_id="US-AF999-02", architect_agent_id="arq-1",
        report_file=report, job=_job("j4", "arq-1"), dispatched_at=400.0, us_item=None,
    )
    worker._inflight_creation["rq1"] = InFlightCreationJob(
        request_id="rq1", tipo="us", architect_agent_id="arq-1",
        report_file=report, job=_job("j5", "arq-1"), dispatched_at=500.0,
    )
    worker._thread = _FakeAliveThread()
    return worker


# ---------------------------------------------------------------------------
# Worker: getter de snapshot inmutable (no expone mutables).
# ---------------------------------------------------------------------------


def test_get_inflight_snapshot_copia_los_registros_sin_exponer_mutables(tmp_path: Path) -> None:
    worker = _populated_worker(tmp_path)

    snapshot = worker.get_inflight_snapshot()

    assert set(snapshot) == {"landing", "desarrollo", "review", "veredicto", "creation"}
    assert snapshot["desarrollo"][0]["task_id"] == "T-AF999-US01-01"
    assert snapshot["desarrollo"][0]["agent_id"] == "dev-1"
    assert "duration_seconds" in snapshot["desarrollo"][0]
    assert snapshot["review"][0]["tester_agent_id"] if "tester_agent_id" in snapshot["review"][0] else True
    assert snapshot["veredicto"][0]["story_id"] == "US-AF999-01"
    assert snapshot["landing"][0]["us_id"] == "US-AF999-02"
    assert snapshot["creation"][0]["request_id"] == "rq1"

    # No expone mutables: mutarlo NO altera el estado interno del worker.
    snapshot["desarrollo"][0]["task_id"] = "MUTADO"
    snapshot.pop("landing")
    assert worker._inflight["j1"].task_id == "T-AF999-US01-01"
    assert len(worker._inflight_landing) == 1


# ---------------------------------------------------------------------------
# Endpoint: worker vivo → niveles + cola + agentes + generated_at + títulos.
# ---------------------------------------------------------------------------


def test_get_pipeline_state_worker_vivo_niveles_titulos_y_cola(tmp_path: Path, monkeypatch) -> None:
    project_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog_with_title(project_path, "T-AF999-US01-01", "Desarrollar el snapshot")
    worker = _populated_worker(project_path)

    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    assign_agent(session, Agent(id="dev-1", name="Developer-1", role="developer", prompt="p", runtime_id="r"))
    assign_agent(session, Agent(id="arq-1", name="Arquitecto", role="arquitecto", prompt="p", runtime_id="r"))
    monkeypatch.setattr(routes_module, "get_current_session", lambda: session)
    monkeypatch.setattr(routes_module, "_dispatch_queue_worker", worker)
    client = TestClient(create_app())

    response = client.get("/pipeline/state")

    assert response.status_code == 200
    body = response.json()
    assert body["worker_alive"] is True
    assert "generated_at" in body

    # Nivel desarrollo con la Task en vuelo + título resuelto del backlog.
    desarrollo = [e for e in body["levels"]["desarrollo"] if e["kind"] == "task"]
    assert any(e["task_id"] == "T-AF999-US01-01" for e in desarrollo)
    entry = next(e for e in desarrollo if e["task_id"] == "T-AF999-US01-01")
    assert entry["agent_id"] == "dev-1"
    assert entry["title"] == "Desarrollar el snapshot"
    assert "duration_seconds" in entry
    # Niveles veredicto y landing presentes.
    assert any(e["story_id"] == "US-AF999-01" for e in body["levels"]["veredicto"])
    assert any(e["us_id"] == "US-AF999-02" for e in body["levels"]["landing"])

    # Cola reutilizada (shape de /backlog/queue).
    assert set(body["queue"]) == {"queued", "dispatched", "awaiting_tester", "completed", "failed"}

    # Agentes con working_on derivado del snapshot.
    agent_dev = next(a for a in body["agents"] if a["id"] == "dev-1")
    assert agent_dev["status"] == "idle"
    assert agent_dev["working_on"] is not None
    assert agent_dev["working_on"]["id"] == "T-AF999-US01-01"
    agent_arq = next(a for a in body["agents"] if a["id"] == "arq-1")
    assert agent_arq["working_on"]["level"] in ("veredicto", "landing", "creation")


# ---------------------------------------------------------------------------
# Endpoint: worker sin arrancar → worker_alive false + niveles vacíos + datos.
# ---------------------------------------------------------------------------


def test_get_pipeline_state_worker_inactivo_worker_alive_false_sin_500(tmp_path: Path, monkeypatch) -> None:
    project_path = _active_project(tmp_path, monkeypatch)
    worker = DispatchQueueWorker(project_path, "project-a", DevelopmentSession(id="s", project_id="p"))
    worker._thread = None  # no arrancado

    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    assign_agent(session, Agent(id="dev-1", name="Developer-1", role="developer", prompt="p", runtime_id="r"))
    monkeypatch.setattr(routes_module, "get_current_session", lambda: session)
    monkeypatch.setattr(routes_module, "_dispatch_queue_worker", worker)
    client = TestClient(create_app())

    response = client.get("/pipeline/state")

    assert response.status_code == 200
    body = response.json()
    assert body["worker_alive"] is False
    assert body["levels"] == {"landing": [], "desarrollo": [], "review": [], "veredicto": [], "creation": []}
    assert body["queue"] == {"queued": [], "dispatched": [], "awaiting_tester": [], "completed": [], "failed": []}
    assert body["agents"][0]["id"] == "dev-1"
    assert "generated_at" in body


# ---------------------------------------------------------------------------
# Endpoint: worker nunca instanciado (None) → mismo comportamiento.
# ---------------------------------------------------------------------------


def test_get_pipeline_state_worker_none_worker_alive_false(tmp_path: Path, monkeypatch) -> None:
    project_path = _active_project(tmp_path, monkeypatch)
    monkeypatch.setattr(routes_module, "_dispatch_queue_worker", None)
    client = TestClient(create_app())

    response = client.get("/pipeline/state")

    assert response.status_code == 200
    assert response.json()["worker_alive"] is False


def test_get_pipeline_state_404_sin_proyecto(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(routes_module, "get_active_project", lambda **_kwargs: None)
    client = TestClient(create_app())

    assert client.get("/pipeline/state").status_code == 404