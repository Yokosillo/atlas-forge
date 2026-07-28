"""Pantalla Dashboard (T-FB002-US02-03): centro de navegación de la TUI.
Muestra el proyecto activo (`get_active_project`, FB-001), el estado de
la sesión de desarrollo actual (`get_current_session`/
`resolve_startup_session`, FB-003) y los agentes lanzados en ella
(`list_agents`, FB-003) con su estado (FB-005), sin reimplementar
ninguna de esas lógicas de dominio. Da acceso a la pantalla Agentes
(T-FB002-US02-04) y permite volver a Workspace para cambiar de proyecto
activo (T-FB002-US02-02).

T-FB002-US03-04 añade acceso a la pantalla Jobs (US-FB002-03) y un
resumen breve del histórico de Jobs de la sesión (conteo por estado, vía
`list_jobs_for_session`, T-FB002-US03-03) — no supervisión completa de
Jobs/Pipelines/eventos, que sigue fuera de alcance de esta Story (ver
Contexto de US-FB002-02): esas capacidades no tienen datos reales que
mostrar todavía más allá de este resumen mínimo."""

from pathlib import Path

from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Static

from brain.core.session_lifecycle import list_agents
from brain.core.session_registry import get_current_session, resolve_startup_session
from brain.dispatcher import list_jobs_for_session
from brain.tmux.manager import DEFAULT_SOCKET_NAME
from brain.workspace.active_project import get_active_project


class DashboardScreen(Screen):
    """Centro de navegación: proyecto activo, estado de sesión, agentes."""

    def __init__(
        self,
        workspace_root: Path | None = None,
        state_dir: Path | None = None,
        socket_name: str = DEFAULT_SOCKET_NAME,
    ) -> None:
        super().__init__()
        self._workspace_root = workspace_root
        self._state_dir = state_dir
        self._socket_name = socket_name

    def _refresh_state(self) -> None:
        self._project = get_active_project(state_dir=self._state_dir)
        self._session = get_current_session() or resolve_startup_session(
            workspace_root=self._workspace_root, state_dir=self._state_dir
        )
        self._agents = list_agents(self._session) if self._session is not None else []
        self._jobs = (
            list_jobs_for_session(self._session.id) if self._session is not None else []
        )

    def compose(self):
        self._refresh_state()

        project_line = (
            f"Proyecto activo: {self._project.name} ({self._project.path})"
            if self._project is not None
            else "Proyecto activo: ninguno"
        )
        session_line = (
            f"Sesión: {self._session.id} ({self._session.status})"
            if self._session is not None
            else "Sesión: ninguna"
        )

        if self._agents:
            agents_lines = [
                f"  - {agent.name} ({agent.role}): {agent.status}"
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
                counts_by_status[job.status] = counts_by_status.get(job.status, 0) + 1
            counts_text = ", ".join(
                f"{status}: {count}" for status, count in sorted(counts_by_status.items())
            )
            jobs_line = f"Jobs de la sesión: {len(self._jobs)} ({counts_text})"
        else:
            jobs_line = "Jobs de la sesión: ninguno todavía"

        yield Vertical(
            Static(project_line, id="active-project"),
            Static(session_line, id="session-state"),
            Static(agents_block, id="agents-list"),
            Static(jobs_line, id="jobs-summary"),
            Button("Ver Agentes", id="go-to-agents"),
            Button("Ver Jobs", id="go-to-jobs"),
            Button("Cambiar de proyecto (Workspace)", id="go-to-workspace"),
        )

    def on_screen_resume(self) -> None:
        # Al volver de Agentes (tras lanzar un agente nuevo) hay que
        # recomponer para reflejar el estado actualizado (criterio de
        # aceptación: "Navegar a Agentes y volver... mantiene la
        # información actualizada").
        self.refresh(recompose=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        from brain.tui.screens.agents import AgentsScreen
        from brain.tui.screens.jobs import JobsScreen
        from brain.tui.screens.workspace import WorkspaceScreen

        if event.button.id == "go-to-agents":
            project_path = self._project.path if self._project is not None else None
            self.app.push_screen(
                AgentsScreen(
                    workspace_root=self._workspace_root,
                    state_dir=self._state_dir,
                    project_path=project_path,
                    socket_name=self._socket_name,
                )
            )
        elif event.button.id == "go-to-jobs":
            self.app.push_screen(
                JobsScreen(
                    workspace_root=self._workspace_root,
                    state_dir=self._state_dir,
                    socket_name=self._socket_name,
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
