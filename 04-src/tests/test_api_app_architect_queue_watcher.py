"""T-FB030-US03-04: `_lifespan` (brain.api.app) lanza automáticamente
`architect_queue_watcher.sh` para el proyecto activo al arrancar
`brain-api`, sin que nadie tenga que ejecutarlo a mano — antes de esta
Task, el mecanismo completo de US-FB030-03 quedaba operativamente inerte
salvo lanzamiento manual en una terminal aparte (incidente real del
2026-08-16, ver
07-informes/incidente-arquitecto-perdido-tras-reinicio-2026-08-16.md).

Verificación real (criterio de aceptación 5): arranca `brain-api` de
verdad (`with TestClient(create_app()) as client`, que sí dispara
`_lifespan`), comprueba el proceso vivo con `pgrep`, cierra una Task de
prueba (`append_to_architect_queue`) y confirma el push tmux real hacia
la sesión del Arquitecto — no basta con lectura de código, mismo motivo
que el propio incidente que motivó esta Task."""

import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import brain.api.app as app_module
import brain.api.routes as routes_module
from brain.api import create_app
from brain.core import resolve_startup_session
from brain.core.session_registry import _reset_registry_for_tests
from brain.dispatcher.architect_queue import append_to_architect_queue
from brain.workspace import discover_projects, select_active_project

_HAS_WATCHER_DEPS = shutil.which("inotifywait") is not None and shutil.which("tmux") is not None


@pytest.fixture(autouse=True)
def _clean_registry():
    _reset_registry_for_tests()
    yield
    _reset_registry_for_tests()


def _make_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()


def _kill_watcher_processes(project_root: str, project_name: str) -> None:
    subprocess.run(
        ["pkill", "-9", "-f", f"architect_queue_watcher.sh {project_root} {project_name}"],
        capture_output=True,
    )


@pytest.mark.skipif(not _HAS_WATCHER_DEPS, reason="requiere inotifywait y tmux instalados")
def test_lifespan_launches_the_watcher_for_the_real_active_project_at_startup(
    tmp_path: Path, monkeypatch
) -> None:
    """Criterio de aceptación 1: arrancar `brain-api` con un proyecto
    activo válido deja el proceso `architect_queue_watcher.sh` corriendo
    sin que nadie lo haya lanzado a mano, verificable con `pgrep`."""
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

    try:
        with TestClient(create_app()):
            time.sleep(1)
            result = subprocess.run(
                [
                    "pgrep",
                    "-f",
                    f"architect_queue_watcher.sh {project.path} {project.name}",
                ],
                capture_output=True,
            )
            assert result.returncode == 0, "el watcher no quedó corriendo tras el arranque"
    finally:
        _kill_watcher_processes(project.path, project.name)


@pytest.mark.skipif(not _HAS_WATCHER_DEPS, reason="requiere inotifywait y tmux instalados")
def test_lifespan_does_not_launch_a_second_watcher_on_restart(
    tmp_path: Path, monkeypatch
) -> None:
    """Criterio de aceptación 3: reiniciar `brain-api` (segunda
    construcción de `TestClient`/`_lifespan` para el mismo proyecto) no
    deja dos watchers corriendo a la vez."""
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

    def _pgrep_line_count() -> int:
        # Un único watcher legítimo produce DOS líneas en `pgrep -f` con
        # este patrón (verificado con `ps --forest`): el proceso bash
        # principal del script y el subshell que bash crea para el lado
        # derecho del pipe `inotifywait -m ... | while read ...` —
        # ambos heredan la misma línea de comandos completa. Por eso este
        # test compara el conteo ANTES/DESPUÉS del segundo `_lifespan` en
        # vez de asumir que "1" es el número correcto de líneas.
        result = subprocess.run(
            ["pgrep", "-f", f"architect_queue_watcher.sh {project.path} {project.name}"],
            capture_output=True,
            text=True,
        )
        return len([line for line in result.stdout.splitlines() if line.strip()])

    try:
        with TestClient(create_app()):
            time.sleep(1)
            count_after_first = _pgrep_line_count()
            assert count_after_first > 0, "el primer arranque no lanzó ningún watcher"

            with TestClient(create_app()):
                time.sleep(1)
                count_after_second = _pgrep_line_count()
                assert count_after_second == count_after_first, (
                    "el segundo arranque lanzó un watcher adicional: "
                    f"{count_after_first} líneas -> {count_after_second} líneas"
                )
    finally:
        _kill_watcher_processes(project.path, project.name)


def test_lifespan_does_not_launch_any_watcher_without_an_active_project(
    tmp_path: Path, monkeypatch
) -> None:
    """Criterio de aceptación 4: sin proyecto activo al arrancar, no se
    lanza ningún watcher ni falla el arranque de `brain-api`. `_STATE_DIR`
    apunta a un `tmp_path` vacío (nunca hubo `select_active_project`) —
    sin este aislamiento, `get_active_project(state_dir=None)` leería el
    proyecto activo REAL del sistema en el que corre la suite, dando un
    falso negativo (el test pasaría por casualidad solo si la máquina que
    ejecuta pytest no tiene ningún proyecto activo seleccionado)."""
    monkeypatch.setattr(routes_module, "_STATE_DIR", tmp_path / "empty-state")
    calls = []
    monkeypatch.setattr(
        app_module,
        "launch_architect_queue_watcher",
        lambda *a, **k: calls.append((a, k)),
    )
    with TestClient(create_app()) as client:
        response = client.get("/health")
        assert response.status_code == 200

    assert calls == []


@pytest.mark.skipif(not _HAS_WATCHER_DEPS, reason="requiere inotifywait y tmux instalados")
def test_lifespan_watcher_pushes_to_the_architect_session_when_a_task_closes(
    tmp_path: Path, monkeypatch
) -> None:
    """Criterio de aceptación 2/5: el watcher lanzado por `_lifespan`
    reacciona de verdad a un cierre de Task real (`append_to_architect_queue`)
    con un push tmux hacia la sesión del Arquitecto — reproduce el
    incidente motivador completo end-to-end."""
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

    session_name = f"arquitecto-{project.name}"
    subprocess.run(["tmux", "kill-session", "-t", session_name], capture_output=True)
    subprocess.run(["tmux", "new-session", "-d", "-s", session_name], check=True)

    try:
        with TestClient(create_app()):
            time.sleep(1)

            append_to_architect_queue(
                project.path,
                project.name,
                agente="developer",
                task_id="T-FB030-US03-04",
                informe="07-informes/FB030-US03/FB030-US03.md#T-FB030-US03-04",
            )

            deadline = time.monotonic() + 10
            content = ""
            while time.monotonic() < deadline:
                result = subprocess.run(
                    ["tmux", "capture-pane", "-p", "-t", session_name],
                    capture_output=True,
                    text=True,
                )
                content = result.stdout
                if "cola de cierres pendientes" in content:
                    break
                time.sleep(0.3)

            assert "cola de cierres pendientes" in content
    finally:
        _kill_watcher_processes(project.path, project.name)
        subprocess.run(["tmux", "kill-session", "-t", session_name], capture_output=True)
