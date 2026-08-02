import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
from backend_server import running_backend  # noqa: E402

from brain.core.session_registry import _reset_registry_for_tests
from brain.tui import FactoryBrainApp
from brain.tui.backend_client import BackendClient, BackendUnavailableError
from brain.tui.screens import ConnectivityCheckScreen, DashboardScreen, WorkspaceScreen
from brain.workspace.active_project import select_active_project
from brain.workspace.discovery import discover_projects


def _make_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()


@pytest.fixture(autouse=True)
def _clean_registry():
    # T-FB019-US01-04: `on_mount` ahora arranca un backend real de prueba
    # en la mayoría de estos tests (antes no era necesario: ni Workspace
    # ni el propio arranque tocaban el backend) — mismo motivo que ya
    # documenta `test_workspace_screen.py::_clean_registry`.
    _reset_registry_for_tests()
    yield
    _reset_registry_for_tests()


@pytest.fixture
def backend():
    # T-FB019-US01-04: `FactoryBrainApp.on_mount` ahora empuja
    # `ConnectivityCheckScreen` antes de decidir Workspace/Dashboard — los
    # tests de arranque necesitan un backend real de prueba (mismo
    # criterio ya aplicado en el resto de la TUI, nunca se mockea la
    # llamada HTTP) para llegar más allá de esa pantalla.
    with running_backend() as base_url:
        yield BackendClient(base_url=base_url)


async def test_app_starts_on_workspace_screen_without_active_project(
    tmp_path, backend
) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    state_dir = tmp_path / "state"

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        assert isinstance(pilot.app.screen, WorkspaceScreen)


async def test_app_starts_on_dashboard_screen_with_valid_active_project(
    tmp_path, backend
) -> None:
    workspace_root = tmp_path / "workspace"
    repo_path = workspace_root / "my-project"
    _make_git_repo(repo_path)
    state_dir = tmp_path / "state"

    discovered = discover_projects(workspace_root)
    select_active_project(discovered[0], discovered=discovered, state_dir=state_dir)

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        assert isinstance(pilot.app.screen, DashboardScreen)


async def test_app_starts_on_workspace_screen_when_active_project_is_invalid(
    tmp_path, backend
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

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        assert isinstance(pilot.app.screen, WorkspaceScreen)


async def test_navigation_mechanism_can_push_and_pop_screens(tmp_path, backend) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    state_dir = tmp_path / "state"

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        assert isinstance(pilot.app.screen, WorkspaceScreen)

        pilot.app.push_screen(DashboardScreen())
        await pilot.pause()
        assert isinstance(pilot.app.screen, DashboardScreen)

        pilot.app.pop_screen()
        await pilot.pause()
        assert isinstance(pilot.app.screen, WorkspaceScreen)


class _AlwaysUnavailableBackendClient(BackendClient):
    """Doble mínimo: simula backend inalcanzable en cada llamada sin
    depender de que un puerto local esté de verdad cerrado (más rápido y
    determinista que apuntar a un puerto libre real y esperar el timeout
    de `requests`)."""

    def get_session(self) -> dict | None:
        raise BackendUnavailableError("backend no disponible (doble de prueba)")


async def test_starting_without_backend_shows_connectivity_message_before_workspace_or_dashboard(
    tmp_path,
) -> None:
    # Criterio de aceptación 1 de T-FB019-US01-04: "Arrancar la TUI sin
    # backend corriendo muestra el mensaje de conectividad ANTES de
    # cualquier intento de renderizar Workspace/Dashboard con datos
    # parciales."
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    state_dir = tmp_path / "state"

    app = FactoryBrainApp(
        workspace_root=workspace_root,
        state_dir=state_dir,
        backend_client=_AlwaysUnavailableBackendClient(),
    )
    async with app.run_test() as pilot:
        assert isinstance(pilot.app.screen, ConnectivityCheckScreen)
        assert not isinstance(pilot.app.screen, (WorkspaceScreen, DashboardScreen))

        error_widgets = pilot.app.screen.query("#connectivity-error")
        assert len(error_widgets.nodes) == 1
        assert "backend" in str(error_widgets.first().content).lower()

        assert len(pilot.app.screen.query("#retry-connectivity").nodes) == 1


async def test_starting_with_backend_available_follows_the_existing_flow_unchanged(
    tmp_path, backend
) -> None:
    # Criterio de aceptación 2: "Arrancar con backend disponible seguido
    # del flujo actual (Workspace o Dashboard según
    # `resolve_startup_project`) sin cambios de comportamiento" — mismo
    # escenario que `test_app_starts_on_dashboard_screen_with_valid_active_project`,
    # verificado explícitamente aquí como criterio propio de esta Task.
    workspace_root = tmp_path / "workspace"
    repo_path = workspace_root / "my-project"
    _make_git_repo(repo_path)
    state_dir = tmp_path / "state"

    discovered = discover_projects(workspace_root)
    select_active_project(discovered[0], discovered=discovered, state_dir=state_dir)

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        assert isinstance(pilot.app.screen, DashboardScreen)
        # La pantalla de conectividad no queda en el historial de
        # navegación (se usó `switch_screen`, no `push_screen`) — no hay
        # nada "a lo que volver" hacia ella.
        assert not any(
            isinstance(screen, ConnectivityCheckScreen) for screen in pilot.app.screen_stack
        )


class _FailsOnceBackendClient(BackendClient):
    """Doble que falla en la primera llamada a `get_session()` y
    responde con éxito (delegando en un `BackendClient` real) a partir de
    la segunda — simula "el backend tarda en levantar, pero ya está
    arriba cuando el desarrollador pulsa Reintentar" sin depender de
    temporización real de un proceso `uvicorn`."""

    def __init__(self, base_url: str) -> None:
        super().__init__(base_url=base_url)
        self._call_count = 0

    def get_session(self) -> dict | None:
        self._call_count += 1
        if self._call_count == 1:
            raise BackendUnavailableError("backend no disponible todavía (doble de prueba)")
        return super().get_session()


async def test_retrying_after_backend_becomes_available_navigates_without_restarting_the_tui(
    tmp_path, backend
) -> None:
    # Criterio de aceptación 3: "Reintentar tras arrancar el backend (sin
    # reiniciar la TUI) navega correctamente al siguiente paso."
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    state_dir = tmp_path / "state"

    flaky_backend = _FailsOnceBackendClient(base_url=backend._base_url)

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=flaky_backend
    )
    async with app.run_test() as pilot:
        assert isinstance(pilot.app.screen, ConnectivityCheckScreen)
        assert len(pilot.app.screen.query("#connectivity-error").nodes) == 1

        await pilot.click("#retry-connectivity")
        await pilot.pause()

        assert isinstance(pilot.app.screen, WorkspaceScreen)


