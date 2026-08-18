import threading
import time
import uuid
from pathlib import Path

import libtmux
import pytest
from fastapi.testclient import TestClient

import brain.api.routes as routes_module
from brain.api import create_app
from brain.core import resolve_startup_session
from brain.core.session_registry import _reset_registry_for_tests
from brain.agents.launch import launch_agent
from brain.dispatcher.architect_verdict_queue import (
    _instance as _verdict_queue_instance,
    get_verdict_queue_status,
)
from brain.dispatcher.job_cancellation_registry import (
    _reset_registry_for_tests as _reset_job_cancellation,
)
from brain.dispatcher.job_history_registry import _reset_registry_for_tests as _reset_job_history
from brain.dispatcher.job_report import read_job_report
from brain.runtime import is_runtime_alive, stop_runtime
from brain.workspace import discover_projects, select_active_project

_COOPERATIVE_AGENT_SCRIPT = str(
    Path(__file__).parent / "fixtures" / "cooperative_agent_sim.sh"
)


@pytest.fixture(autouse=True)
def _clean_registries():
    _reset_registry_for_tests()
    _reset_job_history()
    _reset_job_cancellation()
    _verdict_queue_instance.reset_for_testing()
    yield
    _reset_registry_for_tests()
    _reset_job_history()
    _reset_job_cancellation()
    _verdict_queue_instance.reset_for_testing()


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


def _launch_cooperative_agent(
    role: str, tmp_path: Path, session, isolated_socket: str, monkeypatch, extra_env: str = ""
):
    """Lanza un agente real (mismo mecanismo que `launch_agent`), pero
    sustituyendo el comando de Claude Code por el doble cooperativo de
    prueba (`cooperative_agent_sim.sh`, mismo fixture ya usado en
    test_job_dispatch.py/test_job_chaining.py) — nunca el binario real."""
    import brain.runtime.claude_code as claude_code_module

    monkeypatch.setattr(
        claude_code_module, "DEFAULT_CLAUDE_CODE_COMMAND", f"{extra_env} bash".strip()
    )
    monkeypatch.setattr(
        claude_code_module, "DEFAULT_CLAUDE_CODE_ARGS", [_COOPERATIVE_AGENT_SCRIPT]
    )

    return launch_agent(
        role, "claude-code", None, session, str(tmp_path), socket_name=isolated_socket
    )


