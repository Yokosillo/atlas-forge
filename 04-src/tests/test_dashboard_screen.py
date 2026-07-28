import uuid
from pathlib import Path

import libtmux
import pytest

from brain.agents import CRITIC_ROLE, DEVELOPER_ROLE
from brain.core.session_lifecycle import assign_agent
from brain.core.session_registry import _reset_registry_for_tests
from brain.dashboard import launch_agent
from brain.dispatcher.job_history_registry import (
    _reset_registry_for_tests as _reset_job_history_registry_for_tests,
)
from brain.models import Agent, Runtime
from brain.runtime import start_runtime, stop_runtime
from brain.runtime.agent_runtime_registry import (
    _reset_registry_for_tests as _reset_runtime_registry_for_tests,
)
from brain.runtime.agent_runtime_registry import register_runtime_instance_for_agent
from brain.tui.app import FactoryBrainApp
from brain.tui.screens import AgentsScreen, DashboardScreen, JobsScreen, WorkspaceScreen
from brain.workspace.active_project import select_active_project
from brain.workspace.discovery import discover_projects
from textual.widgets import Select, Static, TextArea

_COOPERATIVE_AGENT_SCRIPT = str(
    Path(__file__).parent / "fixtures" / "cooperative_agent_sim.sh"
)


@pytest.fixture
def isolated_socket():
    """Aísla los tests de esta Task en su propio servidor tmux (los
    agentes lanzados vía `launch_agent` crean sesiones tmux reales), con
    limpieza garantizada incluso si el test falla a medio camino — mismo
    patrón que test_launch_agent.py."""
    name = f"brain-test-{uuid.uuid4().hex[:8]}"
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


@pytest.fixture(autouse=True)
def _reset_session_registry():
    # La sesión de desarrollo es un singleton de proceso
    # (`_SessionRegistry`, FB-003) — se resetea antes y después de cada
    # test para que no dependan del orden de ejecución (mismo patrón que
    # test_session_registry.py).
    _reset_registry_for_tests()
    _reset_runtime_registry_for_tests()
    _reset_job_history_registry_for_tests()
    yield
    _reset_registry_for_tests()
    _reset_runtime_registry_for_tests()
    _reset_job_history_registry_for_tests()


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


def _select_project(workspace_root: Path, state_dir: Path):
    repo_path = workspace_root / "my-project"
    _make_git_repo(repo_path)
    discovered = discover_projects(workspace_root)
    select_active_project(discovered[0], discovered=discovered, state_dir=state_dir)
    return discovered[0]


def _launch_cooperative_agent(session, isolated_socket: str, tmp_path, extra_env: str = ""):
    # Doble cooperativo real (tmux real, nunca el binario real de Claude
    # Code/OpenCode) — mismo patrón ya usado en test_jobs_screen.py.
    runtime_id = f"test-runtime-{uuid.uuid4().hex[:8]}"
    agent = Agent(
        id=str(uuid.uuid4()),
        name="Developer",
        role="developer",
        prompt="p",
        runtime_id=runtime_id,
    )
    command = f"{extra_env} bash".strip()
    runtime = Runtime(
        id=runtime_id,
        name="Test Runtime",
        type="test",
        command=command,
        args=[_COOPERATIVE_AGENT_SCRIPT],
    )
    runtime_instance = start_runtime(
        runtime, agent, str(tmp_path), socket_name=isolated_socket
    )
    assign_agent(session, agent)
    register_runtime_instance_for_agent(agent.id, runtime_instance)
    return agent, runtime_instance


async def test_dashboard_shows_active_project_and_session_state(tmp_path) -> None:
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    project = _select_project(workspace_root, state_dir)

    app = FactoryBrainApp(workspace_root=workspace_root, state_dir=state_dir)
    async with app.run_test() as pilot:
        screen = pilot.app.screen
        assert isinstance(screen, DashboardScreen)

        project_widget = screen.query_one("#active-project")
        assert project.name in str(project_widget.content)

        session_widget = screen.query_one("#session-state")
        assert "active" in str(session_widget.content)

        agents_widget = screen.query_one("#agents-list")
        assert "ninguno" in str(agents_widget.content).lower()


async def test_dashboard_shows_launched_agents_with_status(
    tmp_path, isolated_socket
) -> None:
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    project = _select_project(workspace_root, state_dir)

    app = FactoryBrainApp(workspace_root=workspace_root, state_dir=state_dir)
    async with app.run_test() as pilot:
        screen = pilot.app.screen
        assert isinstance(screen, DashboardScreen)

        agent, _runtime_instance = launch_agent(
            DEVELOPER_ROLE,
            "claude-code",
            None,
            screen._session,
            project.path,
            socket_name=isolated_socket,
        )

        screen.refresh(recompose=True)
        await pilot.pause()

        agents_widget = screen.query_one("#agents-list")
        rendered = str(agents_widget.content)
        assert agent.name in rendered
        assert agent.status in rendered


