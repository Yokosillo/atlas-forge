from dataclasses import dataclass
from typing import Any

from brain.models import Runtime
from brain.tmux import create_session, is_alive, kill_session, run_command
from brain.tmux.manager import DEFAULT_SOCKET_NAME


@dataclass(frozen=True)
class RuntimeInstance:
    """Representa una ejecución concreta de un `Runtime`: la sesión tmux
    donde vive, ligada a un agente y a un directorio de proyecto.

    Mecanismo genérico e independiente de qué runtime concreto (Claude
    Code, OpenCode, Codex) se ejecute — cada especialización
    (`runtime/claude_code.py`, `runtime/opencode.py`, ...) construye su
    propio `Runtime` con la configuración de comando/args que le
    corresponde y reutiliza `start_runtime`/`stop_runtime`/
    `is_runtime_alive` tal cual, sin reimplementar lógica de tmux.
    """

    runtime: Runtime
    session_name: str


def session_name_for(runtime: Runtime, agent: Any) -> str:
    # Desde FB-005 (T-FB005-US01-01) existe un modelo `Agent` real con un
    # `id` propio, estable y legible — se usa preferentemente. El fallback a
    # `id(agent)` (identidad de objeto Python) se conserva por
    # compatibilidad con los tests de FB-004 anteriores a FB-005, que pasan
    # un `object()` de prueba sin atributo `.id` (no se asumía ningún
    # modelo de agente concreto en ese momento del roadmap). El `runtime.id`
    # como prefijo evita que dos runtimes distintos (p. ej. Claude Code y
    # OpenCode) asignados al mismo agente colisionen entre sí.
    agent_identifier = getattr(agent, "id", None) or id(agent)
    return f"{runtime.id}-{agent_identifier}"


def start_runtime(
    runtime: Runtime,
    agent: Any,
    project_path: str,
    socket_name: str = DEFAULT_SOCKET_NAME,
) -> RuntimeInstance:
    """Lanza `runtime` en una sesión tmux nueva, en `project_path`, para
    `agent`.

    `socket_name` permite aislar el servidor tmux usado (p. ej. en tests);
    por defecto usa el servidor propio de Factory Brain.
    """
    session_name = session_name_for(runtime, agent)
    full_command = " ".join([runtime.command, *runtime.args]).strip()

    create_session(session_name, project_path, socket_name=socket_name)
    run_command(session_name, full_command, socket_name=socket_name)

    return RuntimeInstance(runtime=runtime, session_name=session_name)


def stop_runtime(
    runtime_instance: RuntimeInstance, socket_name: str = DEFAULT_SOCKET_NAME
) -> None:
    """Detiene la sesión tmux asociada a `runtime_instance`."""
    kill_session(runtime_instance.session_name, socket_name=socket_name)


def is_runtime_alive(
    runtime_instance: RuntimeInstance, socket_name: str = DEFAULT_SOCKET_NAME
) -> bool:
    """Comprueba si la sesión tmux de `runtime_instance` sigue viva."""
    return is_alive(runtime_instance.session_name, socket_name=socket_name)
