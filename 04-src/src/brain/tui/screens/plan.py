"""Pantalla Plan del Critic (T-FB016-US01-18): la TUI nunca tuvo un
equivalente a `PlanScreen` de la app Android (`T-FB017-US01-04`) —
verificado: no existía ningún fichero `plan*.py` en `tui/screens/`, y
T-FB016-US01-06 (migración de la TUI a cliente del backend) cubrió
explícitamente solo Workspace/Dashboard/Agents/Jobs, sin mencionar Plan.

Mismo patrón ya establecido en `AgentsScreen`/`JobsScreen`: cliente de
`BackendClient`, sin invocar dominio directamente. `GET /plans`
(T-FB016-US01-14, implementada junto con esta Task porque era un
prerequisito real no resuelto: sin lista de planes, esta pantalla no
tenía forma de descubrir qué plan estaba `proposed` sin que alguien le
pasara su `plan_id` a mano) resuelve qué plan mostrar — el más reciente
en estado `proposed`, si hay alguno."""

from pathlib import Path

from textual import work
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Static

from brain.tui.backend_client import BackendClient, BackendUnavailableError, error_detail


def _select_pending_plan(plans: list[dict]) -> dict | None:
    """Elige qué plan mostrar entre los devueltos por `GET /plans`: el más
    reciente en estado `proposed` (pendiente de revisión), o `None` si no
    hay ninguno. `GET /plans` no garantiza ningún orden estable por sí
    mismo más allá del de inserción del registro — se recorre en orden
    inverso para preferir el propuesto MÁS RECIENTE si hubiera varios
    (un segundo `POST /plans` mientras el primero seguía `proposed` sin
    decidir, caso límite pero posible)."""
    for plan in reversed(plans):
        if plan["status"] == "proposed":
            return plan
    return None


class PlanScreen(Screen):
    """Muestra el plan del Critic pendiente de aprobación (si lo hay) con
    sus pasos y estado, y las acciones Aprobar/Rechazar."""

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
        self._plan: dict | None = None

    def compose(self):
        try:
            plans = self._backend.get_plans()
            backend_error = None
        except BackendUnavailableError as error:
            plans = []
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

        self._plan = _select_pending_plan(plans)

        if self._plan is None:
            # Criterio de aceptación explícito: "Sin plan pendiente, la
            # pantalla lo indica explícitamente, sin error ni pantalla en
            # blanco."
            yield Vertical(
                Static(
                    "No hay ningún plan pendiente de aprobación.",
                    id="no-pending-plan",
                ),
                Button("Volver al Dashboard", id="go-to-dashboard"),
            )
            return

        yield Vertical(
            Static(self._render_plan_text(), id="plan-details"),
            VerticalScroll(Static("", id="plan-status"), id="plan-status-scroll"),
            Button("Aprobar plan completo", id="approve-plan"),
            Button("Rechazar", id="reject-plan"),
            Button("Volver al Dashboard", id="go-to-dashboard"),
        )

    def _render_plan_text(self) -> str:
        plan = self._plan
        lines = [f"Objetivo: {plan['goal']}", f"Estado del plan: {plan['status']}", ""]
        for index, step in enumerate(plan["steps"], start=1):
            lines.append(
                f"Paso {index} [{step['status']}] ({step['mechanism']}): {step['description']}"
            )
        return "\n".join(lines)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "approve-plan":
            self._approve_plan()
        elif event.button.id == "reject-plan":
            self._reject_plan()
        elif event.button.id == "go-to-dashboard":
            self.app.pop_screen()

    def _approve_plan(self) -> None:
        status_widget = self.query_one("#plan-status", Static)
        # Criterio de aceptación (paridad con T-FB017-US04-03 en la app):
        # el desarrollador ve que la aprobación está en curso, no silencio
        # hasta que termina o falla — `POST /plans/{id}/approve` es
        # bloqueante (despacha la secuencia completa de Jobs), igual que
        # `POST /jobs` ya lo es en JobsScreen.
        status_widget.update(f"Despachando {len(self._plan['steps'])} pasos...")
        self._approve_plan_in_background(self._plan["plan_id"])

    @work(thread=True)
    def _approve_plan_in_background(self, plan_id: str) -> None:
        # Mismo mecanismo ya usado en `JobsScreen._dispatch_job_in_background`:
        # `POST /plans/{id}/approve` bloquea hasta que la secuencia entera
        # de Jobs termina — invocarlo en el hilo principal de Textual
        # congelaría toda la UI mientras el plan se despacha.
        try:
            plan = self._backend.approve_plan(plan_id)
        except BackendUnavailableError as error:
            self.app.call_from_thread(self._show_backend_error, str(error))
            return
        except Exception as error:
            self.app.call_from_thread(
                self._show_backend_error, f"No se pudo aprobar el plan: {error_detail(error)}"
            )
            return

        self.app.call_from_thread(self._show_plan_result, plan)

    def _reject_plan(self) -> None:
        status_widget = self.query_one("#plan-status", Static)
        try:
            plan = self._backend.reject_plan(self._plan["plan_id"])
        except BackendUnavailableError as error:
            status_widget.update(str(error))
            return
        except Exception as error:
            status_widget.update(f"No se pudo rechazar el plan: {error_detail(error)}")
            return
        self._show_plan_result(plan)

    def _show_backend_error(self, message: str) -> None:
        status_widget = self.query_one("#plan-status", Static)
        status_widget.update(message)

    def _show_plan_result(self, plan: dict) -> None:
        status_widget = self.query_one("#plan-status", Static)
        lines = [f"Plan {plan['status']}."]
        for index, step in enumerate(plan["steps"], start=1):
            lines.append(f"Paso {index} [{step['status']}]: {step['description']}")
        status_widget.update("\n".join(lines))