async def test_navigating_to_agents_and_back_keeps_dashboard_updated(
    tmp_path, isolated_socket
) -> None:
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    project = _select_project(workspace_root, state_dir)

    app = FactoryBrainApp(workspace_root=workspace_root, state_dir=state_dir)
    async with app.run_test() as pilot:
        dashboard_screen = pilot.app.screen
        assert isinstance(dashboard_screen, DashboardScreen)

        await pilot.click("#go-to-agents")
        await pilot.pause()
        assert isinstance(pilot.app.screen, AgentsScreen)

        launch_agent(
            CRITIC_ROLE,
            "claude-code",
            None,
            dashboard_screen._session,
            project.path,
            socket_name=isolated_socket,
        )

        pilot.app.pop_screen()
        await pilot.pause()

        assert pilot.app.screen is dashboard_screen
        agents_widget = dashboard_screen.query_one("#agents-list")
        assert "critic" in str(agents_widget.content).lower()


async def test_going_back_to_workspace_allows_changing_active_project(
    tmp_path,
) -> None:
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _select_project(workspace_root, state_dir)

    app = FactoryBrainApp(workspace_root=workspace_root, state_dir=state_dir)
    async with app.run_test() as pilot:
        assert isinstance(pilot.app.screen, DashboardScreen)

        await pilot.click("#go-to-workspace")
        await pilot.pause()

        assert isinstance(pilot.app.screen, WorkspaceScreen)


async def test_dashboard_provides_dedicated_button_to_access_jobs(
    tmp_path,
) -> None:
    # Criterio de aceptación: "desde el Dashboard, el desarrollador
    # accede a Jobs con un botón dedicado".
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _select_project(workspace_root, state_dir)

    app = FactoryBrainApp(workspace_root=workspace_root, state_dir=state_dir)
    async with app.run_test() as pilot:
        assert isinstance(pilot.app.screen, DashboardScreen)

        await pilot.click("#go-to-jobs")
        await pilot.pause()

        assert isinstance(pilot.app.screen, JobsScreen)


async def test_returning_from_jobs_to_dashboard_keeps_session_state(
    isolated_socket: str, tmp_path
) -> None:
    # Criterio de aceptación: "desde Jobs, el desarrollador vuelve al
    # Dashboard sin perder el estado de la sesión".
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    project = _select_project(workspace_root, state_dir)

    app = FactoryBrainApp(workspace_root=workspace_root, state_dir=state_dir)
    async with app.run_test() as pilot:
        dashboard_screen = pilot.app.screen
        assert isinstance(dashboard_screen, DashboardScreen)
        session = dashboard_screen._session
        # `FactoryBrainApp` no expone `socket_name` en su constructor
        # (decisión deliberada de T-FB002-US02-04, para no ensuciar la
        # API pública de producción con un detalle de test) — se ajusta
        # directamente en la instancia ya construida para que la
        # navegación a Jobs use el socket aislado, no el real.
        dashboard_screen._socket_name = isolated_socket

        developer, dev_instance = _launch_cooperative_agent(
            session, isolated_socket, tmp_path, extra_env="SIM_DELAY=0.1"
        )

        await pilot.click("#go-to-jobs")
        await pilot.pause()
        jobs_screen = pilot.app.screen
        assert isinstance(jobs_screen, JobsScreen)

        await pilot.click("#go-to-dashboard")
        await pilot.pause()

        assert pilot.app.screen is dashboard_screen
        # El estado de la sesión (agentes lanzados) sigue reflejado.
        agents_widget = dashboard_screen.query_one("#agents-list")
        assert developer.name in str(agents_widget.content)

        stop_runtime(dev_instance, socket_name=isolated_socket)


async def test_dashboard_reflects_job_summary_after_returning_from_jobs(
    isolated_socket: str, tmp_path
) -> None:
    # Criterio de aceptación: "el Dashboard, tras volver de Jobs, refleja
    # cualquier cambio relevante" — se implementó como un resumen del
    # histórico de Jobs (conteo por estado).
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    project = _select_project(workspace_root, state_dir)

    app = FactoryBrainApp(workspace_root=workspace_root, state_dir=state_dir)
    async with app.run_test() as pilot:
        dashboard_screen = pilot.app.screen
        assert isinstance(dashboard_screen, DashboardScreen)
        session = dashboard_screen._session
        dashboard_screen._socket_name = isolated_socket

        developer, dev_instance = _launch_cooperative_agent(
            session, isolated_socket, tmp_path, extra_env="SIM_DELAY=0.1"
        )

        jobs_summary_before = str(
            dashboard_screen.query_one("#jobs-summary").content
        )
        assert "ninguno todavía" in jobs_summary_before.lower()

        await pilot.click("#go-to-jobs")
        await pilot.pause()
        jobs_screen = pilot.app.screen
        assert isinstance(jobs_screen, JobsScreen)

        jobs_screen.query_one("#job-description", TextArea).text = "a task"
        await pilot.click("#send-job")
        await pilot.pause()

        import asyncio

        for _ in range(50):
            status_text = str(jobs_screen.query_one("#job-status", Static).content)
            if "completado" in status_text.lower():
                break
            await asyncio.sleep(0.1)

        await pilot.click("#go-to-dashboard")
        await pilot.pause()

        assert pilot.app.screen is dashboard_screen
        jobs_summary_after = str(dashboard_screen.query_one("#jobs-summary").content)
        assert "1" in jobs_summary_after
        assert "completed" in jobs_summary_after.lower()

        stop_runtime(dev_instance, socket_name=isolated_socket)
