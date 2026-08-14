import time
import uuid

import libtmux

# Servidor tmux por defecto de Factory Brain. Un socket_name propio evita
# interferir con sesiones tmux que el usuario ya tenga abiertas fuera de
# la aplicación (servidor tmux por defecto del sistema). Público (sin
# guion bajo) porque se importa desde más de un módulo de `runtime/`
# (Claude Code, OpenCode, y futuros runtimes concretos).
DEFAULT_SOCKET_NAME = "factory-brain"


def _get_server(socket_name: str = DEFAULT_SOCKET_NAME) -> libtmux.Server:
    return libtmux.Server(socket_name=socket_name)


def create_session(
    name: str, working_directory: str, socket_name: str = DEFAULT_SOCKET_NAME
) -> None:
    """Crea una sesión tmux nueva llamada `name`, arrancando en
    `working_directory`. Si ya existe una sesión con ese nombre, la
    sustituye (kill_session=True de libtmux)."""
    server = _get_server(socket_name)
    server.new_session(
        session_name=name, start_directory=working_directory, kill_session=True
    )


def run_command(
    session_name: str, command: str, socket_name: str = DEFAULT_SOCKET_NAME
) -> None:
    """Ejecuta `command` dentro de la sesión `session_name`, en su pane
    activo."""
    server = _get_server(socket_name)
    session = server.sessions.get(session_name=session_name)
    session.active_pane.send_keys(command)


def list_sessions(socket_name: str = DEFAULT_SOCKET_NAME) -> list[str]:
    """Nombres de todas las sesiones tmux vivas en `socket_name`, sin
    necesitar conocer ninguno de antemano (a diferencia de `is_alive`) —
    FB-031, base para que Brain pueda reconciliar su registro en memoria
    contra lo que tmux ya tiene vivo tras un reinicio del proceso.

    `server.sessions` (libtmux) ya devuelve una lista vacía cuando el
    socket no tiene ningún servidor/sesión (verificado contra la versión
    de libtmux fijada en `pyproject.toml`), así que no hace falta manejar
    ese caso aparte — mismo criterio que el resto de funciones de este
    módulo (`is_alive`, `kill_session`) no lanzan excepción ante ausencia."""
    server = _get_server(socket_name)
    return [session.session_name for session in server.sessions]


def is_alive(session_name: str, socket_name: str = DEFAULT_SOCKET_NAME) -> bool:
    """Comprueba si la sesión tmux `session_name` sigue viva.

    Se limita a vivo/no-vivo (sin ciclo de estados fino), según el alcance
    v1 acordado en FB-004: si la sesión tmux existe, el comando lanzado
    dentro sigue vivo o el shell que lo contuvo sigue disponible; si la
    sesión no existe (nunca se creó, o fue destruida), no está viva.
    """
    server = _get_server(socket_name)
    return server.has_session(session_name)


def kill_session(session_name: str, socket_name: str = DEFAULT_SOCKET_NAME) -> None:
    """Mata la sesión tmux `session_name`. No falla si ya no existe."""
    server = _get_server(socket_name)
    if server.has_session(session_name):
        server.kill_session(session_name)


class CommandCaptureTimeoutError(TimeoutError):
    """El comando no terminó (no se vio el marcador de fin) antes del timeout."""


def capture_pane_lines(
    session_name: str, socket_name: str = DEFAULT_SOCKET_NAME
) -> list[str]:
    """Devuelve el contenido visible del pane activo de `session_name`,
    línea a línea (historial de scroll incluido, según libtmux)."""
    server = _get_server(socket_name)
    session = server.sessions.get(session_name=session_name)
    return session.active_pane.capture_pane()


def send_keys_literal(
    session_name: str, keys: str, *, socket_name: str = DEFAULT_SOCKET_NAME
) -> None:
    """Envía teclas literales (como `C-p`, `Down`, `Enter`) al pane de la
    sesión, para interactuar con TUIs que aceptan atajos de teclado
    (OpenCode, Claude Code...). Usa notación de tmux (`send-keys`)."""
    server = _get_server(socket_name)
    session = server.sessions.get(session_name=session_name)
    session.active_pane.cmd('send-keys', keys)


