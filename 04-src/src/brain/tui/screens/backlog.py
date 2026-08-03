"""Pantalla Backlog (T-FB020-US01-02, consume `GET /backlog`/
`GET /backlog/{item_id}` de T-FB020-US01-01): lista de Epics del proyecto
activo con conteo de sus User Stories por estado, detalle de una Epic
(objetivo + desglose de sus User Stories) y detalle de una User
Story/Task (objetivo, criterios de aceptación, Tasks con estado para una
US).

## Por qué es una pantalla propia (no dentro de `plan.py`)

La propia Descripción de la Task deja la decisión abierta ("o pantalla
propia si la de Plan ya está sobrecargada — decidir y documentar"):
`plan.py` ya combina solicitud de plan, aprobación/rechazo con
confirmación de "segunda pulsación", y cancelación con un tercer worker
de hilo — añadirle además listado/detalle de backlog (con su propio
drill-down de tres niveles) lo sobrecargaría. Este módulo sigue el mismo
patrón ya establecido por `agents.py`/`jobs.py`/`plan.py`/`scripts.py`:
cliente de `BackendClient`, sin invocar dominio directamente, construida
y empujada desde `DashboardScreen`.

## Navegación pantalla-por-nivel (mismo patrón que `JobsScreen` empujando
## una nueva instancia de sí misma preseleccionada, `_open_chain_to_critic_form`)

Tres niveles — lista de Epics, detalle de Epic, detalle de item — se
implementan como TRES pantallas distintas (`BacklogScreen`,
`BacklogEpicScreen`, `BacklogItemScreen`), cada una empujada con
`push_screen` sobre la anterior y con un botón "Volver" que hace
`pop_screen`. Cada `compose()` pide su propio dato al backend en el
momento de mostrarse — no hay estado de navegación cacheado entre
pantallas: esto también resuelve la recontextualización por cambio de
proyecto activo "gratis" (mismo argumento ya documentado en
`jobs.py:_render_history_text`): al volver a Dashboard y entrar de nuevo
a Backlog tras cambiar de proyecto, `BacklogScreen` es una instancia
NUEVA que pide `GET /backlog` fresco, nunca arrastra datos del proyecto
anterior.
"""

import re
from pathlib import Path

from textual import work
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Select, Static

from brain.agents import DEVELOPER_ROLE
from brain.tui.backend_client import BackendClient, BackendUnavailableError, error_detail

_EPIC_LABEL_PREFIX_PATTERN = re.compile(r"^(FB-\d{3,})")


def _render_epic_list_text(by_epic: list[dict]) -> str:
    if not by_epic:
        return "El backlog está vacío (aún no hay Epics/User Stories)."
    lines = ["Epics del proyecto activo:"]
    for epic in by_epic:
        line = f"  {epic['epic']}"
        if epic.get("user_stories"):
            line += " · US: " + ", ".join(
                f"{state}={count}" for state, count in sorted(epic["user_stories"].items())
            )
        if epic.get("tasks"):
            line += " · Task: " + ", ".join(
                f"{state}={count}" for state, count in sorted(epic["tasks"].items())
            )
        lines.append(line)
    return "\n".join(lines)


class BacklogScreen(Screen):
    """Lista las Epics del proyecto activo con su conteo de User Stories
    por estado (`GET /backlog`, criterio de aceptación 1) — tocar una
    Epic (botón por fila) abre su detalle (`BacklogEpicScreen`)."""

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
        self._by_epic: list[dict] = []

    def compose(self):
        try:
            report = self._backend.get_backlog()
            backend_error = None
        except BackendUnavailableError as error:
            report = None
            backend_error = str(error)
        except Exception as error:
            # `GET /backlog` propaga un 404 real (sin proyecto activo,
            # T-FB020-US01-01) como `requests.HTTPError` — a diferencia de
            # `get_agents`/`get_jobs`, no es un estado "lista vacía", así
            # que se refleja con el motivo real del backend, mismo
            # criterio que el resto de pantallas ante un fallo real.
            report = None
            backend_error = f"No se pudo consultar el backlog: {error_detail(error)}"

        if backend_error is not None:
            yield Vertical(
                Static(f"No se pudo contactar con el backend: {backend_error}", id="backend-error"),
                Button("Volver al Dashboard", id="go-to-dashboard"),
            )
            return

        self._by_epic = report.get("by_epic", [])

        widgets: list = [Static(_render_epic_list_text(self._by_epic), id="epic-list")]
        for index, epic in enumerate(self._by_epic):
            widgets.append(Button(f"Ver {epic['epic']}", id=f"open-epic-{index}"))
        widgets.append(Button("Volver al Dashboard", id="go-to-dashboard"))

        yield VerticalScroll(*widgets)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "go-to-dashboard":
            self.app.pop_screen()
            return

        if event.button.id is not None and event.button.id.startswith("open-epic-"):
            index = int(event.button.id.removeprefix("open-epic-"))
            epic_label = self._by_epic[index]["epic"]
            epic_id = _epic_id_from_label(epic_label)
            if epic_id is None:
                # Caso real verificado sobre el backlog de este proyecto:
                # el label libre "(ninguna — infraestructura de proyecto)"
                # no sigue la convención `FB-xxx` — no hay ningún
                # `item_id` de Epic que pedir, se ignora el tap (mismo
                # criterio que "sin dato no hay navegación posible", no un
                # error de usuario).
                return
            self.app.push_screen(
                BacklogEpicScreen(
                    epic_id=epic_id,
                    workspace_root=self._workspace_root,
                    state_dir=self._state_dir,
                    backend_client=self._backend,
                )
            )


