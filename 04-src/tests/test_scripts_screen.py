"""Tests de `ScriptsScreen` (T-FB001-US03-03, T-FB018-US01-03): consume
`GET /scripts`/`POST /scripts/{id}/run` vía un backend real en un hilo
(mismo criterio de "comportamiento real" ya aplicado a `AgentsScreen`/
`JobsScreen`) — nunca mockeando `BackendClient` ni el manifiesto.

## ADVERTENCIA DE SEGURIDAD (heredada de `test_api_routes_scripts.py`)

El test que ejecuta `commit` desde la TUI opera SIEMPRE sobre un
repositorio git temporal aislado (real, con `git init` + identidad),
NUNCA sobre el repositorio real de Factory Brain."""

import subprocess
import sys
from pathlib import Path

import pytest
from textual.widgets import Input, Select, Static

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
from backend_server import running_backend  # noqa: E402

from brain.core.session_registry import _reset_registry_for_tests
from brain.tui.app import FactoryBrainApp
from brain.tui.backend_client import BackendClient
from brain.tui.screens import ScriptsScreen
from brain.workspace.active_project import select_active_project
from brain.workspace.discovery import discover_projects
from brain.workspace.project_scripts import MANIFEST_RELATIVE_PATH


@pytest.fixture(autouse=True)
def _reset_session_registry():
    _reset_registry_for_tests()
    yield
    _reset_registry_for_tests()


@pytest.fixture
def backend(tmp_path: Path):
    with running_backend(
        workspace_root=tmp_path / "workspace", state_dir=tmp_path / "state"
    ) as base_url:
        yield BackendClient(base_url=base_url)


def _make_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()


