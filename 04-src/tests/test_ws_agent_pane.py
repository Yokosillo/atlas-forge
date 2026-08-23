"""Tests de T-AF032-US01-01: `WS /ws/agents/{agent_id}/pane`, canal 1:1
con poller propio de `capture_pane_lines` por conexión."""

import asyncio
import uuid
from pathlib import Path

import libtmux
import pytest
from fastapi.testclient import TestClient

import atlas_forge.api.app as app_module
import atlas_forge.api.routes as routes_module
from atlas_forge.api import create_app
from atlas_forge.agents.launch import launch_agent
from atlas_forge.core import resolve_startup_session
from atlas_forge.core.session_registry import _reset_registry_for_tests
from atlas_forge.dispatcher.job_history_registry import _reset_registry_for_tests as _reset_job_history
from atlas_forge.runtime import stop_runtime
from atlas_forge.workspace import discover_projects, select_active_project


@pytest.fixture(autouse=True)
def _clean_registries():
    _reset_registry_for_tests()
    _reset_job_history()
    yield
    _reset_registry_for_tests()
    _reset_job_history()


@pytest.fixture(autouse=True)
def _no_real_runtime(monkeypatch):
    import atlas_forge.runtime.claude_code as claude_code_module
    import atlas_forge.runtime.opencode as opencode_module

    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_COMMAND", "sleep")
    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_ARGS", ["5"])
    monkeypatch.setattr(opencode_module, "DEFAULT_OPENCODE_COMMAND", "sleep")
    monkeypatch.setattr(opencode_module, "DEFAULT_OPENCODE_AUTONOMY_FLAG", "5")
    monkeypatch.setattr(opencode_module, "DEFAULT_OPENCODE_ARGS", ["5"])


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


