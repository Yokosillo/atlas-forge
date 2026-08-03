"""App FastAPI de Factory Brain (T-FB016-US01-01, US-FB016-01): esqueleto
del backend HTTP/WebSocket que expone el dominio ya existente a clientes
distintos de la TUI (empezando por la app Android de FB-017).

## Proceso independiente de la TUI

`brain-api` (este paquete) y `brain` (`brain.cli.main`, la TUI) son dos
procesos Python completamente independientes, cada uno con su propio
`_SessionRegistry`/`_AgentRuntimeRegistry` en memoria (mismos registros que
ya usa la TUI, ver `brain.core.session_registry` /
`brain.runtime.agent_runtime_registry`) — no se unifican en esta Task (ver
"Fuera de alcance" de FB-016: "unificar el estado del backend con el de la
TUI... queda como dos procesos independientes en v1"). Lo que sí resuelve
esta Task es el problema real detectado con `textual-serve` (ver
`02-backlog/roadmap.md`, Fase 2.0): con `textual-serve`, cada cliente que
se conectaba lanzaba un subproceso `brain` nuevo, cada uno con su propio
estado en memoria — un agente lanzado desde un cliente no aparecía en la
lista consultada desde otro. Aquí, en cambio, `create_app()` construye una
única instancia de `FastAPI` que un único proceso `uvicorn` sirve a todos
los clientes que se conecten — todos comparten el mismo
`_SessionRegistry` de ese proceso (verificado en
`test_two_clients_see_the_same_session_state`).

## Dependencia `websockets` (T-FB016-US01-05)

`uvicorn` no trae ningún backend de protocolo WebSocket instalado por
defecto con la instalación mínima (`uvicorn`, sin el extra `[standard]`)
— sin él, cualquier intento real de conexión a `/ws/jobs`/`/ws/plans`
falla con 404 en el handshake, aunque las rutas estén correctamente
declaradas y los tests con `TestClient` (transporte ASGI en memoria, sin
sockets reales) pasen igualmente. Detectado al verificar manualmente el
servidor real arrancado (`brain-api`) con un cliente WebSocket real —no
solo con la suite de tests— antes de dar esta Task por cerrada. Se añade
`websockets` como dependencia explícita del proyecto (en vez del extra
`uvicorn[standard]`, que arrastra más paquetes de los que aquí hacen
falta — `httptools`, `uvloop`, etc. — sin necesidad real en v1)."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from brain.api import routes as routes_module
from brain.api.events import jobs_hub, plans_hub, register_event_loops
from brain.api.routes import router
from brain.core.session_registry import (
    SessionAlreadyActiveError,
    get_current_session,
    resolve_startup_session,
)

# T-FB017-US01-01: ruta del APK más reciente servido por `GET /apk` (ver
# docstring del endpoint más abajo para la justificación completa del
# mecanismo de distribución). No vive dentro del repo de código — es un
# artefacto binario generado por `./gradlew assembleDebug`/`assembleRelease`,
# no algo que deba versionarse en git. Vive en /opt (no en el home del
# usuario) por ser un artefacto de sistema del servicio, no un dato de
# usuario — movido desde ~/factory-brain-releases/ el 2026-08-01.
DEFAULT_APK_PATH = Path("/opt/factory-brain/releases/factory-brain-latest.apk")

# T-FB021-US01-01: directorio raíz de la interfaz web estática (`10-web/`,
# mismo nivel que `10-android/` — coherente con la nomenclatura de clientes).
# Se ancla al propio `app.py` (`parents[4]` = raíz del repo) y NO al cwd, de
# modo que `create_app()` sirva la web igual se lance uvicorn desde la raíz
# del repo o desde dentro de `04-src/`.
WEB_ROOT = Path(__file__).resolve().parents[4] / "10-web"


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Captura el loop principal de `uvicorn` para que `jobs_hub`/
    # `plans_hub` (síncronos, invocados desde endpoints HTTP en
    # threadpool) puedan entregarle eventos de forma segura entre hilos
    # (ver `brain.api.events`). Mecanismo `lifespan` (no `@app.on_event`,
    # deprecado en esta versión de FastAPI).
    register_event_loops(asyncio.get_running_loop())

    # T-FB016-US01-10: arranca la sesión de desarrollo una vez al iniciar
    # el proceso, mismo mecanismo que ya usa `FactoryBrainApp.on_mount`
    # (TUI) — sin esto, `GET /session` devolvía 404 indefinidamente en el
    # proceso systemd real, porque nada invocaba `resolve_startup_session`
    # fuera de la TUI. Si no hay proyecto activo persistido (o ya no es
    # válido), no se lanza ninguna excepción: el servidor sigue vivo,
    # `GET /project`/`GET /session` seguirán devolviendo 404 hasta que se
    # resuelva el proyecto activo por otra vía (`POST /project`,
    # T-FB016-US01-11, o la selección manual que use `select_active_project`).
    #
    # T-FB016-US01-11: si ya existe una sesión activa al llegar aquí (el
    # caso real es `POST /project`, que la re-arranca en caliente sobre el
    # mismo proceso vivo, ANTES de que este `_lifespan` vuelva a
    # ejecutarse en el mismo proceso — nunca ocurre en producción, donde
    # `create_app()` se invoca una única vez por proceso; sí puede darse
    # en un test que construye más de un `TestClient(create_app())` en el
    # mismo proceso pytest), `SessionAlreadyActiveError` se ignora en vez
    # de tumbar el arranque del servidor: la sesión que ya está activa es
    # válida por construcción (nadie la creó salvo el propio dominio), no
    # tiene sentido fallar el arranque por su propia consecuencia.
    #
    # `workspace_root`/`state_dir` (T-FB016-US01-11): se leen de
    # `routes_module._WORKSPACE_ROOT`/`_STATE_DIR` (mismas variables que
    # `GET /projects`/`POST /project` usan) en vez de los valores por
    # defecto implícitos — en producción ambas son `None`
    # (comportamiento idéntico al de antes de esta Task: `Path.cwd()`/
    # ubicación por defecto de `brain.storage`), pero en tests
    # (`tests/fixtures/backend_server.py`) permiten aislar qué proyecto
    # activo real resuelve este arranque, sin tocar el filesystem real
    # del usuario.
    try:
        resolve_startup_session(
            workspace_root=routes_module._WORKSPACE_ROOT,
            state_dir=routes_module._STATE_DIR,
        )
    except SessionAlreadyActiveError:
        pass
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Factory Brain API", lifespan=_lifespan)
    app.include_router(router)

    # T-FB021-US01-01: servir la interfaz web estática bajo un PREFIJO
    # dedicado (`/ui`), NO en la raíz `GET /`. Motivos documentados:
    #
    #   1. `GET /` no es un endpoint de dominio (ver listado completo de
    #      rutas más abajo); montar StaticFiles en la raíz haría que Starlette
    #      sirviera CUALQUIER path desconocido desde el directorio estático,
    #      enmascarando 404s legítimos de la API (un typo de `/scripts` u
    #      otro endpoint devolvería el index.html/404 de la web en vez de un
    #      404 de dominio JSON, rompiendo el contrato de errores de la API).
    #   2. Un prefijo dedicado (`/ui`) mantiene la API de dominio en su propio
    #      namespace, sin colisión con los 26 endpoints existentes y sin
    #      entorpecer el análisis de rutas del router.
    #   3. `html=True` hace que `GET /ui/` sirva `index.html` y `GET /ui`
    #      responda con un redirect 307 a `/ui/` — la "URL raíz elegida" de
    #      la web es `/ui/`.
    # La verificación explícita de que ningún endpoint de dominio usa esta
    # ruta está en `tests/test_api_static_web.py` (no solo asumido aquí).
    app.mount("/ui", StaticFiles(directory=WEB_ROOT, html=True), name="web-ui")

    @app.get("/health")
    def health() -> dict:
        """Confirma que el proceso está vivo y expone la sesión de
        desarrollo activa que este mismo proceso resuelve (`None` si
        todavía no hay ningún proyecto seleccionado) — criterio de
        aceptación de la Task."""
        session = get_current_session()
        return {
            "status": "ok",
            "session_id": session.id if session is not None else None,
        }

    @app.get("/apk")
    def download_apk() -> FileResponse:
        """Sirve el APK compilado más reciente de la app Android
        (T-FB017-US01-01, mecanismo de distribución ya decidido: sin Play
        Store, sin `adb` — el móvil abre esta URL sobre la red Tailscale
        en su navegador y descarga el APK, ver
        `02-backlog/epics/FB-017-app-android.md` para el flujo completo
        paso a paso). Reutiliza este mismo backend en vez de un servidor
        HTTP aparte: ya es un proceso siempre vivo (T-FB016-US01-09)
        alcanzable sobre Tailscale, y servir un fichero estático no es
        lógica de negocio nueva (no decide nada, no valida nada de
        dominio) — no contradice el principio de la Epic FB-016 de "no
        añade lógica de negocio nueva salvo la indicada explícitamente".

        404 explícito si todavía no se ha compilado/copiado ningún APK a
        `DEFAULT_APK_PATH` — nunca un 500 genérico por un fichero
        ausente."""
        if not DEFAULT_APK_PATH.exists():
            raise HTTPException(
                status_code=404,
                detail=f"No hay ningún APK publicado en '{DEFAULT_APK_PATH}' todavía.",
            )
        return FileResponse(
            path=DEFAULT_APK_PATH,
            media_type="application/vnd.android.package-archive",
            filename="factory-brain.apk",
        )

    @app.websocket("/ws/jobs")
    async def ws_jobs(websocket: WebSocket) -> None:
        """Empuja eventos de transición de estado de Job
        (`created`/`running`/`completed`/`failed`) — el cliente no
        necesita hacer polling de `GET /jobs/{job_id}` (criterio de
        aceptación de la Task)."""
        await jobs_hub.connect(websocket)
        try:
            while True:
                # No se espera ningún mensaje entrante del cliente — este
                # canal es solo de servidor a cliente. `receive_text`
                # bloquea hasta que el cliente cierra la conexión, que es
                # exactamente la señal que se necesita para desconectar.
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            jobs_hub.disconnect(websocket)

    @app.websocket("/ws/plans")
    async def ws_plans(websocket: WebSocket) -> None:
        """Empuja el plan propuesto por el Critic y el progreso de su
        despacho (US-FB008-04: construcción, aprobación/rechazo, y cada
        paso en curso/completado/fallido)."""
        await plans_hub.connect(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            plans_hub.disconnect(websocket)

    return app
