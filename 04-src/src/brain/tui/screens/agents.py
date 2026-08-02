"""Pantalla Agentes (T-FB002-US02-04): elegir, lanzar y consultar estado
de agentes.

T-FB016-US01-06: deja de invocar directamente
`brain.core.session_registry`/`brain.agents.launch`/
`brain.agents.registry` — lanzar un agente y consultar la sesión/lista de
agentes pasa por `BackendClient` (`GET /session`, `GET /agents`, `POST
/agents`), el mismo backend que consumirá la app Android.
`list_available_agent_options` (`brain.agents.agent_options`) sigue
siendo local: es un catálogo estático de combinaciones agente/runtime
posibles, sin tocar ningún registro de estado — no hay ni falta ningún
endpoint HTTP para esto (ver `brain.tui.backend_client`).

Añade el botón "Detener" (T-FB016-US01-03, `POST /agents/{agent_id}/stop`)
aplazado explícitamente hasta esta Task — antes no tenía sentido añadirlo
sobre la pantalla que gestionaba su propio estado en memoria, porque
quedaría obsoleto en cuanto se migrara a cliente del backend (mismo
razonamiento ya aplicado en T-FB016-US01-03/-04 para no tocar `brain/tui/`
antes de tiempo).

## Confirmación al detener (T-FB019-US01-03)

Mismo mecanismo idiomático ya decidido y validado en `jobs.py`/`plan.py`
(T-FB019-US01-02): patrón de "segunda pulsación" en la etiqueta del propio
botón, no `textual.widgets.ModalScreen` — ver docstring de módulo de
`plan.py` para la decisión original. Se replica aquí por coherencia
dentro de la misma TUI, sin introducir un segundo mecanismo de
confirmación para el mismo producto.

Aviso de "Job en curso" (paridad con `T-FB017-US04-01` en la app,
`agentsWithRunningJob` en `AgentsViewModel.kt`): mismo cálculo, derivado
de `GET /jobs` — el conjunto de `agent_id` con algún Job `running`, sin
necesitar ningún endpoint nuevo."""

from pathlib import Path

from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Input, Select, Static

from brain.agents.agent_options import list_available_agent_options
from brain.tui.backend_client import BackendClient, BackendUnavailableError, error_detail


def _agents_with_running_job(jobs: list[dict]) -> set[str]:
    """Mismo criterio que `agentsWithRunningJob` en la app Android
    (`AgentsViewModel.kt`, T-FB017-US04-01): el conjunto de `agent_id` con
    algún Job actualmente `running`, derivado de `GET /jobs` sin ningún
    endpoint nuevo."""
    return {job["agent_id"] for job in jobs if job["status"] == "running"}


