"""Pantalla Scripts (T-FB001-US03-03, T-FB018-US01-03): lista los scripts
del catálogo combinado del proyecto activo — genéricos (`origin: "generic"`,
T-FB018-US01-01) y particulares (`origin: "particular"`, T-FB001-US03-01) —
y permite ejecutar uno con un botón, mostrando su resultado completo
(éxito/fallo, salida, exit code) sin teclear el comando manualmente. Para
el único script con parámetro obligatorio (`commit`) pide el mensaje antes
de ejecutar — mismo patrón de formulario ya usado en otras pantallas
(`JobsScreen`). Mismo patrón de cliente HTTP del backend, sin invocar
dominio directamente."""

from pathlib import Path

from textual import work
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Input, Select, Static

from brain.tui.backend_client import BackendClient, BackendUnavailableError, error_detail

# Único script del catálogo combinado que exige un parámetro (`message`),
# T-FB018-US01-03 — los particulares y el resto de genéricos se ejecutan
# sin parámetros adicionales (criterio de aceptación explícito).
_SCRIPT_WITH_MESSAGE_PARAM = "commit"

# Script del catálogo genérico cuyo resultado es el informe estructurado de
# T-FB018-US02-02 (JSON en stdout + `data` en la respuesta HTTP) — se
# presenta con formato en pantalla en vez del JSON crudo (T-FB018-US02-04,
# criterio 3: "el resultado se entiende sin que el desarrollador tenga que
# interpretar JSON crudo en pantalla").
_BACKLOG_STATUS_SCRIPT = "backlog_status"


def _format_backlog_status(data: dict) -> str:
    """Presentación legible del informe estructurado de backlog-status
    (T-FB018-US02-04): conteo por Epic, lista de Tasks listas y cadena de
    mayor apalancamiento — sin que el desarrollador tenga que leer el JSON
    crudo en pantalla. Recibe el dict ya parseado (campo `data` de la
    respuesta HTTP), nunca relee ficheros."""
    if data.get("empty"):
        return "El backlog está vacío (aún no hay US/Tasks)."

    total = data["total"]
    lines = ["Estado del backlog:"]
    lines.append(f"  Total: {total['items']} items · {total['errors']} errores de parseo")

    us = total.get("user_stories", {})
    tasks = total.get("tasks", {})
    if us:
        lines.append(
            "  US: " + ", ".join(f"{state}={count}" for state, count in sorted(us.items()))
        )
    if tasks:
        lines.append(
            "  Task: " + ", ".join(f"{state}={count}" for state, count in sorted(tasks.items()))
        )

    lines.append("\nConteo por Epic:")
    for epic in data.get("by_epic", []):
        epic_line = f"  {epic['epic']}"
        if epic.get("user_stories"):
            epic_line += " · US: " + ", ".join(
                f"{state}={count}" for state, count in sorted(epic["user_stories"].items())
            )
        if epic.get("tasks"):
            epic_line += " · Task: " + ", ".join(
                f"{state}={count}" for state, count in sorted(epic["tasks"].items())
            )
        lines.append(epic_line)

    lines.append("\nTasks LISTA (listas para empezar):")
    if data.get("items_lista"):
        for entry in data["items_lista"]:
            lines.append(f"  {entry['id']}")
    else:
        lines.append("  (ninguna)")

    lines.append("\nCadena de mayor apalancamiento (próximo foco):")
    chain = data.get("max_leverage_chain", [])
    if chain:
        lines.append("  " + " → ".join(entry["id"] for entry in chain))
    else:
        lines.append("  (ninguna)")

    return "\n".join(lines)


