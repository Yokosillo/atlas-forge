"""Distribución de eventos en tiempo real a clientes WebSocket conectados
(T-FB016-US01-05): `WS /ws/jobs` (transiciones de Job) y `WS /ws/plans`
(plan del Critic y su progreso de despacho).

## Por qué un hub aparte, no tocar `dispatch_job`/`dispatch_plan`

`dispatch_job` (FB-008 v1) y `dispatch_plan` (US-FB008-04) son funciones
síncronas y bloqueantes ya cerradas y probadas — insertar en ellas un
callback de notificación WebSocket las acoplaría a un detalle de
transporte de una Epic distinta (FB-016), justo lo que
`02-backlog/epics/FB-016-api-backend.md` pide evitar ("no se duplica
lógica de validación... expone, no reimplementa"). En vez de eso, este
módulo expone un hub de publicación que los ENDPOINTS de la API (que sí
son la capa correcta para saber de WebSockets) usan para emitir un evento
inmediatamente antes/después de invocar `dispatch_job`/`dispatch_plan` —
la propia llamada síncrona ya delimita naturalmente los puntos de
transición observables desde fuera del dominio (creado → despachando →
resultado final), sin necesitar que el dominio conozca a sus observadores.

## Alcance real de "cualquier vía (API o TUI, mismo proceso)"

El criterio de aceptación de esta Task pide que un evento llegue "cuando
un Job despachado por cualquier vía (API o TUI, mismo proceso) cambia de
estado". `brain-api` y `brain` (la TUI) son dos procesos Python
independientes en v1 (ver `02-backlog/epics/FB-016-api-backend.md`,
"Fuera de alcance": "unificar el estado del backend con el de la TUI...
queda como dos procesos independientes en v1") — comunicación entre
procesos distintos está fuera de lo que esta Epic permite construir hoy.
"Mismo proceso" en el criterio se interpreta, por tanto, como: cualquier
despacho que ocurra DENTRO del proceso `brain-api` (hoy, la única vía de
despacho de Jobs que existe ahí es `POST /jobs`) — no una promesa de ver
eventos de la TUI real, que corre en un proceso aparte. Esta lectura no
contradice el alcance ya fijado de FB-016; lo respeta.

## Mecanismo: cola async por conexión, publicada desde código síncrono

Los endpoints HTTP síncronos de FastAPI (`POST /jobs`, `POST /plans/...`)
corren en un threadpool, no en el event loop de `asyncio` donde viven las
conexiones WebSocket — no se puede llamar directamente a una corrutina
desde ahí. Se captura el loop principal al arrancar la app
(`register_event_loop`, en el hook de startup de `create_app`) y se usa
`asyncio.run_coroutine_threadsafe` para entregar el evento de vuelta al
loop de forma segura entre hilos. Sin colas de mensajería externas ni
dependencias nuevas — mismo criterio de simplicidad ya aplicado en
`job_dispatch.py` ("polling simple, no inotifywait... sin necesidad real
en v1")."""

import asyncio
from typing import Any

from fastapi import WebSocket


class _ChannelHub:
    """Un canal (`"jobs"` o `"plans"`) con sus conexiones WebSocket
    activas. No asume ninguna estructura del payload — cada canal decide
    su propio formato de evento."""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def register_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)

    async def _send_to_all(self, payload: dict[str, Any]) -> None:
        # Copia de la lista antes de iterar: `disconnect` puede mutar
        # `_connections` mientras se envía a una conexión ya cerrada por
        # el cliente (el propio `send_json` lanzaría en ese caso).
        for websocket in list(self._connections):
            try:
                await websocket.send_json(payload)
            except Exception:
                self.disconnect(websocket)

    def publish(self, payload: dict[str, Any]) -> None:
        """Publica `payload` a todas las conexiones activas de este canal.

        Callable de forma síncrona (desde un endpoint HTTP normal de
        FastAPI, que corre en threadpool) — si el loop todavía no se ha
        registrado (p. ej. en tests que usan el hub directamente sin
        arrancar `uvicorn`) o no hay conexiones, no hace nada; nunca
        bloquea ni lanza si no hay ningún cliente WebSocket escuchando."""
        if self._loop is None or not self._connections:
            return
        asyncio.run_coroutine_threadsafe(self._send_to_all(payload), self._loop)


jobs_hub = _ChannelHub()
plans_hub = _ChannelHub()


def register_event_loops(loop: asyncio.AbstractEventLoop) -> None:
    """Registra el event loop principal de `uvicorn` en ambos hubs — se
    invoca una vez, en el hook de startup de la app (`create_app`)."""
    jobs_hub.register_event_loop(loop)
    plans_hub.register_event_loop(loop)
