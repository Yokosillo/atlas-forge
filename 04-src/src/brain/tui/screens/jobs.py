"""Pantalla Jobs (T-FB002-US03-01/02/03): formulario para crear y
despachar un Job desde la TUI — descripción de texto libre + agente
destinatario (entre los ya lanzados en la sesión activa).

T-FB016-US01-06: deja de invocar directamente
`brain.core.session_registry`/`brain.dispatcher.*` — crear+despachar un
Job, consultar el histórico y encadenar Developer→Critic pasan por
`BackendClient` (`GET /session`, `GET /agents`, `POST /jobs`, `GET
/jobs`), el mismo backend que consumirá la app Android. El encadenamiento
ya no pasa el objeto `Job` de dominio entre pantallas — se pasa
`previous_job_id` (str), resuelto por el backend en `POST /jobs`
(`previous_job_id`, T-FB016-US01-04) exactamente igual que
`create_job(..., previous_job=...)` ya hacía en dominio."""

from pathlib import Path

from textual import work
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Select, Static, TextArea

from brain.agents import CRITIC_ROLE, DEVELOPER_ROLE
from brain.tui.backend_client import BackendClient, BackendUnavailableError, error_detail


class JobsScreen(Screen):
    """Crea y despacha un Job sobre un agente ya lanzado en la sesión."""

    def __init__(
        self,
        workspace_root: Path | None = None,
        state_dir: Path | None = None,
        backend_client: BackendClient | None = None,
        previous_job_id: str | None = None,
        preselected_agent_id: str | None = None,
    ) -> None:
        super().__init__()
        self._workspace_root = workspace_root
        self._state_dir = state_dir
        self._backend = backend_client if backend_client is not None else BackendClient()
        # Estado de encadenamiento (T-FB002-US03-02): si esta pantalla se
        # construyó para encadenar a Critic, `_previous_job_id` se pasa a
        # `POST /jobs` y `_preselected_agent_id` fija el destinatario en
        # el `Select` (descripción sigue siendo editable — la Task pide
        # "descripción adicional editable, agente destinatario fijado").
        self._previous_job_id = previous_job_id
        self._preselected_agent_id = preselected_agent_id
        self._last_completed_job: dict | None = None
        self._last_completed_job_agent: dict | None = None

    def compose(self):
        try:
            agents = self._backend.get_agents()
            backend_error = None
        except BackendUnavailableError as error:
            agents = []
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

        history_widget = VerticalScroll(
            Static(self._render_history_text(), id="job-history-text"),
            id="job-history",
        )

        if not agents:
            yield Vertical(
                Static(
                    "No hay ningún agente lanzado en la sesión activa. "
                    "Lanza un agente desde la pantalla Agentes antes de "
                    "crear un Job."
                ),
                history_widget,
                Button("Volver al Dashboard", id="go-to-dashboard"),
            )
            return

        select_options = [
            (f"{agent['name']} ({agent['role']})", agent["id"]) for agent in agents
        ]
        default_value = (
            self._preselected_agent_id
            if self._preselected_agent_id is not None
            and any(agent["id"] == self._preselected_agent_id for agent in agents)
            else select_options[0][1]
        )

        description_default = ""
        if self._previous_job_id is not None:
            description_default = "Revisa la implementación anterior."

        yield Vertical(
            Static("Describe la tarea:"),
            TextArea(description_default, id="job-description"),
            Static("Elige el agente destinatario:"),
            Select(
                select_options,
                id="agent-choice",
                allow_blank=False,
                value=default_value,
            ),
            Button("Enviar", id="send-job"),
            VerticalScroll(Static("", id="job-status"), id="job-status-scroll"),
            Static("Histórico de Jobs de la sesión:"),
            history_widget,
            Button("Volver al Dashboard", id="go-to-dashboard"),
        )

    def _render_history_text(self) -> str:
        # Criterio de aceptación: "tras crear y despachar varios Jobs,
        # todos aparecen en el histórico con su estado actual" y "el
        # histórico distingue claramente Jobs completed/failed/running".
        # Se recalcula desde `GET /jobs` (nunca desde estado propio de
        # esta instancia de pantalla) — así sobrevive a navegar a otra
        # pantalla y volver: una nueva `JobsScreen` recompone desde el
        # mismo backend, no pierde nada (criterio de aceptación: "navegar
        # a otra pantalla y volver a Jobs conserva el histórico completo").
        try:
            jobs = self._backend.get_jobs()
        except BackendUnavailableError as error:
            return f"No se pudo contactar con el backend: {error}"

        if not jobs:
            return "Todavía no se ha creado ningún Job en esta sesión."

        lines = []
        for job in jobs:
            description_summary = job["description"].splitlines()[0][:80]
            result_summary = job["result"][:200] if job["result"] else "(sin resultado todavía)"
            lines.append(
                f"[{job['status']}] {job['agent_id']} — {description_summary}\n"
                f"    resultado: {result_summary}"
            )
        return "\n".join(lines)

    def _refresh_history(self) -> None:
        history_text_widget = self.query_one("#job-history-text", Static)
        history_text_widget.update(self._render_history_text())

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "send-job":
            self._create_and_dispatch_job()
        elif event.button.id == "chain-to-critic":
            self._open_chain_to_critic_form()
        elif event.button.id == "go-to-dashboard":
            self.app.pop_screen()

    def _create_and_dispatch_job(self) -> None:
        description_widget = self.query_one("#job-description", TextArea)
        select_widget = self.query_one("#agent-choice", Select)
        status_widget = self.query_one("#job-status", Static)

        description = description_widget.text.strip()
        if not description:
            status_widget.update("Escribe una descripción antes de enviar.")
            return

        if select_widget.value == Select.NULL:
            status_widget.update("Elige un agente destinatario.")
            return

        agent_id = select_widget.value
        try:
            agents = self._backend.get_agents()
        except BackendUnavailableError as error:
            status_widget.update(f"No se pudo contactar con el backend: {error}")
            return

        agent = next((a for a in agents if a["id"] == agent_id), None)
        if agent is None:
            status_widget.update("El agente elegido ya no está disponible.")
            return

        # Criterio de aceptación de US-FB002-03: "la pantalla muestra el
        # progreso (created → running) mientras el agente trabaja". `POST
        # /jobs` es bloqueante del lado del backend (igual que
        # `dispatch_job` ya lo era en dominio) — el mensaje "en curso" se
        # muestra aquí, antes de arrancar el worker de hilo, porque el
        # despacho está a punto de empezar de inmediato.
        status_widget.update(f"Job en curso (running) con {agent['name']}...")
        self._dispatch_job_in_background(description, agent)

    @work(thread=True)
    def _dispatch_job_in_background(self, description: str, agent: dict) -> None:
        # `POST /jobs` es una llamada HTTP síncrona bloqueante (el backend
        # solo responde cuando el Job ya terminó, mismo criterio que
        # `dispatch_job` ya tenía en dominio) — invocarla directamente en
        # el hilo principal de Textual congelaría toda la UI mientras el
        # agente trabaja. Se ejecuta en un worker de hilo (`@work(thread=True)`,
        # mismo mecanismo ya usado antes de esta migración) y se actualiza
        # la UI de vuelta al hilo principal con `call_from_thread`.
        try:
            job = self._backend.create_and_dispatch_job(
                agent["id"], description, previous_job_id=self._previous_job_id
            )
        except BackendUnavailableError as error:
            self.app.call_from_thread(self._show_backend_error, str(error))
            return
        except Exception as error:
            self.app.call_from_thread(
                self._show_backend_error, f"No se pudo crear el Job: {error_detail(error)}"
            )
            return

        self.app.call_from_thread(self._show_job_result, job, agent)

    def _show_backend_error(self, message: str) -> None:
        status_widget = self.query_one("#job-status", Static)
        status_widget.update(message)

    def _show_job_result(self, job: dict, agent: dict) -> None:
        # Resultado completo, sin truncarlo (criterio de aceptación): el
        # `Static` vive dentro de un `VerticalScroll` (`#job-status-scroll`,
        # ver `compose`), así que el texto entero es navegable aunque no
        # quepa en una pantalla.
        status_widget = self.query_one("#job-status", Static)
        self._refresh_history()
        if job["status"] == "completed":
            status_widget.update(f"Job completado:\n{job['result']}")
        else:
            status_widget.update(f"Job falló ({job['status']}): {job['result']}")
            return

        if agent["role"] != DEVELOPER_ROLE:
            return

        self._last_completed_job = job
        self._last_completed_job_agent = agent
        self._render_chain_to_critic_offer()

    def _render_chain_to_critic_offer(self) -> None:
        # Criterio de aceptación: "sin Critic lanzado, la opción de
        # encadenar no está disponible, con mensaje claro" — el propio
        # widget sustituye a cualquier oferta anterior si se vuelve a
        # llamar (p. ej. al completar un segundo Job de Developer en la
        # misma sesión), sin acumular duplicados.
        #
        # `remove()`/`mount()` son operaciones asíncronas en Textual
        # (devuelven un `AwaitRemove`/`AwaitMount`) — hacer `remove()` de
        # un widget con un `id` y `mount()` de otro widget nuevo con el
        # MISMO `id` en la misma llamada síncrona puede completar el
        # `mount()` antes de que el `remove()` retire el widget anterior
        # del árbol, causando `DuplicateIds` (bug real detectado al
        # completar un SEGUNDO Job de Developer sin Critic lanzado).
        # Se evita reutilizando el widget existente (actualizando su
        # contenido) en vez de retirarlo y montar uno nuevo, y solo
        # montando si de verdad no existe ninguno todavía.
        existing_button = self.query("#chain-to-critic")
        existing_message = self.query("#no-critic-message")

        try:
            agents = self._backend.get_agents()
        except BackendUnavailableError:
            agents = []
        critic_launched = any(a["role"] == CRITIC_ROLE for a in agents)

        if critic_launched:
            if existing_message:
                existing_message.remove()
            if not existing_button:
                scroll_container = self.query_one("#job-status-scroll", VerticalScroll)
                scroll_container.mount(
                    Button("Encadenar a Critic", id="chain-to-critic")
                )
        else:
            if existing_button:
                existing_button.remove()
            if existing_message:
                existing_message.first().update(
                    "No se puede encadenar a Critic: no hay ningún agente "
                    "Critic lanzado en la sesión."
                )
            else:
                scroll_container = self.query_one("#job-status-scroll", VerticalScroll)
                scroll_container.mount(
                    Static(
                        "No se puede encadenar a Critic: no hay ningún agente "
                        "Critic lanzado en la sesión.",
                        id="no-critic-message",
                    )
                )

    def _open_chain_to_critic_form(self) -> None:
        if self._last_completed_job is None:
            return

        try:
            agents = self._backend.get_agents()
        except BackendUnavailableError:
            return

        critic = next((a for a in agents if a["role"] == CRITIC_ROLE), None)
        if critic is None:
            return

        self.app.push_screen(
            JobsScreen(
                workspace_root=self._workspace_root,
                state_dir=self._state_dir,
                backend_client=self._backend,
                previous_job_id=self._last_completed_job["id"],
                preselected_agent_id=critic["id"],
            )
        )