def _epic_id_from_label(epic_label: str) -> str | None:
    """Identificador de Epic (`FB-xxx`) a partir de la etiqueta libre
    `**Epic:**` de una US/Task (p. ej. `"FB-020 · Gestión de Backlog
    (alcance v1)"` -> `"FB-020"`) — replica en la TUI el mismo criterio
    que `_EPIC_LABEL_PREFIX_PATTERN` del backend
    (`brain/backlog/detail.py`) y `epicIdFromLabel` de la app Android
    (T-FB020-US01-02): el prefijo, no el string completo — distintas
    Tasks/US de la MISMA Epic real traen sufijos distintos (verificado
    sobre el backlog real de este proyecto: `FB-008` con 8 variantes).
    `None` si el label no sigue la convención (p. ej. el caso real
    `"(ninguna — infraestructura de proyecto)"`)."""
    match = _EPIC_LABEL_PREFIX_PATTERN.match(epic_label.strip())
    return match.group(1) if match else None


class BacklogEpicScreen(Screen):
    """Detalle de una Epic (`GET /backlog/{epic_id}`, criterio de
    aceptación 2): objetivo y desglose de sus User Stories con estado —
    tocar una User Story abre su detalle (`BacklogItemScreen`)."""

    def __init__(
        self,
        epic_id: str,
        workspace_root: Path | None = None,
        state_dir: Path | None = None,
        backend_client: BackendClient | None = None,
    ) -> None:
        super().__init__()
        self._epic_id = epic_id
        self._workspace_root = workspace_root
        self._state_dir = state_dir
        self._backend = backend_client if backend_client is not None else BackendClient()
        self._user_stories: list[dict] = []

    def compose(self):
        try:
            detail = self._backend.get_backlog_item(self._epic_id)
            backend_error = None
        except BackendUnavailableError as error:
            detail = None
            backend_error = str(error)
        except Exception as error:
            detail = None
            backend_error = f"No se pudo consultar la Epic '{self._epic_id}': {error_detail(error)}"

        if backend_error is not None:
            yield Vertical(
                Static(f"No se pudo contactar con el backend: {backend_error}", id="backend-error"),
                Button("Volver", id="go-back"),
            )
            return

        self._user_stories = detail.get("user_stories", [])

        lines = [f"Epic: {detail['id']}", ""]
        # Criterio de aceptación explícito de T-FB020-US01-01/US01-02: un
        # fichero mal formado (aquí, la Epic sin fichero propio o sin
        # `## Objetivo`) se refleja como aviso explícito, sin romper la
        # navegación al resto del backlog.
        if detail.get("parse_warning"):
            lines.append(f"⚠ {detail['parse_warning']}")
            lines.append("")
        lines.append(f"Objetivo: {detail.get('objetivo') or '(sin objetivo declarado)'}")
        lines.append("")
        lines.append("User Stories:")
        if not self._user_stories:
            lines.append("  (ninguna)")

        widgets: list = [Static("\n".join(lines), id="epic-detail")]
        for index, user_story in enumerate(self._user_stories):
            # Paréntesis, no corchetes: `Button.label` interpreta
            # `[...]` como marcado Rich/Textual (estilo), no como texto
            # literal — un estado como `[TODO]` desaparecería del label
            # renderizado (verificado con un test que lo detectó).
            widgets.append(
                Button(f"Ver {user_story['id']} ({user_story['state']})", id=f"open-item-{index}")
            )
        widgets.append(Button("Volver", id="go-back"))

        yield VerticalScroll(*widgets)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "go-back":
            self.app.pop_screen()
            return

        if event.button.id is not None and event.button.id.startswith("open-item-"):
            index = int(event.button.id.removeprefix("open-item-"))
            item_id = self._user_stories[index]["id"]
            self.app.push_screen(
                BacklogItemScreen(
                    item_id=item_id,
                    workspace_root=self._workspace_root,
                    state_dir=self._state_dir,
                    backend_client=self._backend,
                )
            )


