from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from atlas_forge.api import create_app
from atlas_forge.core import resolve_startup_session
from atlas_forge.core.session_registry import _reset_registry_for_tests
from atlas_forge.workspace import discover_projects, select_active_project


@pytest.fixture(autouse=True)
def _clean_registry():
    _reset_registry_for_tests()
    yield
    _reset_registry_for_tests()


def _make_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()


def _workspace_with_active_project(tmp_path: Path) -> tuple[Path, Path]:
    workspace = tmp_path / "workspace"
    _make_git_repo(workspace / "project-a")
    state_dir = tmp_path / "state"

    discovered = discover_projects(workspace)
    select_active_project(discovered[0], discovered=discovered, state_dir=state_dir)

    return workspace, state_dir


def test_health_endpoint_responds_ok_with_no_active_session() -> None:
    app = create_app()
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "session_id": None}


def test_health_endpoint_reports_the_active_session_when_one_exists(
    tmp_path: Path,
) -> None:
    workspace, state_dir = _workspace_with_active_project(tmp_path)
    session = resolve_startup_session(workspace_root=workspace, state_dir=state_dir)
    assert session is not None

    app = create_app()
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "session_id": session.id}


def test_two_clients_see_the_same_session_state(tmp_path: Path) -> None:
    """Contraste directo con el problema real detectado con
    `textual-serve` (cada conexión lanzaba su propio subproceso `atlas_forge`,
    con su propio `_SessionRegistry` en memoria): aquí ambos "clientes"
    (instancias de `TestClient`, cada una como una conexión HTTP
    independiente) hablan contra la MISMA `app` — el mismo proceso — y
    por tanto ven exactamente el mismo estado de sesión, sin que ninguno
    de los dos lo haya establecido más de una vez."""
    workspace, state_dir = _workspace_with_active_project(tmp_path)

    app = create_app()
    client_one = TestClient(app)
    client_two = TestClient(app)

    # Antes de que exista sesión activa, ambos clientes ven None por igual.
    assert client_one.get("/health").json()["session_id"] is None
    assert client_two.get("/health").json()["session_id"] is None

    # Un único arranque de sesión (equivalente a "un cliente lanza un
    # agente"/arranca el proceso) — el otro cliente, sin haber hecho nada
    # él mismo, debe ver el mismo resultado inmediatamente.
    session = resolve_startup_session(workspace_root=workspace, state_dir=state_dir)
    assert session is not None

    response_one = client_one.get("/health").json()
    response_two = client_two.get("/health").json()

    assert response_one["session_id"] == session.id
    assert response_two["session_id"] == session.id
    assert response_one == response_two
