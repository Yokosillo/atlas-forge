from dataclasses import dataclass
from typing import Any, Callable

from brain.models import Runtime
from brain.tmux import create_session, is_alive, kill_session, run_command
from brain.tmux.manager import DEFAULT_SOCKET_NAME

# Registro de "cómo pasar un prompt inicial por línea de comandos" por
# `Runtime.type` (T-FB005-US01-03) — mismo patrón dict-dispatch ya usado
# en `dashboard/launch.py` (`_REGISTER_AGENT_BY_ROLE`) para no acoplar
# este módulo genérico a los detalles de cada runtime concreto (ver
# docstring de `RuntimeInstance`: "cada especialización... construye su
# propio Runtime... sin reimplementar lógica de tmux"). Import perezoso
# (dentro de la función, no a nivel de módulo) para evitar un ciclo de
# imports: `claude_code.py`/`opencode.py` no dependen de `generic.py` hoy,
# pero mantenerlo perezoso es más robusto ante refactors futuros de ese
# grafo de dependencias.
def _prompt_args_builder_by_type() -> dict[str, Callable[[str], list[str]]]:
    from brain.runtime.claude_code import build_prompt_args as claude_code_prompt_args
    from brain.runtime.opencode import build_prompt_args as opencode_prompt_args

    return {
        "claude-code": claude_code_prompt_args,
        "opencode": opencode_prompt_args,
    }


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

    ## Prompt inicial del agente (T-FB005-US01-03)

    Si `agent` tiene un `prompt` no vacío Y `runtime.type` tiene un
    constructor de argumentos de prompt registrado (Claude Code, OpenCode
    — ver `_prompt_args_builder_by_type`), ese prompt se añade al MISMO
    comando de arranque, como argumento de línea de comandos (verificado
    contra el `--help` real de ambas CLIs: Claude Code lo acepta como
    argumento posicional, OpenCode como flag `--prompt`) — nunca tecleado
    después con un `run_command` separado. Esto evita tener que esperar a
    que la interfaz de la CLI esté lista para aceptar input (no hay
    ninguna espera/timeout que gestionar: el prompt ya viaja en el mismo
    comando que arranca el proceso).

    Sin `agent.prompt` (agentes de prueba sin ese atributo, mismo
    `getattr` defensivo que ya usa `session_name_for`) o con un
    `runtime.type` sin constructor registrado (runtimes de prueba
    genéricos, p. ej. `test_runtime_generic.py`), el comportamiento es
    exactamente el mismo que antes de esta Task — no se añade ningún
    argumento de prompt."""
    session_name = session_name_for(runtime, agent)

    command_parts = [runtime.command, *runtime.args]

    prompt = getattr(agent, "prompt", None)
    prompt_args_builder = _prompt_args_builder_by_type().get(runtime.type)
    if prompt and prompt_args_builder is not None:
        command_parts += prompt_args_builder(prompt)

    full_command = " ".join(command_parts).strip()

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


def extract_model_from_runtime(runtime: Runtime) -> str | None:
    """Extrae el modelo LLM asociado a `runtime`, si lo tiene
    (T-FB005-US05-01, `GET /agents` necesita reflejarlo).

    No se introduce ningún campo `model` nuevo en `Runtime` ni en `Agent`
    — el modelo ya vive dentro de `runtime.args` (`register_opencode_runtime`
    añade `["--model", <valor>]` cuando se indica uno, ver
    `runtime/opencode.py`); esta función busca ese flag de forma genérica,
    sin acoplarse a qué tipo concreto de runtime lo usa (hoy solo
    OpenCode, pero la búsqueda no asume `runtime.type == "opencode"` — un
    futuro runtime que también use `--model` funcionaría igual sin
    cambios aquí). Devuelve `None` explícito si no hay flag `--model` en
    `args` (Claude Code hoy, o OpenCode sin modelo indicado) — nunca una
    cadena vacía ni un valor inventado."""
    if "--model" not in runtime.args:
        return None
    model_flag_index = runtime.args.index("--model")
    if model_flag_index + 1 >= len(runtime.args):
        return None
    return runtime.args[model_flag_index + 1]
