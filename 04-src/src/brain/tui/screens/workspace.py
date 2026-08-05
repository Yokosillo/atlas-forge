"""Pantalla Workspace (T-FB002-US02-02): descubre los repositorios Git
disponibles y permite seleccionar uno como proyecto activo, reutilizando
`discover_projects`/`select_active_project` (FB-001 v1) sin
reimplementar esa lógica. Al seleccionar, navega automáticamente al
Dashboard (T-FB002-US02-03).

Si se llega aquí desde el Dashboard (`can_return_to_dashboard=True` — p.
ej. para "cambiar de proyecto" y luego arrepentirse), también se puede
volver sin seleccionar nada (criterio de aceptación 5 de US-FB002-02:
"desde cualquier pantalla... puede volver al Dashboard"). Si esta es la
pantalla inicial de la app (no hay proyecto activo todavía, arrancada
desde `FactoryBrainApp.on_mount`), no hay Dashboard al que volver, así
que ese botón no se muestra. No se infiere de `App.screen_stack`
(Textual mantiene ahí una pantalla `_default` de base incluso antes de
empujar la primera pantalla real de la app, lo que haría que la
inferencia fuera siempre `True`) — se recibe explícito de quien
construye la pantalla.

## Mensaje de onboarding (T-FB019-US01-06)

Paso 2 de la guía de primer arranque (conectar → elegir proyecto →
navegación operativa revelada, mismo criterio NNG ya aplicado en la app,
`T-FB017-US03-03`) — `can_return_to_dashboard` distingue el mensaje:
mismo indicador que ya usaba la pantalla para el botón "Volver al
Dashboard", reutilizado aquí porque describe exactamente la misma
distinción semántica (¿hay un contexto ya resuelto detrás, o es el hueco
real de "todavía no elegiste nada"?).

- `can_return_to_dashboard=False` (arranque inicial, contexto no
  resuelto): "No hay ningún proyecto activo. Elige uno de la lista para
  continuar." — comunica explícitamente el estado y qué falta, no solo
  la lista desnuda.
- `can_return_to_dashboard=True` (cambiar de proyecto desde el
  Dashboard, contexto YA resuelto): se mantiene el mensaje corto
  "Selecciona un proyecto:" — no hay ningún vacío que justificar aquí,
  el desarrollador ya tenía un proyecto activo y decidió cambiarlo por
  su cuenta; el mensaje de onboarding sonaría fuera de lugar ("no hay
  proyecto activo" sería falso en este momento)."""

from pathlib import Path

from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, ListItem, ListView, Static

from brain.tui.backend_client import BackendClient
from brain.tui.screens.dashboard import DashboardScreen
from brain.workspace.active_project import select_active_project
from brain.workspace.discovery import discover_projects


class WorkspaceScreen(Screen):
    """Descubre y permite seleccionar el proyecto activo."""

    def __init__(
        self,
        workspace_root: Path | None = None,
        state_dir: Path | None = None,
        can_return_to_dashboard: bool = False,
        backend_client: BackendClient | None = None,
    ) -> None:
        super().__init__()
        self._workspace_root = (
            workspace_root if workspace_root is not None else Path.cwd()
        )
        self._state_dir = state_dir
        self._can_return_to_dashboard = can_return_to_dashboard
        self._backend = backend_client if backend_client is not None else BackendClient()
        self._discovered = discover_projects(
            self._workspace_root, state_dir=self._state_dir
        )

    def compose(self):
        if not self._discovered:
            widgets = [
                Static(
                    "No se ha descubierto ningún repositorio Git en el "
                    f"workspace ('{self._workspace_root}')."
                )
            ]
        else:
            selection_message = (
                "Selecciona un proyecto:"
                if self._can_return_to_dashboard
                else "No hay ningún proyecto activo. Elige uno de la lista para continuar."
            )
            widgets = [
                Static(selection_message, id="project-selection-message"),
                ListView(
                    *[
                        ListItem(Static(project.name), id=f"project-{index}")
                        for index, project in enumerate(self._discovered)
                    ],
                    id="project-list",
                ),
            ]

        if self._can_return_to_dashboard:
            widgets.append(Button("Volver al Dashboard", id="go-to-dashboard"))

        yield Vertical(*widgets)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        index = event.list_view.index
        if index is None:
            return

        selected_project = self._discovered[index]
        select_active_project(
            selected_project,
            discovered=self._discovered,
            state_dir=self._state_dir,
        )
        self.app.push_screen(
            DashboardScreen(
                workspace_root=self._workspace_root,
                state_dir=self._state_dir,
                backend_client=self._backend,
            )
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "go-to-dashboard":
            self.app.pop_screen()