class AgentsScreen(Screen):
    """Elige, lanza, detiene y consulta el estado de los agentes de la sesión."""

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
        self._options = list_available_agent_options()
        self._agents: list[dict] = []
        # T-FB019-US01-03: confirmación de "segunda pulsación" — el
        # `agent_id` con la confirmación pendiente, o `None` si no hay
        # ninguna en curso. Un solo `str | None` basta (a diferencia de un
        # `bool` en `JobsScreen`/`PlanScreen`) porque aquí puede haber
        # varios botones "Detener" simultáneos, uno por agente.
        self._stop_confirmation_pending_for: str | None = None

    def _render_agents_block(self) -> str:
        if not self._agents:
            return "Agentes lanzados: ninguno"

        agents_lines = [
            f"  - {agent['name']} ({agent['role']}): {agent['status']}"
            for agent in self._agents
        ]
        return "\n".join(["Agentes lanzados:", *agents_lines])

    def _refresh_agents_widget(self) -> None:
        agents_widget = self.query_one("#agents-list", Static)
        agents_widget.update(self._render_agents_block())

        # Reconcilia los botones existentes con los agentes actuales en
        # vez de "borrar todo y volver a montar" — `remove()`/`mount()`
        # son operaciones asíncronas en Textual, y montar un botón con un
        # `id` que otro `remove()` todavía no ha retirado del árbol causa
        # `DuplicateIds` (mismo bug real ya documentado y evitado en
        # `JobsScreen._render_chain_to_critic_offer`, T-FB002-US03-02).
        stop_container = self.query_one("#stop-buttons")
        stoppable_ids = {
            agent["id"] for agent in self._agents if agent["status"] != "stopped"
        }
        existing_ids = {
            button.id.removeprefix("stop-")
            for button in stop_container.query(".stop-agent-button")
        }

        for agent_id in existing_ids - stoppable_ids:
            stop_container.query_one(f"#stop-{agent_id}").remove()

        agents_by_id = {agent["id"]: agent for agent in self._agents}
        for agent_id in stoppable_ids - existing_ids:
            agent = agents_by_id[agent_id]
            stop_container.mount(
                Button(
                    f"Detener {agent['name']}",
                    id=f"stop-{agent_id}",
                    classes="stop-agent-button",
                )
            )

    def compose(self):
        try:
            self._agents = self._backend.get_agents()
            backend_error = None
        except BackendUnavailableError as error:
            self._agents = []
            backend_error = str(error)

        if backend_error is not None:
            yield Vertical(
                Static(
                    f"No se pudo contactar con el backend: {backend_error}",
                    id="backend-error",
                ),
                Button("Volver al Dashboard", id="go-to-dashboard"),
            )
            return

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
            Static(self._render_agents_block(), id="agents-list"),
            Vertical(id="stop-buttons"),
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
        self.call_after_refresh(self._refresh_agents_widget)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "launch-agent":
            self._launch_selected_agent()
        elif button_id == "go-to-dashboard":
            self.app.pop_screen()
        elif button_id.startswith("stop-"):
            self._stop_agent(button_id.removeprefix("stop-"))

    def _launch_selected_agent(self) -> None:
        select_widget = self.query_one("#agent-choice", Select)
        model_widget = self.query_one("#model-input", Input)
        result_widget = self.query_one("#launch-result", Static)

        if select_widget.value == Select.NULL:
            result_widget.update("Elige una combinación de agente y runtime.")
            return

        agent_role, runtime_type = select_widget.value
        model = model_widget.value.strip() or None

        try:
            agent = self._backend.launch_agent(agent_role, runtime_type, model)
        except BackendUnavailableError as error:
            result_widget.update(f"No se pudo contactar con el backend: {error}")
            return
        except Exception as error:  # requests.HTTPError con detail del dominio
            result_widget.update(f"No se pudo lanzar el agente: {error_detail(error)}")
            return

        result_widget.update(
            f"Agente '{agent['name']}' ({agent['role']}) operativo, "
            f"estado: {agent['status']}."
        )

        self._agents = self._backend.get_agents()
        self._refresh_agents_widget()

    def _stop_agent(self, agent_id: str) -> None:
        # T-FB019-US01-03: patrón de "segunda pulsación" (mismo mecanismo
        # ya validado en `JobsScreen`/`PlanScreen`, ver docstring de
        # módulo) — el primer clic pide confirmar, advirtiendo si el
        # agente tiene un Job en curso; el segundo clic mientras la
        # confirmación sigue pendiente para ESE `agent_id` ejecuta la
        # parada real.
        if self._stop_confirmation_pending_for != agent_id:
            self._stop_confirmation_pending_for = agent_id
            try:
                jobs = self._backend.get_jobs()
            except BackendUnavailableError:
                jobs = []
            has_running_job = agent_id in _agents_with_running_job(jobs)
            label = (
                "¿Seguro? Tiene un Job en curso — se interrumpirá. Confirmar detener"
                if has_running_job
                else "¿Seguro? Confirmar detener"
            )
            try:
                self.query_one(f"#stop-{agent_id}", Button).label = label
            except Exception:
                pass
            return

        self._stop_confirmation_pending_for = None
        result_widget = self.query_one("#launch-result", Static)
        try:
            agent = self._backend.stop_agent(agent_id)
        except BackendUnavailableError as error:
            result_widget.update(f"No se pudo contactar con el backend: {error}")
            return
        except Exception as error:
            result_widget.update(f"No se pudo detener el agente: {error_detail(error)}")
            return

        result_widget.update(f"Agente '{agent['name']}' detenido (stopped).")
        self._agents = self._backend.get_agents()
        self._refresh_agents_widget()
