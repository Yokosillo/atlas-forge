import time
import uuid
from pathlib import Path

import libtmux
import pytest
from fastapi.testclient import TestClient

import brain.api.routes as routes_module
import brain.agents.launch as launch_module
from brain.api import create_app
from brain.core import resolve_startup_session
from brain.core.session_lifecycle import list_agents
from brain.core.session_registry import _reset_registry_for_tests
from brain.dispatcher.job_history_registry import (
    _reset_registry_for_tests as _reset_job_history,
)
from brain.runtime import get_runtime_instance_for_agent, stop_runtime
from brain.workspace import discover_projects, select_active_project

_COOPERATIVE_AGENT_SCRIPT = str(
    Path(__file__).parent / "fixtures" / "cooperative_agent_sim.sh"
)


@pytest.fixture(autouse=True)
def _clean_registry():
    _reset_registry_for_tests()
    _reset_job_history()
    yield
    _reset_registry_for_tests()
    _reset_job_history()


@pytest.fixture(autouse=True)
def _no_real_runtime(monkeypatch):
    """Mismo patrón de aislamiento ya usado en test_launch_agent.py: nunca
    invocar los binarios reales de Claude Code/OpenCode en tests."""
    import brain.runtime.claude_code as claude_code_module
    import brain.runtime.opencode as opencode_module

    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_COMMAND", "sleep")
    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_ARGS", ["5"])
    monkeypatch.setattr(opencode_module, "DEFAULT_OPENCODE_COMMAND", "sleep")
    monkeypatch.setattr(opencode_module, "DEFAULT_OPENCODE_AUTONOMY_FLAG", "5")
    monkeypatch.setattr(opencode_module, "DEFAULT_OPENCODE_ARGS", ["5"])


@pytest.fixture
def isolated_socket(monkeypatch):
    """Aísla el endpoint POST /agents en su propio servidor tmux (el
    socket real no es parámetro del body HTTP — ver `routes._SOCKET_NAME`),
    con limpieza garantizada incluso si el test falla a medio camino."""
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
    """Arranca un proyecto activo y una sesión de desarrollo activa reales
    y aislados (nunca el estado real del sistema en `~/.local/share/brain`)
    y hace que `routes.get_active_project` (el que de verdad consulta el
    endpoint) devuelva ese proyecto — `load_active_project` sin `state_dir`
    explícito leería del filesystem real del usuario, ajeno a este test."""
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


def test_get_project_returns_404_when_no_project_is_active(monkeypatch) -> None:
    monkeypatch.setattr(routes_module, "get_active_project", lambda **_kwargs: None)
    client = TestClient(create_app())

    response = client.get("/project")

    assert response.status_code == 404


def test_get_project_returns_the_real_active_project(
    tmp_path: Path, monkeypatch
) -> None:
    project, _session = _active_project_and_session(tmp_path, monkeypatch)
    client = TestClient(create_app())

    response = client.get("/project")

    assert response.status_code == 200
    assert response.json() == {
        "id": project.id,
        "name": project.name,
        "path": project.path,
        "repository": project.repository,
        "workspace_id": project.workspace_id,
    }


def test_get_session_returns_404_when_no_session_is_active() -> None:
    client = TestClient(create_app())

    response = client.get("/session")

    assert response.status_code == 404


def test_get_session_returns_the_real_active_session(
    tmp_path: Path, monkeypatch
) -> None:
    _project, session = _active_project_and_session(tmp_path, monkeypatch)
    client = TestClient(create_app())

    response = client.get("/session")

    assert response.status_code == 200
    assert response.json()["id"] == session.id
    assert response.json()["status"] == "active"


def test_get_agents_returns_404_when_no_session_is_active() -> None:
    client = TestClient(create_app())

    response = client.get("/agents")

    assert response.status_code == 404


