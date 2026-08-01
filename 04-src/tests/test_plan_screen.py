import functools
import sys
from pathlib import Path

import pytest
from textual.widgets import Static

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
from backend_server import running_backend  # noqa: E402

from brain.api.plan_registry import _reset_registry_for_tests as _reset_plan_registry
from brain.core.session_registry import (
    _reset_registry_for_tests,
    resolve_startup_session,
)
from brain.dispatcher.job_history_registry import (
    _reset_registry_for_tests as _reset_job_history_registry_for_tests,
)
from brain.dispatcher.job_plan_builder import build_job_plan_for_story
from brain.runtime.agent_runtime_registry import (
    _reset_registry_for_tests as _reset_runtime_registry_for_tests,
)
from brain.tui.app import FactoryBrainApp
from brain.tui.backend_client import BackendClient
from brain.tui.screens import PlanScreen
from brain.workspace.active_project import select_active_project
from brain.workspace.discovery import discover_projects

_COOPERATIVE_AGENT_SCRIPT = str(
    Path(__file__).parent / "fixtures" / "cooperative_agent_sim.sh"
)


@pytest.fixture(autouse=True)
def _reset_registries():
    _reset_registry_for_tests()
    _reset_runtime_registry_for_tests()
    _reset_job_history_registry_for_tests()
    _reset_plan_registry()
    yield
    _reset_registry_for_tests()
    _reset_runtime_registry_for_tests()
    _reset_job_history_registry_for_tests()
    _reset_plan_registry()


@pytest.fixture(autouse=True)
def _no_real_runtime(monkeypatch):
    import brain.runtime.claude_code as claude_code_module
    import brain.runtime.opencode as opencode_module

    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_COMMAND", "sleep")
    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_ARGS", ["5"])
    monkeypatch.setattr(opencode_module, "DEFAULT_OPENCODE_COMMAND", "sleep")
    monkeypatch.setattr(opencode_module, "DEFAULT_OPENCODE_AUTONOMY_FLAG", "5")


@pytest.fixture
def backend(tmp_path: Path):
    with running_backend(
        workspace_root=tmp_path / "workspace", state_dir=tmp_path / "state"
    ) as base_url:
        yield BackendClient(base_url=base_url)


def _make_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()


def _select_project_and_start_backend_session(workspace_root: Path, state_dir: Path):
    repo_path = workspace_root / "my-project"
    _make_git_repo(repo_path)
    discovered = discover_projects(workspace_root)
    select_active_project(discovered[0], discovered=discovered, state_dir=state_dir)
    resolve_startup_session(workspace_root=workspace_root, state_dir=state_dir)
    return discovered[0]


def _write_task(
    tasks_dir: Path, story_id: str, correlative: str, slug: str, title: str, body: str
) -> None:
    content = (
        f"# T-{story_id}-{correlative}-{slug} · {title}\n\n"
        f"**User Story:** {story_id}\n\n"
        "## Descripción\n\n"
        f"{body}\n\n"
        "## Estado\n\n"
        "TODO\n"
    )
    (tasks_dir / f"T-{story_id}-{correlative}-{slug}.md").write_text(
        content, encoding="utf-8"
    )


def _isolated_backlog(tmp_path: Path, monkeypatch, story_id: str = "FB999-US01") -> None:
    """Mismo patrón ya usado en `test_api_routes_plans.py`: aísla `POST
    /plans` de un `tasks_dir` de prueba, en vez del backlog real del
    producto."""
    import brain.api.routes as routes_module

    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(exist_ok=True)
    _write_task(
        tasks_dir,
        story_id,
        "01",
        "paso-agente",
        "Implementar la funcionalidad",
        body="Requiere criterio de diseño e implementación real.",
    )
    monkeypatch.setattr(
        routes_module,
        "build_job_plan_for_story",
        functools.partial(build_job_plan_for_story, tasks_dir=tasks_dir),
    )


def _launch_cooperative_developer(backend: BackendClient, monkeypatch, extra_env: str = ""):
    import brain.runtime.claude_code as claude_code_module

    monkeypatch.setattr(
        claude_code_module, "DEFAULT_CLAUDE_CODE_COMMAND", f"{extra_env} bash".strip()
    )
    monkeypatch.setattr(
        claude_code_module, "DEFAULT_CLAUDE_CODE_ARGS", [_COOPERATIVE_AGENT_SCRIPT]
    )
    return backend.launch_agent("developer", "claude-code", None)