def run_command_and_capture(
    session_name: str,
    command: str,
    timeout_seconds: float = 30.0,
    poll_interval_seconds: float = 0.2,
    socket_name: str = DEFAULT_SOCKET_NAME,
) -> tuple[list[str], int]:
    """Ejecuta `command` en `session_name` y espera a que termine,
    devolviendo su salida capturada y el código de salida.

    ## Mecanismo de captura (v1)

    tmux/libtmux no ofrece un "ejecutar y esperar output" nativo como
    `subprocess.run` — `send_keys` teclea el comando en el pane sin
    bloquear. El mecanismo elegido para v1, verificado experimentalmente
    antes de implementarlo:

    1. Antes de enviar nada, se mide cuántas líneas tiene ya el pane
       (`capture_pane_lines`) — es el punto de corte (`start_line`).
       Esto evita arrastrar la salida de ejecuciones previas cuando la
       sesión tmux se reutiliza (mismo agente, varios Jobs consecutivos).
    2. Se añade al comando un marcador de fin único y su código de salida:
       `<command>; echo <marker>_EXIT$?`.
    3. Se hace polling de `capture-pane` hasta encontrar una línea que
       empiece exactamente por `<marker>_EXIT` (seguida del código de
       salida), o hasta agotar `timeout_seconds`
       (`CommandCaptureTimeoutError`).
    4. El "resultado" se recorta como las líneas del pane entre
       `start_line` y la línea del marcador.

    ## Limitación conocida de v1

    El "resultado" capturado es una aproximación simplificada: incluye
    ruido de terminal (el eco del propio comando enviado, el prompt del
    shell) mezclado con la salida real del comando, porque `capture-pane`
    devuelve el contenido visual del pane tal cual, no un stream de stdout
    aislado. Para un runtime real como Claude Code (proceso interactivo de
    larga duración, no un comando que termina), esto es aceptable como
    primer incremento — el "comando" enviado sería la instrucción/prompt
    del Job, y el marcador de fin solo puede insertarse de forma fiable si
    el propio runtime devuelve el control al shell tras responder (algo
    que v1 no puede garantizar para un proceso interactivo real de verdad;
    ver la nota explícita en `dispatcher/job_dispatch.py` sobre este
    supuesto). Un parseo más preciso de la salida (aislar solo la
    respuesta del agente, sin ruido de shell) queda para una iteración
    posterior, cuando haya uso real que lo justifique.

    Además: si `command` termina el propio shell (p. ej. contiene `exit`
    o mata el proceso que lo contiene), el marcador de fin nunca llegará a
    ejecutarse — no hay shell vivo para el `echo` posterior. Este caso se
    manifiesta como `CommandCaptureTimeoutError` (agotado el timeout sin
    ver el marcador), no como un fallo con motivo específico. Verificado
    experimentalmente durante el desarrollo de esta Task: un comando con
    `exit 1` deja `has_session()` en `False` inmediatamente. No hay
    mitigación en v1 — es una limitación conocida y aceptada del mecanismo
    de marcador de shell.
    """
    start_line = len(capture_pane_lines(session_name, socket_name=socket_name))

    marker = f"JOBDONE_{uuid.uuid4().hex[:12]}"
    full_command = f"{command}; echo {marker}_EXIT$?"

    run_command(session_name, full_command, socket_name=socket_name)

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        content = capture_pane_lines(session_name, socket_name=socket_name)
        marker_indices = [
            i
            for i, line in enumerate(content)
            if line.strip().startswith(f"{marker}_EXIT")
        ]
        if marker_indices:
            marker_idx = marker_indices[-1]
            marker_line = content[marker_idx].strip()
            exit_code = int(marker_line[len(f"{marker}_EXIT") :])
            result_lines = content[start_line:marker_idx]
            return result_lines, exit_code
        time.sleep(poll_interval_seconds)

    raise CommandCaptureTimeoutError(
        f"El comando en la sesión '{session_name}' no terminó en "
        f"{timeout_seconds}s (marcador '{marker}' no detectado)."
    )