def test_post_jobs_creates_and_dispatches_a_real_job(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """Criterio de aceptación: POST /jobs crea y despacha un Job real,
    reflejado con el mismo resultado que si se hubiera despachado desde
    la TUI (mismo mecanismo, doble cooperativo real vía tmux)."""
    _project, session = _active_project_and_session(tmp_path, monkeypatch)
    agent, runtime_instance = _launch_cooperative_agent(
        "developer", tmp_path, session, isolated_socket, monkeypatch
    )

    client = TestClient(create_app())
    response = client.post(
        "/jobs", json={"agent_id": agent.id, "description": "implement the feature"}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "completed"
    assert "cooperative result" in body["result"]

    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_get_job_returns_status_and_result_after_completion(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """Criterio de aceptación: GET /jobs/{job_id} devuelve el estado
    (completed) y el resultado."""
    _project, session = _active_project_and_session(tmp_path, monkeypatch)
    agent, runtime_instance = _launch_cooperative_agent(
        "developer", tmp_path, session, isolated_socket, monkeypatch
    )

    client = TestClient(create_app())
    created = client.post(
        "/jobs", json={"agent_id": agent.id, "description": "implement the feature"}
    ).json()

    response = client.get(f"/jobs/{created['id']}")

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["result"] == created["result"]

    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_get_job_returns_404_for_unknown_job_id(tmp_path: Path, monkeypatch) -> None:
    _active_project_and_session(tmp_path, monkeypatch)
    client = TestClient(create_app())

    response = client.get("/jobs/does-not-exist")

    assert response.status_code == 404


def test_get_jobs_returns_the_same_history_as_the_tui_screen(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """Criterio de aceptación: GET /jobs devuelve el mismo histórico que
    vería la pantalla Jobs de la TUI (mismo origen de datos,
    list_jobs_for_session, no duplicado)."""
    from brain.dispatcher import list_jobs_for_session

    _project, session = _active_project_and_session(tmp_path, monkeypatch)
    agent, runtime_instance = _launch_cooperative_agent(
        "developer", tmp_path, session, isolated_socket, monkeypatch
    )

    client = TestClient(create_app())
    client.post(
        "/jobs", json={"agent_id": agent.id, "description": "implement the feature"}
    )

    response = client.get("/jobs")

    assert response.status_code == 200
    domain_jobs = list_jobs_for_session(session.id)
    assert [job["id"] for job in response.json()] == [job.id for job in domain_jobs]
    assert len(response.json()) == 1

    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_get_jobs_returns_404_when_no_session_is_active() -> None:
    client = TestClient(create_app())

    response = client.get("/jobs")

    assert response.status_code == 404


def test_post_jobs_chains_developer_result_into_architect_job(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """Criterio de aceptación: encadenar un Job de Developer como entrada
    de un Job de Arquitecto (previous_job_id) funciona igual que hoy en la
    TUI (US-FB008-02) — verificado end-to-end vía HTTP. `SIM_ROLE=critic`
    es solo la etiqueta interna del doble cooperativo de prueba
    (`cooperative_agent_sim.sh`), no depende del rol real lanzado."""
    _project, session = _active_project_and_session(tmp_path, monkeypatch)
    developer, dev_runtime = _launch_cooperative_agent(
        "developer", tmp_path, session, isolated_socket, monkeypatch
    )
    architect, architect_runtime = _launch_cooperative_agent(
        "arquitecto", tmp_path, session, isolated_socket, monkeypatch, extra_env="SIM_ROLE=critic"
    )

    client = TestClient(create_app())
    dev_job = client.post(
        "/jobs",
        json={"agent_id": developer.id, "description": "implement something"},
    ).json()
    assert dev_job["status"] == "completed"

    architect_job = client.post(
        "/jobs",
        json={
            "agent_id": architect.id,
            "description": "review this implementation",
            "previous_job_id": dev_job["id"],
        },
    ).json()

    assert architect_job["status"] == "completed"
    assert "reviewed the following prior result" in architect_job["result"]

    stop_runtime(dev_runtime, socket_name=isolated_socket)
    stop_runtime(architect_runtime, socket_name=isolated_socket)


def test_post_jobs_rejects_developer_to_developer_chaining(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """T-FB008-US07-01 vía HTTP (consumidor real de `create_job`): encadenar
    Developer→Developer se rechaza con 400 y mensaje explícito, sin crear el
    Job — el dominio no registra nada (no hay Job nuevo en el histórico)."""
    _project, session = _active_project_and_session(tmp_path, monkeypatch)
    developer, dev_runtime = _launch_cooperative_agent(
        "developer", tmp_path, session, isolated_socket, monkeypatch
    )

    client = TestClient(create_app())
    dev_job = client.post(
        "/jobs",
        json={"agent_id": developer.id, "description": "implement something"},
    ).json()
    assert dev_job["status"] == "completed"

    before = {job["id"] for job in client.get("/jobs").json()}
    response = client.post(
        "/jobs",
        json={
            "agent_id": developer.id,
            "description": "implement something else",
            "previous_job_id": dev_job["id"],
        },
    )
    after = {job["id"] for job in client.get("/jobs").json()}

    assert response.status_code == 400
    assert "debe encadenarse a un Arquitecto" in response.json()["detail"]
    assert after == before  # ningún Job nuevo registrado

    stop_runtime(dev_runtime, socket_name=isolated_socket)


def test_post_jobs_returns_404_for_unknown_agent(tmp_path: Path, monkeypatch) -> None:
    _active_project_and_session(tmp_path, monkeypatch)
    client = TestClient(create_app())

    response = client.post(
        "/jobs", json={"agent_id": "does-not-exist", "description": "do something"}
    )

    assert response.status_code == 404


def test_post_jobs_returns_404_for_unknown_previous_job_id(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    _project, session = _active_project_and_session(tmp_path, monkeypatch)
    agent, runtime_instance = _launch_cooperative_agent(
        "developer", tmp_path, session, isolated_socket, monkeypatch
    )

    client = TestClient(create_app())
    response = client.post(
        "/jobs",
        json={
            "agent_id": agent.id,
            "description": "review this",
            "previous_job_id": "does-not-exist",
        },
    )

    assert response.status_code == 404

    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_post_jobs_returns_404_when_no_session_is_active() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/jobs", json={"agent_id": "whatever", "description": "do something"}
    )

    assert response.status_code == 404


def test_post_job_cancel_interrupts_the_original_post_jobs_request(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """Criterio de aceptación central de US-FB008-05 (el que dejó pendiente
    T-FB008-US05-01): la petición `POST /jobs` ORIGINAL — la que despachó
    el Job y está bloqueada esperando su resultado — recibe efectivamente
    la respuesta de cancelación, no un timeout normal, cuando otra petición
    concurrente llama a `POST /jobs/{id}/cancel`. Verificado con tmux real
    (agente cooperativo con `SIM_DELAY=10`) y un test de tiempos: la
    petición original debe resolver en mucho menos que su timeout de
    despacho real y que el delay simulado del agente."""
    _project, session = _active_project_and_session(tmp_path, monkeypatch)
    agent, runtime_instance = _launch_cooperative_agent(
        "developer", tmp_path, session, isolated_socket, monkeypatch, extra_env="SIM_DELAY=10"
    )

    client = TestClient(create_app())
    original_request_result: dict = {}

    def _dispatch_original_request() -> None:
        response = client.post(
            "/jobs",
            json={"agent_id": agent.id, "description": "implement the feature"},
        )
        original_request_result["status_code"] = response.status_code
        original_request_result["body"] = response.json()

    started_at = time.monotonic()
    original_thread = threading.Thread(target=_dispatch_original_request)
    original_thread.start()

    # Espera a que el Job exista y esté `running` antes de cancelarlo desde
    # la petición concurrente — evita una condición de carrera contra el
    # arranque del hilo de la petición original.
    deadline = time.monotonic() + 5.0
    job_id = None
    while job_id is None and time.monotonic() < deadline:
        jobs = client.get("/jobs").json()
        running = [job for job in jobs if job["status"] == "running"]
        if running:
            job_id = running[0]["id"]
        else:
            time.sleep(0.05)
    assert job_id is not None

    cancel_response = client.post(f"/jobs/{job_id}/cancel")
    original_thread.join(timeout=5.0)
    elapsed = time.monotonic() - started_at

    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == "cancelled"

    assert not original_thread.is_alive()
    assert original_request_result["status_code"] == 201
    assert original_request_result["body"]["status"] == "cancelled"
    # Muy por debajo del delay simulado del agente (10s) — la petición
    # original recibió la cancelación, no esperó a que el agente reportara.
    assert elapsed < 5.0

    assert is_runtime_alive(runtime_instance, socket_name=isolated_socket) is True

    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_post_job_cancel_returns_400_for_a_job_that_already_completed(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    _project, session = _active_project_and_session(tmp_path, monkeypatch)
    agent, runtime_instance = _launch_cooperative_agent(
        "developer", tmp_path, session, isolated_socket, monkeypatch
    )

    client = TestClient(create_app())
    job = client.post(
        "/jobs", json={"agent_id": agent.id, "description": "implement the feature"}
    ).json()
    assert job["status"] == "completed"

    response = client.post(f"/jobs/{job['id']}/cancel")

    assert response.status_code == 400
    assert "completed" in response.json()["detail"]

    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_post_job_cancel_returns_404_for_unknown_job_id(
    tmp_path: Path, monkeypatch
) -> None:
    _active_project_and_session(tmp_path, monkeypatch)
    client = TestClient(create_app())

    response = client.post("/jobs/does-not-exist/cancel")

    assert response.status_code == 404


def test_post_job_cancel_returns_404_when_no_session_is_active() -> None:
    client = TestClient(create_app())

    response = client.post("/jobs/whatever/cancel")

    assert response.status_code == 404


def test_post_jobs_with_story_id_writes_report_and_marks_story_review(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """T-FB024-US15-01, criterio de aceptación central: `POST /jobs` con
    `story_id` informado, al completarse el Job, genera el informe de
    cierre en `07-informes` — de punta a punta, con tmux real (doble
    cooperativo), no mockeando la lógica de negocio.

    T-FB008-US14-02: `trigger_architect_verdict` ya no encola un
    veredicto directamente (la cola FIFO ciega de `architect_verdict_queue`
    se sustituyó por reparto vía el Dispatcher, que comprueba
    disponibilidad real del Arquitecto) — ahora, cuando TODAS las Tasks
    de la Story están `DONE` en el backlog real del proyecto activo,
    marca la propia User Story en `state: REVIEW`. Se crea una US y una
    Task sintéticas ya `DONE` en `project-a/02-backlog/` para verificar
    el disparo real (antes de esta Task, disparaba sin comprobar nada,
    bug de diseño corregido)."""
    _project, session = _active_project_and_session(tmp_path, monkeypatch)
    backlog_dir = tmp_path / "workspace" / "project-a" / "02-backlog"
    stories_dir = backlog_dir / "user-stories"
    stories_dir.mkdir(parents=True, exist_ok=True)
    story_path = stories_dir / "US-FB024-15-titulo.md"
    story_path.write_text(
        "---\nid: US-FB024-15\ntype: user-story\ntitle: Titulo\nstate: TODO\n"
        "dependencies: []\nepic: FB-024\n---\n\n# US-FB024-15\n\n## Contexto\n\nC.\n",
        encoding="utf-8",
    )
    tasks_dir = backlog_dir / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    (tasks_dir / "T-FB024-US15-01.md").write_text(
        "---\nid: T-FB024-US15-01\ntype: task\ntitle: Task\nstate: DONE\n"
        "dependencies: []\nepic: FB-024\nuser_story: US-FB024-15\npriority: Alta\n---\n\n"
        "# T-FB024-US15-01\n\n## Objetivo\n\nObjetivo.\n\n## Criterios de aceptación\n\n1. Y.\n",
        encoding="utf-8",
    )
    agent, runtime_instance = _launch_cooperative_agent(
        "developer", tmp_path, session, isolated_socket, monkeypatch
    )

    from brain.dispatcher.job_report import write_job_report as _real_write_job_report

    reports_root = tmp_path / "07-informes"

    def _write_to_tmp(job):
        return _real_write_job_report(job, reports_root=reports_root)

    monkeypatch.setattr(routes_module, "write_job_report", _write_to_tmp)

    client = TestClient(create_app())
    response = client.post(
        "/jobs",
        json={
            "agent_id": agent.id,
            "description": "implement the feature",
            "story_id": "US-FB024-15",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "completed"

    story_text = story_path.read_text(encoding="utf-8")
    assert "state: REVIEW" in story_text

    report = read_job_report("US-FB024-15", body["id"], reports_root=reports_root)
    assert report is not None
    assert "cooperative result" in report

    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_post_jobs_without_story_id_does_not_write_report_or_enqueue_verdict(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """T-FB024-US15-01, test de regresión dedicado: un Job sin `story_id`
    no dispara ni informe ni veredicto — comportamiento actual preservado."""
    _project, session = _active_project_and_session(tmp_path, monkeypatch)
    agent, runtime_instance = _launch_cooperative_agent(
        "developer", tmp_path, session, isolated_socket, monkeypatch
    )

    write_report_calls = []
    monkeypatch.setattr(
        routes_module,
        "write_job_report",
        lambda job: write_report_calls.append(job.id),
    )
    verdict_calls = []
    monkeypatch.setattr(
        routes_module,
        "trigger_architect_verdict",
        lambda story_id, session_arg, socket_name=None: verdict_calls.append(story_id),
    )

    client = TestClient(create_app())
    response = client.post(
        "/jobs", json={"agent_id": agent.id, "description": "implement the feature"}
    )

    assert response.status_code == 201
    assert response.json()["status"] == "completed"
    assert write_report_calls == []
    assert verdict_calls == []

    status = get_verdict_queue_status()
    assert status["active"] is None
    assert status["waiting"] == []

    stop_runtime(runtime_instance, socket_name=isolated_socket)
