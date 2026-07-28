"""Pantalla Agentes (T-FB002-US02-04): elegir, lanzar y consultar estado
de agentes, migrando la funcionalidad ya construida en
`brain-launch-agent` (T-FB002-US01-04) a esta pantalla de la TUI
unificada. Reutiliza `list_available_agent_options`/`launch_agent`/
`confirm_launch` (FB-002/FB-005) sin reimplementar su lógica de
dominio — solo sustituye la interacción por `input()` de terminal por
widgets de Textual (`Select`/`Input`/`Button`)."""

from pathlib import Path

from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Input, Select, Static

from brain.core.session_lifecycle import list_agents
from brain.core.session_registry import get_current_session, resolve_startup_session
from brain.dashboard import AgentChoice, confirm_launch, list_available_agent_options
from brain.tmux.manager import DEFAULT_SOCKET_NAME


class AgentsScreen(Screen):
    """Elige, lanza y consulta el estado de los agentes de la sesión."""

    def __init__(
        self,
        workspace_root: Path | None = None,
        state_dir: Path | None = None,
        project_path: str | None = None,
        socket_name: str = DEFAULT_SOCKET_NAME,
    ) -> None:
        super().__init__()
        self._workspace_root = workspace_root
        self._state_dir = state_dir
        self._project_path = project_path
        self._socket_name = socket_name
        self._options = list_available_agent_options()

    def _current_session(self):
        return get_current_session() or resolve_startup_session(
            workspace_root=self._workspace_root, state_dir=self._state_dir
        )

    def compose(self):
        session = self._current_session()
        agents = list_agents(session) if session is not None else []

        if agents:
            agents_lines = [
                f"  - {agent.name} ({agent.role}): {agent.status}"
                for agent in agents
            ]
            agents_block = "\n".join(["Agentes lanzados:", *agents_lines])
        else:
            agents_block = "Agentes lanzados: ninguno"

        select_options = [
            (
                f"{option.agent_role} sobre {option.runtime_name} "
                f"({'admite modelo' if option.supports_model else 'no admite modelo'})",
                (option.agent_role, option.runtime_type),
            )
            for option in self._options
        ]

        default_value = select_options[0][1] if select_options else Select.BLANK

        yield Vertical(
            Static(agents_block, id="agents-list"),
            Static("Elige agente + runtime:"),
            Select(
                select_options,
                id="agent-choice",
                allow_blank=False,
                value=default_value,
            ),
            Input(placeholder="Modelo (opcional, solo OpenCode)", id="model-input"),
            Button("Lanzar", id="launch-agent"),
            Static("", id="launch-result"),
            Button("Volver al Dashboard", id="go-to-dashboard"),
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "launch-agent":
            self._launch_selected_agent()
        elif event.button.id == "go-to-dashboard":
            self.app.pop_screen()

    def _launch_selected_agent(self) -> None:
        select_widget = self.query_one("#agent-choice", Select)
        model_widget = self.query_one("#model-input", Input)
        result_widget = self.query_one("#launch-result", Static)

        if select_widget.value == Select.NULL:
            result_widget.update("Elige una combinación de agente y runtime.")
            return

        agent_role, runtime_type = select_widget.value
        model = model_widget.value.strip() or None

        session = self._current_session()
        if session is None:
            result_widget.update("No hay ninguna sesión de desarrollo activa.")
            return

        choice = AgentChoice(agent_role=agent_role, runtime_type=runtime_type, model=model)
        message = confirm_launch(
            choice, session, self._project_path, socket_name=self._socket_name
        )
        result_widget.update(message)

        agents_widget = self.query_one("#agents-list", Static)
        agents = list_agents(session)
        agents_lines = [
            f"  - {agent.name} ({agent.role}): {agent.status}" for agent in agents
        ]
        agents_widget.update("\n".join(["Agentes lanzados:", *agents_lines]))
