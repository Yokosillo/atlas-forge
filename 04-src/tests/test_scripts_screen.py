"""Tests de `ScriptsScreen` (T-FB001-US03-03): consume `GET /scripts`/
`POST /scripts/{id}/run` vía un backend real en un hilo (mismo criterio de
"comportamiento real" ya aplicado a `AgentsScreen`/`JobsScreen`) — nunca
mockeando `BackendClient` ni el manifiesto."""

import sys
from pathlib import Path

import pytest
from textual.widgets import Select, Static

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


async def test_a_project_without_scripts_shows_an_empty_state_without_error(
    tmp_path, backend
) -> None:
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

        assert len(screen.query(Select)) == 0
        assert "no tiene scripts particulares" in str(
            screen.query_one("Static").content
        )


async def test_running_a_valid_script_shows_its_output_without_typing_the_command(
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
