import functools
import threading
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
from brain.agents.launch import launch_agent
from brain.dispatcher.job_history_registry import _reset_registry_for_tests as _reset_job_history
from brain.dispatcher.job_plan_builder import build_job_plan_for_story
from brain.models import JobPlan, JobPlanStep
from brain.runtime import stop_runtime
from brain.workspace import discover_projects, select_active_project

_COOPERATIVE_AGENT_SCRIPT = str(
    Path(__file__).parent / "fixtures" / "cooperative_agent_sim.sh"
)


@pytest.fixture(autouse=True)
def _clean_registries():
    _reset_registry_for_tests()
    _reset_job_history()
    _reset_plan_registry()
    yield
    _reset_registry_for_tests()
    _reset_job_history()
    _reset_plan_registry()


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


def _write_task(
    tasks_dir: Path, story_id: str, correlative: str, slug: str, title: str, body: str
) -> None:
    content = (
        f"# T-{story_id}-{correlative}-{slug} · {title}\n\n"
        f"**User Story:** {story_id}\n\n"
        "## Descripción\n\n"
        f"{body}\n\n"
        "## Estado\n\n"
        "TODO\n"
    )
    (tasks_dir / f"T-{story_id}-{correlative}-{slug}.md").write_text(
        content, encoding="utf-8"
    )


def _isolated_backlog(tmp_path: Path, monkeypatch, story_id: str = "FB999-US01") -> None:
    """Aísla `POST /plans` de un `tasks_dir` real de prueba, en vez del
    backlog real del producto (frágil: sus Tasks reales cambian de estado
    con cada aprobación del crítico) — monkeypatchea la función tal como
    la ve `routes_module` (mismo patrón ya usado para `get_active_project`)."""
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    _write_task(
        tasks_dir,
        story_id,
        "01",
        "paso-agente",
        "Implementar la funcionalidad",
        body="Requiere criterio de diseño e implementación real.",
    )
    monkeypatch.setattr(
        routes_module,
        "build_job_plan_for_story",
        functools.partial(build_job_plan_for_story, tasks_dir=tasks_dir),
    )


def _launch_cooperative_developer(
    tmp_path: Path, session, isolated_socket: str, monkeypatch
):
    import brain.runtime.claude_code as claude_code_module

    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_COMMAND", "bash")
    monkeypatch.setattr(
        claude_code_module, "DEFAULT_CLAUDE_CODE_ARGS", [_COOPERATIVE_AGENT_SCRIPT]
    )
    return launch_agent(
        "developer", "claude-code", None, session, str(tmp_path), socket_name=isolated_socket
    )


def test_post_plans_builds_a_real_plan_without_dispatching_anything(
    tmp_path: Path, monkeypatch
) -> None:
    """Criterio de aceptación: POST /plans devuelve un plan real, sin
    despachar ningún Job todavía."""
    _isolated_backlog(tmp_path, monkeypatch)
    client = TestClient(create_app())

    response = client.post("/plans", json={"goal": "FB999-US01"})

    assert response.status_code == 201
    body = response.json()
    assert body["goal"] == "FB999-US01"
    assert body["status"] == "proposed"
    assert len(body["steps"]) == 1
    assert body["steps"][0]["status"] == "pending"
    assert "plan_id" in body


def test_post_plan_reject_prevents_any_dispatch(tmp_path: Path, monkeypatch) -> None:
    """Criterio de aceptación: rechazar funciona igual que en el dominio
    — ningún Job del plan se despacha."""
    _isolated_backlog(tmp_path, monkeypatch)
    client = TestClient(create_app())
    plan_id = client.post("/plans", json={"goal": "FB999-US01"}).json()["plan_id"]

    response = client.post(f"/plans/{plan_id}/reject")

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert response.json()["steps"][0]["status"] == "pending"


