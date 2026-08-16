"""Backend real (`brain-api`) en un hilo aparte, para tests de las
pantallas de la TUI migradas a cliente del backend (T-FB016-US01-06):
"mismo criterio de test contra comportamiento real ya aplicado en el
resto del proyecto" (Descripción de la Task) — nunca se mockea la
llamada HTTP entera, se arranca el proceso ASGI real (uvicorn) sirviendo
la misma `create_app()` de producción, en un puerto local libre, y se
apaga limpiamente al terminar el test.

No sigue el patrón `test_*.py` deliberadamente (aunque vive bajo
`tests/fixtures/`, mismo directorio que `cooperative_agent_sim.sh`) —
`pyproject.toml` fija `testpaths = ["tests"]`, que pytest recorre de
forma recursiva; con el patrón por defecto `test_*.py` este módulo se
habría recolectado como suite de tests sin tener ninguno. Se importa
explícitamente desde los ficheros de test que lo necesitan."""

import socket
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import uvicorn

import brain.api.app as app_module
import brain.api.routes as routes_module
from brain.api.app import create_app


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextmanager
def running_backend(
    socket_name: str | None = None,
    workspace_root: Path | None = None,
    state_dir: Path | None = None,
):
    """Arranca `create_app()` real en un hilo con su propio event loop,
    en un puerto local libre, y lo detiene limpiamente al salir del
    context manager. Devuelve la `base_url` (`http://127.0.0.1:<puerto>`)
    para construir un `BackendClient` apuntando a este servidor de
    prueba.

    Si `socket_name` no se indica, se genera uno aislado automáticamente
    y se aplica a `routes_module._SOCKET_NAME` (mismo mecanismo ya usado
    en `test_api_routes_agents.py`/`test_api_routes_jobs.py`) — este
    proceso de test y el backend de prueba comparten el mismo intérprete
    Python, así que monkeypatchear el módulo real tiene efecto sobre las
    peticiones que sirve el servidor arrancado aquí. Cualquier agente
    lanzado a través de este backend de prueba usa sesiones tmux propias
    de ese socket aislado, nunca el socket real del sistema
    (`DEFAULT_SOCKET_NAME`).

    `workspace_root`/`state_dir` (T-FB016-US01-11): igual que
    `_SOCKET_NAME`, se aplican a `routes_module._WORKSPACE_ROOT`/
    `_STATE_DIR` para que el `_lifespan` real de `create_app()`
    (`resolve_startup_session()` sin argumentos explícitos, ver
    `brain/api/app.py`) nunca toque el proyecto activo real persistido
    del usuario en esta máquina (`~/.local/share/brain/`) — bug real
    detectado al implementar `GET /projects`/`POST /project`: sin este
    aislamiento, un backend de prueba en una VM con un proyecto real ya
    activo (de otra sesión de trabajo ajena a este test) arranca una
    sesión real con ESE proyecto en el registro global compartido del
    proceso de test, chocando con la sesión aislada que cada test arma
    después vía `resolve_startup_session(workspace_root=..., state_dir=...)`
    explícito."""
    isolated_socket_name = (
        socket_name if socket_name is not None else f"brain-test-{uuid.uuid4().hex[:8]}"
    )
    original_socket_name = routes_module._SOCKET_NAME
    original_workspace_root = routes_module._WORKSPACE_ROOT
    original_state_dir = routes_module._STATE_DIR
    routes_module._SOCKET_NAME = isolated_socket_name
    routes_module._WORKSPACE_ROOT = workspace_root
    routes_module._STATE_DIR = state_dir

    # T-FB030-US03-04: `_lifespan` ahora lanza `architect_queue_watcher.sh`
    # como subproceso real de larga duración para el proyecto activo que
    # resuelva — cuando este fixture se invoca SIN `state_dir` (algunos
    # tests de arranque de la TUI lo hacen a propósito, ver docstring de
    # arriba), `_lifespan` resolvería el proyecto activo REAL persistido
    # del usuario en esta máquina y dejaría ese watcher corriendo
    # indefinidamente tras el test, sin relación con lo que el test
    # prueba. Mismo stub que ya aplican `test_ws_agent_pane.py`/
    # `test_session_reconciliation.py`/`test_api_routes_plans.py` para el
    # `_lifespan` vía `TestClient`, aquí centralizado para cualquier
    # llamador de `running_backend` (servidor uvicorn real en hilo).
    with patch.object(app_module, "launch_architect_queue_watcher", lambda *a, **k: None):
        port = _free_port()
        config = uvicorn.Config(
            create_app(), host="127.0.0.1", port=port, log_level="warning"
        )
        server = uvicorn.Server(config)

        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()

        deadline = time.monotonic() + 5.0
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        if not server.started:
            routes_module._SOCKET_NAME = original_socket_name
            routes_module._WORKSPACE_ROOT = original_workspace_root
            routes_module._STATE_DIR = original_state_dir
            raise RuntimeError("El backend de prueba no arrancó a tiempo.")

        try:
            yield f"http://127.0.0.1:{port}"
        finally:
            server.should_exit = True
            thread.join(timeout=5.0)
            routes_module._SOCKET_NAME = original_socket_name
            routes_module._WORKSPACE_ROOT = original_workspace_root
            routes_module._STATE_DIR = original_state_dir

            try:
                import libtmux

                libtmux.Server(socket_name=isolated_socket_name).kill()
            except Exception:
                pass
