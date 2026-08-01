"""Pantalla Scripts (T-FB001-US03-03): lista los scripts particulares
catalogados del proyecto activo (`GET /scripts`) y permite ejecutar uno
con un botón, mostrando su resultado completo (éxito/fallo, salida, exit
code) sin teclear el comando manualmente — mismo patrón ya establecido en
`AgentsScreen`/`JobsScreen`: cliente HTTP del backend, sin invocar dominio
directamente."""

from pathlib import Path

from textual import work
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Select, Static

from brain.tui.backend_client import BackendClient, BackendUnavailableError, error_detail


class ScriptsScreen(Screen):
    """Ejecuta scripts particulares catalogados del proyecto activo."""

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

        # Criterio de aceptación explícito: "un proyecto sin scripts
        # particulares... se refleja correctamente, sin error" — lista
        # vacía visible, no un mensaje de error (mismo criterio ya
        # aplicado en `AgentsScreen`/`JobsScreen` para sus propias listas
        # vacías).
        if not self._scripts:
            yield Vertical(
                Static(
                    "El proyecto activo no tiene scripts particulares "
                    "catalogados (sin manifiesto .factory-brain/scripts.yml, "
                    "o vacío)."
                ),
                Button("Volver al Dashboard", id="go-to-dashboard"),
            )
            return

        select_options = [
            (f"{script['name']} ({script['id']})", script["id"]) for script in self._scripts
        ]

        yield Vertical(
            Static("Scripts del proyecto:"),
            Select(
                select_options,
                id="script-choice",
                allow_blank=False,
                value=select_options[0][1],
            ),
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
        result_widget.update(f"Ejecutando '{script_id}'...")
        self._run_script_in_background(script_id)

    @work(thread=True)
    def _run_script_in_background(self, script_id: str) -> None:
        # `POST /scripts/{id}/run` es una llamada HTTP síncrona bloqueante
        # (el backend responde solo cuando el subproceso ya terminó,
        # mismo criterio ya aplicado a `POST /jobs`) — invocarla en el
        # hilo principal de Textual congelaría la UI mientras el script
        # corre. Mismo mecanismo ya usado en `JobsScreen`
        # (`_dispatch_job_in_background`).
        try:
            result = self._backend.run_script(script_id)
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