def _init_real_git_repo(path: Path) -> None:
    """Repositorio git REAL y aislado (identidad configurada para que
    `git commit` funcione) — los tests de `commit` SIEMPRE usan esto."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test Worker"], check=True
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test-worker@example.invalid"],
        check=True,
    )


def _write_manifest(project_path: Path, content: str) -> None:
    manifest_path = project_path / MANIFEST_RELATIVE_PATH
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(content, encoding="utf-8")


def _select_project_and_start_backend_session(workspace_root: Path, state_dir: Path) -> Path:
    from brain.core.session_registry import resolve_startup_session

    repo_path = workspace_root / "my-project"
    _make_git_repo(repo_path)
    discovered = discover_projects(workspace_root)
    select_active_project(discovered[0], discovered=discovered, state_dir=state_dir)
    resolve_startup_session(workspace_root=workspace_root, state_dir=state_dir)
    return repo_path


async def test_a_project_without_particular_scripts_shows_the_generic_catalog(
    tmp_path, backend
) -> None:
    """Criterio 4 de T-FB018-US01-03: un proyecto sin scripts particulares
    (sin manifiesto) sigue mostrando el catálogo genérico con normalidad —
    no depende de que existan ambos catálogos."""
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _select_project_and_start_backend_session(workspace_root, state_dir)

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        screen = ScriptsScreen(
            workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
        )
        pilot.app.push_screen(screen)
        await pilot.pause()

        # Sin manifiesto, la pantalla muestra el catálogo genérico (no una
        # lista vacía ni un mensaje de error).
        select_widget = screen.query_one("#script-choice", Select)
        assert select_widget.value == "commit"
        assert len(select_widget._options) == len(
            [e for e in screen._scripts if e["origin"] == "generic"]
        )


async def test_running_a_particular_script_shows_its_output_without_typing_the_command(
    tmp_path, backend
) -> None:
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    repo_path = _select_project_and_start_backend_session(workspace_root, state_dir)
    _write_manifest(
        repo_path,
        """
        scripts:
          - id: greet
            name: "Greet"
            command: "echo hello-from-tui"
        """,
    )

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        screen = ScriptsScreen(
            workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
        )
        pilot.app.push_screen(screen)
        await pilot.pause()

        # El catálogo combinado muestra ambos orígenes; elegimos el script
        # particular (no el genérico por defecto).
        screen.query_one("#script-choice", Select).value = "greet"
        await pilot.pause()
        await pilot.click("#run-script")

        result_widget = screen.query_one("#script-result", Static)
        for _ in range(50):
            if "hello-from-tui" in str(result_widget.content):
                break
            await pilot.pause(0.05)

        assert "hello-from-tui" in str(result_widget.content)
        assert "Éxito" in str(result_widget.content)


async def test_a_failing_script_reflects_its_reason_without_breaking_the_screen(
    tmp_path, backend
) -> None:
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    repo_path = _select_project_and_start_backend_session(workspace_root, state_dir)
    _write_manifest(
        repo_path,
        """
        scripts:
          - id: broken
            name: "Broken"
            command: "echo went-wrong >&2; exit 7"
        """,
    )

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        screen = ScriptsScreen(
            workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
        )
        pilot.app.push_screen(screen)
        await pilot.pause()

        screen.query_one("#script-choice", Select).value = "broken"
        await pilot.pause()
        await pilot.click("#run-script")

        result_widget = screen.query_one("#script-result", Static)
        for _ in range(50):
            if "went-wrong" in str(result_widget.content):
                break
            await pilot.pause(0.05)

        assert "went-wrong" in str(result_widget.content)
        assert "Falló" in str(result_widget.content)

        # La pantalla sigue operable tras el fallo — el botón "Volver al
        # Dashboard" sigue presente y funcional (criterio de aceptación:
        # "sin romper ni bloquear el resto de la interfaz").
        assert screen.query_one("#go-to-dashboard") is not None


async def test_commit_requires_a_message_before_running(tmp_path, backend) -> None:
    """Criterio 2 de T-FB018-US01-03: ejecutar `commit` desde la TUI pide
    el mensaje antes de lanzar el script — sin mensaje no se ejecuta."""
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    repo_path = _select_project_and_start_backend_session(workspace_root, state_dir)
    _init_real_git_repo(repo_path)
    (repo_path / "file.txt").write_text("v1", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_path), "add", "file.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(repo_path), "commit", "-q", "-m", "add file.txt"], check=True
    )
    # Cambio real pendiente de comitear.
    (repo_path / "file.txt").write_text("v2", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_path), "add", "file.txt"], check=True)

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        screen = ScriptsScreen(
            workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
        )
        pilot.app.push_screen(screen)
        await pilot.pause()

        # `commit` es la selección por defecto; sin mensaje, se pide.
        assert screen.query_one("#script-choice", Select).value == "commit"
        await pilot.click("#run-script")
        result_widget = screen.query_one("#script-result", Static)
        assert "Escribe un mensaje para el commit" in str(result_widget.content)

        # Con mensaje, se ejecuta y el commit real usa ese mensaje.
        screen.query_one("#commit-message", Input).value = "commit desde la TUI"
        await pilot.pause()
        screen._run_selected_script()
        await pilot.pause()
        for _ in range(50):
            if "Éxito" in str(result_widget.content):
                break
            await pilot.pause(0.05)

        assert "Éxito" in str(result_widget.content)
        log = subprocess.run(
            ["git", "-C", str(repo_path), "log", "-1", "--format=%s"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert log == "commit desde la TUI"


def _write_backlog_file(path: Path, item_id: str, *, state: str, priority: str) -> None:
    path.write_text(
        f"# {item_id}\n"
        f"**Epic:** FB-999 · Epic de prueba\n"
        f"## Estado\n\n{state}\n\n"
        f"## Dependencias\n\nNinguna.\n\n"
        f"## Prioridad\n\n{priority}\n",
        encoding="utf-8",
    )


async def test_backlog_status_result_is_presented_readably_not_as_raw_json(
    tmp_path, backend
) -> None:
    """Criterios 2 y 3 de T-FB018-US02-04: ejecutar `backlog-status` desde
    la TUI muestra el conteo por Epic, la lista de Tasks listas y la cadena
    de mayor apalancamiento — sin que el desarrollador tenga que interpretar
    JSON crudo en pantalla."""
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    repo_path = _select_project_and_start_backend_session(workspace_root, state_dir)
    _init_real_git_repo(repo_path)
    backlog = repo_path / "02-backlog"
    (backlog / "user-stories").mkdir(parents=True)
    (backlog / "tasks").mkdir(parents=True)
    _write_backlog_file(backlog / "user-stories" / "US-FB999-01.md", "US-FB999-01", state="DONE", priority="Alta.")
    _write_backlog_file(backlog / "user-stories" / "US-FB999-02.md", "US-FB999-02", state="TODO", priority="Alta.")
    _write_backlog_file(backlog / "tasks" / "T-FB999-01.md", "T-FB999-01", state="TODO", priority="Crítica.")

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        screen = ScriptsScreen(
            workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
        )
        pilot.app.push_screen(screen)
        await pilot.pause()

        screen.query_one("#script-choice", Select).value = "backlog_status"
        await pilot.pause()
        await pilot.click("#run-script")

        result_widget = screen.query_one("#script-result", Static)
        for _ in range(50):
            if "Estado del backlog" in str(result_widget.content):
                break
            await pilot.pause(0.05)

        content = str(result_widget.content)
        # Presentación legible, no JSON crudo.
        assert "Conteo por Epic" in content
        assert "FB-999" in content
        assert "T-FB999-01" in content
        assert "US-FB999-02" in content
        assert "Cadena de mayor apalancamiento" in content
        assert '{"' not in content
