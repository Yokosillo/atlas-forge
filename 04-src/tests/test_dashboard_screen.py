import asyncio
import sys
from pathlib import Path

import pytest
from textual.widgets import Static, TextArea

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
from backend_server import running_backend  # noqa: E402

from brain.core.session_registry import (
    _reset_registry_for_tests,
    resolve_startup_session,
)
from brain.dispatcher.job_history_registry import (
    _reset_registry_for_tests as _reset_job_history_registry_for_tests,
)
from brain.runtime.agent_runtime_registry import (
    _reset_registry_for_tests as _reset_runtime_registry_for_tests,
)
from brain.tui.app import FactoryBrainApp
from brain.tui.backend_client import BackendClient
from brain.tui.screens import AgentsScreen, DashboardScreen, JobsScreen, WorkspaceScreen
from brain.workspace.active_project import select_active_project
from brain.workspace.discovery import discover_projects

_COOPERATIVE_AGENT_SCRIPT = str(
    Path(__file__).parent / "fixtures" / "cooperative_agent_sim.sh"
)


def _make_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()


@pytest.fixture(autouse=True)
def _reset_session_registry():
    # La sesión de desarrollo es un singleton de proceso del backend
    # (`_SessionRegistry`, FB-003) — se resetea antes y después de cada
    # test para que no dependan del orden de ejecución (mismo patrón que
    # test_session_registry.py). T-FB016-US01-06: sigue siendo el mismo
    # registro en memoria, ahora vive en el proceso `brain-api` de prueba
    # en vez de en el proceso de la TUI, pero es el mismo módulo Python
    # importado por ambos (`_reset_registry_for_tests` opera sobre el
    # estado del propio proceso de test, que es donde corre `create_app()`
    # también en `running_backend`).
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
    # T-FB016-US01-06: las 4 pantallas ahora consultan un backend real
    # (brain-api) en vez de invocar dominio directamente — se arranca un
    # backend de prueba real (mismo `create_app()` de producción) en un
    # hilo, mismo criterio de "test contra comportamiento real" ya
    # aplicado en el resto del proyecto (nunca se mockea la llamada HTTP).
    #
    # `workspace_root`/`state_dir` aislados en el propio `tmp_path` del
    # test (T-FB016-US01-11): sin esto, el `_lifespan` real de
    # `create_app()` resolvería el proyecto activo REAL persistido del
    # usuario en esta máquina (`~/.local/share/brain/`), no el proyecto
    # de prueba que cada test arma después — mismo `tmp_path` que
    # `_select_project_and_start_backend_session` usa más abajo, para que
    # ambos coincidan.
    with running_backend(
        workspace_root=tmp_path / "workspace", state_dir=tmp_path / "state"
    ) as base_url:
        yield BackendClient(base_url=base_url)


def _select_project(workspace_root: Path, state_dir: Path):
    repo_path = workspace_root / "my-project"
    _make_git_repo(repo_path)
    discovered = discover_projects(workspace_root)
    select_active_project(discovered[0], discovered=discovered, state_dir=state_dir)
    return discovered[0]


def _select_project_and_start_backend_session(workspace_root: Path, state_dir: Path):
    """Selecciona el proyecto activo (FB-001, disco) Y arranca la sesión
    de desarrollo (FB-003) del lado del BACKEND — no de la TUI.

    `GET /session` (T-FB016-US01-02) solo consulta `get_current_session()`,
    nunca la resuelve: un backend real (systemd, T-FB016-US01-09) arranca
    su sesión una única vez con su propio `workspace_root` fijo, no por
    cliente que se conecta. Aquí, backend de prueba y proceso de test
    comparten intérprete (`running_backend`, mismo módulo `brain.core.
    session_registry`), así que resolver la sesión aquí directamente
    equivale a "la sesión que el backend real ya tendría arrancada" antes
    de que la TUI (cliente) haga su primera petición — sin este paso,
    `GET /session`/`GET /agents` devolverían 404 indefinidamente en el
    test, un problema de orquestación del propio test, no del código de
    la TUI ni del backend."""
    project = _select_project(workspace_root, state_dir)
    resolve_startup_session(workspace_root=workspace_root, state_dir=state_dir)
    return project


