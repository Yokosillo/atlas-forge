import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from brain.models import Runtime
from brain.tmux import create_session, is_alive, kill_session, run_command, send_keys_literal
from brain.tmux.manager import DEFAULT_SOCKET_NAME

# Tiempo de espera antes del Enter de confirmación del diálogo de confianza
# de carpeta de Claude Code (ver `start_runtime`). Empírico: tiempo
# suficiente para que la CLI pinte el diálogo si va a aparecer, sin
# ralentizar perceptiblemente el arranque cuando no aparece.
_CLAUDE_CODE_TRUST_DIALOG_WAIT_SECONDS = 1.5

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


def sanitize_session_name_part(value: str) -> str:
    """Normaliza `value` para que sea válida dentro de un nombre de sesión
    tmux (`-t`): tmux usa `:` como separador `session:window.pane`, y un
    nombre con espacios obliga a citarlo en cada comando manual de conexión
    (`tmux attach -t <nombre>`, ver criterio 4 de `T-FB030-US01-01`). Se
    sustituye cualquier carácter que no sea alfanumérico, `-` o `_` por
    `-`, se pasa a minúsculas, y se colapsan guiones repetidos resultantes
    de sustituir varios caracteres seguidos (p. ej. espacios múltiples).

    Pública (sin guion bajo) desde T-FB031-US02-02: `core/
    session_reconciliation.py` la reutiliza para normalizar el nombre del
    proyecto real de la misma forma que `session_name_for` lo hizo al
    construir el nombre de sesión original — comparar `parsed.project_name`
    (ya sanitizado por `parse_session_name`) contra el nombre del proyecto
    sin normalizar produciría falsos negativos en cuanto hubiera mayúsculas
    o espacios."""
    sanitized = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-")
    return sanitized.lower()


def session_name_for(runtime: Runtime, agent: Any, project_path: str) -> str:
    """Nombre de sesión tmux determinista `<rol>-<proyecto>` (roles de
    instancia única, p. ej. Arquitecto) o `<rol>-N-<proyecto>` (roles
    multi-instancia, p. ej. Developer) — FB-030/US-FB030-01, sustituye el
    esquema opaco anterior (`f"{runtime.id}-{agent.id}"`, UUID aleatorio
    sin relación con el proyecto).

    El `<rol>-N` sale de `agent.name` ("Arquitecto", "Developer-2", ...)
    ya en minúsculas — no se recalcula el número de instancia aquí: reusa
    tal cual el mismo criterio de numeración que `_next_developer_name`
    (`agents/developer.py`) ya aplicó al fijar `agent.name` antes de
    lanzar el runtime, así que ambos quedan sincronizados por construcción
    (mismo número visible en `agent.name` y en el nombre de sesión), sin
    duplicar la lógica de conteo. `project_path` es el mismo que ya recibe
    `start_runtime` — el nombre del proyecto es `Path(project_path).name`,
    igual criterio que `Project.name` en `workspace/discovery.py`.

    Fallback a `f"{runtime.id}-{id(agent)}"` (identidad de objeto Python,
    con `runtime.id` como prefijo para no colisionar entre runtimes
    distintos sobre el mismo agente) cuando `agent` no tiene `.name` —
    conservado por compatibilidad con tests de FB-004 anteriores a FB-005
    que pasan un `object()` de prueba sin ese atributo (no se asumía
    ningún modelo de agente concreto en ese punto del roadmap)."""
    agent_name = getattr(agent, "name", None)
    role_source = agent_name if agent_name else f"{runtime.id}-{id(agent)}"
    project_name = Path(project_path).name if project_path else ""

    role_part = sanitize_session_name_part(str(role_source))
    project_part = sanitize_session_name_part(project_name)

    if not project_part:
        return role_part
    return f"{role_part}-{project_part}"


@dataclass(frozen=True)
class ParsedSessionName:
    """Resultado de `parse_session_name`: a qué rol y proyecto pertenece
    un nombre de sesión tmux normalizado (FB-030), y su número de
    instancia si el rol es multi-instancia (Developer). `instance` es
    `None` para roles de instancia única (Arquitecto y análogos) — no `1`
    ni ningún otro valor por defecto, para que el caller pueda distinguir
    "no aplica" de "instancia 1" sin ambigüedad."""

    role: str
    project_name: str
    instance: int | None


