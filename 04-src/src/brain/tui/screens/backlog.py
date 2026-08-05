"""Pantalla Backlog (T-FB020-US01-02, consume `GET /backlog`/
`GET /backlog/{item_id}` de T-FB020-US01-01): lista de Epics del proyecto
activo con conteo de sus User Stories por estado, detalle de una Epic
(objetivo + desglose de sus User Stories) y detalle de una User
Story/Task (objetivo, criterios de aceptación, Tasks con estado para una
US).

## Código de color y progreso (T-FB020-US03-01)

Equivalencia semántica explícita con la paleta WCAG ya validada de
Android (`colorForBacklogState`, `BacklogScreen.kt`, que reutiliza
literalmente los valores de `colorForAgentStatus`): esta TUI no tiene
noción de contraste WCAG (terminal, sin control sobre el tema/fondo real
del usuario) — en su lugar usa los NOMBRES de color semánticamente
equivalentes de Rich/Textual, los mismos que ya eligen la mayoría de
temas de terminal para transmitir "éxito"/"pendiente"/"neutro":

| Estado             | Android (hex, WCAG ≥3:1)      | TUI (Rich markup) |
|---------------------|--------------------------------|--------------------|
| `DONE`              | `0xFF2E7D32` (verde)           | `[green]`          |
| `TODO`              | `0xFFEF6C00` (ámbar/naranja)   | `[dark_orange]`    |
| no reconocido       | `0xFF757575` (gris)            | `[bright_black]`   |

Mismo criterio de igualdad EXACTA que el backend
(`brain/models/backlog.py::STATE_DONE`/`STATE_TODO`,
`parser.py::classify_todo_items`, `state == "DONE"`): un valor como
`"DONE (aplicada directamente por el crítico...)"` (caso real verificado
en el backlog de este proyecto) NO es `"DONE"` para el propio dominio,
así que tampoco lo es aquí — cae al color neutro, nunca al verde/ámbar
por defecto (criterio de aceptación explícito de la Task).

`Static`/`Button` de Textual interpretan `[...]` como marcado Rich por
defecto (`markup=True`) — el color se aplica envolviendo el texto de
estado en `[color]...[/color]`, NUNCA sustituyéndolo (mismo criterio de
accesibilidad que Android: el indicador es complementario al texto, no
su reemplazo).

Progreso agregado por Epic (criterio de aceptación 2): representación
textual proporcional (`███░░ 3/5`, `_progress_bar_text`) sobre el conteo
de User Stories `DONE`/total — misma decisión ya documentada en
`epicProgressFraction` (Android): User Stories, no Tasks, por ser la
unidad de valor de producto más estable que usa el propio backlog.

Expandir/colapsar in-place (criterio de aceptación 3): cada Epic del
listado tiene un botón "Expandir"/"Colapsar" que despliega/oculta su
desglose de US/Task por estado (ya visible hoy, ahora con color) SIN
empujar una pantalla nueva — convive con la navegación de drill-down ya
construida en T-FB020-US01-02 (el botón "Ver {epic}" original sigue
navegando a `BacklogEpicScreen` para el detalle completo, US a US).

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

_STATE_MARKUP_COLOR = {
    "DONE": "green",
    "TODO": "dark_orange",
}
_UNKNOWN_STATE_MARKUP_COLOR = "bright_black"

_PROGRESS_BAR_WIDTH = 10


def _markup_color_for_state(state: str | None) -> str:
    """Nombre de color Rich equivalente semántico de `colorForBacklogState`
    (Android) — ver tabla de equivalencia en el docstring de módulo.
    Igualdad EXACTA contra `"DONE"`/`"TODO"` (mismo criterio que el propio
    backend, `state == "DONE"`), nunca un prefijo/heurística de texto
    libre: un estado no reconocido cae siempre al gris neutro, nunca se
    confunde con `DONE`/`TODO` (criterio de aceptación explícito)."""
    return _STATE_MARKUP_COLOR.get(state, _UNKNOWN_STATE_MARKUP_COLOR)


def _colorize_state(state: str | None) -> str:
    """Envuelve el texto literal de `state` en marcado Rich de color —
    complementario, nunca sustituto del texto (mismo criterio de
    accesibilidad que el indicador de Android)."""
    label = state if state is not None else "desconocido"
    return f"[{_markup_color_for_state(state)}]{label}[/]"


def _epic_progress_fraction(epic: dict) -> float:
    """Progreso agregado `DONE / total` de una Epic sobre el conteo de
    User Stories — misma función y misma decisión ya documentada en
    `epicProgressFraction` (Android, `BacklogScreen.kt`): User Stories,
    no Tasks, ver ese docstring para el razonamiento completo. `0.0` si
    la Epic no tiene ninguna User Story todavía (nunca división por cero)."""
    user_stories = epic.get("user_stories", {})
    total = sum(user_stories.values())
    if total == 0:
        return 0.0
    done = user_stories.get("DONE", 0)
    return done / total


def _progress_bar_text(epic: dict) -> str | None:
    """Representación textual proporcional del progreso de una Epic
    (criterio de aceptación 2, p. ej. `███░░░░░░░ 3/10`) — `None` si la
    Epic no tiene ninguna User Story todavía (nada que mostrar, mismo
    criterio que Android oculta la barra en ese caso)."""
    user_stories = epic.get("user_stories", {})
    total = sum(user_stories.values())
    if total == 0:
        return None
    done = user_stories.get("DONE", 0)
    fraction = _epic_progress_fraction(epic)
    filled = round(fraction * _PROGRESS_BAR_WIDTH)
    bar = "█" * filled + "░" * (_PROGRESS_BAR_WIDTH - filled)
    return f"{bar} {done}/{total} US DONE"


def _render_epic_list_text(by_epic: list[dict], expanded_epics: set[int]) -> str:
    if not by_epic:
        return "El backlog está vacío (aún no hay Epics/User Stories)."
    lines = ["Epics del proyecto activo:"]
    for index, epic in enumerate(by_epic):
        line = f"  {epic.get('epic_label', epic['epic'])}"
        lines.append(line)
        progress_text = _progress_bar_text(epic)
        if progress_text is not None:
            lines.append(f"    {progress_text}")
        if index not in expanded_epics:
            continue
        if epic.get("user_stories"):
            us_summary = ", ".join(
                f"{_colorize_state(state)}={count}"
                for state, count in sorted(epic["user_stories"].items())
            )
            lines.append(f"    US: {us_summary}")
        if epic.get("tasks"):
            task_summary = ", ".join(
                f"{_colorize_state(state)}={count}"
                for state, count in sorted(epic["tasks"].items())
            )
            lines.append(f"    Task: {task_summary}")
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
        # T-FB020-US03-01, criterio de aceptación 3: expandir/colapsar
        # in-place — índices de Epic actualmente desplegadas. Estado
        # puramente de presentación de esta instancia de pantalla (no
        # sobrevive a "Volver al Dashboard" y reentrar, mismo criterio que
        # el resto de la TUI: cada navegación a Backlog es una instancia
        # nueva que empieza colapsada).
        self._expanded_epics: set[int] = set()

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

        widgets: list = [Static(self._render_epic_list(), id="epic-list")]
        for index, epic in enumerate(self._by_epic):
            is_expanded = index in self._expanded_epics
            widgets.append(
                Button(
                    "Colapsar" if is_expanded else "Expandir",
                    id=f"toggle-epic-{index}",
                )
            )
            widgets.append(Button(f"Ver {epic['epic']}", id=f"open-epic-{index}"))
        widgets.append(Button("Volver al Dashboard", id="go-to-dashboard"))

        yield VerticalScroll(*widgets)

    def _render_epic_list(self) -> str:
        return _render_epic_list_text(self._by_epic, self._expanded_epics)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "go-to-dashboard":
            self.app.pop_screen()
            return

        if event.button.id is not None and event.button.id.startswith("toggle-epic-"):
            index = int(event.button.id.removeprefix("toggle-epic-"))
            self._toggle_epic_expanded(index, event.button)
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

    def _toggle_epic_expanded(self, index: int, toggle_button: Button) -> None:
        # T-FB020-US03-01, criterio de aceptación 3: sin abandonar la
        # pantalla de listado — actualiza el `Static` ya montado
        # (`#epic-list`) y la etiqueta del propio botón, sin recomponer
        # toda la pantalla ni volver a pedir `GET /backlog`.
        if index in self._expanded_epics:
            self._expanded_epics.discard(index)
            toggle_button.label = "Expandir"
        else:
            self._expanded_epics.add(index)
            toggle_button.label = "Colapsar"
        self.query_one("#epic-list", Static).update(self._render_epic_list())


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
            # Paréntesis alrededor del estado (no corchetes sueltos como
            # texto literal — ver comentario histórico en el git blame de
            # esta línea): pero DENTRO de los paréntesis sí se usa marcado
            # `[color]...[/]` real (T-FB020-US03-01) — `Button.label`
            # interpreta `[...]` como marcado Rich, que es precisamente lo
            # que se quiere aquí (un `[TODO]` literal desaparecería; un
            # `[dark_orange]TODO[/]` se renderiza en color, intencionado).
            widgets.append(
                Button(
                    f"Ver {user_story['id']} ({_colorize_state(user_story['state'])})",
                    id=f"open-item-{index}",
                )
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

        state_label = _colorize_state(detail.get("state")) if detail.get("state") else "desconocido"
        lines = [f"{detail['id']} [{detail.get('kind')}] — Estado: {state_label}"]
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
                    lines.append(f"  {task['id']} ({_colorize_state(task['state'])})")
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
