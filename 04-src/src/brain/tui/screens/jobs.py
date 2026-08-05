"""Pantalla Jobs (T-FB002-US03-01/02/03): formulario para crear y
despachar un Job desde la TUI — descripción de texto libre + agente
destinatario (entre los ya lanzados en la sesión activa).

T-FB016-US01-06: deja de invocar directamente
`brain.core.session_registry`/`brain.dispatcher.*` — crear+despachar un
Job y consultar el histórico pasan por `BackendClient` (`GET /session`,
`GET /agents`, `POST /jobs`, `GET /jobs`), el mismo backend que consumirá
la app Android. El encadenamiento manual Developer→Critic (T-FB002-US03-02)
se eliminó junto con el rol `critic` (FB-022): el veredicto sobre el
trabajo del Developer ahora lo emite automáticamente el Arquitecto
(`brain/dispatcher/architect_verdict_queue.py`), sin intervención manual
desde esta pantalla. `previous_job_id` (str) sigue existiendo como
parámetro de esta pantalla porque `POST /jobs` lo soporta de forma
genérica (`previous_job_id`, T-FB016-US01-04), no solo para el
encadenamiento ya retirado.

## Cancelar Job (T-FB019-US01-02)

`POST /jobs` (`create_and_dispatch_job`) es una única llamada bloqueante
— no devuelve el `job_id` hasta que el Job entero termina, así que no
sirve por sí sola para saber QUÉ cancelar mientras sigue en curso. El
backend registra el Job en el histórico de la sesión (`record_job`,
`create_and_record_job`) ANTES de invocar `dispatch_job` — verificado
leyendo `job_orchestration.py`/`routes.py::post_jobs` — así que
`GET /jobs` desde OTRO hilo, mientras el despacho bloqueante sigue en
curso, ya puede ver ese mismo Job con su `id` real en estado
`created`/`running`. `_locate_dispatched_job_in_background` hace polling
breve sobre `GET /jobs` (buscando por `description` exacta, ya que es lo
único que la pantalla conoce de antemano) para resolver el `job_id` sin
tener que ampliar `POST /jobs` para devolverlo de forma anticipada —
mismo criterio de "envoltura fina, sin lógica de dominio nueva" que el
resto de este cliente."""

import time
from pathlib import Path

from textual import work
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Select, Static, TextArea

from brain.tui.backend_client import BackendClient, BackendUnavailableError, error_detail

