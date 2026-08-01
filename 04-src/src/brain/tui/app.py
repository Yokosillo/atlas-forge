"""Aplicación Textual de Factory Brain: app raíz y navegación entre
pantallas (Workspace ↔ Dashboard ↔ Agentes, US-FB002-02).

Flujo de arranque (`01-documentacion/05-tui.md`, "Flujo principal";
`01-documentacion/00-vision.md`): si no hay proyecto activo persistido
(o el persistido ya no es válido), arranca en Workspace; si lo hay,
arranca directamente en Dashboard — mismo criterio ya resuelto por
`resolve_startup_project` (FB-001), reutilizado aquí sin reimplementarlo.
"""

from pathlib import Path

from textual.app import App

from brain.tui.backend_client import BackendClient
from brain.tui.screens import DashboardScreen, WorkspaceScreen
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
        outcome = resolve_startup_project(
            workspace_root=self._workspace_root, state_dir=self._state_dir
        )
        if isinstance(outcome, ProjectRecovered):
            self.push_screen(
                DashboardScreen(
                    workspace_root=self._workspace_root,
                    state_dir=self._state_dir,
                    backend_client=self._backend,
                )
            )
        else:
            self.push_screen(
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
    FactoryBrainApp().run()
