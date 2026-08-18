"""App FastAPI de Factory Brain (T-FB016-US01-01, US-FB016-01): esqueleto
del backend HTTP/WebSocket que expone el dominio ya existente a clientes.

## Proceso único de larga duración

`create_app()` construye una única instancia de `FastAPI` que un único
proceso `uvicorn` sirve a todos los clientes que se conecten — todos
comparten el mismo `_SessionRegistry`/`_AgentRuntimeRegistry` en memoria
(ver `brain.core.session_registry` / `brain.runtime.agent_runtime_registry`),
de modo que un agente lanzado desde un cliente aparece en la lista
consultada desde otro (verificado en
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
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from brain.api import routes as routes_module
from brain.api.cache_bust import get_cache_bust_version
from brain.api.events import jobs_hub, plans_hub, register_event_loops
from brain.api.routes import router
from brain.core.reconciliation_log import append_reconciliation_log
from brain.core.session_reconciliation import reconcile_session_agents
from brain.core.session_registry import (
    SessionAlreadyActiveError,
    get_current_session,
    resolve_startup_session,
)
from brain.agents.session_limit_watcher import SessionLimitWatcher
from brain.dispatcher.architect_queue import launch_architect_queue_watcher
from brain.dispatcher.dispatch_queue_worker import DispatchQueueWorker
from brain.runtime.agent_runtime_registry import get_runtime_instance_for_agent
from brain.runtime.generic import is_runtime_alive
from brain.tmux import capture_pane_lines, list_sessions
from brain.workspace.active_project import get_active_project

# T-FB021-US01-01: directorio raíz de la interfaz web estática (`10-web/`).
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

    # T-FB031-US02-02: tras resolver la sesión del proyecto activo,
    # reengancha cada sesión tmux real del socket que ya pertenezca a ese
    # proyecto (FB-031, ver `core/session_reconciliation.py`) — sin esto,
    # un reinicio del proceso deja `session.agents` vacío mientras las
    # sesiones tmux de agentes ya lanzados siguen vivas (caso motivador
    # real reproducido en la propia sesión de trabajo que originó esta
    # Epic). Se consulta `get_current_session()` en vez de reutilizar el
    # valor de retorno de `resolve_startup_session` de arriba porque
    # también cubre el camino `SessionAlreadyActiveError` (la sesión ya
    # existía, pero sigue siendo la sesión correcta a reconciliar). Sin
    # proyecto activo (`None`), no hay nada que reconciliar todavía — el
    # flujo de selección de proyecto (FB-001) debe completarse primero.
    #
    # `active_project` se resuelve aquí (antes que en versiones previas de
    # este bloque) porque tanto el log de reconciliación de abajo como el
    # watcher del Arquitecto más adelante necesitan `project.path`/
    # `project.name` — misma llamada de solo lectura reutilizada por
    # ambos, sin resolverla dos veces.
    active_project = get_active_project(state_dir=routes_module._STATE_DIR)

    # `socket_name=routes_module._SOCKET_NAME` (no el valor por defecto de
    # `list_sessions`): mismo patrón ya establecido en `api/routes.py`
    # para que los tests puedan aislarse en su propio servidor tmux vía
    # `monkeypatch` sin arriesgar interferir con el socket real
    # `factory-brain` de producción durante la suite.
    current_session = get_current_session()
    if current_session is not None:
        reconciled, ignored = reconcile_session_agents(
            current_session, socket_name=routes_module._SOCKET_NAME
        )
        # T-FB037-US02-01: persiste el resultado ya calculado arriba —
        # puramente aditivo, no cambia qué sesiones se reenganchan
        # (`reconcile_session_agents` decide eso en solitario, sin saber
        # que este log existe). Requiere `active_project` (mismo dato que
        # `append_to_architect_queue` usa para su propia ruta) además de
        # `current_session` — sin proyecto activo no hay
        # `project.path`/`project.name` con los que calcular la ubicación
        # del log, igual que el watcher del Arquitecto más abajo. Un
        # fallo al escribir el log no debe tumbar el arranque del
        # servidor (mismo criterio de "mejor esfuerzo" que
        # `append_to_architect_queue` en el resto del código).
        if active_project is not None:
            try:
                total_sessions = len(
                    list_sessions(socket_name=routes_module._SOCKET_NAME)
                )
                recognized = total_sessions - sum(
                    1
                    for entry in ignored
                    if entry["reason"] in ("nombre_no_reconocido", "otro_proyecto", "rol_invalido")
                )
                append_reconciliation_log(
                    active_project.path,
                    active_project.name,
                    total_sessions=total_sessions,
                    recognized=recognized,
                    reconciled=[agent.name for agent in reconciled],
                    ignored=ignored,
                )
            except Exception:
                pass

    # T-FB030-US03-04: lanza `architect_queue_watcher.sh` para el proyecto
    # activo, para que el aviso al Arquitecto de un cierre de Task
    # (`US-FB030-03`) funcione sin que nadie tenga que ejecutar el script
    # a mano en una terminal aparte — antes de esta Task, el mecanismo
    # completo quedaba operativamente inerte salvo lanzamiento manual
    # (incidente real del 2026-08-16, ver
    # `07-informes/incidente-arquitecto-perdido-tras-reinicio-2026-08-16.md`).
    # Sin proyecto activo, no hay `project_root`/`project_name` con los que
    # calcular su destino — no se lanza nada (criterio de aceptación 4),
    # sin que esto haga fallar el arranque de `brain-api`.
    # `project.path`/`project.name` (no un literal): deben coincidir
    # exactamente con lo que ya usa `append_to_architect_queue` al cerrar
    # una Task (mismo `project_name` sin sanear, saneado internamente con
    # la misma regla en `architect_queue_path`/`session_name_for`) y con la
    # sesión tmux real del Arquitecto (`arquitecto-<project_name saneado>`,
    # T-FB030-US01-01) — un `project_name` distinto calcularía una cola o
    # una sesión destino que no existen.
    if active_project is not None:
        launch_architect_queue_watcher(active_project.path, active_project.name)

    # T-FB008-US10-02: arranca el Dispatcher de fondo de la cola de
    # despacho (`T-FB008-US10-01`) — un hilo `daemon` DENTRO de este
    # mismo proceso (no un script externo como `architect_queue_watcher.sh`,
    # ver docstring de `dispatch_queue_worker.py` para el porqué:
    # necesita `list_agents`/`dispatch_job` reales sobre la misma sesión
    # en memoria). Requiere tanto `active_project` como `current_session`
    # ya resueltos (mismo agente/sesión que el resto del dominio de este
    # proceso) — sin proyecto activo o sin sesión, no se lanza nada, sin
    # que esto haga fallar el arranque de `brain-api` (mismo criterio que
    # el watcher del Arquitecto justo arriba).
    if active_project is not None and current_session is not None:
        routes_module._dispatch_queue_worker = DispatchQueueWorker(
            active_project.path,
            active_project.name,
            current_session,
            socket_name=routes_module._SOCKET_NAME,
        )
        routes_module._dispatch_queue_worker.start()

    # T-FB024-US21-01: arranca el watcher de límite de sesión de Claude
    # Code — mismo patrón y mismo requisito (`current_session` real ya
    # resuelto) que `_dispatch_queue_worker` justo arriba; a diferencia de
    # ese, no depende de `active_project` (revisa el pane de cada agente
    # `claude-code` de la sesión, sin necesitar el backlog de ningún
    # proyecto concreto).
    if current_session is not None:
        routes_module._session_limit_watcher = SessionLimitWatcher(
            current_session,
            socket_name=routes_module._SOCKET_NAME,
        )
        routes_module._session_limit_watcher.start()

    yield

    # Shutdown: detiene el hilo `daemon` del Dispatcher al cerrar la app
    # (`with TestClient(...)` en tests, o el propio `uvicorn` en
    # producción) — sin esto, un hilo de polling quedaría corriendo
    # indefinidamente contra un `project_root`/`tmp_path` que un test ya
    # borró al salir de su fixture, o se acumularían hilos huérfanos
    # entre tests que construyen `TestClient(create_app())` repetidas
    # veces en el mismo proceso pytest (verificado explícitamente: sin
    # este shutdown, 4 ficheros de test existentes que ya usan `with
    # TestClient(...)` habrían dejado un hilo de fondo vivo cada uno).
    if routes_module._dispatch_queue_worker is not None:
        routes_module._dispatch_queue_worker.stop()
        routes_module._dispatch_queue_worker = None

    if routes_module._session_limit_watcher is not None:
        routes_module._session_limit_watcher.stop()
        routes_module._session_limit_watcher = None


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
    # Fallback SPA (T-FB024): rutas propias por sección (`/ui/roles`,
    # `/ui/arquitecto`...) que no corresponden a ningún fichero estático real
    # deben servir el mismo `index.html` (el router de `app.js` decide qué
    # pintar según `location.pathname`), no un 404 — sin este fallback,
    # recargar la página en `/ui/roles` rompería porque `StaticFiles` no
    # encuentra ningún fichero con ese nombre.
    #
    # Verificado con `TestClient` real (no supuesto): declarar una ruta
    # `@app.get("/ui/{full_path:path}")` ANTES del `mount("/ui", ...)`
    # intercepta TODO bajo `/ui/*`, incluidos los assets reales (`app.js`
    # nunca llegaría a `StaticFiles`); declararla DESPUÉS nunca se alcanza
    # (Starlette resuelve por orden de declaración y el mount ya capturó el
    # prefijo completo). Por eso el fallback es una subclase de
    # `StaticFiles` que intenta servir el asset real primero y solo cae a
    # `index.html` si `StaticFiles` habría respondido 404 — un único mount,
    # sin ruta duplicada ni ambigüedad de orden.
    class _SPAStaticFiles(StaticFiles):
        async def get_response(self, path, scope):
            try:
                response = await super().get_response(path, scope)
                # T-FB021-US01-03: inyectar cache-bust version en HTML servido.
                # Starlette pasa `path="."` (normpath de la raíz) cuando se pide
                # `/ui/` — sin normalizarlo aquí, el placeholder
                # `{{CACHE_BUST_VERSION}}` llegaba literal al navegador en la
                # ruta principal y el cache-busting nunca invalidaba los assets
                # cacheados.
                if path in ("", "."):
                    path = "index.html"
                if path in ("index.html", "agent-pane.html"):
                    # Lee el fichero y reemplaza el placeholder
                    file_path = self.directory / path
                    if file_path.is_file():
                        from fastapi.responses import HTMLResponse
                        body = file_path.read_bytes()
                        cache_version = get_cache_bust_version(WEB_ROOT)
                        body = body.replace(
                            b"{{CACHE_BUST_VERSION}}", cache_version.encode("utf-8")
                        )
                        return HTMLResponse(content=body)
                return response
            except StarletteHTTPException as exc:
                if exc.status_code == 404:
                    return await super().get_response("index.html", scope)
                raise

    app.mount("/ui", _SPAStaticFiles(directory=WEB_ROOT, html=True), name="web-ui")

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

    @app.websocket("/ws/agents/{agent_id}/pane")
    async def ws_agent_pane(websocket: WebSocket, agent_id: str) -> None:
        """Empuja el contenido del pane tmux de `agent_id` mientras cambie
        (T-FB032-US01-01) — equivalente en vivo de `GET /agents/{id}/pane`,
        sin que el cliente tenga que pedirlo en bucle.

        Canal 1:1, NO un `_ChannelHub` compartido (`brain.api.events`):
        cada conexión abre su propio bucle de polling dedicado a su
        `agent_id` — no hace falta un registro de conexiones ni publicar a
        "todas las conexiones activas", porque no hay ninguna otra
        conexión que deba ver este mismo contenido. `jobs_hub`/`plans_hub`
        resuelven un problema que este canal no tiene: entregar un evento
        publicado desde código SÍNCRONO en threadpool (`POST /jobs`) al
        loop async — aquí el propio poller ya vive dentro de esta misma
        corrutina, sin cruzar threads.

        Resolución del agente/runtime: mismo patrón de 4 chequeos que
        `get_agent_pane` (`api/routes.py:544`) — sesión activa, agente
        existe, runtime registrado, runtime vivo. Si cualquiera falla, se
        cierra la conexión con `websocket.close(code=4004, reason=...)`
        tras aceptarla (RFC 6455 no define un código de cierre para
        "recurso no encontrado" — el rango 4000-4999 es de aplicación,
        sin registro IANA necesario; 4004 se eligió por analogía mnemónica
        con el 404 HTTP que usa el endpoint REST equivalente, no por
        ningún estándar que lo imponga). Se acepta la conexión primero
        (`websocket.accept()`) porque un cliente no puede leer el
        `reason` de un cierre en el propio handshake de rechazo en todos
        los navegadores — aceptar y cerrar inmediatamente después es más
        fiable para que el cliente vea el motivo.
        """
        await websocket.accept()

        session = get_current_session()
        if session is None:
            await websocket.close(
                code=4004, reason="No hay ninguna sesión de desarrollo activa."
            )
            return

        agent = routes_module._find_agent_by_id(session, agent_id)
        if agent is None:
            await websocket.close(
                code=4004,
                reason=f"No existe ningún agente con id '{agent_id}'.",
            )
            return

        runtime_instance = get_runtime_instance_for_agent(agent.id)
        if runtime_instance is None:
            await websocket.close(
                code=4004,
                reason=f"No hay ningún runtime registrado para el agente '{agent_id}'.",
            )
            return

        if not is_runtime_alive(runtime_instance, socket_name=routes_module._SOCKET_NAME):
            await websocket.close(
                code=4004,
                reason=f"El agente '{agent_id}' no tiene una sesión tmux viva que mostrar.",
            )
            return

        # `capture_pane_lines` es SÍNCRONA y bloqueante (ejecuta `tmux
        # capture-pane` real vía libtmux) — llamarla directamente aquí
        # bloquearía el event loop entero mientras dura esa I/O,
        # congelando TODAS las demás conexiones WebSocket del proceso
        # (otros paneles, `/ws/jobs`, `/ws/plans`). `asyncio.to_thread`
        # la ejecuta en el threadpool por defecto de `asyncio`, sin
        # bloquear el loop.
        last_content: list[str] | None = None
        try:
            while True:
                content = await asyncio.to_thread(
                    capture_pane_lines,
                    runtime_instance.session_name,
                    socket_name=routes_module._SOCKET_NAME,
                )
                if content != last_content:
                    last_content = content
                    await websocket.send_json(
                        {
                            "event": "pane_content",
                            "agent_id": agent_id,
                            "content": "\n".join(content),
                        }
                    )
                # Mismo orden de magnitud que el polling de `dispatch_job`
                # (`_REPORT_READ_RETRY_DELAY_SECONDS`/`poll_interval_seconds`
                # por defecto, `job_dispatch.py`) — 0.2s, el valor menor
                # del rango 0.2-1s que pide la Task: prioriza latencia
                # baja sobre carga de CPU, coherente con ser un canal 1:1
                # (nunca hay más de un poller por agente con conexión
                # activa, no un fan-out costoso).
                await asyncio.sleep(0.2)
        except WebSocketDisconnect:
            pass

    return app
