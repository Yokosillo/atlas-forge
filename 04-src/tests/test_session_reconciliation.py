import uuid
from pathlib import Path

import libtmux
import pytest
from fastapi.testclient import TestClient

import brain.api.routes as routes_module
from brain.api import create_app
from brain.core import resolve_startup_session
from brain.core.session_registry import _reset_registry_for_tests
from brain.dispatcher.job_history_registry import (
    _reset_registry_for_tests as _reset_job_history,
)
from brain.tmux.manager import create_session, run_command
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
    reinicio de `brain-api`). Arrancar `_lifespan` desde cero (construir
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
    tmux, solo ignorada por Brain)."""
    from brain.tmux.manager import is_alive

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