# T-FB019-US01-02: margen para que `GET /jobs` (hilo de localización)
# encuentre el Job recién creado por `POST /jobs` (hilo de despacho) —
# ambas peticiones HTTP corren en hilos Python distintos del mismo
# proceso TUI, sin ninguna sincronización explícita entre ellas más que
# este polling. `record_job` ya deja el Job visible en el histórico
# antes de que `dispatch_job` empiece a esperar (ver docstring de
# módulo), así que la ventana real suele cerrarse en milisegundos.
_JOB_LOCATE_TIMEOUT_SECONDS = 5.0
_JOB_LOCATE_POLL_INTERVAL_SECONDS = 0.2


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
        # `_previous_job_id` se pasa a `POST /jobs` y `_preselected_agent_id`
        # fija el destinatario en el `Select` si esta pantalla se construye
        # ya con un agente/Job previo determinados (descripción sigue
        # siendo editable). El encadenamiento manual Developer→Critic que
        # originalmente motivó estos dos parámetros (T-FB002-US03-02) se
        # eliminó junto con el rol `critic` (FB-022); se conservan porque
        # `POST /jobs` sigue soportando `previous_job_id` de forma genérica.
        self._previous_job_id = previous_job_id
        self._preselected_agent_id = preselected_agent_id
        # T-FB019-US01-02: `job_id` del despacho actualmente en curso, una
        # vez localizado por `_locate_dispatched_job_in_background` — `None`
        # antes de despachar y tras terminar (éxito, fallo o cancelación),
        # habilita/deshabilita el botón "Cancelar Job".
        self._dispatching_job_id: str | None = None
        # Identifica el despacho vigente para el worker de localización —
        # ver docstring de `_locate_dispatched_job_in_background` para la
        # condición de carrera concreta que evita.
        self._active_dispatch_token: object | None = None
        # Confirmación de "segunda pulsación" (punto 3 de la Descripción de
        # la Task): Textual no usa diálogos modales en ningún sitio de esta
        # TUI — un primer clic en "Cancelar Job" pide confirmar, un segundo
        # clic mientras `_cancel_confirmation_pending` sigue activo ejecuta
        # la cancelación real.
        self._cancel_confirmation_pending = False

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
        elif event.button.id == "cancel-job":
            self._handle_cancel_job_button()
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
        self._unmount_cancel_job_button()
        self._cancel_confirmation_pending = False
        dispatch_token = object()
        self._active_dispatch_token = dispatch_token
        self._dispatch_job_in_background(description, agent)
        self._locate_dispatched_job_in_background(description, dispatch_token)

    def _handle_cancel_job_button(self) -> None:
        if self._dispatching_job_id is None:
            # El botón solo está montado mientras hay un `job_id`
            # localizado — este `return` es defensivo, no debería
            # alcanzarse en la práctica.
            return

        if not self._cancel_confirmation_pending:
            self._cancel_confirmation_pending = True
            # T-FB019-US01-02: la confirmación se refleja en la ETIQUETA
            # del propio botón, no en `#job-status` — encontrado durante
            # el desarrollo de esta Task: `#job-status` vive dentro de un
            # `VerticalScroll` sin altura fija (`#job-status-scroll`, ya
            # existente antes de esta Task) que crece con su contenido;
            # cambiar su texto entre el primer y segundo clic desplazaba
            # el botón "Cancelar Job" una fila hacia abajo justo entre
            # ambos clics, dejando el segundo clic apuntando a coordenadas
            # que ya no correspondían al botón. El texto del botón, en
            # cambio, no reposiciona nada del resto del layout.
            try:
                self.query_one("#cancel-job", Button).label = "¿Seguro? Confirmar cancelación"
            except Exception:
                pass
            return

        self._cancel_confirmation_pending = False
        status_widget = self.query_one("#job-status", Static)
        status_widget.update("Cancelando Job...")
        self._cancel_job_in_background(self._dispatching_job_id)

    @work(thread=True)
    def _locate_dispatched_job_in_background(self, description: str, dispatch_token: object) -> None:
        # Ver docstring de módulo: `POST /jobs` no devuelve el `job_id`
        # hasta que el Job termina — este worker aparte, en su propio
        # hilo, hace polling breve sobre `GET /jobs` para encontrar el
        # Job recién creado (por `description` exacta, ya que es lo único
        # que esta pantalla conoce de antemano) mientras el despacho
        # bloqueante sigue en curso en el OTRO worker.
        #
        # `dispatch_token` (objeto centinela único por despacho, ver
        # `_create_and_dispatch_job`) evita una condición de carrera real
        # encontrada durante el desarrollo: si el usuario cancela el Job
        # ANTES de que este worker termine su búsqueda, una lectura tardía
        # de `GET /jobs` podría seguir viendo `status == "running"` (el
        # backend aún no ha propagado la transición a `cancelled`) y
        # volver a montar el botón "Cancelar Job" ya retirado. Comparando
        # contra `self._active_dispatch_token` en cada iteración, el
        # worker se detiene en cuanto detecta que ya no es el despacho
        # vigente, sin depender de ningún timing exacto del backend.
        deadline = time.monotonic() + _JOB_LOCATE_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if self._active_dispatch_token is not dispatch_token:
                return
            try:
                jobs = self._backend.get_jobs()
            except BackendUnavailableError:
                return
            if self._active_dispatch_token is not dispatch_token:
                return
            matching_job = next(
                (
                    job
                    for job in jobs
                    if job["description"] == description
                    and job["status"] in ("created", "running")
                ),
                None,
            )
            if matching_job is not None:
                self.app.call_from_thread(
                    self._set_dispatching_job_id, matching_job["id"], dispatch_token
                )
                return
            time.sleep(_JOB_LOCATE_POLL_INTERVAL_SECONDS)

    def _set_dispatching_job_id(self, job_id: str, dispatch_token: object) -> None:
        # Mismo `dispatch_token` que el worker de localización — si el
        # despacho vigente ya cambió (cancelado, o un nuevo Job despachado
        # mientras este callback esperaba su turno en el hilo principal),
        # este resultado ya obsoleto se descarta en vez de remontar un
        # botón que no corresponde al estado actual de la pantalla.
        if self._active_dispatch_token is not dispatch_token:
            return
        try:
            if not self.is_mounted:
                return
        except Exception:
            return
        self._dispatching_job_id = job_id
        self._mount_cancel_job_button()

    def _mount_cancel_job_button(self) -> None:
        # Montado dinámicamente dentro de `#job-status-scroll`, NO como
        # botón permanente del `Vertical` raíz — un botón siempre presente
        # ahí desplazaría verticalmente el resto del layout fuera del
        # viewport visible en una terminal pequeña, rompiendo `pilot.click`
        # en los tests existentes.
        if self.query("#cancel-job"):
            return
        try:
            scroll_container = self.query_one("#job-status-scroll", VerticalScroll)
        except Exception:
            return
        scroll_container.mount(Button("Cancelar Job", id="cancel-job"))

    def _unmount_cancel_job_button(self) -> None:
        self._dispatching_job_id = None
        # Invalida el token del despacho vigente — el worker de
        # localización (si sigue en vuelo) lo detecta en su siguiente
        # comprobación y se detiene sin remontar el botón (ver docstring
        # de `_locate_dispatched_job_in_background`).
        self._active_dispatch_token = None
        existing = self.query("#cancel-job")
        if existing:
            existing.remove()

    @work(thread=True)
    def _cancel_job_in_background(self, job_id: str) -> None:
        try:
            job = self._backend.cancel_job(job_id)
        except BackendUnavailableError as error:
            self.app.call_from_thread(self._show_backend_error, str(error))
            return
        except Exception as error:
            self.app.call_from_thread(
                self._show_backend_error, f"No se pudo cancelar el Job: {error_detail(error)}"
            )
            return

        self.app.call_from_thread(self._show_cancel_result, job)

    def _show_cancel_result(self, job: dict) -> None:
        # `dispatch_job` (dominio) ya deja el agente `idle` al cancelar
        # (T-FB008-US05-01) — no hay nada más que hacer aquí salvo
        # reflejarlo.
        status_widget = self.query_one("#job-status", Static)
        status_widget.update(f"Job cancelado ({job['status']}): {job['result']}")
        self._unmount_cancel_job_button()
        self._refresh_history()

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

        self.app.call_from_thread(self._show_job_result, job)

    def _show_backend_error(self, message: str) -> None:
        status_widget = self.query_one("#job-status", Static)
        status_widget.update(message)

    def _show_job_result(self, job: dict) -> None:
        # Resultado completo, sin truncarlo (criterio de aceptación): el
        # `Static` vive dentro de un `VerticalScroll` (`#job-status-scroll`,
        # ver `compose`), así que el texto entero es navegable aunque no
        # quepa en una pantalla.
        status_widget = self.query_one("#job-status", Static)
        self._refresh_history()
        # T-FB019-US01-02: el despacho ya terminó (completed/failed) — no
        # queda nada que cancelar, sin esperar a que el usuario pulse
        # "Cancelar Job" y reciba el 400 del backend (Job no `running`).
        self._unmount_cancel_job_button()
        if job["status"] == "completed":
            status_widget.update(f"Job completado:\n{job['result']}")
        else:
            status_widget.update(f"Job falló ({job['status']}): {job['result']}")
