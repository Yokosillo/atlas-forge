"""Pantalla Jobs (T-FB002-US03-01/02/03): formulario para crear y
despachar un Job desde la TUI — descripción de texto libre + agente
destinatario (entre los ya lanzados en la sesión activa), invocando
`create_job`/`dispatch_job` (FB-008, ya construidos) sin reimplementar
su lógica de dominio. El `RuntimeInstance` del agente elegido se obtiene
con `get_runtime_instance_for_agent` (T-FB002-US03-00) — no se relanza
ni se reconstruye el runtime aquí.

T-FB002-US03-02 añade: mostrar el resultado completo (sin truncarlo,
en un contenedor desplazable) y, si el Job era de Developer y se
completó con éxito, ofrecer encadenar su resultado como entrada de un
nuevo Job para Critic (`create_job(..., previous_job=job)`, US-FB008-02,
ya construido y probado en `test_job_chaining.py` — reutilizado tal
cual, sin reimplementar el encadenamiento aquí).

T-FB002-US03-03 añade: histórico de Jobs de la sesión activa, que
sobrevive a navegar a otra pantalla y volver — `Job` (FB-008) no está
asociado a `DevelopmentSession` como colección consultable, así que se
registra cada Job creado en `job_history_registry` (registro nuevo en
memoria de proceso, mismo patrón que `agent_runtime_registry`/
`job_count_registry`, ver su docstring para la justificación completa
de por qué no se modifica `create_job`/`DevelopmentSession`).

T-FB002-US03-04 añade: botón "Volver al Dashboard" (mismo patrón que
`AgentsScreen`/`WorkspaceScreen`), cerrando el ciclo completo de
navegación de la TUI."""

from pathlib import Path

from textual import work
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Select, Static, TextArea

from brain.agents import CRITIC_ROLE, DEVELOPER_ROLE
from brain.core.session_lifecycle import list_agents
from brain.core.session_registry import get_current_session, resolve_startup_session
from brain.dispatcher import (
    JobCreationError,
    create_job,
    dispatch_job,
    list_jobs_for_session,
    record_job,
)
from brain.models import Agent, Job
from brain.runtime import RuntimeInstance, get_runtime_instance_for_agent
from brain.tmux.manager import DEFAULT_SOCKET_NAME


