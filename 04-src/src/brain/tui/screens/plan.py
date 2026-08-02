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
en estado `proposed`, si hay alguno.

## Cancelar plan (T-FB019-US01-02)

A diferencia de cancelar un Job (`jobs.py`), aquí el `plan_id` YA es
conocido de antemano (`self._plan["plan_id"]`, resuelto en `compose`) —
no hace falta ningún mecanismo de localización. El botón "Cancelar plan"
aparece al aprobar (mientras `POST /plans/{id}/approve` sigue bloqueado
despachando la secuencia de pasos en otro hilo) e invoca
`POST /plans/{id}/cancel` desde un tercer worker de hilo.

## Confirmación al aprobar (T-FB019-US01-03)

Decisión de mecanismo idiomático: Textual soporta `ModalScreen` de forma
nativa (equivalente más directo al `AlertDialog` de Compose usado en
T-FB017-US04-01), pero esta TUI no usa ningún diálogo modal en ningún
sitio — el patrón ya establecido y validado en `_handle_cancel_plan_button`
(esta misma pantalla) y `JobsScreen._handle_cancel_job_button`
(T-FB019-US01-02) es "segunda pulsación" reflejada en la etiqueta del
propio botón. Se aplica el mismo mecanismo a "Aprobar plan completo" por
coherencia dentro de la misma TUI — introducir un `ModalScreen` solo para
esta acción, mientras el resto sigue con "segunda pulsación", dividiría
el lenguaje de confirmación del producto sin necesidad real (ninguna de
las dos acciones es más compleja que la otra: ambas son sí/no de una
acción irreversible)."""

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
        # T-FB019-US01-02: mismo patrón de "segunda pulsación" ya usado en
        # `JobsScreen` (Textual no usa diálogos modales en esta TUI) —
        # `False` hasta el primer clic en "Cancelar plan".
        self._cancel_confirmation_pending = False
        # T-FB019-US01-03: mismo patrón para "Aprobar plan completo" —
        # `False` hasta el primer clic.
        self._approve_confirmation_pending = False

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
            Button("Cancelar plan", id="cancel-plan", disabled=True),
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
        elif event.button.id == "cancel-plan":
            self._handle_cancel_plan_button()
        elif event.button.id == "go-to-dashboard":
            self.app.pop_screen()

    def _approve_plan(self) -> None:
        # T-FB019-US01-03: patrón de "segunda pulsación" (ver docstring de
        # módulo) — el primer clic pide confirmar con el número de pasos,
        # el segundo clic mientras la confirmación sigue pendiente
        # despacha de verdad.
        if not self._approve_confirmation_pending:
            self._approve_confirmation_pending = True
            step_count = len(self._plan["steps"])
            try:
                self.query_one("#approve-plan", Button).label = (
                    f"¿Seguro? Se despacharán {step_count} pasos. Confirmar aprobar"
                )
            except Exception:
                pass
            return

        self._approve_confirmation_pending = False
        status_widget = self.query_one("#plan-status", Static)
        # Criterio de aceptación (paridad con T-FB017-US04-03 en la app):
        # el desarrollador ve que la aprobación está en curso, no silencio
        # hasta que termina o falla — `POST /plans/{id}/approve` es
        # bloqueante (despacha la secuencia completa de Jobs), igual que
        # `POST /jobs` ya lo es en JobsScreen.
        status_widget.update(f"Despachando {len(self._plan['steps'])} pasos...")
        # T-FB019-US01-02: el `plan_id` ya se conoce (a diferencia de un
        # Job recién despachado) — el botón "Cancelar plan" se habilita de
        # inmediato, sin necesitar ningún mecanismo de localización.
        self.query_one("#cancel-plan", Button).disabled = False
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

    def _handle_cancel_plan_button(self) -> None:
        status_widget = self.query_one("#plan-status", Static)

        if not self._cancel_confirmation_pending:
            self._cancel_confirmation_pending = True
            status_widget.update(
                "¿Seguro que quieres cancelar este plan? Pulsa 'Cancelar plan' "
                "de nuevo para confirmar."
            )
            return

        self._cancel_confirmation_pending = False
        status_widget.update("Cancelando plan...")
        self._cancel_plan_in_background(self._plan["plan_id"])

    @work(thread=True)
    def _cancel_plan_in_background(self, plan_id: str) -> None:
        try:
            plan = self._backend.cancel_plan(plan_id)
        except BackendUnavailableError as error:
            self.app.call_from_thread(self._show_backend_error, str(error))
            return
        except Exception as error:
            self.app.call_from_thread(
                self._show_backend_error, f"No se pudo cancelar el plan: {error_detail(error)}"
            )
            return

        self.app.call_from_thread(self._show_cancel_plan_result, plan)

    def _show_cancel_plan_result(self, plan: dict) -> None:
        # `dispatch_plan` (dominio, T-FB008-US08-01) ya cancela el paso
        # `running` (el agente involucrado queda `idle`) y detiene el
        # despacho de los pasos pendientes — no hay nada más que hacer
        # aquí salvo reflejarlo.
        self.query_one("#cancel-plan", Button).disabled = True
        self._show_plan_result(plan)

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

        # T-FB019-US01-02: punto final común (aprobación completada,
        # rechazo, o bloqueo por fallo intermedio) — ninguno de esos
        # estados deja pasos pendientes/en curso que cancelar. Si llegó
        # aquí desde `_show_cancel_plan_result`, ya estaba deshabilitado;
        # deshabilitarlo de nuevo no tiene efecto adicional.
        if plan["status"] != "approved" or all(
            step["status"] in ("completed", "failed", "cancelled") for step in plan["steps"]
        ):
            self.query_one("#cancel-plan", Button).disabled = True
