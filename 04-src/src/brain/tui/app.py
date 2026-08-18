"""Aplicación Textual de Factory Brain: app raíz y navegación entre
pantallas (Workspace ↔ Dashboard ↔ Agentes, US-FB002-02).

Flujo de arranque (`docs/interfaces-tui.md`, "Flujo principal";
`docs/index.md`): si no hay proyecto activo persistido
(o el persistido ya no es válido), arranca en Workspace; si lo hay,
arranca directamente en Dashboard — mismo criterio ya resuelto por
`resolve_startup_project` (FB-001), reutilizado aquí sin reimplementarlo.

T-FB019-US01-04: antes de decidir Workspace vs. Dashboard, `on_mount`
empuja primero `ConnectivityCheckScreen` — ver docstring de ese módulo
para el porqué. Solo cuando la conexión con el backend se confirma
(`on_connected`, invocado por la propia pantalla) se resuelve
`resolve_startup_project` y se reemplaza la pantalla de conectividad por
Workspace/Dashboard (`switch_screen`, no `push_screen`: la comprobación
de conectividad no debe quedar en el historial de navegación al que se
pueda "volver atrás")."""

import sys
from pathlib import Path

from textual.app import App

from brain.system_preferences import get_tui_enabled
from brain.tui.backend_client import BackendClient
from brain.tui.screens import ConnectivityCheckScreen, DashboardScreen, WorkspaceScreen
from brain.workspace.startup import ProjectRecovered, resolve_startup_project


class FactoryBrainApp(App):
    """App raíz de Factory Brain."""

    def __init__(
        self,
        workspace_root: Path | None = None,
        state_dir: Path | None = None,
        backend_client: BackendClient | None = None,
    ) -> None:
        super().__init__()
        self._workspace_root = workspace_root
        self._state_dir = state_dir
        # T-FB016-US01-06: expuesto en el constructor (a diferencia de
        # `socket_name` en su momento, deliberadamente no expuesto,
        # T-FB002-US02-04) porque `DashboardScreen` lo necesita YA dentro
        # de su primer `compose()` — inyectarlo después de construir la
        # pantalla (como se hacía con `socket_name`, que solo se usaba al
        # pulsar un botón) llegaría demasiado tarde para el primer render.
        self._backend = backend_client if backend_client is not None else BackendClient()

    def on_mount(self) -> None:
        self.push_screen(
            ConnectivityCheckScreen(
                on_connected=self._navigate_to_startup_screen,
                workspace_root=self._workspace_root,
                state_dir=self._state_dir,
                backend_client=self._backend,
            )
        )

    def _navigate_to_startup_screen(self) -> None:
        outcome = resolve_startup_project(
            workspace_root=self._workspace_root, state_dir=self._state_dir
        )
        if isinstance(outcome, ProjectRecovered):
            self.switch_screen(
                DashboardScreen(
                    workspace_root=self._workspace_root,
                    state_dir=self._state_dir,
                    backend_client=self._backend,
                )
            )
        else:
            self.switch_screen(
                WorkspaceScreen(
                    workspace_root=self._workspace_root,
                    state_dir=self._state_dir,
                    backend_client=self._backend,
                )
            )


def run() -> None:
    """Arranca la app. Reutilizada por el entrypoint de consola `brain`
    (T-FB002-US02-05) — no hay un entrypoint `brain-tui` separado, para
    no coexistir dos superficies de interfaz para lo mismo."""
    if not get_tui_enabled():
        print("TUI bloqueada por política de seguridad: superficie sin mantenimiento activo.")
        print("Para reactivarla, use: PUT /system/preferences con tui_enabled: true")
        sys.exit(1)
    FactoryBrainApp().run()
