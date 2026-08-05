import asyncio
import sys
import threading
from pathlib import Path

import pytest
from textual.widgets import Button, Select

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
from backend_server import running_backend  # noqa: E402

from brain.agents import ARQUITECTO_ROLE, DEVELOPER_ROLE
from brain.core.session_registry import (
    _reset_registry_for_tests,
    resolve_startup_session,
)
from brain.tui.screens.agents import _eligible_agent_options
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

_COOPERATIVE_AGENT_SCRIPT = str(
    Path(__file__).parent / "fixtures" / "cooperative_agent_sim.sh"
)


def _launch_cooperative_agent(
    backend: BackendClient,
    monkeypatch,
    extra_env: str = "",
    role: str = "developer",
) -> dict:
    # Mismo patrón que `test_jobs_screen.py::_launch_cooperative_agent`:
    # doble cooperativo real (tmux real) en vez del binario real de
    # Claude Code, lanzado a través de `POST /agents` para que el agente
    # exista de verdad en el registro que la TUI consulta vía HTTP.
    import brain.runtime.claude_code as claude_code_module

    monkeypatch.setattr(
        claude_code_module, "DEFAULT_CLAUDE_CODE_COMMAND", f"{extra_env} bash".strip()
    )
    monkeypatch.setattr(
        claude_code_module, "DEFAULT_CLAUDE_CODE_ARGS", [_COOPERATIVE_AGENT_SCRIPT]
    )
    return backend.launch_agent(role, "claude-code", None)


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

        _select_option(select_widget, ARQUITECTO_ROLE, "claude-code")
        await pilot.click("#launch-agent")
        await pilot.pause()

        assert pilot.app.screen is agents_screen

        agents = backend.get_agents()
        assert {agent["role"] for agent in agents} == {DEVELOPER_ROLE, ARQUITECTO_ROLE}


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
            for option in _eligible_agent_options()
        }
        actual_keys = {value for _label, value in select_widget._options}
        assert actual_keys == expected_keys
        # T-FB016-US01-19: la opción Critic + OpenCode ya no se ofrece en la
        # TUI (mismo criterio de producto que `GET /agents/options`).
        assert ("critic", "opencode") not in actual_keys


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

        import asyncio

        # T-FB019-US01-03: "Detener" pide confirmación (patrón de
        # "segunda pulsación") — primer clic pide confirmar, segundo clic
        # detiene de verdad.
        await pilot.click(stop_button_id)
        await pilot.pause()
        await asyncio.sleep(0.25)
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


async def test_stop_confirmation_and_a_single_click_does_not_stop_anything(
    tmp_path, backend
) -> None:
    # Criterios de aceptación de T-FB019-US01-03: "Detener un agente desde
    # la TUI pide confirmación antes de ejecutar la acción real" y
    # "Cancelar la confirmación no ejecuta ninguna llamada al backend" —
    # aquí "cancelar" es simplemente no dar el segundo clic.
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
        stop_button_id = f"#stop-{agent['id']}"

        await pilot.click(stop_button_id)
        await pilot.pause()

        stop_button = agents_screen.query_one(stop_button_id, Button)
        assert "seguro" in str(stop_button.label).lower()

        # Ningún clic de confirmación llegó a darse: el agente sigue tal
        # cual estaba, verificado desde OTRO cliente de la API (no solo
        # inferido del estado de la pantalla).
        other_client = BackendClient(base_url=backend._base_url)
        unchanged_agent = next(
            a for a in other_client.get_agents() if a["id"] == agent["id"]
        )
        assert unchanged_agent["status"] != "stopped"


async def test_stop_confirmation_warns_when_agent_has_a_running_job(
    tmp_path, backend, monkeypatch
) -> None:
    # Criterio de aceptación: "Si el agente tiene un Job en curso, la
    # confirmación lo advierte explícitamente" — mismo criterio ya
    # validado en la app Android (`agentsWithRunningJob`,
    # T-FB017-US04-01), replicado aquí derivado de `GET /jobs`.
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _select_project_and_start_backend_session(workspace_root, state_dir)

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        agent = _launch_cooperative_agent(backend, monkeypatch, extra_env="SIM_DELAY=10")

        agents_screen = AgentsScreen(
            workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
        )
        pilot.app.push_screen(agents_screen)
        await pilot.pause()

        def _dispatch_slow_job():
            backend.create_and_dispatch_job(agent["id"], "a running task")

        thread = threading.Thread(target=_dispatch_slow_job, daemon=True)
        thread.start()

        # Espera activa a que el Job "running" aparezca en `GET /jobs`
        # antes de pulsar "Detener" — igual que el mecanismo de
        # localización ya usado en `test_jobs_screen.py`.
        deadline = asyncio.get_event_loop().time() + 5.0
        while asyncio.get_event_loop().time() < deadline:
            jobs = backend.get_jobs()
            if any(
                job["description"] == "a running task" and job["status"] == "running"
                for job in jobs
            ):
                break
            await asyncio.sleep(0.05)

        stop_button_id = f"#stop-{agent['id']}"
        await pilot.click(stop_button_id)
        await pilot.pause()

        stop_button = agents_screen.query_one(stop_button_id, Button)
        label_text = str(stop_button.label).lower()
        assert "seguro" in label_text
        assert "job en curso" in label_text or "tarea en curso" in label_text

        thread.join(timeout=15.0)
