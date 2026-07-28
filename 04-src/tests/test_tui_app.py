import shutil
from pathlib import Path

from brain.tui import FactoryBrainApp
from brain.tui.screens import DashboardScreen, WorkspaceScreen
from brain.workspace.active_project import select_active_project
from brain.workspace.discovery import discover_projects


def _make_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()


async def test_app_starts_on_workspace_screen_without_active_project(
    tmp_path,
) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    state_dir = tmp_path / "state"

    app = FactoryBrainApp(workspace_root=workspace_root, state_dir=state_dir)
    async with app.run_test() as pilot:
        assert isinstance(pilot.app.screen, WorkspaceScreen)


async def test_app_starts_on_dashboard_screen_with_valid_active_project(
    tmp_path,
) -> None:
    workspace_root = tmp_path / "workspace"
    repo_path = workspace_root / "my-project"
    _make_git_repo(repo_path)
    state_dir = tmp_path / "state"

    discovered = discover_projects(workspace_root)
    select_active_project(discovered[0], discovered=discovered, state_dir=state_dir)

    app = FactoryBrainApp(workspace_root=workspace_root, state_dir=state_dir)
    async with app.run_test() as pilot:
        assert isinstance(pilot.app.screen, DashboardScreen)


async def test_app_starts_on_workspace_screen_when_active_project_is_invalid(
    tmp_path,
) -> None:
    # Proyecto persistido cuya ruta ya no existe (movido/borrado) — debe
    # caer a Workspace, no a Dashboard (mismo criterio de
    # resolve_startup_project, FB-001).
    workspace_root = tmp_path / "workspace"
    repo_path = workspace_root / "my-project"
    _make_git_repo(repo_path)
    state_dir = tmp_path / "state"

    discovered = discover_projects(workspace_root)
    select_active_project(discovered[0], discovered=discovered, state_dir=state_dir)
    shutil.rmtree(repo_path)

    app = FactoryBrainApp(workspace_root=workspace_root, state_dir=state_dir)
    async with app.run_test() as pilot:
        assert isinstance(pilot.app.screen, WorkspaceScreen)


async def test_navigation_mechanism_can_push_and_pop_screens(tmp_path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    state_dir = tmp_path / "state"

    app = FactoryBrainApp(workspace_root=workspace_root, state_dir=state_dir)
    async with app.run_test() as pilot:
        assert isinstance(pilot.app.screen, WorkspaceScreen)

        pilot.app.push_screen(DashboardScreen())
        await pilot.pause()
        assert isinstance(pilot.app.screen, DashboardScreen)

        pilot.app.pop_screen()
        await pilot.pause()
        assert isinstance(pilot.app.screen, WorkspaceScreen)