class BacklogItemScreen(Screen):
    """Detalle de una User Story/Task (`GET /backlog/{item_id}`, criterio
    de aceptación 3): objetivo, criterios de aceptación, y — solo para
    una User Story — la lista de sus Tasks con estado.

    Para una User Story, además el botón "Lanzar desarrollo"
    (T-FB020-US02-02, consume `POST /backlog/{story_id}/launch-development`
    de T-FB020-US02-01): elegir un agente Developer ya lanzado (mismo
    `Select`/catálogo que `JobsScreen`, no un selector nuevo) y despachar
    sin escribir ninguna descripción a mano. Despacho en worker de hilo
    (`@work(thread=True)`, mismo mecanismo que
    `JobsScreen._dispatch_job_in_background` — `POST /jobs`/este endpoint
    son bloqueantes del lado del backend). `_launch_in_flight` es el guard
    de doble-clic (criterio de aceptación explícito: "un segundo clic...
    no despacha un segundo Job") — el botón se deshabilita nada más
    pulsarlo, ANTES de arrancar el worker, así que un segundo clic
    mientras el primero sigue en vuelo no llega a ejecutar el handler.
    Un 400 (sin Tasks `TODO`)/404 (agente inválido) se muestra con el
    `detail` REAL del backend (`error_detail`, ya compartido con el resto
    de esta TUI) — nunca un mensaje genérico."""

    def __init__(
        self,
        item_id: str,
        workspace_root: Path | None = None,
        state_dir: Path | None = None,
        backend_client: BackendClient | None = None,
    ) -> None:
        super().__init__()
        self._item_id = item_id
        self._workspace_root = workspace_root
        self._state_dir = state_dir
        self._backend = backend_client if backend_client is not None else BackendClient()
        self._is_user_story = False
        self._launch_in_flight = False

    def compose(self):
        try:
            detail = self._backend.get_backlog_item(self._item_id)
            backend_error = None
        except BackendUnavailableError as error:
            detail = None
            backend_error = str(error)
        except Exception as error:
            detail = None
            backend_error = f"No se pudo consultar el item '{self._item_id}': {error_detail(error)}"

        if backend_error is not None:
            yield Vertical(
                Static(f"No se pudo contactar con el backend: {backend_error}", id="backend-error"),
                Button("Volver", id="go-back"),
            )
            return

        lines = [f"{detail['id']} [{detail.get('kind')}] — Estado: {detail.get('state') or 'desconocido'}"]
        if detail.get("epic"):
            lines.append(f"Epic: {detail['epic']}")
        lines.append("")
        if detail.get("parse_warning"):
            lines.append(f"⚠ {detail['parse_warning']}")
            lines.append("")
        lines.append(f"Objetivo: {detail.get('objetivo') or '(sin objetivo declarado)'}")
        lines.append("")
        lines.append(
            f"Criterios de aceptación: {detail.get('criterios_aceptacion') or '(sin criterios declarados)'}"
        )

        # Solo presente para una User Story (`kind == "US"`) — una Task no
        # trae este campo (backend: `build_item_detail`,
        # `brain/backlog/detail.py`). "Lanzar desarrollo" (T-FB020-US02-02)
        # es también exclusivo de una User Story, mismo criterio: el
        # endpoint `POST /backlog/{story_id}/launch-development`
        # (T-FB020-US02-01) solo acepta ids de User Story.
        self._is_user_story = detail.get("kind") == "US"
        if self._is_user_story:
            lines.append("")
            lines.append("Tasks:")
            tasks = detail.get("tasks", [])
            if tasks:
                for task in tasks:
                    lines.append(f"  {task['id']} [{task['state']}]")
            else:
                lines.append("  (ninguna)")

        widgets: list = [Static("\n".join(lines), id="item-detail")]

        if self._is_user_story:
            try:
                agents = self._backend.get_agents()
            except BackendUnavailableError:
                agents = []
            developer_agents = [a for a in agents if a["role"] == DEVELOPER_ROLE]

            if not developer_agents:
                widgets.append(
                    Static(
                        "No hay ningún agente Developer lanzado en la sesión activa. "
                        "Lanza uno desde la pantalla Agentes antes de lanzar el "
                        "desarrollo.",
                        id="no-developer-message",
                    )
                )
            else:
                select_options = [
                    (f"{agent['name']} ({agent['role']})", agent["id"]) for agent in developer_agents
                ]
                widgets.append(Static("Lanzar desarrollo — elige el agente Developer:"))
                widgets.append(
                    Select(
                        select_options,
                        id="launch-development-agent-choice",
                        allow_blank=False,
                        value=select_options[0][1],
                    )
                )
                widgets.append(Button("Lanzar desarrollo", id="launch-development"))
                widgets.append(
                    VerticalScroll(
                        Static("", id="launch-development-status"),
                        id="launch-development-status-scroll",
                    )
                )

        widgets.append(Button("Volver", id="go-back"))

        yield VerticalScroll(*widgets)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "go-back":
            self.app.pop_screen()
        elif event.button.id == "launch-development":
            self._handle_launch_development_button()

    def _handle_launch_development_button(self) -> None:
        # Criterio de aceptación explícito: "un segundo clic... mientras
        # la petición anterior sigue en vuelo no despacha un segundo Job"
        # — el guard se comprueba y fija ANTES de cualquier operación
        # asíncrona, así que un segundo clic síncrono mientras el primero
        # sigue en vuelo se descarta aquí mismo.
        if self._launch_in_flight:
            return

        select_widget = self.query_one("#launch-development-agent-choice", Select)
        status_widget = self.query_one("#launch-development-status", Static)

        if select_widget.value == Select.NULL:
            status_widget.update("Elige un agente Developer.")
            return

        agent_id = select_widget.value
        self._launch_in_flight = True
        try:
            self.query_one("#launch-development", Button).disabled = True
        except Exception:
            pass
        status_widget.update("Lanzando desarrollo...")
        self._launch_development_in_background(agent_id)

    @work(thread=True)
    def _launch_development_in_background(self, agent_id: str) -> None:
        # `POST /backlog/{story_id}/launch-development` es bloqueante,
        # mismo motivo que `JobsScreen._dispatch_job_in_background` — un
        # worker de hilo aparte evita congelar la UI mientras el agente
        # trabaja.
        try:
            job = self._backend.launch_development(self._item_id, agent_id)
        except BackendUnavailableError as error:
            self.app.call_from_thread(self._show_launch_development_error, str(error))
            return
        except Exception as error:
            # Criterio de aceptación explícito: el motivo REAL del backend
            # (400 sin Tasks TODO, 404 agente inválido) — `error_detail`
            # extrae el `detail` real, nunca un mensaje genérico.
            self.app.call_from_thread(
                self._show_launch_development_error, error_detail(error)
            )
            return

        self.app.call_from_thread(self._show_launch_development_result, job)

    def _show_launch_development_error(self, message: str) -> None:
        self._launch_in_flight = False
        try:
            self.query_one("#launch-development", Button).disabled = False
        except Exception:
            pass
        try:
            self.query_one("#launch-development-status", Static).update(message)
        except Exception:
            pass

    def _show_launch_development_result(self, job: dict) -> None:
        # Criterio de aceptación explícito: "el Job lanzado aparece en la
        # pantalla de Jobs de la sesión sin cambios adicionales en esa
        # pantalla" — no se hace nada más aquí que confirmar el despacho;
        # `JobsScreen` lo verá vía su propio `GET /jobs`, mismo mecanismo
        # que cualquier otro Job (criterio de aceptación de
        # T-FB020-US02-01: indistinguible de `POST /jobs`).
        self._launch_in_flight = False
        try:
            self.query_one("#launch-development", Button).disabled = False
        except Exception:
            pass
        try:
            self.query_one("#launch-development-status", Static).update(
                f"Job despachado ({job['status']}) — visible en la pantalla Jobs."
            )
        except Exception:
            pass
