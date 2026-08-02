"""Pantalla de verificación de conectividad (T-FB019-US01-04): paso
explícito y visible antes de decidir Workspace vs. Dashboard al arrancar
la TUI.

Antes de esta Task, `FactoryBrainApp.on_mount` invocaba directamente
`resolve_startup_project` (100% local, filesystem) y empujaba
`WorkspaceScreen`/`DashboardScreen` sin haber verificado nunca que el
backend estuviera disponible. `WorkspaceScreen.compose()` no toca el
backend en absoluto — solo `discover_projects` local — así que arrancar
sin backend corriendo aterrizaba en una `WorkspaceScreen` aparentemente
normal (sin biblioteca de proyectos "descubiertos" con problema alguno),
dejando el primer fallo real de conectividad para más tarde, en cuanto el
usuario navegara a una pantalla que sí llama al backend. Esta Task mueve
esa comprobación al frente, como paso propio.

## Endpoint reutilizado

`GET /session` vía `BackendClient.get_session()` — ya el endpoint más
ligero de toda la superficie del cliente (ya usado por `DashboardScreen`,
ya trata 404 como estado válido "sin sesión activa" sin lanzar). No se
crea ningún endpoint de salud nuevo: si `GET /session` responde (200 o
404), el backend está disponible; si `BackendClient` lanza
`BackendUnavailableError`, no lo está — mismo mecanismo que ya usan
`DashboardScreen`/`AgentsScreen`/etc. para detectarlo, sin inventar nada.

## Por qué una pantalla propia y no una comprobación silenciosa en `on_mount`

El criterio de aceptación pide un paso "propio y visible": una pantalla
dedicada dentro del stack de navegación de Textual, en vez de una
comprobación inline dentro de `on_mount` de la app (que no tendría dónde
mostrar el mensaje de error ni el botón de reintentar sin, en la
práctica, reimplementar aquí mismo lo que ya hace `Screen`). Se resuelve
con `Screen.compose()`: fiel al mismo patrón que ya usa `DashboardScreen`
para su propio `backend-error`/`retry-backend` cuando el backend cae
DESPUÉS del arranque — aquí se aplica el mismo patrón mientras aún no se
ha decidido a qué pantalla navegar.
"""

from pathlib import Path

from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Static

from brain.tui.backend_client import BackendClient, BackendUnavailableError


class ConnectivityCheckScreen(Screen):
    """Verifica la conexión con el backend antes de navegar a
    Workspace/Dashboard. `on_connected` se invoca (vía `self.app.call_later`
    para no acoplarse al instante exacto de montaje) en cuanto la
    comprobación tiene éxito, dejando que quien construya esta pantalla
    decida a qué pantalla navegar después — la propia `ConnectivityCheckScreen`
    no conoce `resolve_startup_project` ni el resto del flujo de arranque."""

    def __init__(
        self,
        on_connected,
        workspace_root: Path | None = None,
        state_dir: Path | None = None,
        backend_client: BackendClient | None = None,
    ) -> None:
        super().__init__()
        self._on_connected = on_connected
        self._workspace_root = workspace_root
        self._state_dir = state_dir
        self._backend = backend_client if backend_client is not None else BackendClient()

    def compose(self):
        try:
            self._backend.get_session()
            backend_error = None
        except BackendUnavailableError as error:
            backend_error = str(error)

        if backend_error is not None:
            yield Vertical(
                Static(
                    f"No se pudo contactar con el backend: {backend_error}",
                    id="connectivity-error",
                ),
                Button("Reintentar", id="retry-connectivity"),
            )
            return

        # Conexión correcta: no hay nada que mostrar, se navega de
        # inmediato — `call_after_refresh` para que la propia pantalla
        # termine de montarse antes de que quien la reemplace en el stack
        # actúe sobre `self.app`.
        self.call_after_refresh(self._on_connected)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "retry-connectivity":
            # Criterio de aceptación: "Reintentar tras arrancar el backend
            # (sin reiniciar la TUI) navega correctamente al siguiente
            # paso" — recomponer vuelve a intentar `GET /session`; si esta
            # vez responde, `compose()` invoca `_on_connected` en vez de
            # volver a mostrar el error.
            self.refresh(recompose=True)