async def test_pending_plan_is_visible_with_its_steps_and_status(
    tmp_path, backend, monkeypatch
) -> None:
    # Criterio de aceptación: "Un plan propuesto por el Critic es visible
    # desde la TUI con sus pasos y estados."
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _select_project_and_start_backend_session(workspace_root, state_dir)
    _isolated_backlog(tmp_path, monkeypatch)

    # `POST /plans` vía el mismo backend real de prueba usado por la TUI
    # (BackendClient de la TUI no tiene `request_plan`/`POST /plans` en su
    # superficie — no lo necesita ninguna pantalla existente, se usa
    # `requests` directo aquí solo para preparar el escenario del test).
    _create_plan_via_backend(backend, "FB999-US01")

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        plan_screen = PlanScreen(
            workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
        )
        pilot.app.push_screen(plan_screen)
        await pilot.pause()

        details_text = str(plan_screen.query_one("#plan-details", Static).content)
        assert "FB999-US01" in details_text
        assert "proposed" in details_text.lower()
        assert "Paso 1" in details_text

        assert len(plan_screen.query("#approve-plan").nodes) == 1
        assert len(plan_screen.query("#reject-plan").nodes) == 1


def _create_plan_via_backend(backend: BackendClient, goal: str) -> dict:
    import requests

    response = requests.post(f"{backend._base_url}/plans", json={"goal": goal}, timeout=10)
    response.raise_for_status()
    return response.json()


async def test_no_pending_plan_shows_explicit_message(tmp_path, backend) -> None:
    # Criterio de aceptación: "Sin plan pendiente, la pantalla lo indica
    # explícitamente, sin error ni pantalla en blanco."
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _select_project_and_start_backend_session(workspace_root, state_dir)

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        plan_screen = PlanScreen(
            workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
        )
        pilot.app.push_screen(plan_screen)
        await pilot.pause()

        message_widgets = plan_screen.query("#no-pending-plan")
        assert len(message_widgets.nodes) == 1
        assert "no hay ningún plan pendiente" in str(message_widgets.first().content).lower()

        assert len(plan_screen.query("#approve-plan").nodes) == 0
        assert len(plan_screen.query("#reject-plan").nodes) == 0


async def test_approving_from_the_tui_dispatches_the_plan_and_get_plan_reflects_it(
    tmp_path, backend, monkeypatch
) -> None:
    # Criterio de aceptación: "Aprobar/rechazar desde la TUI tiene el
    # mismo efecto que desde la app (verificado consultando GET
    # /plans/{id} desde otro cliente tras la acción)" — aquí "otro
    # cliente" es una segunda instancia de BackendClient apuntando al
    # mismo backend de prueba, exactamente el escenario real de "la app y
    # la TUI comparten el mismo backend-api".
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _select_project_and_start_backend_session(workspace_root, state_dir)
    _isolated_backlog(tmp_path, monkeypatch)
    _launch_cooperative_developer(backend, monkeypatch, extra_env="SIM_DELAY=0.1")

    plan = _create_plan_via_backend(backend, "FB999-US01")

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        plan_screen = PlanScreen(
            workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
        )
        pilot.app.push_screen(plan_screen)
        await pilot.pause()

        await pilot.click("#approve-plan")
        await pilot.pause()

        import asyncio

        # "Otro cliente": una segunda instancia de BackendClient contra el
        # mismo backend de prueba, sin pasar por la instancia de la TUI —
        # se consulta el estado REAL del backend (no el texto de la UI,
        # que depende de que `call_from_thread` ya haya recompuesto el
        # widget) hasta que el plan deje de estar `approved` con un paso
        # todavía `running` (POST /plans/{id}/approve es bloqueante: en
        # cuanto el worker de hilo de la TUI reciba su respuesta, el
        # despacho real ya terminó del lado del backend).
        other_client = BackendClient(base_url=backend._base_url)
        fetched = other_client.get_plan(plan["plan_id"])
        deadline = asyncio.get_event_loop().time() + 20.0
        while fetched["steps"][0]["status"] == "running" and asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.1)
            fetched = other_client.get_plan(plan["plan_id"])

        assert fetched["status"] == "approved"
        assert fetched["steps"][0]["status"] == "completed"


async def test_rejecting_from_the_tui_reflects_via_get_plan(
    tmp_path, backend, monkeypatch
) -> None:
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _select_project_and_start_backend_session(workspace_root, state_dir)
    _isolated_backlog(tmp_path, monkeypatch)

    plan = _create_plan_via_backend(backend, "FB999-US01")

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        plan_screen = PlanScreen(
            workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
        )
        pilot.app.push_screen(plan_screen)
        await pilot.pause()

        await pilot.click("#reject-plan")
        await pilot.pause()

        other_client = BackendClient(base_url=backend._base_url)
        fetched = other_client.get_plan(plan["plan_id"])
        assert fetched["status"] == "rejected"


async def test_navigating_from_dashboard_to_plan_screen(tmp_path, backend) -> None:
    # Criterio de aceptación de la Descripción: "Añadir la navegación a
    # esta pantalla desde el DashboardScreen, junto a las demás."
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _select_project_and_start_backend_session(workspace_root, state_dir)

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        await pilot.pause()

        await pilot.click("#go-to-plan")
        await pilot.pause()

        assert isinstance(pilot.app.screen, PlanScreen)
