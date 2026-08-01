import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
from backend_server import running_backend  # noqa: E402

from brain.core.session_registry import _reset_registry_for_tests
from brain.tui.app import FactoryBrainApp
from brain.tui.backend_client import BackendClient
from brain.tui.screens import DashboardScreen, WorkspaceScreen
from brain.workspace.active_project import get_active_project, select_active_project
from brain.workspace.discovery import discover_projects


@pytest.fixture(autouse=True)
def _clean_registry():
    _reset_registry_for_tests()
    yield
    _reset_registry_for_tests()


@pytest.fixture
def backend_client():
    # T-FB016-US01-06: DashboardScreen ahora consulta un backend real
    # (brain-api) en vez de invocar dominio directamente — se arranca un
    # backend de prueba real (mismo `create_app()` de producción) en un
    # hilo, mismo criterio de "test contra comportamiento real" ya
    # aplicado en el resto del proyecto (nunca se mockea la llamada HTTP).
    with running_backend() as base_url:
        yield BackendClient(base_url=base_url)


def _make_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()


async def test_workspace_screen_shows_discovered_projects(tmp_path) -> None:
    workspace_root = tmp_path / "workspace"
    _make_git_repo(workspace_root / "project-alpha")
    _make_git_repo(workspace_root / "project-beta")
    state_dir = tmp_path / "state"

    app = FactoryBrainApp(workspace_root=workspace_root, state_dir=state_dir)
    async with app.run_test() as pilot:
        screen = pilot.app.screen
        assert isinstance(screen, WorkspaceScreen)

        list_view = screen.query_one("#project-list")
        item_names = [item.children[0].content for item in list_view.children]
        assert set(str(name) for name in item_names) == {
            "project-alpha",
            "project-beta",
        }


async def test_selecting_a_project_persists_it_active_and_navigates_to_dashboard(
    tmp_path,
) -> None:
    workspace_root = tmp_path / "workspace"
    _make_git_repo(workspace_root / "project-alpha")
    state_dir = tmp_path / "state"

    app = FactoryBrainApp(workspace_root=workspace_root, state_dir=state_dir)
    async with app.run_test() as pilot:
        screen = pilot.app.screen
        list_view = screen.query_one("#project-list")
        list_view.focus()
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()

        active = get_active_project(state_dir=state_dir)
        assert active is not None
        assert active.name == "project-alpha"
        assert isinstance(pilot.app.screen, DashboardScreen)


async def test_workspace_screen_shows_clear_message_when_no_repos_discovered(
    tmp_path,
) -> None:
    workspace_root = tmp_path / "empty-workspace"
    workspace_root.mkdir()
    state_dir = tmp_path / "state"

    app = FactoryBrainApp(workspace_root=workspace_root, state_dir=state_dir)
    async with app.run_test() as pilot:
        screen = pilot.app.screen
        assert isinstance(screen, WorkspaceScreen)

        static_widgets = screen.query("Static")
        rendered_texts = [str(widget.content) for widget in static_widgets]
        assert any("no se ha descubierto" in text.lower() for text in rendered_texts)


async def test_workspace_screen_as_initial_screen_has_no_return_to_dashboard_button(
    tmp_path,
) -> None:
    # Al arrancar sin proyecto activo, Workspace es la única pantalla del
    # stack — no hay Dashboard al que volver, así que el botón no debe
    # aparecer (criterio de aceptación 5 de US-FB002-02 no aplica aquí).
    workspace_root = tmp_path / "workspace"
    _make_git_repo(workspace_root / "project-alpha")
    state_dir = tmp_path / "state"

    app = FactoryBrainApp(workspace_root=workspace_root, state_dir=state_dir)
    async with app.run_test() as pilot:
        screen = pilot.app.screen
        assert isinstance(screen, WorkspaceScreen)
        assert len(screen.query("#go-to-dashboard").nodes) == 0


async def test_returning_from_workspace_to_dashboard_without_selecting_a_project(
    tmp_path, backend_client
) -> None:
    # Criterio de aceptación 5 de US-FB002-02: "desde cualquier pantalla
    # (Workspace, Agentes), el desarrollador puede volver al Dashboard" —
    # aquí, llegando a Workspace desde el Dashboard (p. ej. para "cambiar
    # de proyecto") y arrepintiéndose sin seleccionar nada.
    workspace_root = tmp_path / "workspace"
    repo_path = workspace_root / "my-project"
    _make_git_repo(repo_path)
    state_dir = tmp_path / "state"

    discovered = discover_projects(workspace_root)
    select_active_project(discovered[0], discovered=discovered, state_dir=state_dir)

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend_client
    )
    async with app.run_test() as pilot:
        dashboard_screen = pilot.app.screen
        assert isinstance(dashboard_screen, DashboardScreen)

        await pilot.click("#go-to-workspace")
        await pilot.pause()
        assert isinstance(pilot.app.screen, WorkspaceScreen)

        await pilot.click("#go-to-dashboard")
        await pilot.pause()
        assert pilot.app.screen is dashboard_screen