def test_post_plan_approve_dispatches_the_real_plan(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """Criterio de aceptación: aprobar despacha el plan completo,
    reutilizando dispatch_plan (US-FB008-04) sin reimplementarlo."""
    _project, session = _active_project_and_session(tmp_path, monkeypatch)
    _isolated_backlog(tmp_path, monkeypatch)
    agent, runtime_instance = _launch_cooperative_developer(
        tmp_path, session, isolated_socket, monkeypatch
    )

    client = TestClient(create_app())
    plan_id = client.post("/plans", json={"goal": "FB999-US01"}).json()["plan_id"]

    response = client.post(f"/plans/{plan_id}/approve")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "approved"
    assert body["steps"][0]["status"] == "completed"

    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_post_plan_approve_returns_404_without_active_session(
    tmp_path: Path, monkeypatch
) -> None:
    _isolated_backlog(tmp_path, monkeypatch)
    client = TestClient(create_app())
    plan_id = client.post("/plans", json={"goal": "FB999-US01"}).json()["plan_id"]

    response = client.post(f"/plans/{plan_id}/approve")

    assert response.status_code == 404


def test_plan_endpoints_return_404_for_unknown_plan_id() -> None:
    client = TestClient(create_app())

    assert client.get("/plans/does-not-exist").status_code == 404
    assert client.post("/plans/does-not-exist/approve").status_code == 404
    assert client.post("/plans/does-not-exist/reject").status_code == 404


def test_ws_plans_receives_progress_event_on_post_plans(
    tmp_path: Path, monkeypatch
) -> None:
    """Criterio de aceptación: /ws/plans refleja el progreso del
    despacho — aquí, el propio evento de construcción del plan."""
    _isolated_backlog(tmp_path, monkeypatch)

    with TestClient(create_app()) as client:
        with client.websocket_connect("/ws/plans") as websocket:
            response = client.post("/plans", json={"goal": "FB999-US01"})
            plan_id = response.json()["plan_id"]

            event = websocket.receive_json()

    assert event["event"] == "plan_progress"
    assert event["plan_id"] == plan_id
    assert event["status"] == "proposed"


def test_ws_jobs_receives_status_events_when_a_job_is_dispatched_via_api(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """Criterio de aceptación: un cliente conectado a /ws/jobs recibe un
    evento cuando un Job despachado (aquí, vía API — la única vía de
    despacho de Jobs que existe dentro del proceso brain-api, ver
    docstring de brain.api.events) cambia de estado."""
    _project, session = _active_project_and_session(tmp_path, monkeypatch)
    agent, runtime_instance = _launch_cooperative_developer(
        tmp_path, session, isolated_socket, monkeypatch
    )

    with TestClient(create_app()) as client:
        with client.websocket_connect("/ws/jobs") as websocket:
            response = client.post(
                "/jobs",
                json={"agent_id": agent.id, "description": "implement the feature"},
            )
            job_id = response.json()["id"]

            created_event = websocket.receive_json()
            final_event = websocket.receive_json()

    assert created_event["event"] == "job_status"
    assert created_event["id"] == job_id
    assert created_event["status"] == "created"

    assert final_event["event"] == "job_status"
    assert final_event["id"] == job_id
    assert final_event["status"] == "completed"

    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_concurrent_approve_calls_dispatch_the_plan_only_once(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """Criterio de aceptación explícito de T-FB016-US01-08: dos llamadas
    casi simultáneas a POST /plans/{plan_id}/approve para el mismo plan
    resultan en un único despacho real (dispatch_plan invocado una sola
    vez) — disparadas de verdad de forma concurrente (dos hilos Python
    reales, no secuencial), contra el mismo TestClient/app.

    Para que el test exponga la carrera de forma DETERMINISTA (no
    depender de que dos hilos reales se solapen "por suerte" en una
    ventana de microsegundos, lo que haría el test flaky-por-diseño-débil
    y capaz de pasar en verde incluso sin el lock real): se inserta un
    delay artificial breve DENTRO de `present_plan_for_approval` — la
    misma operación protegida por `get_plan_lock` en producción — para
    forzar que el segundo hilo llegue a la sección crítica mientras el
    primero sigue "dentro" de la comprobación de estado. Verificado
    manualmente (retirando el lock real y restaurándolo de inmediato, no
    como parte de la suite permanente) que sin el lock este mismo test
    falla de forma consistente: `call_count` no llega a superar 1 antes
    de que la segunda petición concurrente reciba una respuesta que no es
    200 (colisión real al despachar/transicionar el mismo `JobPlan` desde
    dos hilos a la vez) — confirma que el test detecta la ausencia de
    protección, no solo que pasa "porque sí"."""
    _project, session = _active_project_and_session(tmp_path, monkeypatch)
    _isolated_backlog(tmp_path, monkeypatch)
    agent, runtime_instance = _launch_cooperative_developer(
        tmp_path, session, isolated_socket, monkeypatch
    )

    client = TestClient(create_app())
    plan_id = client.post("/plans", json={"goal": "FB999-US01"}).json()["plan_id"]

    real_dispatch_plan = routes_module.dispatch_plan
    real_present_plan_for_approval = routes_module.present_plan_for_approval
    call_count = 0
    call_count_lock = threading.Lock()
    both_threads_ready = threading.Barrier(2, timeout=5.0)

    def _counting_dispatch_plan(*args, **kwargs):
        nonlocal call_count
        with call_count_lock:
            call_count += 1
        return real_dispatch_plan(*args, **kwargs)

    def _slow_present_plan_for_approval(*args, **kwargs):
        # Delay dentro de la sección crítica real (bajo el lock, en
        # producción): da tiempo a que el segundo hilo intente entrar
        # mientras el primero sigue dentro, forzando el solapamiento que
        # el lock debe impedir.
        import time

        time.sleep(0.2)
        return real_present_plan_for_approval(*args, **kwargs)

    responses: list = [None, None]

    def _approve(index: int) -> None:
        both_threads_ready.wait()
        responses[index] = client.post(f"/plans/{plan_id}/approve")

    with monkeypatch.context() as m:
        m.setattr(routes_module, "dispatch_plan", _counting_dispatch_plan)
        m.setattr(
            routes_module, "present_plan_for_approval", _slow_present_plan_for_approval
        )

        thread_a = threading.Thread(target=_approve, args=(0,))
        thread_b = threading.Thread(target=_approve, args=(1,))
        thread_a.start()
        thread_b.start()
        thread_a.join(timeout=30.0)
        thread_b.join(timeout=30.0)

    assert call_count == 1

    assert all(response.status_code == 200 for response in responses)
    bodies = [response.json() for response in responses]
    # Exactamente una de las dos respuestas ganó la transición real
    # (already_decided=False); la otra recibe el estado ya fijado.
    assert sorted(body["already_decided"] for body in bodies) == [False, True]
    # Ambas reflejan el mismo estado final del plan, ya despachado.
    assert all(body["status"] == "approved" for body in bodies)

    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_approve_after_already_rejected_returns_current_state_without_changing_it(
    tmp_path: Path, monkeypatch
) -> None:
    """Criterio de aceptación explícito: una llamada a /approve después
    de que el plan ya esté rejected no cambia el estado ya fijado —
    devuelve el estado actual con already_decided=True, no un error
    genérico ni una transición silenciosa."""
    # /approve exige sesión activa (verificado antes que la idempotencia,
    # mismo criterio ya usado por el resto de endpoints de la API) — se
    # arranca aquí aunque el plan vaya a quedar rejected sin despachar
    # nada, para que el 200 esperado no se confunda con el 404 de "no hay
    # sesión activa".
    _active_project_and_session(tmp_path, monkeypatch)
    _isolated_backlog(tmp_path, monkeypatch)
    client = TestClient(create_app())
    plan_id = client.post("/plans", json={"goal": "FB999-US01"}).json()["plan_id"]

    reject_response = client.post(f"/plans/{plan_id}/reject")
    assert reject_response.json()["status"] == "rejected"

    approve_response = client.post(f"/plans/{plan_id}/approve")

    assert approve_response.status_code == 200
    body = approve_response.json()
    assert body["already_decided"] is True
    assert body["status"] == "rejected"


def test_reject_after_already_approved_returns_current_state_without_changing_it(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    _project, session = _active_project_and_session(tmp_path, monkeypatch)
    _isolated_backlog(tmp_path, monkeypatch)
    agent, runtime_instance = _launch_cooperative_developer(
        tmp_path, session, isolated_socket, monkeypatch
    )

    client = TestClient(create_app())
    plan_id = client.post("/plans", json={"goal": "FB999-US01"}).json()["plan_id"]

    approve_response = client.post(f"/plans/{plan_id}/approve")
    assert approve_response.json()["status"] == "approved"

    reject_response = client.post(f"/plans/{plan_id}/reject")

    assert reject_response.status_code == 200
    body = reject_response.json()
    assert body["already_decided"] is True
    assert body["status"] == "approved"

    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_post_plans_first_call_reports_already_decided_false(
    tmp_path: Path, monkeypatch
) -> None:
    _isolated_backlog(tmp_path, monkeypatch)
    client = TestClient(create_app())
    plan_id = client.post("/plans", json={"goal": "FB999-US01"}).json()["plan_id"]

    response = client.post(f"/plans/{plan_id}/reject")

    assert response.json()["already_decided"] is False


def test_get_plans_lists_all_plans_registered_in_the_process(
    tmp_path: Path, monkeypatch
) -> None:
    """T-FB016-US01-14, criterio de aceptación: 'GET /plans devuelve todos
    los planes propuestos en el proceso actual (proposed, approved,
    rejected, blocked), no solo el último.'"""
    _isolated_backlog(tmp_path, monkeypatch, story_id="FB999-US01")
    client = TestClient(create_app())

    # Dos solicitudes reales para el mismo goal registran dos planes
    # DISTINTOS (cada `POST /plans` construye un `JobPlan` nuevo, sin
    # deduplicar por `goal`) — suficiente para verificar que `GET /plans`
    # lista más de uno, sin depender de un segundo backlog aislado.
    plan_a_id = client.post("/plans", json={"goal": "FB999-US01"}).json()["plan_id"]
    plan_b_id = client.post("/plans", json={"goal": "FB999-US01"}).json()["plan_id"]

    response = client.get("/plans")

    assert response.status_code == 200
    plan_ids = [plan["plan_id"] for plan in response.json()]
    assert plan_a_id in plan_ids
    assert plan_b_id in plan_ids
    assert len(plan_ids) == 2


def test_get_plans_keeps_a_decided_plan_with_its_final_status(
    tmp_path: Path, monkeypatch
) -> None:
    """Criterio de aceptación explícito: 'Un plan ya approved/rejected
    sigue apareciendo en la lista con su estado final — no se elimina del
    registro tras decidirse.'"""
    _isolated_backlog(tmp_path, monkeypatch)
    client = TestClient(create_app())
    plan_id = client.post("/plans", json={"goal": "FB999-US01"}).json()["plan_id"]

    client.post(f"/plans/{plan_id}/reject")

    response = client.get("/plans")

    assert response.status_code == 200
    plan = next(p for p in response.json() if p["plan_id"] == plan_id)
    assert plan["status"] == "rejected"


def test_get_plans_returns_an_empty_list_when_no_plan_was_ever_requested() -> None:
    client = TestClient(create_app())

    response = client.get("/plans")

    assert response.status_code == 200
    assert response.json() == []


def test_ws_plans_receives_per_step_progress_events_during_approve(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """T-FB017-US04-03, criterio de aceptación: 'la pantalla refleja qué
    paso está en curso... sin esperar a que termine toda la secuencia' —
    verificado end-to-end vía WebSocket con tmux real, plan de 2 pasos
    registrado directamente (evita depender de la heurística de desglose
    para controlar el número exacto de pasos). Antes de esta Task,
    `WS /ws/plans` solo emitía un evento antes y otro después de la
    secuencia COMPLETA — este test falla si esa regresión reaparece."""
    _project, session = _active_project_and_session(tmp_path, monkeypatch)
    agent, runtime_instance = _launch_cooperative_developer(
        tmp_path, session, isolated_socket, monkeypatch
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

    with TestClient(create_app()) as client:
        with client.websocket_connect("/ws/plans") as websocket:
            client.post(f"/plans/{plan_id}/approve")

            # Recoge eventos hasta ver el estado final (ambos pasos
            # `completed`) — `POST /plans/{id}/approve` (TestClient
            # síncrono) ya ha completado del todo para cuando llegamos
            # aquí, pero cada `plans_hub.publish` encoló su evento en el
            # loop asíncrono vía `run_coroutine_threadsafe`
            # independientemente de ese orden, así que ya están
            # disponibles para leer en la conexión WebSocket.
            events = []
            while len(events) < 20:
                event = websocket.receive_json()
                events.append(event)
                if event["status"] == "approved" and all(
                    step["status"] == "completed" for step in event["steps"]
                ):
                    break

    step_status_sequences = [
        [step["status"] for step in event["steps"]] for event in events
    ]

    # Al menos un evento INTERMEDIO real, con el paso 1 ya completed y el
    # paso 2 todavía sin terminar — la propia evidencia de que no hubo que
    # esperar al final de la secuencia completa para ver progreso.
    assert ["completed", "running"] in step_status_sequences or [
        "completed",
        "pending",
    ] in step_status_sequences
    # Y el evento final refleja ambos pasos completed.
    assert step_status_sequences[-1] == ["completed", "completed"]

    stop_runtime(runtime_instance, socket_name=isolated_socket)
