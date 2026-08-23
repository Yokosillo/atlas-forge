import uuid
from pathlib import Path

import libtmux
import pytest
from fastapi.testclient import TestClient

import atlas_forge.api.routes as routes_module
from atlas_forge.api import create_app
from atlas_forge.core import resolve_startup_session
from atlas_forge.core.session_registry import _reset_registry_for_tests
from atlas_forge.dispatcher.job_history_registry import (
    _reset_registry_for_tests as _reset_job_history,
)
from atlas_forge.tmux.manager import create_session, run_command
from atlas_forge.workspace import discover_projects, select_active_project

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


@pytest.fixture
def isolated_socket(monkeypatch):
    name = f"atlas_forge-test-{uuid.uuid4().hex[:8]}"
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


def _active_project_and_session(tmp_path: Path, monkeypatch, project_dir_name: str):
    """Arranca un proyecto activo y una sesión de desarrollo reales y
    aislados, ANTES de construir el `TestClient` (que es lo que dispara
    `_lifespan` y, con él, la reconciliación bajo prueba).

    A diferencia de `test_api_routes_agents.py` (que solo necesita
    `routes_module.get_active_project` para los endpoints HTTP), este
    fichero SÍ necesita que `_lifespan` mismo resuelva el proyecto
    correcto: `_lifespan` llama `resolve_startup_session` con
    `routes_module._WORKSPACE_ROOT`/`_STATE_DIR` (no con los valores
    locales de este helper) — sin este `monkeypatch` adicional,
    `_lifespan` resolvería contra el filesystem/estado real del usuario
    en vez del `tmp_path` aislado de este test."""
    workspace = tmp_path / "workspace"
    _make_git_repo(workspace / project_dir_name)
    state_dir = tmp_path / "state"

    discovered = discover_projects(workspace)
    project = next(p for p in discovered if p.name == project_dir_name)
    select_active_project(project, discovered=discovered, state_dir=state_dir)
    monkeypatch.setattr(routes_module, "get_active_project", lambda **_kwargs: project)
    monkeypatch.setattr(routes_module, "_WORKSPACE_ROOT", workspace)
    monkeypatch.setattr(routes_module, "_STATE_DIR", state_dir)

    session = resolve_startup_session(workspace_root=workspace, state_dir=state_dir)
    assert session is not None
    return project, session


