import uuid
from pathlib import Path

import libtmux
import pytest

from brain.agents import CRITIC_ROLE, DEVELOPER_ROLE
from brain.core.session_lifecycle import list_agents
from brain.core.session_registry import _reset_registry_for_tests
from brain.dashboard import list_available_agent_options
from brain.tui.app import FactoryBrainApp
from brain.tui.screens import AgentsScreen, DashboardScreen
from brain.workspace.active_project import select_active_project
from brain.workspace.discovery import discover_projects
from textual.widgets import Select


def _make_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()


@pytest.fixture(autouse=True)
def _reset_session_registry():
    # Singleton de proceso (FB-003) — se resetea antes/después de cada
    # test para no depender del orden de ejecución (mismo patrón que
    # test_session_registry.py / test_dashboard_screen.py).
    _reset_registry_for_tests()
    yield
    _reset_registry_for_tests()


@pytest.fixture(autouse=True)
def _no_real_runtime(monkeypatch):
    """Sustituye los comandos reales de Claude Code/OpenCode por `sleep`
    para no invocar los binarios reales al lanzar agentes en los tests."""
    import brain.runtime.claude_code as claude_code_module
    import brain.runtime.opencode as opencode_module

    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_COMMAND", "sleep")
    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_ARGS", ["5"])
    monkeypatch.setattr(opencode_module, "DEFAULT_OPENCODE_COMMAND", "sleep")
    monkeypatch.setattr(opencode_module, "DEFAULT_OPENCODE_AUTONOMY_FLAG", "5")


@pytest.fixture
def isolated_socket():
    """Aísla los tests de esta Task en su propio servidor tmux (los
    agentes lanzados vía `launch_agent`/`confirm_launch` crean sesiones
    tmux reales), con limpieza garantizada incluso si el test falla a
    medio camino — mismo patrón que test_launch_agent.py /
    test_dashboard_screen.py."""
    name = f"brain-test-{uuid.uuid4().hex[:8]}"
    try:
        yield name
    finally:
        try:
            libtmux.Server(socket_name=name).kill()
        except Exception:
            pass


def _select_project(workspace_root: Path, state_dir: Path):
    repo_path = workspace_root / "my-project"
    _make_git_repo(repo_path)
    discovered = discover_projects(workspace_root)
    select_active_project(discovered[0], discovered=discovered, state_dir=state_dir)
    return discovered[0]


def _select_option(select_widget: Select, agent_role: str, runtime_type: str) -> None:
    select_widget.value = (agent_role, runtime_type)


async def test_choosing_developer_opencode_and_model_leaves_agent_operative(
    tmp_path, isolated_socket
) -> None:
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    project = _select_project(workspace_root, state_dir)

    app = FactoryBrainApp(workspace_root=workspace_root, state_dir=state_dir)
    async with app.run_test() as pilot:
        dashboard_screen = pilot.app.screen
        assert isinstance(dashboard_screen, DashboardScreen)

        agents_screen = AgentsScreen(
            workspace_root=workspace_root,
            state_dir=state_dir,
            project_path=project.path,
            socket_name=isolated_socket,
        )
        pilot.app.push_screen(agents_screen)
        await pilot.pause()

        select_widget = agents_screen.query_one("#agent-choice", Select)
        _select_option(select_widget, DEVELOPER_ROLE, "opencode")
        model_input = agents_screen.query_one("#model-input")
        model_input.value = "openrouter/some-model"

        await pilot.click("#launch-agent")
        await pilot.pause()

        result_widget = agents_screen.query_one("#launch-result")
        result_text = str(result_widget.content)
        assert "operativo" in result_text.lower()

        session = agents_screen._current_session()
        agents = list_agents(session)
        assert len(agents) == 1
        launched_agent = agents[0]
        assert launched_agent.role == DEVELOPER_ROLE

        agents_widget = agents_screen.query_one("#agents-list")
        assert launched_agent.name in str(agents_widget.content)

        # Reflejado después en el Dashboard (mismo `list_agents`, FB-003).
        pilot.app.pop_screen()
        await pilot.pause()
        assert pilot.app.screen is dashboard_screen
        dashboard_agents_widget = dashboard_screen.query_one("#agents-list")
        assert launched_agent.name in str(dashboard_agents_widget.content)


async def test_invalid_combination_shows_clear_message_without_launching_anything(
    tmp_path, isolated_socket
) -> None:
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    project = _select_project(workspace_root, state_dir)

    app = FactoryBrainApp(workspace_root=workspace_root, state_dir=state_dir)
    async with app.run_test() as pilot:
        agents_screen = AgentsScreen(
            workspace_root=workspace_root,
            state_dir=state_dir,
            project_path=project.path,
            socket_name=isolated_socket,
        )
        pilot.app.push_screen(agents_screen)
        await pilot.pause()

        select_widget = agents_screen.query_one("#agent-choice", Select)
        _select_option(select_widget, DEVELOPER_ROLE, "claude-code")
        model_input = agents_screen.query_one("#model-input")
        model_input.value = "some-model"

        await pilot.click("#launch-agent")
        await pilot.pause()

        result_widget = agents_screen.query_one("#launch-result")
        result_text = str(result_widget.content)
        assert "no se pudo lanzar" in result_text.lower()
        assert "modelo" in result_text.lower()

        session = agents_screen._current_session()
        assert list_agents(session) == []


async def test_launching_a_second_agent_works_on_same_session_without_leaving_screen(
    tmp_path, isolated_socket
) -> None:
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    project = _select_project(workspace_root, state_dir)

    app = FactoryBrainApp(workspace_root=workspace_root, state_dir=state_dir)
    async with app.run_test() as pilot:
        agents_screen = AgentsScreen(
            workspace_root=workspace_root,
            state_dir=state_dir,
            project_path=project.path,
            socket_name=isolated_socket,
        )
        pilot.app.push_screen(agents_screen)
        await pilot.pause()

        select_widget = agents_screen.query_one("#agent-choice", Select)

        _select_option(select_widget, DEVELOPER_ROLE, "claude-code")
        await pilot.click("#launch-agent")
        await pilot.pause()

        _select_option(select_widget, CRITIC_ROLE, "claude-code")
        await pilot.click("#launch-agent")
        await pilot.pause()

        assert pilot.app.screen is agents_screen

        session = agents_screen._current_session()
        agents = list_agents(session)
        assert {agent.role for agent in agents} == {DEVELOPER_ROLE, CRITIC_ROLE}


async def test_catalog_matches_list_available_agent_options(tmp_path) -> None:
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _select_project(workspace_root, state_dir)

    app = FactoryBrainApp(workspace_root=workspace_root, state_dir=state_dir)
    async with app.run_test() as pilot:
        agents_screen = AgentsScreen(workspace_root=workspace_root, state_dir=state_dir)
        pilot.app.push_screen(agents_screen)
        await pilot.pause()

        select_widget = agents_screen.query_one("#agent-choice", Select)
        expected_keys = {
            (option.agent_role, option.runtime_type)
            for option in list_available_agent_options()
        }
        actual_keys = {value for _label, value in select_widget._options}
        assert actual_keys == expected_keys
