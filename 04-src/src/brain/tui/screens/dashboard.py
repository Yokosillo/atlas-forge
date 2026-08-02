"""Pantalla Dashboard (T-FB002-US02-03): centro de navegación de la TUI.
Muestra el proyecto activo, el estado de la sesión de desarrollo actual y
los agentes lanzados en ella con su estado, y da acceso a Agentes/Jobs y
a Workspace para cambiar de proyecto activo.

T-FB016-US01-06: deja de invocar directamente
`brain.core.session_registry`/`brain.dispatcher.*` — sesión, agentes y
resumen de Jobs se consultan vía `BackendClient` (`GET /session`, `GET
/agents`, `GET /jobs`), el mismo backend que la app Android. `get_active_project`
(FB-001, `brain.workspace.active_project`) sigue siendo local — no está en
la lista de módulos prohibidos por el criterio de aceptación de esa Task,
y es configuración de disco del propio cliente, no estado compartido
entre procesos (ver `brain.tui.backend_client` para la justificación
completa).

## Navegación condicionada al contexto resuelto (T-FB019-US01-05)

"Contexto resuelto" para esta pantalla = backend conectado (ya
garantizado ANTES de llegar aquí por `ConnectivityCheckScreen`,
T-FB019-US01-04 — `DashboardScreen` nunca se construye sin haber pasado
esa comprobación) + proyecto activo existente (`get_active_project`, ya
consultado en `_refresh_state`).

Camino real verificado: hoy `DashboardScreen` solo se construye desde dos
sitios (`grep -rn "DashboardScreen(" brain/`) — `FactoryBrainApp._navigate_to_startup_screen`,
solo alcanzable cuando `resolve_startup_project` devuelve
`ProjectRecovered` (proyecto ya validado), y
`WorkspaceScreen.on_list_view_selected`, justo después de
`select_active_project`. En ambos casos el proyecto activo YA está
garantizado por construcción antes de llegar aquí — no existe hoy ningún
camino real de producto que aterrice en `DashboardScreen` sin proyecto
activo. La condicionalidad de abajo es defensiva (documentada como tal,
no un caso que se pueda disparar hoy desde la navegación real) y deja
preparado el hueco que llenará `T-FB019-US01-06` (guía de "elige un
proyecto" en vez de nada) si en el futuro se abre otro camino hacia esta
pantalla."""

from pathlib import Path

from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Static

from brain.tui.backend_client import BackendClient, BackendUnavailableError
from brain.workspace.active_project import get_active_project


