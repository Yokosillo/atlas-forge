import sys
from pathlib import Path

import pytest
from textual.widgets import Select

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
from backend_server import running_backend  # noqa: E402

from brain.agents import CRITIC_ROLE, DEVELOPER_ROLE
from brain.core.session_registry import (
    _reset_registry_for_tests,
    resolve_startup_session,
)
from brain.dashboard import list_available_agent_options
from brain.dispatcher.job_history_registry import (
    _reset_registry_for_tests as _reset_job_history_registry_for_tests,
)
from brain.runtime.agent_runtime_registry import (
    _reset_registry_for_tests as _reset_runtime_registry_for_tests,
)
from brain.tui.app import FactoryBrainApp
from brain.tui.backend_client import BackendClient
from brain.tui.screens import AgentsScreen, DashboardScreen
from brain.workspace.active_project import select_active_project
from brain.workspace.discovery import discover_projects


def _make_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()


@pytest.fixture(autouse=True)
def _reset_registries():
    # Singleton de proceso (FB-003/FB-004/FB-008) — se resetea antes/después
    # de cada test para no depender del orden de ejecución (mismo patrón
    # que test_session_registry.py / test_dashboard_screen.py).
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


@pytest.fixture
def backend(tmp_path: Path):
    # T-FB016-US01-06: AgentsScreen ahora consulta un backend real
    # (brain-api) en vez de invocar dominio directamente — se arranca un
    # backend de prueba real (mismo `create_app()` de producción) en un
    # hilo, mismo criterio de "test contra comportamiento real" ya
    # aplicado en el resto del proyecto (nunca se mockea la llamada HTTP;
    # el aislamiento del socket tmux ya lo gestiona `running_backend`).
    #
    # `workspace_root`/`state_dir` aislados en `tmp_path`
    # (T-FB016-US01-11): evita que el `_lifespan` real resuelva el
    # proyecto activo REAL del usuario en esta máquina — ver docstring
    # equivalente en `test_dashboard_screen.py`.
    with running_backend(
        workspace_root=tmp_path / "workspace", state_dir=tmp_path / "state"
    ) as base_url:
        yield BackendClient(base_url=base_url)


def _select_project_and_start_backend_session(workspace_root: Path, state_dir: Path):
    # Ver justificación completa en test_dashboard_screen.py: GET /session
    # solo consulta, nunca resuelve — se arranca aquí para que el backend
    # de prueba (mismo proceso Python que el test) tenga sesión activa
    # antes de que la TUI haga su primera petición.
    repo_path = workspace_root / "my-project"
    _make_git_repo(repo_path)
    discovered = discover_projects(workspace_root)
    select_active_project(discovered[0], discovered=discovered, state_dir=state_dir)
    resolve_startup_session(workspace_root=workspace_root, state_dir=state_dir)
    return discovered[0]


def _select_option(select_widget: Select, agent_role: str, runtime_type: str) -> None:
    select_widget.value = (agent_role, runtime_type)


async def test_choosing_developer_opencode_and_model_leaves_agent_operative(
    tmp_path, backend
) -> None:
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _select_project_and_start_backend_session(workspace_root, state_dir)

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        dashboard_screen = pilot.app.screen
        assert isinstance(dashboard_screen, DashboardScreen)

        agents_screen = AgentsScreen(
            workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
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

        agents = backend.get_agents()
        assert len(agents) == 1
        launched_agent = agents[0]
        assert launched_agent["role"] == DEVELOPER_ROLE

        agents_widget = agents_screen.query_one("#agents-list")
        assert launched_agent["name"] in str(agents_widget.content)

        # Reflejado también desde otro cliente (criterio de aceptación de
        # esta Task): consultado directamente por HTTP, sin pasar por la
        # pantalla que lo lanzó — no solo "el mismo `list_agents`" como
        # antes de la migración, ahora es literalmente otra conexión.
        agents_from_another_client = BackendClient(base_url=backend._base_url).get_agents()
        assert any(a["id"] == launched_agent["id"] for a in agents_from_another_client)

        # Reflejado después en el Dashboard.
        pilot.app.pop_screen()
        await pilot.pause()
        assert pilot.app.screen is dashboard_screen
        dashboard_agents_widget = dashboard_screen.query_one("#agents-list")
        assert launched_agent["name"] in str(dashboard_agents_widget.content)


async def test_invalid_combination_shows_clear_message_without_launching_anything(
    tmp_path, backend
) -> None:
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _select_project_and_start_backend_session(workspace_root, state_dir)

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        agents_screen = AgentsScreen(
            workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
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

        assert backend.get_agents() == []


async def test_launching_a_second_agent_works_on_same_session_without_leaving_screen(
    tmp_path, backend
) -> None:
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _select_project_and_start_backend_session(workspace_root, state_dir)

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        agents_screen = AgentsScreen(
            workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
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

        agents = backend.get_agents()
        assert {agent["role"] for agent in agents} == {DEVELOPER_ROLE, CRITIC_ROLE}


async def test_catalog_matches_list_available_agent_options(tmp_path, backend) -> None:
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _select_project_and_start_backend_session(workspace_root, state_dir)

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        agents_screen = AgentsScreen(
            workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
        )
        pilot.app.push_screen(agents_screen)
        await pilot.pause()

        select_widget = agents_screen.query_one("#agent-choice", Select)
        expected_keys = {
            (option.agent_role, option.runtime_type)
            for option in list_available_agent_options()
        }
        actual_keys = {value for _label, value in select_widget._options}
        assert actual_keys == expected_keys


async def test_stopping_an_agent_from_the_tui_is_reflected_via_the_api(
    tmp_path, backend
) -> None:
    """Criterio de aceptación explícito de T-FB016-US01-06: detener un
    agente desde la TUI (botón nuevo, `POST /agents/{agent_id}/stop`,
    T-FB016-US01-03) lo refleja como `stopped` también si se consulta
    desde la API — verificado aquí con OTRO `BackendClient` apuntando al
    mismo backend de prueba, simulando un cliente HTTP externo (`curl`,
    la app Android)."""
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _select_project_and_start_backend_session(workspace_root, state_dir)

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        agents_screen = AgentsScreen(
            workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
        )
        pilot.app.push_screen(agents_screen)
        await pilot.pause()

        select_widget = agents_screen.query_one("#agent-choice", Select)
        _select_option(select_widget, DEVELOPER_ROLE, "claude-code")
        await pilot.click("#launch-agent")
        await pilot.pause()

        agent = backend.get_agents()[0]
        assert agent["status"] != "stopped"

        stop_button_id = f"#stop-{agent['id']}"
        assert len(agents_screen.query(stop_button_id).nodes) == 1
        await pilot.click(stop_button_id)
        await pilot.pause()

        result_widget = agents_screen.query_one("#launch-result")
        assert "detenido" in str(result_widget.content).lower()

        # Ya no ofrece un botón "Detener" para un agente ya stopped.
        assert len(agents_screen.query(stop_button_id).nodes) == 0

        # Reflejado desde OTRO cliente de la API, no solo en esta pantalla.
        other_client = BackendClient(base_url=backend._base_url)
        agents_from_another_client = other_client.get_agents()
        stopped_agent = next(
            a for a in agents_from_another_client if a["id"] == agent["id"]
        )
        assert stopped_agent["status"] == "stopped"