async def test_full_onboarding_sequence_connect_then_choose_project_then_operational_nav(
    tmp_path,
) -> None:
    # T-FB019-US01-06: evidencia directa de la secuencia completa de
    # onboarding descrita en la Story (US-FB019-01, criterio de
    # aceptación 3) dentro de una única ejecución — paso 1 (conectar,
    # T-FB019-US01-04) → paso 2 (elegir proyecto, mensaje ampliado de
    # esta Task) → navegación operativa revelada sin pasos adicionales
    # (T-FB019-US01-05), en vez de tres tests desconectados que cubren
    # cada paso por separado.
    workspace_root = tmp_path / "workspace"
    repo_path = workspace_root / "my-project"
    repo_path.mkdir(parents=True)
    (repo_path / ".git").mkdir()
    state_dir = tmp_path / "state"

    with running_backend(
        workspace_root=workspace_root, state_dir=state_dir
    ) as base_url:
        # Mismo doble que `_FailsOnceBackendClient` (falla en la primera
        # llamada, delega en el backend real de prueba a partir de la
        # segunda) — apunta al backend YA arrancado desde el principio,
        # sin depender de temporización real de un proceso `uvicorn` ni
        # de un puerto falso que podría no fallar rápido de forma
        # determinista.
        flaky_backend = _FailsOnceBackendClient(base_url=base_url)

        app = FactoryBrainApp(
            workspace_root=workspace_root, state_dir=state_dir, backend_client=flaky_backend
        )
        async with app.run_test() as pilot:
            # Paso 1: sin backend, mensaje de conectividad con reintentar.
            assert isinstance(pilot.app.screen, ConnectivityCheckScreen)
            assert len(pilot.app.screen.query("#connectivity-error").nodes) == 1

            await pilot.click("#retry-connectivity")
            await pilot.pause()

            # Paso 2: backend disponible, pero sin proyecto activo — el
            # mensaje explica explícitamente qué falta.
            workspace_screen = pilot.app.screen
            assert isinstance(workspace_screen, WorkspaceScreen)
            message_widget = workspace_screen.query_one("#project-selection-message")
            assert "no hay ningún proyecto activo" in str(message_widget.content).lower()

            list_view = workspace_screen.query_one("#project-list")
            list_view.focus()
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

            # Paso 3: contexto resuelto — navegación operativa visible
            # sin ningún paso adicional.
            dashboard_screen = pilot.app.screen
            assert isinstance(dashboard_screen, DashboardScreen)
            for button_id in (
                "#go-to-agents",
                "#go-to-jobs",
                "#go-to-plan",
                "#go-to-scripts",
            ):
                assert len(dashboard_screen.query(button_id).nodes) == 1
            assert len(dashboard_screen.query("#no-active-project-guidance").nodes) == 0