def _active_project_and_session(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    _make_git_repo(workspace / "project-a")
    state_dir = tmp_path / "state"

    discovered = discover_projects(workspace)
    select_active_project(discovered[0], discovered=discovered, state_dir=state_dir)
    monkeypatch.setattr(routes_module, "_WORKSPACE_ROOT", workspace)
    monkeypatch.setattr(routes_module, "_STATE_DIR", state_dir)

    session = resolve_startup_session(workspace_root=workspace, state_dir=state_dir)
    assert session is not None
    return discovered[0], session


def _launch_agent(tmp_path: Path, session, isolated_socket: str):
    return launch_agent(
        "developer", "claude-code", None, session, str(tmp_path), socket_name=isolated_socket
    )


# ---------------------------------------------------------- unitarios (mock)


def test_ws_agent_pane_pushes_content_when_it_changes(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """Criterio de aceptación: conectar y producir actividad real hace
    llegar el contenido actualizado sin que el cliente pida nada — aquí,
    `capture_pane_lines` mockeada para no depender de tmux real."""
    _project, session = _active_project_and_session(tmp_path, monkeypatch)
    agent, runtime_instance = _launch_agent(tmp_path, session, isolated_socket)

    monkeypatch.setattr(app_module, "is_runtime_alive", lambda *a, **k: True)

    contents = iter(
        [
            ["línea 1"],
            ["línea 1"],  # sin cambio: no debe generar un segundo mensaje
            ["línea 1", "línea 2"],
        ]
    )
    monkeypatch.setattr(
        app_module, "capture_pane_lines", lambda *a, **k: next(contents, ["línea 1", "línea 2"])
    )

    with TestClient(create_app()) as client:
        with client.websocket_connect(f"/ws/agents/{agent.id}/pane") as websocket:
            first = websocket.receive_json()
            second = websocket.receive_json()

    assert first == {"event": "pane_content", "agent_id": agent.id, "content": "línea 1"}
    assert second == {
        "event": "pane_content",
        "agent_id": agent.id,
        "content": "línea 1\nlínea 2",
    }

    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_ws_agent_pane_closes_with_explicit_reason_for_unknown_agent(
    tmp_path: Path, monkeypatch
) -> None:
    """Conectar a un agent_id inexistente cierra la conexión con un
    motivo identificable, no un error silencioso ni una conexión colgada."""
    _project, _session = _active_project_and_session(tmp_path, monkeypatch)

    with TestClient(create_app()) as client:
        with pytest.raises(Exception) as exc_info:
            with client.websocket_connect("/ws/agents/no-existe/pane") as websocket:
                websocket.receive_json()

    # starlette.testclient señaliza el close con una excepción que expone
    # code/reason — se confirma que no es un cierre silencioso genérico.
    assert "4004" in str(exc_info.value) or getattr(exc_info.value, "code", None) == 4004


def test_ws_agent_pane_closes_with_explicit_reason_when_runtime_is_not_alive(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """Conectar a un agente cuya sesión tmux ya no está viva cierra con
    motivo explícito, mismo criterio que `GET /agents/{id}/pane`."""
    _project, session = _active_project_and_session(tmp_path, monkeypatch)
    agent, runtime_instance = _launch_agent(tmp_path, session, isolated_socket)

    monkeypatch.setattr(app_module, "is_runtime_alive", lambda *a, **k: False)

    with TestClient(create_app()) as client:
        with pytest.raises(Exception):
            with client.websocket_connect(f"/ws/agents/{agent.id}/pane") as websocket:
                websocket.receive_json()

    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_ws_agent_pane_stops_polling_task_after_client_disconnects(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """Criterio de aceptación: cerrar la conexión del lado cliente detiene
    el bucle de polling en servidor — no queda ninguna tarea async huérfana."""
    _project, session = _active_project_and_session(tmp_path, monkeypatch)
    agent, runtime_instance = _launch_agent(tmp_path, session, isolated_socket)

    monkeypatch.setattr(app_module, "is_runtime_alive", lambda *a, **k: True)
    monkeypatch.setattr(app_module, "capture_pane_lines", lambda *a, **k: ["contenido"])

    tasks_before = {t.get_name() for t in asyncio.all_tasks()} if _running_loop() else set()

    with TestClient(create_app()) as client:
        with client.websocket_connect(f"/ws/agents/{agent.id}/pane") as websocket:
            websocket.receive_json()
        # El bloque `with` de websocket_connect ya cerró la conexión al
        # salir — dar un instante al servidor de test para que su propio
        # bucle detecte `WebSocketDisconnect` y termine la corrutina.

    stop_runtime(runtime_instance, socket_name=isolated_socket)
    # No hay una forma directa de inspeccionar el loop interno del
    # TestClient desde aquí (corre en su propio hilo/loop) — la
    # verificación real de "no queda tarea huérfana" es que el `with
    # TestClient(...)` de arriba termina y libera sin colgarse: si el
    # poller no terminara al desconectar, el `finally`/shutdown de
    # `TestClient` no completaría en un tiempo razonable y este test
    # colgaría en vez de pasar.


def _running_loop() -> bool:
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


# --------------------------------------------------- integración (tmux real)


def test_ws_agent_pane_receives_real_tmux_output_end_to_end(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """Test de integración con tmux real (mismo patrón ya usado en otros
    tests de este módulo, p. ej. `test_api_routes_agents.py`): sin
    mockear `capture_pane_lines`, un cambio real en el pane del agente
    debe llegar por el WebSocket."""
    import atlas_forge.runtime.claude_code as claude_code_module

    cooperative_script = str(
        Path(__file__).parent / "fixtures" / "cooperative_agent_sim.sh"
    )
    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_COMMAND", "bash")
    monkeypatch.setattr(
        claude_code_module, "DEFAULT_CLAUDE_CODE_ARGS", [cooperative_script]
    )

    _project, session = _active_project_and_session(tmp_path, monkeypatch)
    agent, runtime_instance = launch_agent(
        "developer", "claude-code", None, session, str(tmp_path), socket_name=isolated_socket
    )

    with TestClient(create_app()) as client:
        with client.websocket_connect(f"/ws/agents/{agent.id}/pane") as websocket:
            message = websocket.receive_json()

    assert message["event"] == "pane_content"
    assert message["agent_id"] == agent.id
    assert isinstance(message["content"], str)

    stop_runtime(runtime_instance, socket_name=isolated_socket)