class ScriptsScreen(Screen):
    """Ejecuta scripts (genéricos y particulares) del proyecto activo."""

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
        self._scripts: list[dict] = []
        self._selected_script_id: str | None = None

    def compose(self):
        try:
            self._scripts = self._backend.get_scripts()
            backend_error = None
        except BackendUnavailableError as error:
            self._scripts = []
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

        # Criterio de aceptación explícito de T-FB001-US03-03 y
        # T-FB018-US01-03: un proyecto sin scripts (ni particulares ni
        # genéricos — solo ocurre si no hay sesión activa, ya que el
        # catálogo genérico es fijo) se refleja correctamente, sin error.
        if not self._scripts:
            yield Vertical(
                Static(
                    "No hay ningún script catalogado (sin sesión activa, "
                    "o sin catálogo genérico disponible)."
                ),
                Button("Volver al Dashboard", id="go-to-dashboard"),
            )
            return

        select_options = [
            (
                f"{script['name']} ({script['id']})"
                f"[{'Genérico' if script['origin'] == 'generic' else 'Proyecto'}]",
                script["id"],
            )
            for script in self._scripts
        ]

        yield Vertical(
            Static("Scripts del proyecto (genéricos y particulares):"),
            Select(
                select_options,
                id="script-choice",
                allow_blank=False,
                value=select_options[0][1],
            ),
            Static("Mensaje del commit (obligatorio solo para 'commit'):"),
            Input("", id="commit-message", placeholder="Ej.: Implementa la funcionalidad X"),
            Button("Ejecutar", id="run-script"),
            VerticalScroll(Static("", id="script-result"), id="script-result-scroll"),
            Button("Volver al Dashboard", id="go-to-dashboard"),
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "run-script":
            self._run_selected_script()
        elif event.button.id == "go-to-dashboard":
            self.app.pop_screen()

    def _run_selected_script(self) -> None:
        select_widget = self.query_one("#script-choice", Select)
        result_widget = self.query_one("#script-result", Static)

        if select_widget.value == Select.NULL:
            result_widget.update("Elige un script.")
            return

        script_id = select_widget.value
        self._selected_script_id = script_id
        message = None
        if script_id == _SCRIPT_WITH_MESSAGE_PARAM:
            message = self.query_one("#commit-message", Input).value.strip()
            if not message:
                result_widget.update("Escribe un mensaje para el commit.")
                return

        result_widget.update(f"Ejecutando '{script_id}'...")
        self._run_script_in_background(script_id, message)

    @work(thread=True)
    def _run_script_in_background(self, script_id: str, message: str | None) -> None:
        # `POST /scripts/{id}/run` es una llamada HTTP síncrona bloqueante
        # (el backend responde solo cuando el subproceso ya terminó,
        # mismo criterio ya aplicado a `POST /jobs`) — invocarla en el
        # hilo principal de Textual congelaría la UI mientras el script
        # corre. Mismo mecanismo ya usado en `JobsScreen`
        # (`_dispatch_job_in_background`).
        try:
            result = self._backend.run_script(script_id, message=message)
        except BackendUnavailableError as error:
            self.app.call_from_thread(self._show_result_text, str(error))
            return
        except Exception as error:
            self.app.call_from_thread(
                self._show_result_text, f"No se pudo ejecutar el script: {error_detail(error)}"
            )
            return

        self.app.call_from_thread(self._show_script_result, result)

    def _show_result_text(self, text: str) -> None:
        self.query_one("#script-result", Static).update(text)

    def _show_script_result(self, result: dict) -> None:
        # Resultado completo, sin truncar (mismo criterio ya aplicado en
        # `JobsScreen` para el resultado de un Job) — el `Static` vive
        # dentro de un `VerticalScroll`, navegable aunque no quepa en una
        # pantalla.
        if result["success"]:
            if self._selected_script_id == _BACKLOG_STATUS_SCRIPT and result.get("data"):
                # T-FB018-US02-04: el informe estructurado se presenta con
                # formato (conteo por Epic, Tasks listas, cadena de mayor
                # apalancamiento), no como JSON crudo; la capa opcional de
                # síntesis en prosa (T-FB018-US02-03) se añade si llegó.
                text = _format_backlog_status(result["data"])
                if result.get("prose"):
                    text += f"\n\nSíntesis en prosa:\n{result['prose']}"
            else:
                text = f"Éxito (exit code {result['exit_code']}):\n{result['stdout']}"
        elif result["exit_code"] is not None:
            text = (
                f"Falló (exit code {result['exit_code']}):\n"
                f"stdout:\n{result['stdout']}\nstderr:\n{result['stderr']}"
            )
        else:
            # El script nunca llegó a ejecutarse (script_id desconocido,
            # manifiesto mal formado, timeout) — criterio de aceptación
            # explícito: "se refleja con su motivo, sin romper ni
            # bloquear el resto de la interfaz".
            text = f"No se pudo ejecutar: {result['error_message']}"

        self.query_one("#script-result", Static).update(text)