async def test_dashboard_shows_active_project_and_session_state(tmp_path, backend) -> None:
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    project = _select_project_and_start_backend_session(workspace_root, state_dir)

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        screen = pilot.app.screen
        assert isinstance(screen, DashboardScreen)

        project_widget = screen.query_one("#active-project")
        assert project.name in str(project_widget.content)

        session_widget = screen.query_one("#session-state")
        assert "active" in str(session_widget.content)

        agents_widget = screen.query_one("#agents-list")
        assert "ninguno" in str(agents_widget.content).lower()


async def test_dashboard_shows_launched_agents_with_status(tmp_path, backend) -> None:
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _select_project_and_start_backend_session(workspace_root, state_dir)

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        screen = pilot.app.screen
        assert isinstance(screen, DashboardScreen)

        agent = backend.launch_agent("developer", "claude-code", None)

        screen.refresh(recompose=True)
        await pilot.pause()

        agents_widget = screen.query_one("#agents-list")
        rendered = str(agents_widget.content)
        assert agent["name"] in rendered
        assert agent["status"] in rendered


async def test_navigating_to_agents_and_back_keeps_dashboard_updated(
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

        await pilot.click("#go-to-agents")
        await pilot.pause()
        assert isinstance(pilot.app.screen, AgentsScreen)

        backend.launch_agent("critic", "claude-code", None)

        pilot.app.pop_screen()
        await pilot.pause()

        assert pilot.app.screen is dashboard_screen
        agents_widget = dashboard_screen.query_one("#agents-list")
        assert "critic" in str(agents_widget.content).lower()


async def test_going_back_to_workspace_allows_changing_active_project(
    tmp_path, backend
) -> None:
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _select_project_and_start_backend_session(workspace_root, state_dir)

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        assert isinstance(pilot.app.screen, DashboardScreen)

        await pilot.click("#go-to-workspace")
        await pilot.pause()

        assert isinstance(pilot.app.screen, WorkspaceScreen)


async def test_dashboard_provides_dedicated_button_to_access_jobs(tmp_path, backend) -> None:
    # Criterio de aceptación: "desde el Dashboard, el desarrollador
    # accede a Jobs con un botón dedicado".
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _select_project_and_start_backend_session(workspace_root, state_dir)

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        assert isinstance(pilot.app.screen, DashboardScreen)

        await pilot.click("#go-to-jobs")
        await pilot.pause()

        assert isinstance(pilot.app.screen, JobsScreen)


async def test_returning_from_jobs_to_dashboard_keeps_session_state(tmp_path, backend) -> None:
    # Criterio de aceptación: "desde Jobs, el desarrollador vuelve al
    # Dashboard sin perder el estado de la sesión".
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _select_project_and_start_backend_session(workspace_root, state_dir)

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        dashboard_screen = pilot.app.screen
        assert isinstance(dashboard_screen, DashboardScreen)

        agent = backend.launch_agent("developer", "claude-code", None)

        await pilot.click("#go-to-jobs")
        await pilot.pause()
        jobs_screen = pilot.app.screen
        assert isinstance(jobs_screen, JobsScreen)

        await pilot.click("#go-to-dashboard")
        await pilot.pause()

        assert pilot.app.screen is dashboard_screen
        # El estado de la sesión (agentes lanzados) sigue reflejado.
        agents_widget = dashboard_screen.query_one("#agents-list")
        assert agent["name"] in str(agents_widget.content)


async def test_dashboard_reflects_job_summary_after_returning_from_jobs(
    tmp_path, backend, monkeypatch
) -> None:
    # Criterio de aceptación: "el Dashboard, tras volver de Jobs, refleja
    # cualquier cambio relevante" — se implementó como un resumen del
    # histórico de Jobs (conteo por estado). Necesita que el Job termine
    # de verdad (completed) en un tiempo razonable de test — el doble
    # cooperativo real (`cooperative_agent_sim.sh`), no `sleep` (que nunca
    # escribe el fichero de reporte y haría que dispatch_job agote su
    # timeout de 30s).
    import brain.runtime.claude_code as claude_code_module

    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_COMMAND", "bash")
    monkeypatch.setattr(
        claude_code_module, "DEFAULT_CLAUDE_CODE_ARGS", [_COOPERATIVE_AGENT_SCRIPT]
    )

    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _select_project_and_start_backend_session(workspace_root, state_dir)

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        dashboard_screen = pilot.app.screen
        assert isinstance(dashboard_screen, DashboardScreen)

        backend.launch_agent("developer", "claude-code", None)

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
