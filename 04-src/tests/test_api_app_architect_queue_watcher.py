"""T-AF030-US03-05: `_lifespan` (atlas_forge.api.app) ya NO lanza
`architect_queue_watcher.sh` al arrancar `atlas-forge-api`. El canal
Developer→Arquitecto lo cubre el ciclo de veredicto del Dispatcher
(`dispatch_queue_worker.run_architect_verdict_dispatch_cycle`,
T-AF008-US14-02); el mecanismo deprecado `architect_queue.jsonl` +
`architect_queue_watcher.sh` se retiró (ver `00-gobierno/DISPATCHER.md`,
sección "Canal Developer→Arquitecto": "está deprecado y no debe utilizarse").

Estos tests verifican el contrato nuevo: al arrancar `atlas-forge-api` (incluso
con un proyecto activo, que era la condición que antes disparaba el
lanzamiento) NO queda ningún proceso `architect_queue_watcher.sh` corriendo,
y el arranque sigue sirviendo `/health` (la retirada no rompe el `_lifespan`).
"""

import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import atlas_forge.api.routes as routes_module
from atlas_forge.api import create_app
from atlas_forge.core import resolve_startup_session
from atlas_forge.core.session_registry import _reset_registry_for_tests
from atlas_forge.workspace import discover_projects, select_active_project

_HAS_WATCHER_DEPS = shutil.which("inotifywait") is not None and shutil.which("tmux") is not None


@pytest.fixture(autouse=True)
def _clean_registry():
    _reset_registry_for_tests()
    yield
    _reset_registry_for_tests()


def _make_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()


def _watcher_process_count(project_root: str, project_name: str) -> int:
    result = subprocess.run(
        ["pgrep", "-f", f"architect_queue_watcher.sh {project_root} {project_name}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return 0
    return len([line for line in result.stdout.splitlines() if line.strip()])


@pytest.mark.skipif(not _HAS_WATCHER_DEPS, reason="requiere inotifywait y tmux instalados")
def test_lifespan_does_not_launch_the_deprecated_architect_watcher(
    tmp_path: Path, monkeypatch
) -> None:
    """Criterio de aceptación 2: arrancar `atlas-forge-api` con un proyecto activo
    válido (la condición que antes disparaba el lanzamiento) NO deja ningún
    proceso `architect_queue_watcher.sh` corriendo, y el arranque responde
    `/health` con 200."""
    workspace = tmp_path / "workspace"
    project_dir_name = f"proj-{uuid.uuid4().hex[:8]}"
    _make_git_repo(workspace / project_dir_name)
    state_dir = tmp_path / "state"

    discovered = discover_projects(workspace)
    project = next(p for p in discovered if p.name == project_dir_name)
    select_active_project(project, discovered=discovered, state_dir=state_dir)
    monkeypatch.setattr(routes_module, "_WORKSPACE_ROOT", workspace)
    monkeypatch.setattr(routes_module, "_STATE_DIR", state_dir)
    resolve_startup_session(workspace_root=workspace, state_dir=state_dir)

    with TestClient(create_app()) as client:
        time.sleep(1)
        assert client.get("/health").status_code == 200
        assert (
            _watcher_process_count(project.path, project.name) == 0
        ), "el lifespan volvió a lanzar el watcher deprecado"


def test_lifespan_starts_health_without_an_active_project(
    tmp_path: Path, monkeypatch
) -> None:
    """Sin proyecto activo al arrancar, `atlas-forge-api` sigue sirviendo `/health`
    con 200 — la retirada del watcher no rompe el arranque."""
    monkeypatch.setattr(routes_module, "_STATE_DIR", tmp_path / "empty-state")
    with TestClient(create_app()) as client:
        assert client.get("/health").status_code == 200
