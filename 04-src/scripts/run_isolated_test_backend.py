"""Arranca un `brain-api` real y completamente aislado, para que la suite
Puppeteer de `10-web/tests/` (T-FB022-US15-03, US-FB022-15) pueda navegar
contra un backend HTTP real sin tocar producción.

Reutiliza el patrón de aislamiento ya usado por varios Developer para
verificar cambios de `10-web/` en esta sesión (`state_dir`/socket tmux
temporales, proyecto activo preseleccionado — ver
`07-informes/US-FB024-11/corregir-editor-modelo-filas-sinteticas.md`),
formalizado aquí en `tests/fixtures/backend_server.py::running_backend`
(mismo mecanismo, ya usado por varios `test_*.py` de la suite pytest):
`uvicorn.Server` real en un hilo, `_SOCKET_NAME`/`_WORKSPACE_ROOT`/
`_STATE_DIR` de `routes_module` apuntando a un directorio temporal propio
de esta ejecución, y `launch_architect_queue_watcher` parcheado a
no-op dentro del propio `running_backend` (ningún proceso externo se
lanza).

## Protocolo con el llamador (Node/Puppeteer)

1. Este script imprime UNA línea `READY <base_url>\n` en stdout en
   cuanto el servidor está escuchando — el llamador lee esa línea para
   saber el puerto real (`_free_port()` interno, nunca fijo) y cuándo
   empezar a navegar.
2. El proceso se queda vivo indefinidamente después, sirviendo el
   backend real, hasta que el llamador lo termina (`SIGTERM`, o cerrando
   su stdin — cualquiera de los dos dispara un cierre limpio: apaga
   `uvicorn`, restaura las variables de `routes_module`, mata el socket
   tmux aislado).
3. Cualquier error de arranque se imprime como `ERROR <mensaje>\n` en
   stdout y el proceso termina con código de salida distinto de 0 —
   el llamador debe tratar cualquier línea que no empiece por `READY`
   como fallo de arranque, no asumir que la primera línea siempre es la
   correcta.

## Por qué un proceso Python aparte, no `TestClient` embebido en Puppeteer

Puppeteer necesita un servidor HTTP real escuchando en un puerto (para
que Chromium pueda navegar `http://127.0.0.1:<puerto>/ui/` con `fetch`
real desde el navegador) — `TestClient`/`ASGITransport` en memoria (lo
que usa el resto de la suite `pytest`) no sirve aquí, no hay conexión de
red real que Chromium pueda abrir. `running_backend` ya resuelve
exactamente esto (mismo `uvicorn.Server` real que usa producción), así
que este script es solo el puente CLI que lo expone a un proceso Node
externo."""

from __future__ import annotations

import argparse
import signal
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seed-project-name",
        default="puppeteer-test-project",
        help="Nombre del proyecto sintético que se preselecciona como activo.",
    )
    parser.add_argument(
        "--launch-agent-roles",
        default="",
        help=(
            "Lista de roles separados por coma (p. ej. 'arquitecto,developer') "
            "a lanzar como agentes REALES antes de imprimir READY — para "
            "tests que necesitan comparar filas ya lanzadas (no solo "
            "sintéticas). Cada uno se lanza con el doble cooperativo de "
            "tmux ya usado por la suite pytest "
            "(`tests/fixtures/cooperative_agent_sim.sh`, sustituyendo el "
            "comando real de Claude Code) — tmux real, pero nunca un "
            "runtime real de Claude Code/OpenCode, mismo criterio de "
            "aislamiento que el resto de esta suite."
        ),
    )
    args = parser.parse_args()

    from fixtures.backend_server import running_backend  # noqa: E402

    tmp_dir = tempfile.TemporaryDirectory(prefix="brain-puppeteer-")
    tmp_path = Path(tmp_dir.name)
    workspace_root = tmp_path / "workspace"
    project_path = workspace_root / args.seed_project_name
    (project_path / ".git").mkdir(parents=True)
    state_dir = tmp_path / "state"

    from brain.workspace import discover_projects, select_active_project

    discovered = discover_projects(workspace_root)
    project = next(p for p in discovered if p.name == args.seed_project_name)
    select_active_project(project, discovered=discovered, state_dir=state_dir)

    roles_to_launch = [r.strip() for r in args.launch_agent_roles.split(",") if r.strip()]
    if roles_to_launch:
        import brain.runtime.claude_code as claude_code_module

        cooperative_script = str(
            Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "cooperative_agent_sim.sh"
        )
        claude_code_module.DEFAULT_CLAUDE_CODE_COMMAND = "bash"
        claude_code_module.DEFAULT_CLAUDE_CODE_ARGS = [cooperative_script]

    stop_event = threading.Event()

    def _handle_signal(signum, frame):  # noqa: ANN001, ARG001
        stop_event.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    try:
        with running_backend(workspace_root=workspace_root, state_dir=state_dir) as base_url:
            if roles_to_launch:
                # `running_backend` genera un socket tmux aislado
                # internamente y lo aplica a `routes_module._SOCKET_NAME` —
                # se lee de ahí (no `DEFAULT_SOCKET_NAME`, el real de
                # producción) para que los agentes de esta ejecución vivan
                # en el mismo socket aislado que el propio backend sirve.
                import brain.api.routes as routes_module
                from brain.agents.launch import launch_agent
                from brain.core import resolve_startup_session

                isolated_socket = routes_module._SOCKET_NAME
                session = resolve_startup_session(
                    workspace_root=workspace_root, state_dir=state_dir
                )
                for role in roles_to_launch:
                    launch_agent(
                        role, "claude-code", None, session, str(tmp_path),
                        socket_name=isolated_socket,
                    )

            print(f"READY {base_url}", flush=True)
            # Espera hasta señal de cierre O a que el llamador cierre su
            # extremo de stdin (EOF) — cualquiera de los dos dispara el
            # cierre limpio del `with` (apaga uvicorn, mata el socket
            # tmux aislado, restaura routes_module).
            def _wait_stdin_eof():
                try:
                    sys.stdin.readline()
                finally:
                    stop_event.set()

            stdin_thread = threading.Thread(target=_wait_stdin_eof, daemon=True)
            stdin_thread.start()
            stop_event.wait()
    except Exception as error:  # pragma: no cover - solo si algo va mal
        print(f"ERROR {error}", flush=True)
        tmp_dir.cleanup()
        sys.exit(1)

    tmp_dir.cleanup()


if __name__ == "__main__":
    main()
