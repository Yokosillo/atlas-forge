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

from brain.tui.screens import DashboardScreen, WorkspaceScreen
from brain.workspace.startup import ProjectRecovered, resolve_startup_project


class FactoryBrainApp(App):
    """App raíz de Factory Brain."""

    def __init__(
        self,
        workspace_root: Path | None = None,
        state_dir: Path | None = None,
    ) -> None:
        super().__init__()
        self._workspace_root = workspace_root
        self._state_dir = state_dir

    def on_mount(self) -> None:
        outcome = resolve_startup_project(
            workspace_root=self._workspace_root, state_dir=self._state_dir
        )
        if isinstance(outcome, ProjectRecovered):
            self.push_screen(
                DashboardScreen(
                    workspace_root=self._workspace_root, state_dir=self._state_dir
                )
            )
        else:
            self.push_screen(
                WorkspaceScreen(
                    workspace_root=self._workspace_root, state_dir=self._state_dir
                )
            )


def run() -> None:
    """Arranca la app. Reutilizada por el entrypoint de consola `brain`
    (T-FB002-US02-05) — no hay un entrypoint `brain-tui` separado, para
    no coexistir dos superficies de interfaz para lo mismo."""
    FactoryBrainApp().run()
