"""T-AF023-US03-01 (integración HTTP): el campo `persistent` del `Agent` se
asigna por rol a través del registro de lanzamiento real `POST /agents`, y no
se expone en la serialización (`GET /agents`), de modo que la UI no necesita
el flag — el sistema lo decide de forma transparente por rol.

Los tests unitarios de `test_agent_persistent.py` ejercen `launch_agent`
directamente; estos cubren el hueco de verificar el criterio por la ruta
HTTP documentada y que la respuesta no filtra el campo."""

import uuid
from pathlib import Path

import libtmux
import pytest
from fastapi.testclient import TestClient

import atlas_forge.api.routes as routes_module
from atlas_forge.api import create_app
from atlas_forge.core import resolve_startup_session
from atlas_forge.core.session_registry import _reset_registry_for_tests
from atlas_forge.workspace import discover_projects, select_active_project


@pytest.fixture(autouse=True)
def _clean_registry():
    _reset_registry_for_tests()
    yield
    _reset_registry_for_tests()


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
    monkeypatch.setattr(
        routes_module, "get_active_project", lambda **_kwargs: discovered[0]
    )

    session = resolve_startup_session(workspace_root=workspace, state_dir=state_dir)
    assert session is not None
    return discovered[0], session


def _launch_via_api(role: str, client: TestClient) -> dict:
    response = client.post(
        "/agents", json={"role": role, "runtime_type": "claude-code"}
    )
    assert response.status_code == 201 or response.status_code == 200
    return response.json()


def test_post_agents_assigns_persistent_by_role(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """Criterio 2 (ruta HTTP): lanzar por `POST /agents` asigna `persistent`
    según el rol — Arquitecto `true`, Developer/Tester `false`."""
    _project, session = _active_project_and_session(tmp_path, monkeypatch)
    client = TestClient(create_app())

    _launch_via_api("arquitecto", client)
    architect = next(a for a in session.agents if a.role == "arquitecto")
    assert architect.persistent is True

    _launch_via_api("developer", client)
    developer = next(a for a in session.agents if a.role == "developer")
    assert developer.persistent is False

    _launch_via_api("tester", client)
    tester = next(a for a in session.agents if a.role == "tester")
    assert tester.persistent is False


def test_agents_serialization_does_not_expose_persistent(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """Criterio 3 (transparencia): `GET /agents` no expone el flag `persistent`
    — la UI no necesita mostrarlo; el sistema lo decide por rol."""
    _project, _session = _active_project_and_session(tmp_path, monkeypatch)
    client = TestClient(create_app())

    _launch_via_api("arquitecto", client)
    _launch_via_api("developer", client)

    agents = client.get("/agents").json()
    assert len(agents) == 2
    assert all("persistent" not in agent for agent in agents)