def parse_session_name(name: str) -> ParsedSessionName | None:
    """Función inversa de `session_name_for` (FB-031/US-FB031-02): dado un
    nombre de sesión tmux, reconoce si sigue el patrón normalizado
    `<rol>-<proyecto>` o `<rol>-<n>-<proyecto>` y extrae rol/proyecto/
    instancia — o devuelve `None` si no coincide con ningún patrón
    (sesión tmux ajena al sistema, o de la generación anterior al nombre
    determinista, `f"{runtime.id}-{agent.id}"`). Nunca lanza excepción:
    "no reconocido" es un resultado válido y esperado, no un error.

    ## Estrategia de desambiguación (criterio explícito de la Task)

    `project_name` puede contener guiones internos (nombres reales del
    workspace, p. ej. `PROD-006-factory-brain`), así que no basta con
    partir `name` por `-` y asumir posiciones fijas: hace falta saber
    dónde termina el rol/número de instancia y empieza el proyecto.
    Se resuelve así, en vez de separación posicional ingenua:

    1. Lista CERRADA de roles válidos conocidos — `brain.agents.list_roles()`,
       el mismo registro dinámico que ya puebla `agents/developer.py` y
       `agents/arquitecto.py` vía `register_role` (import perezoso, dentro
       de la función: `runtime/generic.py` no puede importar `brain.agents`
       a nivel de módulo sin crear un ciclo, ya que `agents/developer.py`
       y `agents/arquitecto.py` ya importan `brain.runtime` para
       `RuntimeInstance`). Si el primer segmento de `name` no está en esa
       lista, `name` no es un nombre normalizado — se devuelve `None` de
       inmediato, sin intentar ningún otro patrón.
    2. Con el rol identificado como primer segmento, el segundo segmento
       decide entre los dos patrones: si es un entero puro (`\\d+`), es el
       patrón multi-instancia (`<rol>-<n>-<proyecto>`) y el resto de
       segmentos (desde el tercero) es `project_name`; si no lo es, es el
       patrón de instancia única (`<rol>-<proyecto>`) y el resto de
       segmentos (desde el segundo) es `project_name`.
    3. Esto es seguro porque un `project_name` real, tal como lo sanitiza
       `sanitize_session_name_part`, nunca puede EMPEZAR por un segmento
       que sea un entero puro seguido de un guion y solo eso — sería
       indistinguible en el propio nombre del proyecto real de un
       workspace (p. ej. un proyecto llamado literalmente "2"), caso no
       observado en el workspace actual y aceptado como limitación
       conocida, igual que otras heurísticas de nombre de este proyecto
       (ver `_next_developer_name`, `agents/developer.py`).
    4. `project_name` puede quedar vacío (cadena vacía) si `name` es
       exactamente un rol válido sin ningún segmento más — refleja el caso
       degenerado ya contemplado en `session_name_for` cuando
       `project_path` está vacío (devuelve solo `role_part`, sin proyecto).
    """
    from brain.agents import list_roles

    valid_roles = set(list_roles())
    parts = name.split("-")
    if not parts or parts[0] not in valid_roles:
        return None

    role = parts[0]
    remainder = parts[1:]

    if remainder and remainder[0].isdigit():
        instance = int(remainder[0])
        project_name = "-".join(remainder[1:])
        return ParsedSessionName(role=role, project_name=project_name, instance=instance)

    project_name = "-".join(remainder)
    return ParsedSessionName(role=role, project_name=project_name, instance=None)


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
    session_name = session_name_for(runtime, agent, project_path)

    command_parts = [runtime.command, *runtime.args]

    prompt = getattr(agent, "prompt", None)
    prompt_args_builder = _prompt_args_builder_by_type().get(runtime.type)
    if prompt and prompt_args_builder is not None:
        command_parts += prompt_args_builder(prompt)

    full_command = " ".join(command_parts).strip()

    create_session(session_name, project_path, socket_name=socket_name)
    run_command(session_name, full_command, socket_name=socket_name)

    # Claude Code puede mostrar el diálogo "Do you trust this folder?" antes
    # de procesar el prompt inicial, dejando el agente atascado ahí (visto en
    # producción: dos veces en un día) hasta que alguien manda un Enter a
    # mano. Un Enter extra confirma la opción por defecto del diálogo si
    # aparece; si el proyecto ya es de confianza y no aparece, el Enter no
    # tiene ningún efecto negativo (verificado contra ambos casos). Solo
    # para Claude Code: OpenCode y los runtimes de prueba genéricos
    # (`test_runtime_generic.py`) no tienen este diálogo y no deben recibir
    # teclas adicionales no solicitadas.
    if runtime.type == "claude-code":
        time.sleep(_CLAUDE_CODE_TRUST_DIALOG_WAIT_SECONDS)
        send_keys_literal(session_name, "Enter", socket_name=socket_name)

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