def test_reconciles_arquitecto_and_developer_sessions_created_without_register_agent(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """Criterio de aceptación explícito de la Task: crear sesiones tmux
    reales con nombres normalizados (Arquitecto y Developer-1) SIN pasar
    por `register_agent`/`register_developer` — simula que el proceso
    que las lanzó y registró ya no existe (el caso motivador real: un
    reinicio de `atlas-forge-api`). Arrancar `_lifespan` desde cero (construir
    `TestClient`) debe reenganchar ambas y `GET /agents` debe listarlas
    en `idle`."""
    project, _session = _active_project_and_session(
        tmp_path, monkeypatch, "mi-proyecto-real"
    )

    # Sesiones tmux reales, con el nombre EXACTO que produciría
    # session_name_for para este proyecto — creadas a mano, no vía
    # register_agent, para simular el proceso ya muerto.
    arquitecto_session_name = f"arquitecto-{project.name}"
    developer_session_name = f"developer-1-{project.name}"
    create_session(arquitecto_session_name, str(tmp_path), socket_name=isolated_socket)
    create_session(developer_session_name, str(tmp_path), socket_name=isolated_socket)

    # `with` es imprescindible: `TestClient(app)` sin `with` NO ejecuta el
    # lifespan de FastAPI (verificado explícitamente antes de escribir
    # este test) — la reconciliación bajo prueba vive dentro de
    # `_lifespan`, así que sin `with` este test pasaría en falso (0
    # agentes, sin ejercitar el código real).
    with TestClient(create_app()) as client:
        response = client.get("/agents")
        assert response.status_code == 200
        agents = response.json()

        assert len(agents) == 2
        roles_and_status = {(a["role"], a["status"]) for a in agents}
        assert roles_and_status == {("arquitecto", "idle"), ("developer", "idle")}

        names = {a["name"] for a in agents}
        assert names == {"Arquitecto", "Developer-1"}

        session_names = {a["session_name"] for a in agents}
        assert session_names == {arquitecto_session_name, developer_session_name}


def test_does_not_reconcile_a_session_from_a_different_project(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """Criterio de aceptación explícito: una sesión tmux normalizada de
    OTRO proyecto en el mismo socket no aparece en GET /agents del
    proyecto que se acaba de arrancar."""
    project, _session = _active_project_and_session(
        tmp_path, monkeypatch, "proyecto-activo"
    )

    own_session_name = f"arquitecto-{project.name}"
    other_project_session_name = "arquitecto-otro-proyecto-distinto"
    create_session(own_session_name, str(tmp_path), socket_name=isolated_socket)
    create_session(
        other_project_session_name, str(tmp_path), socket_name=isolated_socket
    )

    with TestClient(create_app()) as client:
        response = client.get("/agents")

        assert response.status_code == 200
        agents = response.json()
        assert len(agents) == 1
        assert agents[0]["session_name"] == own_session_name


def test_unrecognized_tmux_session_is_neither_reconciled_nor_destroyed(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """Criterio de aceptación explícito: una sesión tmux sin nombre
    reconocible no aparece en GET /agents ni se destruye (sigue viva en
    tmux, solo ignorada por Atlas Forge)."""
    from atlas_forge.tmux.manager import is_alive

    _project, _session = _active_project_and_session(
        tmp_path, monkeypatch, "proyecto-con-sesion-ajena"
    )

    unrelated_session_name = "una-sesion-tmux-cualquiera-ajena"
    create_session(unrelated_session_name, str(tmp_path), socket_name=isolated_socket)

    with TestClient(create_app()) as client:
        response = client.get("/agents")

        assert response.status_code == 200
        assert response.json() == []
        # No se destruye: sigue viva en tmux, solo ignorada.
        assert is_alive(unrelated_session_name, socket_name=isolated_socket) is True


def test_reconciled_agent_receives_a_real_job_successfully(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """Criterio de aceptación explícito: el agente reenganchado recibe un
    Job de prueba con éxito, usando su sesión tmux ya existente (sin
    relanzar nada) — verificado con un doble cooperativo real de tmux,
    no un runtime real de Claude Code/OpenCode."""
    project, _session = _active_project_and_session(
        tmp_path, monkeypatch, "proyecto-con-job-real"
    )

    developer_session_name = f"developer-1-{project.name}"
    create_session(developer_session_name, str(tmp_path), socket_name=isolated_socket)
    run_command(
        developer_session_name,
        f"bash {_COOPERATIVE_AGENT_SCRIPT}",
        socket_name=isolated_socket,
    )

    with TestClient(create_app()) as client:
        agents = client.get("/agents").json()
        assert len(agents) == 1
        agent_id = agents[0]["id"]

        response = client.post(
            "/jobs",
            json={"agent_id": agent_id, "description": "implement the feature"},
        )

        assert response.status_code == 201
        job = response.json()
        assert job["status"] == "completed"
        assert "cooperative result" in job["result"]


def test_lifespan_writes_a_reconciliation_log_entry_reflecting_the_reconciled_agent(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """T-AF037-US02-01, criterio de aceptación explícito de la Task:
    reiniciar `atlas-forge-api` con al menos un agente vivo (sesión tmux
    reconocible) y confirmar que la entrada de log resultante refleja el
    número correcto de sesiones reenganchadas. `with TestClient(...)`
    dispara `_lifespan` real, igual que el resto de este fichero."""
    import json

    from atlas_forge.core.reconciliation_log import reconciliation_log_path

    project, _session = _active_project_and_session(
        tmp_path, monkeypatch, "proyecto-con-log-real"
    )

    developer_session_name = f"developer-1-{project.name}"
    unrelated_session_name = "una-sesion-tmux-cualquiera-ajena"
    create_session(developer_session_name, str(tmp_path), socket_name=isolated_socket)
    create_session(unrelated_session_name, str(tmp_path), socket_name=isolated_socket)

    with TestClient(create_app()) as client:
        response = client.get("/agents")
        assert response.status_code == 200
        assert len(response.json()) == 1  # confirma que sí hubo reconciliación real

    log_path = reconciliation_log_path(project.path, project.name)
    assert log_path.is_file()

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])

    assert entry["total_sessions"] == 2
    assert entry["reconciled_count"] == 1
    assert entry["reconciled"] == ["Developer-1"]
    assert entry["ignored_count"] == 1
    assert entry["ignored"] == [
        {"session_name": unrelated_session_name, "reason": "nombre_no_reconocido"}
    ]
    assert "ts" in entry and entry["ts"]


def test_infer_runtime_and_model_detects_opencode_from_pane(monkeypatch) -> None:
    """US-AF031-03, criterio 1/2: una sesión cuyo pane muestra la barra de
    estado de OpenCode (`"Build · "`) se infiere como OpenCode, y el
    nombre de pantalla extraído se mapea al id REAL del catálogo
    ("DeepSeek V4 Flash" -> "opencode-go/deepseek-v4-flash") para que
    `GET /agents` devuelva un modelo concreto — en vez de asumir siempre
    Claude Code."""
    from atlas_forge.core import session_reconciliation as sr

    monkeypatch.setattr(sr, "is_alive", lambda *a, **k: True)
    monkeypatch.setattr(
        sr,
        "capture_pane_lines",
        lambda *a, **k: [
            "some output line",
            "Build · DeepSeek V4 Flash DeepSeek",
        ],
    )

    runtime, model = sr._infer_runtime_and_model_for_session("developer-1-proj")

    assert runtime.type == "opencode"
    assert runtime.id == "opencode"
    assert model == "opencode-go/deepseek-v4-flash"


def test_infer_runtime_and_model_leaves_model_none_for_unmatched_display_name(
    monkeypatch,
) -> None:
    """US-AF031-03, criterio 2: si el nombre tras `"Build · "` no coincide
    con ninguna entrada del catálogo, el runtime se detecta como OpenCode
    pero el modelo se deja `None` — nunca un valor inventado."""
    from atlas_forge.core import session_reconciliation as sr

    monkeypatch.setattr(sr, "is_alive", lambda *a, **k: True)
    monkeypatch.setattr(
        sr,
        "capture_pane_lines",
        lambda *a, **k: ["Build · Modelo Desconocido Futurista"],
    )

    runtime, model = sr._infer_runtime_and_model_for_session("developer-1-proj")

    assert runtime.type == "opencode"
    assert model is None


def test_infer_runtime_and_model_defaults_to_claude_code_without_pattern(
    monkeypatch,
) -> None:
    """US-AF031-03, criterio 3: sin ningún patrón reconocible en el pane
    (agente recién lanzado, CLI distinto, o Claude Code), se conserva el
    comportamiento documentado: `claude-code` por defecto, modelo `None`."""
    from atlas_forge.core import session_reconciliation as sr

    monkeypatch.setattr(sr, "is_alive", lambda *a, **k: True)
    monkeypatch.setattr(
        sr, "capture_pane_lines", lambda *a, **k: ["just some shell output"]
    )

    runtime, model = sr._infer_runtime_and_model_for_session("developer-1-proj")

    assert runtime.type == "claude-code"
    assert runtime.id == "claude-code"
    assert model is None


def test_infer_runtime_and_model_handles_dead_session(monkeypatch) -> None:
    """US-AF031-03, criterio 3: una sesión no viva (o un fallo al capturar
    el pane) no rompe la inferencia — se conserva el default claude-code."""
    from atlas_forge.core import session_reconciliation as sr

    monkeypatch.setattr(sr, "is_alive", lambda *a, **k: False)

    runtime, model = sr._infer_runtime_and_model_for_session("developer-1-proj")

    assert runtime.type == "claude-code"
    assert model is None