def test_get_agents_reflects_an_agent_launched_directly_via_domain(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """Criterio de aceptación: arrancar sesión, lanzar agente vía llamada
    directa a dominio (sin pasar por HTTP), consultar por HTTP y ver el
    mismo agente."""
    from brain.agents.launch import launch_agent

    _project, session = _active_project_and_session(tmp_path, monkeypatch)
    agent, runtime_instance = launch_agent(
        "developer", "claude-code", None, session, str(tmp_path), socket_name=isolated_socket
    )

    client = TestClient(create_app())
    response = client.get("/agents")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": agent.id,
            "name": agent.name,
            "role": agent.role,
            "status": agent.status,
            "runtime_id": agent.runtime_id,
            "model": None,
            "session_name": runtime_instance.session_name,
            "last_command_at": None,
            "limited_until": None,
        }
    ]

    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_post_agents_launches_a_real_agent_and_get_agents_reflects_it(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """Criterio de aceptación: POST /agents lanza un agente real (mismo
    mecanismo que la TUI) y aparece reflejado inmediatamente en GET
    /agents."""
    _project, _session = _active_project_and_session(tmp_path, monkeypatch)
    client = TestClient(create_app())

    post_response = client.post(
        "/agents", json={"role": "developer", "runtime_type": "claude-code"}
    )
    assert post_response.status_code == 201
    launched = post_response.json()
    assert launched["role"] == "developer"

    get_response = client.get("/agents")
    assert get_response.status_code == 200
    assert any(agent["id"] == launched["id"] for agent in get_response.json())

    runtime_instance = get_runtime_instance_for_agent(launched["id"])
    assert runtime_instance is not None
    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_post_agents_with_developer_number_creates_that_numbered_instance(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """T-FB005-US01-08 (2026-08-18): POST /agents con `developer_number`
    crea la instancia con ESE nombre (slot fijo e independiente de
    Developer), aunque no sea el siguiente por orden de lanzamiento."""
    _project, _session = _active_project_and_session(tmp_path, monkeypatch)
    client = TestClient(create_app())

    post_response = client.post(
        "/agents",
        json={
            "role": "developer",
            "runtime_type": "claude-code",
            "developer_number": 3,
        },
    )
    assert post_response.status_code == 201
    launched = post_response.json()
    assert launched["role"] == "developer"
    assert launched["name"] == "Developer-3"

    runtime_instance = get_runtime_instance_for_agent(launched["id"])
    assert runtime_instance is not None
    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_post_agents_rejects_duplicate_developer_number(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """T-FB005-US01-08: relanzar el slot de un Developer aún vivo se
    traduce a 400 con el motivo del dominio — nunca un segundo
    "Developer-3" (garantía de nombres únicos)."""
    _project, _session = _active_project_and_session(tmp_path, monkeypatch)
    client = TestClient(create_app())

    first = client.post(
        "/agents",
        json={
            "role": "developer",
            "runtime_type": "claude-code",
            "developer_number": 3,
        },
    )
    assert first.status_code == 201

    duplicate = client.post(
        "/agents",
        json={
            "role": "developer",
            "runtime_type": "claude-code",
            "developer_number": 3,
        },
    )
    assert duplicate.status_code == 400
    assert "Ya existe un Developer 'Developer-3'" in duplicate.json()["detail"]

    runtime_instance = get_runtime_instance_for_agent(first.json()["id"])
    assert runtime_instance is not None
    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_post_agents_rejects_invalid_developer_number(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """T-FB005-US01-08: `developer_number` < 1 se rechaza en el contrato
    (pydantic, 422) antes de tocar el dominio."""
    _project, _session = _active_project_and_session(tmp_path, monkeypatch)
    client = TestClient(create_app())

    response = client.post(
        "/agents",
        json={
            "role": "developer",
            "runtime_type": "claude-code",
            "developer_number": 0,
        },
    )
    assert response.status_code == 422


def test_post_agents_launches_a_real_ux_agent_and_get_agents_reflects_it(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """Criterio de aceptación (T-FB024-US13-01): `POST /agents` con
    `role: "ux"` deja de responder "rol no reconocido" y lanza una
    instancia real, reflejada en `GET /agents` con los mismos campos que
    cualquier otro agente."""
    _project, _session = _active_project_and_session(tmp_path, monkeypatch)
    client = TestClient(create_app())

    post_response = client.post(
        "/agents", json={"role": "ux", "runtime_type": "claude-code"}
    )
    assert post_response.status_code == 201
    launched = post_response.json()
    assert launched["role"] == "ux"

    get_response = client.get("/agents")
    assert get_response.status_code == 200
    matching = [a for a in get_response.json() if a["id"] == launched["id"]]
    assert len(matching) == 1
    for field in ("id", "status", "runtime_id", "model", "session_name"):
        assert field in matching[0]

    runtime_instance = get_runtime_instance_for_agent(launched["id"])
    assert runtime_instance is not None
    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_post_agents_launches_a_real_auditor_oss_agent_and_get_agents_reflects_it(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """Criterio de aceptación (T-FB024-US13-02): `POST /agents` con
    `role: "auditor_oss"` deja de responder "rol no reconocido" y lanza
    una instancia real, reflejada en `GET /agents` con los mismos campos
    que cualquier otro agente."""
    _project, _session = _active_project_and_session(tmp_path, monkeypatch)
    client = TestClient(create_app())

    post_response = client.post(
        "/agents", json={"role": "auditor_oss", "runtime_type": "claude-code"}
    )
    assert post_response.status_code == 201
    launched = post_response.json()
    assert launched["role"] == "auditor_oss"

    get_response = client.get("/agents")
    assert get_response.status_code == 200
    matching = [a for a in get_response.json() if a["id"] == launched["id"]]
    assert len(matching) == 1
    for field in ("id", "status", "runtime_id", "model", "session_name"):
        assert field in matching[0]

    runtime_instance = get_runtime_instance_for_agent(launched["id"])
    assert runtime_instance is not None
    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_post_agents_with_initial_job_returns_agent_and_job_in_same_response(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """Criterio de aceptación (T-FB016-US01-16): `POST /agents` con
    `initial_job_description` informado devuelve agente + Job en la misma
    respuesta 201, verificado con tmux real (doble cooperativo) — el Job
    queda `completed` con su resultado, y el agente aparece registrado e
    `idle` en `GET /agents` después."""
    import brain.runtime.claude_code as claude_code_module

    _project, session = _active_project_and_session(tmp_path, monkeypatch)
    monkeypatch.setattr(
        claude_code_module, "DEFAULT_CLAUDE_CODE_COMMAND", "bash"
    )
    monkeypatch.setattr(
        claude_code_module, "DEFAULT_CLAUDE_CODE_ARGS", [_COOPERATIVE_AGENT_SCRIPT]
    )

    client = TestClient(create_app())
    response = client.post(
        "/agents",
        json={
            "role": "developer",
            "runtime_type": "claude-code",
            "initial_job_description": "implement the feature",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert set(body.keys()) == {"agent", "job"}
    assert body["agent"]["role"] == "developer"
    assert body["agent"]["status"] == "idle"
    assert body["job"]["agent_id"] == body["agent"]["id"]
    assert body["job"]["status"] == "completed"
    assert "cooperative result" in body["job"]["result"]

    # El Job queda en el histórico consultable de la sesión.
    jobs_response = client.get("/jobs")
    assert jobs_response.status_code == 200
    assert any(job["id"] == body["job"]["id"] for job in jobs_response.json())

    # El agente queda registrado e idle.
    agents_response = client.get("/agents")
    assert agents_response.status_code == 200
    launched = next(a for a in agents_response.json() if a["id"] == body["agent"]["id"])
    assert launched["status"] == "idle"

    runtime_instance = get_runtime_instance_for_agent(body["agent"]["id"])
    assert runtime_instance is not None
    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_post_agents_without_initial_job_is_identical_to_previous_response(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """Criterio de aceptación (T-FB016-US01-16): `POST /agents` sin
    `initial_job_description` se comporta exactamente igual que hoy —
    respuesta 201 plana con los datos del agente (sin envolver en
    `agent`/`job`) y sin ningún Job creado."""
    _project, _session = _active_project_and_session(tmp_path, monkeypatch)
    client = TestClient(create_app())

    response = client.post(
        "/agents", json={"role": "developer", "runtime_type": "claude-code"}
    )

    assert response.status_code == 201
    body = response.json()
    assert set(body.keys()) == {
        "id",
        "name",
        "role",
        "status",
        "runtime_id",
        "model",
        "session_name",
        "last_command_at",
        "limited_until",
    }
    assert body["status"] == "idle"

    jobs_response = client.get("/jobs")
    assert jobs_response.status_code == 200
    assert jobs_response.json() == []

    runtime_instance = get_runtime_instance_for_agent(body["id"])
    assert runtime_instance is not None
    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_post_agents_initial_job_dispatch_failure_keeps_agent_and_reports_failed_job(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """Criterio de aceptación de T-FB008-US06-01 expuesto por el endpoint:
    si el despacho del Job inicial falla (runtime que nunca reporta →
    timeout), el agente permanece registrado e `idle` y el Job se devuelve
    `failed` con el motivo en `result` — el fallo nunca revierte el
    registro del agente."""
    import brain.runtime.claude_code as claude_code_module
    from brain.dispatcher import dispatch_job as _real_dispatch_job

    _project, session = _active_project_and_session(tmp_path, monkeypatch)
    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_COMMAND", "bash")
    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_ARGS", [])

    # Acorta el timeout del despacho del Job inicial para no esperar los
    # 30s por defecto en un test (el endpoint no expone ese parámetro; se
    # ajusta el dispatch_job que usa `launch_agent_with_initial_job`).
    monkeypatch.setattr(
        launch_module,
        "dispatch_job",
        lambda job, agent, runtime_instance, timeout_seconds=30.0,
        poll_interval_seconds=0.2, socket_name="default",
        _timeout=0.4, _poll=0.1: _real_dispatch_job(
            job, agent, runtime_instance,
            timeout_seconds=_timeout, poll_interval_seconds=_poll,
            socket_name=socket_name,
        ),
    )

    client = TestClient(create_app())
    response = client.post(
        "/agents",
        json={
            "role": "developer",
            "runtime_type": "claude-code",
            "initial_job_description": "this job will time out",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["agent"]["status"] == "idle"
    assert body["job"]["status"] == "failed"
    assert "Timeout" in body["job"]["result"]

    agents_response = client.get("/agents")
    launched = next(a for a in agents_response.json() if a["id"] == body["agent"]["id"])
    assert launched["status"] == "idle"

    runtime_instance = get_runtime_instance_for_agent(body["agent"]["id"])
    assert runtime_instance is not None
    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_post_agents_with_initial_job_still_passes_state_dir_to_get_active_project(
    tmp_path: Path, monkeypatch
) -> None:
    """Criterio de aceptación de T-FB016-US01-16: el flujo con Job inicial
    también llama a `get_active_project(state_dir=_STATE_DIR)` (bug
    recurrente ya corregido tres veces en este fichero — no regresar aquí)."""
    isolated_state_dir = tmp_path / "state"
    monkeypatch.setattr(routes_module, "_STATE_DIR", isolated_state_dir)
    _project, _session = _active_project_and_session(tmp_path, monkeypatch)

    captured = {}

    def recording_get_active_project(**kwargs):
        captured["kwargs"] = kwargs
        return _project

    monkeypatch.setattr(
        routes_module, "get_active_project", recording_get_active_project
    )

    client = TestClient(create_app())
    response = client.post(
        "/agents",
        json={
            "role": "developer",
            "runtime_type": "claude-code",
            "initial_job_description": "some task",
        },
    )

    assert response.status_code == 201
    assert captured["kwargs"].get("state_dir") == isolated_state_dir


def test_post_agents_with_unrecognized_role_returns_400_with_domain_message(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """Criterio de aceptación: combinación inválida devuelve 4xx con el
    mismo mensaje de motivo que ya lanza AgentLaunchError, no un texto
    reinventado."""
    from brain.agents.launch import AgentLaunchError, launch_agent

    _project, session = _active_project_and_session(tmp_path, monkeypatch)

    try:
        launch_agent(
            "unknown-role", "claude-code", None, session, str(tmp_path),
            socket_name=isolated_socket,
        )
        expected_message = None
    except AgentLaunchError as error:
        expected_message = str(error)

    assert expected_message is not None

    client = TestClient(create_app())
    response = client.post(
        "/agents", json={"role": "unknown-role", "runtime_type": "claude-code"}
    )

    assert response.status_code == 400
    assert response.json()["detail"] == expected_message


def test_post_agents_over_developer_limit_returns_400_not_500(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """T-FB024-US12-01: superar el límite de Developer simultáneos lanza
    `RuntimeError` desde `register_developer` (`agents/developer.py:124`),
    que antes se propagaba sin capturar y FastAPI lo convertía en un 500
    genérico. Debe traducirse a 400 con el mismo mensaje explícito del
    dominio, igual que el resto de rechazos de esta ruta."""
    from brain.agents.developer import MAX_SIMULTANEOUS_DEVELOPERS

    _project, session = _active_project_and_session(tmp_path, monkeypatch)
    client = TestClient(create_app())

    launched = []
    for _ in range(MAX_SIMULTANEOUS_DEVELOPERS):
        response = client.post(
            "/agents",
            json={"role": "developer", "runtime_type": "claude-code"},
        )
        assert response.status_code == 201
        launched.append(response.json())

    response = client.post(
        "/agents",
        json={"role": "developer", "runtime_type": "claude-code"},
    )

    assert response.status_code == 400
    assert "No se puede lanzar otro Developer" in response.json()["detail"]

    for agent in launched:
        instance = get_runtime_instance_for_agent(agent["id"])
        if instance is not None:
            stop_runtime(instance, socket_name=isolated_socket)


def test_post_agents_with_claude_code_model_infers_runtime_and_launches(
    tmp_path: Path, monkeypatch, isolated_socket,
) -> None:
    """T-FB024-US11-13 (2026-08-17): Claude Code SÍ admite indicar modelo
    al lanzar — corrección de la premisa original (T-FB002-US01-01) que
    asumía lo contrario sin verificarlo contra `claude --help`. Sin
    `runtime_type` explícito, el runtime se infiere del modelo del
    catálogo (`sonnet` → `claude_code` → `claude-code`)."""
    import brain.runtime.claude_code as claude_code_module

    _project, _session = _active_project_and_session(tmp_path, monkeypatch)
    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_COMMAND", "bash")
    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_ARGS", [])
    client = TestClient(create_app())

    response = client.post(
        "/agents",
        json={"role": "developer", "model": "sonnet"},
    )

    assert response.status_code in (200, 201)
    body = response.json()
    assert body["runtime_id"] == "claude-code"


# ---------------------------------------------------------------------
# T-FB005-US07-02: lanzamiento con runtime explícito y separado del modelo
# ---------------------------------------------------------------------


def test_post_agents_without_runtime_returns_400_with_clear_message_and_no_partial_effects(
    tmp_path: Path, monkeypatch
) -> None:
    """Criterio 1/2 de T-FB005-US07-02: el lanzamiento requiere una elección
    explícita de runtime. Un request sin `runtime_type` ni modelo resoluble
    se rechaza con 400 y un motivo claro ANTES de lanzar nada — ningún
    agente queda registrado (sin efectos parciales)."""
    _project, session = _active_project_and_session(tmp_path, monkeypatch)
    client = TestClient(create_app())

    response = client.post("/agents", json={"role": "developer"})

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "runtime" in detail
    assert "runtime_type" in detail
    # Sin efectos parciales: no se lanzó ni registró ningún agente.
    assert list_agents(session) == []


def test_post_agents_rejects_model_belonging_to_another_runtime(
    tmp_path: Path, monkeypatch
) -> None:
    """Criterio 3 de T-FB005-US07-02: un modelo se acepta solo cuando la
    capacidad del runtime elegido lo permite. Enviar un modelo del catálogo
    que pertenece a otro runtime (aquí `sonnet`, del catálogo, contra
    un runtime `opencode`) se rechaza con 400 antes de lanzar nada."""
    _project, session = _active_project_and_session(tmp_path, monkeypatch)
    client = TestClient(create_app())

    response = client.post(
        "/agents",
        json={"role": "developer", "runtime_type": "opencode", "model_id": "sonnet"},
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "pertenece al runtime" in detail
    assert "claude-code" in detail
    assert "opencode" in detail
    assert list_agents(session) == []


def test_post_agents_honors_explicit_runtime_over_model_inference(
    tmp_path: Path, monkeypatch
) -> None:
    """Regresión de la vía que podía ignorar un runtime seleccionado
    (raíz de T-FB024-US12-03, cerrada en US-FB005-07): si el request trae
    `runtime_type` explícito (`claude-code`) junto a un modelo del catálogo
    de OTRO runtime (`opencode-go/deepseek-v4-flash`), el runtime explícito
    se HONRA — no se reescribe en silencio al runtime del modelo. Se
    rechaza con 400 porque el modelo pertenece a OpenCode, no porque
    Claude Code rechace modelo en sí (T-FB024-US11-13, 2026-08-17: Claude
    Code SÍ admite indicar modelo al lanzar desde esta corrección)."""
    _project, session = _active_project_and_session(tmp_path, monkeypatch)
    client = TestClient(create_app())

    response = client.post(
        "/agents",
        json={
            "role": "developer",
            "runtime_type": "claude-code",
            "model": "opencode-go/deepseek-v4-flash",
        },
    )

    assert response.status_code == 400
    assert "opencode" in response.json()["detail"]
    assert "claude-code" in response.json()["detail"]
    assert list_agents(session) == []


def test_post_agents_launches_opencode_with_explicit_runtime_and_keeps_runtime_id(
    tmp_path: Path, monkeypatch, isolated_socket,
) -> None:
    """Criterio 3/4 de T-FB005-US07-02: con runtime explícito (`opencode`)
    y un modelo del MISMO runtime (catalogado, el runtime lo admite) el
    lanzamiento procede y la instancia conserva `runtime_id === "opencode"`
    (runtime fijo, inmutable durante la vida de la instancia)."""
    _project, _session = _active_project_and_session(tmp_path, monkeypatch)
    client = TestClient(create_app())

    response = client.post(
        "/agents",
        json={
            "role": "developer",
            "runtime_type": "opencode",
            "model_id": "opencode-go/deepseek-v4-flash",
        },
    )

    assert response.status_code == 201
    launched = response.json()
    assert launched["role"] == "developer"
    assert launched["runtime_id"] == "opencode"

    runtime_instance = get_runtime_instance_for_agent(launched["id"])
    assert runtime_instance is not None
    assert runtime_instance.runtime.type == "opencode"
    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_post_agents_passes_state_dir_to_get_active_project(
    tmp_path: Path, monkeypatch
) -> None:
    """Criterio de aceptación de T-FB016-US01-13: `POST /agents` aísla
    `state_dir` llamando a `get_active_project(state_dir=_STATE_DIR)` (nunca
    la llamada sin parámetro que leería del filesystem real del usuario)."""
    isolated_state_dir = tmp_path / "state"
    monkeypatch.setattr(routes_module, "_STATE_DIR", isolated_state_dir)
    _project, _session = _active_project_and_session(tmp_path, monkeypatch)

    captured = {}

    def recording_get_active_project(**kwargs):
        captured["kwargs"] = kwargs
        return _project

    monkeypatch.setattr(
        routes_module, "get_active_project", recording_get_active_project
    )

    client = TestClient(create_app())
    response = client.post(
        "/agents", json={"role": "developer", "runtime_type": "claude-code"}
    )

    assert response.status_code == 201
    assert captured["kwargs"].get("state_dir") == isolated_state_dir


def test_post_agents_returns_404_when_no_session_is_active() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/agents", json={"role": "developer", "runtime_type": "claude-code"}
    )

    assert response.status_code == 404


def test_get_agents_reports_unavailable_when_runtime_died_externally(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """Criterio de aceptación explícito de T-FB016-US01-07: un agente
    cuyo proceso tmux se mata externamente (`tmux kill-session` directo,
    fuera de `POST /agents/{id}/stop`) pasa a reportarse como
    `unavailable` la próxima vez que se consulta `GET /agents` — nunca
    sigue como `idle`/`working`."""
    from brain.tmux.manager import kill_session

    _project, _session = _active_project_and_session(tmp_path, monkeypatch)
    client = TestClient(create_app())

    launched = client.post(
        "/agents", json={"role": "developer", "runtime_type": "claude-code"}
    ).json()
    assert launched["status"] == "idle"

    runtime_instance = get_runtime_instance_for_agent(launched["id"])
    kill_session(runtime_instance.session_name, socket_name=isolated_socket)

    response = client.get("/agents")

    assert response.status_code == 200
    refreshed = next(a for a in response.json() if a["id"] == launched["id"])
    assert refreshed["status"] == "unavailable"


def test_get_agents_reports_limited_status_with_recovery_time(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """Criterio de aceptación de T-FB024-US21-01: un agente con el
    patrón de límite de sesión aparece en `GET /agents` con estado
    distinguible (`limited`) y `limited_until` (hora de recuperación)
    visible — distinto de `idle`/`working`/`stopped`/`unavailable`."""
    from brain.agents.lifecycle import mark_limited

    _project, session = _active_project_and_session(tmp_path, monkeypatch)
    client = TestClient(create_app())

    launched = client.post(
        "/agents", json={"role": "developer", "runtime_type": "claude-code"}
    ).json()
    assert launched["status"] == "idle"
    assert launched["limited_until"] is None

    agent = next(a for a in session.agents if a.id == launched["id"])
    mark_limited(agent, "2026-08-17T01:30:00+00:00")

    response = client.get("/agents")

    assert response.status_code == 200
    refreshed = next(a for a in response.json() if a["id"] == launched["id"])
    assert refreshed["status"] == "limited"
    assert refreshed["limited_until"] == "2026-08-17T01:30:00+00:00"


def test_get_agents_does_not_rewrite_a_stopped_agent_to_unavailable(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """Criterio de aceptación explícito: un agente detenido a propósito
    (`stopped`, T-FB016-US01-03) no se ve afectado por la verificación de
    liveness — sigue `stopped`, nunca se reescribe a `unavailable`.

    Rol no-Developer (Arquitecto) a propósito: con Developer
    (T-FB024-US12-02), detener elimina el agente por completo de
    `session.agents`, y este test dejaría de poder comprobar que sigue
    `stopped` en `GET /agents` — sencillamente ya no aparecería."""
    _project, _session = _active_project_and_session(tmp_path, monkeypatch)
    client = TestClient(create_app())

    launched = client.post(
        "/agents", json={"role": "arquitecto", "runtime_type": "claude-code"}
    ).json()

    stop_response = client.post(f"/agents/{launched['id']}/stop")
    assert stop_response.status_code == 200
    assert stop_response.json()["status"] == "stopped"

    response = client.get("/agents")

    assert response.status_code == 200
    refreshed = next(a for a in response.json() if a["id"] == launched["id"])
    assert refreshed["status"] == "stopped"


def test_stopping_a_developer_removes_it_from_get_agents_and_frees_the_limit(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """T-FB024-US12-02, criterios 1 y 2: "Detener" sobre un Developer
    elimina el `Agent` por completo (`GET /agents` deja de listarlo), y el
    límite de Developer simultáneos se libera de inmediato — lanzar uno
    nuevo justo después nunca falla por límite alcanzado con instancias
    fantasma."""
    from brain.agents.developer import MAX_SIMULTANEOUS_DEVELOPERS

    _project, _session = _active_project_and_session(tmp_path, monkeypatch)
    client = TestClient(create_app())

    launched = []
    for _ in range(MAX_SIMULTANEOUS_DEVELOPERS):
        response = client.post(
            "/agents", json={"role": "developer", "runtime_type": "claude-code"}
        )
        assert response.status_code == 201
        launched.append(response.json())

    # Límite alcanzado: lanzar uno más falla.
    over_limit = client.post(
        "/agents", json={"role": "developer", "runtime_type": "claude-code"}
    )
    assert over_limit.status_code == 400

    # Detener uno cualquiera de los ya lanzados.
    stop_response = client.post(f"/agents/{launched[0]['id']}/stop")
    assert stop_response.status_code == 200

    get_response = client.get("/agents")
    assert get_response.status_code == 200
    remaining_ids = {a["id"] for a in get_response.json()}
    assert launched[0]["id"] not in remaining_ids

    # El límite ya está libre: lanzar uno nuevo funciona sin error.
    relaunch = client.post(
        "/agents", json={"role": "developer", "runtime_type": "claude-code"}
    )
    assert relaunch.status_code == 201

    for agent in launched[1:] + [relaunch.json()]:
        instance = get_runtime_instance_for_agent(agent["id"])
        if instance is not None:
            stop_runtime(instance, socket_name=isolated_socket)


def test_get_agents_options_returns_the_full_unfiltered_catalog(
    tmp_path, monkeypatch,
) -> None:
    """El filtro que ocultaba Critic + OpenCode (T-FB016-US01-19) se
    eliminó junto con el rol `critic` (FB-022): `GET /agents/options`
    ahora devuelve exactamente el catálogo del dominio
    (`list_available_agent_options`), sin ninguna combinación excluida."""
    from brain.agents.agent_options import list_available_agent_options

    client = TestClient(create_app())
    response = client.get("/agents/options")

    assert response.status_code == 200
    body = response.json()
    full = [
        {
            "agent_role": o.agent_role,
            "model_id": o.model_id,
            "model_name": o.model_name,
            "runtime_type": o.runtime_type,
            "runtime_name": o.runtime_name,
            "supports_model": o.supports_model,
        }
        for o in list_available_agent_options()
    ]
    assert body == full
    assert len(body) > 0


def test_get_agent_pane_returns_the_real_tmux_content_of_a_launched_agent(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """Criterio de aceptación (T-FB016-US01-12): `GET /agents/{id}/pane`
    devuelve el contenido real del pane de tmux de un agente lanzado de
    verdad (con tmux real, no mockeado — mismo aislamiento de comandos
    reales que el resto de la suite)."""
    from brain.agents.launch import launch_agent

    _project, session = _active_project_and_session(tmp_path, monkeypatch)
    agent, runtime_instance = launch_agent(
        "developer", "opencode", None, session, str(tmp_path),
        socket_name=isolated_socket,
    )

    client = TestClient(create_app())

    content = ""
    for _ in range(20):
        response = client.get(f"/agents/{agent.id}/pane")
        assert response.status_code == 200
        body = response.json()
        assert body["agent_id"] == agent.id
        assert isinstance(body["content"], str)
        if body["content"].strip():
            content = body["content"]
            break
        time.sleep(0.1)

    assert content, "El pane de un agente lanzado debe tener contenido visible"

    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_get_agent_pane_returns_404_when_no_session_is_active() -> None:
    client = TestClient(create_app())

    response = client.get("/agents/whatever/pane")

    assert response.status_code == 404
    assert "sesión" in response.json()["detail"]


def test_get_agent_pane_returns_404_when_agent_does_not_exist(
    tmp_path: Path, monkeypatch
) -> None:
    _project, _session = _active_project_and_session(tmp_path, monkeypatch)
    client = TestClient(create_app())

    response = client.get("/agents/does-not-exist/pane")

    assert response.status_code == 404
    assert "no existe" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# GET/PUT /agents/{agent_id}/model y GET /agents/{agent_id}/available-models
# (T-FB021-US07-01)
# ---------------------------------------------------------------------------


def test_get_agent_model_returns_404_when_no_session(monkeypatch) -> None:
    monkeypatch.setattr(routes_module, "get_current_session", lambda **_kwargs: None)
    client = TestClient(create_app())

    response = client.get("/agents/any-id/model")

    assert response.status_code == 404


def test_get_agent_model_returns_404_when_agent_does_not_exist(
    tmp_path: Path, monkeypatch
) -> None:
    _project, _session = _active_project_and_session(tmp_path, monkeypatch)
    client = TestClient(create_app())

    response = client.get("/agents/does-not-exist/model")

    assert response.status_code == 404
    assert "no existe" in response.json()["detail"].lower()


def test_get_agent_model_returns_null_for_non_opencode_agent(
    tmp_path: Path, monkeypatch, isolated_socket,
) -> None:
    """Agente Claude Code lanzado → GET /agents/{id}/model devuelve model: null
    (el agente existe pero su runtime no es OpenCode, asi que no hay modelo que
    leer)."""
    _project, _session = _active_project_and_session(tmp_path, monkeypatch)
    client = TestClient(create_app())

    resp = client.post("/agents", json={"role": "developer", "runtime_type": "claude-code"})
    assert resp.status_code in (200, 201)
    agent_id = resp.json()["id"]

    resp = client.get(f"/agents/{agent_id}/model")
    assert resp.status_code == 200
    body = resp.json()
    assert body["agent_id"] == agent_id
    assert body["model"] is None


def test_get_agent_model_returns_model_for_opencode_with_sleep_binary(
    tmp_path: Path, monkeypatch, isolated_socket,
) -> None:
    """Agente OpenCode lanzado (con sleep) → el endpoint no falla, devuelve
    model: null (porque sleep no tiene barra de estado 'Build · ')."""
    _project, _session = _active_project_and_session(tmp_path, monkeypatch)
    client = TestClient(create_app())

    resp = client.post("/agents", json={"role": "developer", "runtime_type": "opencode"})
    assert resp.status_code in (200, 201)
    agent_id = resp.json()["id"]

    resp = client.get(f"/agents/{agent_id}/model")
    assert resp.status_code == 200
    body = resp.json()
    assert body["agent_id"] == agent_id
    assert body["model"] is None  # sleep no tiene barra de estado


def test_put_agent_model_on_claude_code_sends_model_command_to_pane(
    tmp_path: Path, monkeypatch, isolated_socket,
) -> None:
    """T-FB024-US11-13 (decisión de producto 2026-08-17): Claude Code SÍ
    admite cambio de modelo en caliente — PUT /agents/{id}/model envía
    '/model <id>' + Enter al pane real vía `set_active_model_claude_code`.
    Verificado contra una sesión tmux REAL (bash en vez del binario
    `claude`, mismo patrón que el resto de tests de este fichero) — el
    texto debe aparecer en el pane capturado, no solo asumirse por un
    200 OK."""
    import brain.runtime.claude_code as claude_code_module

    _project, _session = _active_project_and_session(tmp_path, monkeypatch)
    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_COMMAND", "bash")
    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_ARGS", [])
    client = TestClient(create_app())

    resp = client.post("/agents", json={"role": "developer", "runtime_type": "claude-code"})
    assert resp.status_code in (200, 201)
    agent_id = resp.json()["id"]

    resp = client.put(
        f"/agents/{agent_id}/model",
        json={"model": "haiku"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"agent_id": agent_id, "model": "haiku", "changed": True}

    runtime_instance = get_runtime_instance_for_agent(agent_id)
    server = libtmux.Server(socket_name=isolated_socket)
    session = server.sessions.get(session_name=runtime_instance.session_name)
    pane_content = "\n".join(session.active_pane.capture_pane())
    assert "/model haiku" in pane_content


def test_put_agent_model_returns_400_when_model_field_is_missing(
    tmp_path: Path, monkeypatch, isolated_socket,
) -> None:
    _project, _session = _active_project_and_session(tmp_path, monkeypatch)
    client = TestClient(create_app())

    resp = client.post("/agents", json={"role": "developer", "runtime_type": "opencode"})
    assert resp.status_code in (200, 201)
    agent_id = resp.json()["id"]

    resp = client.put(f"/agents/{agent_id}/model", json={})
    assert resp.status_code == 400
    assert "model" in resp.json()["detail"].lower()


def test_put_agent_model_returns_changed_false_on_sleep_opencode(
    tmp_path: Path, monkeypatch, isolated_socket,
) -> None:
    """Agente OpenCode lanzado con sleep → intento de cambio de modelo via
    keystrokes en un pane sin OpenCode real devuelve 200 con changed=false
    (no lanza excepcion)."""
    _project, _session = _active_project_and_session(tmp_path, monkeypatch)
    client = TestClient(create_app())

    resp = client.post("/agents", json={"role": "developer", "runtime_type": "opencode"})
    assert resp.status_code in (200, 201)
    agent_id = resp.json()["id"]

    resp = client.put(
        f"/agents/{agent_id}/model",
        json={"model": "deepseek/deepseek-chat"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["agent_id"] == agent_id
    assert body["model"] == "deepseek/deepseek-chat"
    assert body["changed"] is False  # sleep binario no responde a C-p / C-x


def test_get_agent_available_models_returns_list_for_opencode(
    tmp_path: Path, monkeypatch, isolated_socket,
) -> None:
    _project, _session = _active_project_and_session(tmp_path, monkeypatch)
    client = TestClient(create_app())

    resp = client.post("/agents", json={"role": "developer", "runtime_type": "opencode"})
    assert resp.status_code in (200, 201)
    agent_id = resp.json()["id"]

    resp = client.get(f"/agents/{agent_id}/available-models")
    assert resp.status_code == 200
    body = resp.json()
    assert body["agent_id"] == agent_id
    assert body["supports_model"] is True
    assert isinstance(body["models"], list)
    assert len(body["models"]) > 0
    assert "opencode-go/deepseek-v4-flash" in [m["id"] for m in body["models"]]


def test_get_agent_available_models_returns_claude_code_catalog_for_claude_code(
    tmp_path: Path, monkeypatch, isolated_socket,
) -> None:
    """T-FB024-US11-13 (decisión de producto 2026-08-17): un agente Claude
    Code VIVO sí admite cambio de modelo en caliente (vía '/model <id>'
    por tmux, POST /agents/{id}/send-keys) — el catálogo devuelto se
    filtra a los modelos del runtime claude_code (sonnet/opus/haiku), no
    a los de opencode."""
    _project, _session = _active_project_and_session(tmp_path, monkeypatch)
    client = TestClient(create_app())

    resp = client.post("/agents", json={"role": "developer", "runtime_type": "claude-code"})
    assert resp.status_code in (200, 201)
    agent_id = resp.json()["id"]

    resp = client.get(f"/agents/{agent_id}/available-models")
    assert resp.status_code == 200
    body = resp.json()
    assert body["agent_id"] == agent_id
    assert body["supports_model"] is True
    assert body["models"]
    assert all(m["runtime"] == "claude_code" for m in body["models"])


def test_get_agent_status_model_returns_404_when_no_session(monkeypatch) -> None:
    monkeypatch.setattr(routes_module, "get_current_session", lambda **_kwargs: None)
    client = TestClient(create_app())

    response = client.get("/agents/any-id/status-model")

    assert response.status_code == 404


def test_get_agent_status_model_returns_404_when_agent_does_not_exist(
    tmp_path: Path, monkeypatch
) -> None:
    _project, _session = _active_project_and_session(tmp_path, monkeypatch)
    client = TestClient(create_app())

    response = client.get("/agents/does-not-exist/status-model")

    assert response.status_code == 404
    assert "no existe" in response.json()["detail"].lower()


def test_get_agent_status_model_returns_400_when_agent_is_working(
    tmp_path: Path, monkeypatch, isolated_socket,
) -> None:
    """T-FB024-US11-05, criterio de aceptación 2: nunca interactúa con el
    pane de un agente `working` — rechazo explícito con motivo, no un
    intento silencioso ni un None ambiguo."""
    from brain.agents.lifecycle import mark_working

    _project, session = _active_project_and_session(tmp_path, monkeypatch)
    client = TestClient(create_app())

    resp = client.post("/agents", json={"role": "developer", "runtime_type": "claude-code"})
    assert resp.status_code in (200, 201)
    agent_id = resp.json()["id"]

    agent = next(a for a in list_agents(session) if a.id == agent_id)
    mark_working(agent)

    response = client.get(f"/agents/{agent_id}/status-model")

    assert response.status_code == 400
    assert "working" in response.json()["detail"].lower()


def test_get_agent_status_model_returns_null_for_non_claude_code_agent(
    tmp_path: Path, monkeypatch, isolated_socket,
) -> None:
    """Agente OpenCode (idle) → GET /agents/{id}/status-model devuelve
    model: null (get_active_model_claude_code solo actúa sobre Claude
    Code) — nunca envía /status a un runtime que no lo entiende."""
    _project, _session = _active_project_and_session(tmp_path, monkeypatch)
    client = TestClient(create_app())

    resp = client.post("/agents", json={"role": "developer", "runtime_type": "opencode"})
    assert resp.status_code in (200, 201)
    agent_id = resp.json()["id"]

    resp = client.get(f"/agents/{agent_id}/status-model")
    assert resp.status_code == 200
    body = resp.json()
    assert body["agent_id"] == agent_id
    assert body["model"] is None


def test_get_agent_status_model_returns_null_when_idle_claude_code_pane_has_no_status_panel(
    tmp_path: Path, monkeypatch, isolated_socket,
) -> None:
    """Agente Claude Code `idle` (con `sleep` como binario de prueba, mismo
    patrón que el resto de tests de esta suite): el endpoint envía
    /status sin fallar, pero como `sleep` no entiende el comando ni
    imprime un panel real, el parseo no encuentra el patrón "Model:" y
    devuelve null — no inventa un valor."""
    _project, _session = _active_project_and_session(tmp_path, monkeypatch)
    client = TestClient(create_app())

    resp = client.post("/agents", json={"role": "developer", "runtime_type": "claude-code"})
    assert resp.status_code in (200, 201)
    agent_id = resp.json()["id"]

    resp = client.get(f"/agents/{agent_id}/status-model")
    assert resp.status_code == 200
    body = resp.json()
    assert body["agent_id"] == agent_id
    assert body["model"] is None