class DashboardScreen(Screen):
    """Centro de navegación: proyecto activo, estado de sesión, agentes."""

    def __init__(
        self,
        workspace_root: Path | None = None,
        state_dir: Path | None = None,
        backend_client: BackendClient | None = None,
    ) -> None:
        super().__init__()
        self._workspace_root = workspace_root
        self._state_dir = state_dir
        self._backend = backend_client if backend_client is not None else BackendClient()

    def _refresh_state(self) -> None:
        self._project = get_active_project(state_dir=self._state_dir)
        try:
            self._session = self._backend.get_session()
            self._agents = self._backend.get_agents()
            self._jobs = self._backend.get_jobs()
            self._backend_error = None
        except BackendUnavailableError as error:
            self._session = None
            self._agents = []
            self._jobs = []
            self._backend_error = str(error)

    def compose(self):
        self._refresh_state()

        if self._backend_error is not None:
            yield Vertical(
                Static(
                    f"No se pudo contactar con el backend: {self._backend_error}",
                    id="backend-error",
                ),
                Button("Reintentar", id="retry-backend"),
            )
            return

        project_line = (
            f"Proyecto activo: {self._project.name} ({self._project.path})"
            if self._project is not None
            else "Proyecto activo: ninguno"
        )
        session_line = (
            f"Sesión: {self._session['id']} ({self._session['status']})"
            if self._session is not None
            else "Sesión: ninguna"
        )

        if self._agents:
            agents_lines = [
                f"  - {agent['name']} ({agent['role']}): {agent['status']}"
                for agent in self._agents
            ]
            agents_block = "\n".join(["Agentes lanzados:", *agents_lines])
        else:
            agents_block = "Agentes lanzados: ninguno"

        if self._jobs:
            # Resumen mínimo (conteo por estado), no supervisión completa
            # de Jobs — el histórico detallado vive en la propia pantalla
            # Jobs (T-FB002-US03-03), no se duplica aquí.
            counts_by_status: dict[str, int] = {}
            for job in self._jobs:
                counts_by_status[job["status"]] = counts_by_status.get(job["status"], 0) + 1
            counts_text = ", ".join(
                f"{status}: {count}" for status, count in sorted(counts_by_status.items())
            )
            jobs_line = f"Jobs de la sesión: {len(self._jobs)} ({counts_text})"
        else:
            jobs_line = "Jobs de la sesión: ninguno todavía"

        widgets = [
            Static(project_line, id="active-project"),
            Static(session_line, id="session-state"),
            Static(agents_block, id="agents-list"),
            Static(jobs_line, id="jobs-summary"),
        ]

        # T-FB019-US01-05: la navegación operativa (Agentes/Jobs/Plan/
        # Scripts) requiere contexto resuelto — proyecto activo, además
        # del backend ya garantizado por `ConnectivityCheckScreen` antes
        # de llegar aquí. No hay hoy ningún camino real de producto que
        # aterrice en esta pantalla sin proyecto activo (ver docstring de
        # módulo) — esta rama es defensiva, y el hueco que llena
        # (T-FB019-US01-06) es la guía real de qué falta.
        if self._project is None:
            widgets.append(
                Static(
                    "Sin proyecto activo: elige uno desde Workspace antes de "
                    "acceder a Agentes, Jobs, Plan o Scripts.",
                    id="no-active-project-guidance",
                )
            )
        else:
            widgets.extend(
                [
                    Button("Ver Agentes", id="go-to-agents"),
                    Button("Ver Jobs", id="go-to-jobs"),
                    Button("Ver Plan", id="go-to-plan"),
                    Button("Ver Scripts", id="go-to-scripts"),
                ]
            )

        widgets.append(Button("Cambiar de proyecto (Workspace)", id="go-to-workspace"))

        yield Vertical(*widgets)

    def on_screen_resume(self) -> None:
        # Al volver de Agentes (tras lanzar un agente nuevo) hay que
        # recomponer para reflejar el estado actualizado (criterio de
        # aceptación: "Navegar a Agentes y volver... mantiene la
        # información actualizada").
        self.refresh(recompose=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        from brain.tui.screens.agents import AgentsScreen
        from brain.tui.screens.jobs import JobsScreen
        from brain.tui.screens.plan import PlanScreen
        from brain.tui.screens.scripts import ScriptsScreen
        from brain.tui.screens.workspace import WorkspaceScreen

        if event.button.id == "retry-backend":
            self.refresh(recompose=True)
        elif event.button.id == "go-to-agents":
            self.app.push_screen(
                AgentsScreen(
                    workspace_root=self._workspace_root,
                    state_dir=self._state_dir,
                    backend_client=self._backend,
                )
            )
        elif event.button.id == "go-to-jobs":
            self.app.push_screen(
                JobsScreen(
                    workspace_root=self._workspace_root,
                    state_dir=self._state_dir,
                    backend_client=self._backend,
                )
            )
        elif event.button.id == "go-to-plan":
            self.app.push_screen(
                PlanScreen(
                    workspace_root=self._workspace_root,
                    state_dir=self._state_dir,
                    backend_client=self._backend,
                )
            )
        elif event.button.id == "go-to-scripts":
            self.app.push_screen(
                ScriptsScreen(
                    workspace_root=self._workspace_root,
                    state_dir=self._state_dir,
                    backend_client=self._backend,
                )
            )
        elif event.button.id == "go-to-workspace":
            self.app.push_screen(
                WorkspaceScreen(
                    workspace_root=self._workspace_root,
                    state_dir=self._state_dir,
                    can_return_to_dashboard=True,
                )
            )