class JobsScreen(Screen):
    """Crea y despacha un Job sobre un agente ya lanzado en la sesión."""

    def __init__(
        self,
        workspace_root: Path | None = None,
        state_dir: Path | None = None,
        socket_name: str = DEFAULT_SOCKET_NAME,
        previous_job: Job | None = None,
        preselected_agent_id: str | None = None,
    ) -> None:
        super().__init__()
        self._workspace_root = workspace_root
        self._state_dir = state_dir
        self._socket_name = socket_name
        # Estado de encadenamiento (T-FB002-US03-02): si esta pantalla se
        # construyó para encadenar a Critic, `_previous_job` se pasa a
        # `create_job` y `_preselected_agent_id` fija el destinatario en
        # el `Select` (descripción sigue siendo editable — la Task pide
        # "descripción adicional editable, agente destinatario fijado").
        self._previous_job = previous_job
        self._preselected_agent_id = preselected_agent_id
        self._last_completed_job: Job | None = None
        self._last_completed_job_agent: Agent | None = None

    def _current_session(self):
        return get_current_session() or resolve_startup_session(
            workspace_root=self._workspace_root, state_dir=self._state_dir
        )

    def compose(self):
        session = self._current_session()
        agents = list_agents(session) if session is not None else []
        history_widget = VerticalScroll(
            Static(self._render_history_text(session), id="job-history-text"),
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
            (f"{agent.name} ({agent.role})", agent.id) for agent in agents
        ]
        default_value = (
            self._preselected_agent_id
            if self._preselected_agent_id is not None
            and any(agent.id == self._preselected_agent_id for agent in agents)
            else select_options[0][1]
        )

        description_default = ""
        if self._previous_job is not None:
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

    def _render_history_text(self, session) -> str:
        # Criterio de aceptación: "tras crear y despachar varios Jobs,
        # todos aparecen en el histórico con su estado actual" y "el
        # histórico distingue claramente Jobs completed/failed/running".
        # Se recalcula desde `list_jobs_for_session` (nunca desde estado
        # propio de esta instancia de pantalla) — así sobrevive a navegar
        # a otra pantalla y volver: una nueva `JobsScreen` recompone desde
        # el mismo registro, no pierde nada (criterio de aceptación:
        # "navegar a otra pantalla y volver a Jobs conserva el histórico
        # completo").
        if session is None:
            return "Sin sesión activa."

        jobs = list_jobs_for_session(session.id)
        if not jobs:
            return "Todavía no se ha creado ningún Job en esta sesión."

        lines = []
        for job in jobs:
            description_summary = job.description.splitlines()[0][:80]
            result_summary = job.result[:200] if job.result else "(sin resultado todavía)"
            lines.append(
                f"[{job.status}] {job.agent_id} — {description_summary}\n"
                f"    resultado: {result_summary}"
            )
        return "\n".join(lines)

    def _refresh_history(self) -> None:
        session = self._current_session()
        history_text_widget = self.query_one("#job-history-text", Static)
        history_text_widget.update(self._render_history_text(session))

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

        session = self._current_session()
        if session is None:
            status_widget.update("No hay ninguna sesión de desarrollo activa.")
            return

        agent_id = select_widget.value
        agent = next(
            (a for a in list_agents(session) if a.id == agent_id), None
        )
        if agent is None:
            status_widget.update("El agente elegido ya no está disponible.")
            return

        runtime_instance = get_runtime_instance_for_agent(agent.id)
        if runtime_instance is None:
            status_widget.update(
                f"No se encontró el runtime del agente '{agent.name}' — "
                "no se puede despachar el Job."
            )
            return

        try:
            job = create_job(
                description, agent, session, previous_job=self._previous_job
            )
        except JobCreationError as error:
            status_widget.update(f"No se pudo crear el Job: {error}")
            return

        record_job(session.id, job)
        self._refresh_history()

        # Criterio de aceptación de US-FB002-03: "la pantalla muestra el
        # progreso (created → running) mientras el agente trabaja" —
        # `dispatch_job` transiciona `job.status` a `running` justo al
        # empezar (`mark_running`, T-FB008-US01-03). Se refleja aquí
        # explícitamente (en vez de esperar a que el worker de hilo lo
        # haga, que solo se comunica de vuelta al terminar) porque el
        # despacho está a punto de arrancar de inmediato.
        status_widget.update(f"Job creado ({job.status}). Despachando a {agent.name}...")
        self._dispatch_job_in_background(job, agent, runtime_instance)
        status_widget.update(f"Job en curso (running) con {agent.name}...")

    @work(thread=True)
    def _dispatch_job_in_background(
        self,
        job: Job,
        agent: Agent,
        runtime_instance: RuntimeInstance,
        timeout_seconds: float = 30.0,
        poll_interval_seconds: float = 0.2,
    ) -> None:
        # `dispatch_job` es una llamada síncrona bloqueante (hace polling
        # con `time.sleep` mientras espera el reporte del agente, T-FB008-
        # US01-03) — invocarla directamente en el hilo principal de
        # Textual congelaría toda la UI mientras el agente trabaja. Se
        # ejecuta en un worker de hilo (`@work(thread=True)`) para que el
        # resto de la TUI (incluyendo cualquier otra pantalla) siga
        # respondiendo, y se actualiza la UI de vuelta al hilo principal
        # con `call_from_thread` (requisito de Textual: los widgets no son
        # thread-safe si se tocan directamente desde otro hilo).
        # `timeout_seconds`/`poll_interval_seconds` se exponen con los
        # mismos defaults que `dispatch_job`, coherente con el resto de
        # funciones de esta capa que ya exponen sus propios timeouts.
        dispatch_job(
            job,
            agent,
            runtime_instance,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            socket_name=self._socket_name,
        )
        self.app.call_from_thread(self._show_job_result, job, agent)

    def _show_job_result(self, job: Job, agent: Agent) -> None:
        # Resultado completo, sin truncarlo (criterio de aceptación): el
        # `Static` vive dentro de un `VerticalScroll` (`#job-status-scroll`,
        # ver `compose`), así que el texto entero es navegable aunque no
        # quepa en una pantalla.
        status_widget = self.query_one("#job-status", Static)
        self._refresh_history()
        if job.status == "completed":
            status_widget.update(f"Job completado:\n{job.result}")
        else:
            status_widget.update(f"Job falló ({job.status}): {job.result}")
            return

        if agent.role != DEVELOPER_ROLE:
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

        session = self._current_session()
        critic_launched = session is not None and any(
            a.role == CRITIC_ROLE for a in list_agents(session)
        )

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
        session = self._current_session()
        if session is None or self._last_completed_job is None:
            return

        critic = next(
            (a for a in list_agents(session) if a.role == CRITIC_ROLE), None
        )
        if critic is None:
            return

        self.app.push_screen(
            JobsScreen(
                workspace_root=self._workspace_root,
                state_dir=self._state_dir,
                socket_name=self._socket_name,
                previous_job=self._last_completed_job,
                preselected_agent_id=critic.id,
            )
        )
