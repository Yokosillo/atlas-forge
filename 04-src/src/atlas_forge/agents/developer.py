from pathlib import Path

from atlas_forge.agents.governance import (
    project_governance_instruction,
    project_identity_instruction,
)
from atlas_forge.agents.registry import register_agent
from atlas_forge.agents.roles import RoleConfig, register_role
from atlas_forge.core.session_lifecycle import list_agents
from atlas_forge.models import Agent, DevelopmentSession, Runtime
from atlas_forge.runtime import RuntimeInstance
from atlas_forge.system_preferences import get_max_simultaneous_developers
from atlas_forge.tmux.manager import DEFAULT_SOCKET_NAME

DEVELOPER_ROLE = "developer"
# Estados que ocupan una plaza real del límite de Developers simultáneos
# (T-AF005-US01-09): solo los ACTIVOS. Un `unavailable` (cayó fuera de
# atlas_forge) o `stopped` (detenido a propósito) ya no mantiene un runtime vivo,
# así que no debe bloquear lanzar otros Developer. `limited` se cuenta como
# activo porque sigue ocupando un runtime/sesión real.
ACTIVE_DEVELOPER_STATUSES = frozenset({"idle", "working", "limited"})
# Valor por defecto (US-AF024-12): el limite real y editable vive en
# `system_preferences.json` via `get_max_simultaneous_developers` —
# `register_developer` lo lee ahi, esta constante solo es el fallback
# cuando no hay preferencia guardada. Se mantiene exportada porque
# `test_developer_agent.py` la usa para acotar cuantas instancias lanzar
# en el test del limite, sin depender del `state_dir` real del proceso.
MAX_SIMULTANEOUS_DEVELOPERS = 3
DEVELOPER_PROMPT = (
    "Eres el agente Developer de Atlas Forge. Tu responsabilidad es "
    "implementar funcionalidades: escribir código, modificar "
    "documentación, crear tests, refactorizar y generar propuestas. "
    "No validas tu propio trabajo — esa responsabilidad corresponde al "
    "agente Arquitecto.\n"
    "\n"
    "Cuando termines tu trabajo, comunica el resultado de forma "
    "estructurada y sin ambigüedad, en texto plano, con estos tres campos "
    "(cada uno en su propia línea, precedido por el nombre entre guiones):\n"
    "- Resultado: 'éxito' o 'fallo'.\n"
    "- Resumen: qué implementaste, de forma concisa.\n"
    "- Siguiente paso sugerido: una única acción recomendada para quien "
    "revise tu trabajo (normalmente el Arquitecto).\n"
    "\n"
    "Este protocolo de reporte es genérico de Atlas Forge y no asume "
    "ningún formato de fichero, marcador ni carpeta propios de un proyecto "
    "concreto: si el proyecto que te emplea define su propia convención de "
    "entrega, te lo indicará explícitamente; en caso contrario, este es el "
    "formato que debes usar para que otro agente o un humano pueda leer tu "
    "reporte."
)


def build_developer_prompt(project_path: str) -> str:
    """Prompt en TRES capas para Developer: rol base (`DEVELOPER_PROMPT`)
    + identidad del proyecto activo (`project_identity_instruction`,
    T-AF005-US01-07, siempre presente) + gobierno específico del
    proyecto si aplica (`project_governance_instruction`, solo si existen
    `00-gobierno/DEVELOPER.md` y `00-gobierno/METODOLOGIA.md` en
    `project_path`). La decisión de incluir la capa de gobierno se toma
    AQUÍ en Python, antes de construir el string final — el agente solo
    recibe la instrucción ya decidida."""
    return (
        DEVELOPER_PROMPT
        + project_identity_instruction(project_path)
        + project_governance_instruction(project_path, DEVELOPER_ROLE)
    )


def _developer_name_number(name: str) -> int | None:
    """Extrae el número de instancia de un nombre de Developer
    ("Developer-3" -> 3); `None` si el nombre no sigue el patrón
    `Developer-N`. Nombres fuera de patrón (legacy o de otros roles que
    nunca deberían llegar aquí) se ignoran en la numeración en vez de
    romperla."""
    prefix = "Developer-"
    if not name.startswith(prefix):
        return None
    try:
        return int(name[len(prefix):])
    except ValueError:
        return None


def _next_developer_name(session: DevelopmentSession) -> str:
    """Numeración incremental (`Developer-1`, `Developer-2`, ...) — esquema
    elegido, entre las alternativas consideradas (sufijo corto del
    `agent.id`, timestamp), porque es lo único legible de un vistazo en
    `GET /agents`/la lista de la TUI/app: un `agent.id` truncado
    (`Developer-a3f9`) identifica de forma única pero no dice nada sobre
    el ORDEN de lanzamiento, que es justo el dato útil para el
    desarrollador que lanzó varios Developer y quiere saber cuál es cuál
    ("el segundo que lancé", no "el que tiene id a3f9"). El número se
    calcula como `max(números en uso entre los Developers vivos) + 1`,
    no como `count + 1` (T-AF005-US01-08): desde T-AF024-US12-02,
    `stop_agent` retira por completo el Developer de `session.agents`, así
    que un conteo bajaría al matar uno y `count + 1` reutilizaría un
    número aún en uso por otro Developer vivo. Ese nombre visible alimenta
    el nombre de sesión tmux (`session_name_for`, `atlas_forge/runtime/
    generic.py`), así que un nombre duplicado ya no es cosmético: es una
    colisión real de sesión tmux. El `max + 1` garantiza que un número en
    uso nunca se reutilice mientras su Developer siga vivo. No se persiste
    un contador aparte: si no queda ningún Developer vivo, la numeración
    "vuelve" a empezar en `Developer-1`, aceptable porque en ese momento
    no hay ninguna sesión tmux con la que colisionar."""
    highest_number = 0
    for agent in list_agents(session):
        if isinstance(agent, Agent) and agent.role == DEVELOPER_ROLE:
            number = _developer_name_number(agent.name)
            if number is not None:
                highest_number = max(highest_number, number)
    return f"Developer-{highest_number + 1}"


def register_developer(
    session: DevelopmentSession,
    runtime: Runtime,
    project_path: str,
    socket_name: str = DEFAULT_SOCKET_NAME,
    state_dir: Path | None = None,
    developer_number: int | None = None,
) -> tuple[Agent, RuntimeInstance]:
    """Registra un agente Developer NUEVO en `session` (T-AF005-US01-04):
    a diferencia de Arquitecto (sigue con `register_agent_with_reuse`,
    reutilizado sin cambios), cada llamada crea un `Agent` y
    `RuntimeInstance` nuevos — nunca devuelve una instancia existente. El
    usuario necesita varios Developer trabajando en paralelo dentro de la
    misma sesión (límite real detectado en uso: antes, lanzar "Developer"
    dos veces devolvía siempre el mismo agente).

    `session_name_for` (`atlas_forge/runtime/generic.py`, AF-030) construye el
    nombre de la sesión tmux a partir de `agent.name` ("Developer-N",
    número ya asignado arriba por `_next_developer_name`) + el nombre del
    proyecto — no colisiona entre Developers distintos del mismo proyecto
    porque cada uno recibe un N distinto, verificado con test explícito.

    T-AF022-US06-02: rechaza explícitamente un intento de superar el
    límite configurado en `session` con feedback claro — no falla en
    silencio. US-AF024-12: el límite ya no es la constante fija
    `MAX_SIMULTANEOUS_DEVELOPERS`, se lee de `system_preferences.json`
    (`state_dir`, mismo criterio que `_STATE_DIR` en `atlas_forge.api.routes` —
    `None` resuelve al `state_dir` real del proceso, parámetro expuesto
    solo para que los tests puedan aislarse en uno propio).

    `developer_number` (2026-08-18, T-AF005-US01-08): cada Developer es
    un "slot" independiente y con posición fija (Developer-1/2/3, ver la
    US-AF005-01) — la interfaz Web lanza desde una fila concreta y el
    agente debe nacer con ESE número, no con el que el conteo del backend
    decida en ese instante. Si viene informado, el nombre se fija como
    "Developer-<developer_number>" (rechazando duplicados entre los vivos
    y números < 1); si viene `None`, se mantiene el esquema incremental
    `_next_developer_name` (`max + 1`), usado por la TUI y por los tests
    que no eligen slot. Ambos caminos garantizan que un número nunca se
    reutiliza mientras su Developer siga vivo.
    """
    max_developers = get_max_simultaneous_developers(state_dir=state_dir)
    developers = [
        agent
        for agent in list_agents(session)
        if isinstance(agent, Agent) and agent.role == DEVELOPER_ROLE
    ]
    # T-AF005-US01-09: el límite cuenta SOLO a los Developers activos
    # (`idle`/`working`/`limited`). Un `unavailable`/`stopped` ya no ocupa
    # una plaza real de runtime — no debe bloquear lanzar otros Developer.
    # La comprobación de nombre duplicado de abajo sigue usando TODOS los
    # Developers (incluido el `unavailable`), para que el slot concreto
    # siga bloqueado hasta liberarlo ("Liberar → Lanzar").
    existing = sum(
        1 for agent in developers if agent.status in ACTIVE_DEVELOPER_STATUSES
    )
    if existing >= max_developers:
        raise RuntimeError(
            f"No se puede lanzar otro Developer: ya hay "
            f"{existing} Developer(s) activos en la sesión (máximo "
            f"{max_developers}). Detén alguno antes de "
            f"lanzar uno nuevo."
        )

    if developer_number is not None:
        if developer_number < 1:
            raise RuntimeError(
                f"Número de Developer inválido: {developer_number} "
                f"(mínimo 1)."
            )
        name = f"Developer-{developer_number}"
        if any(agent.name == name for agent in developers):
            raise RuntimeError(
                f"Ya existe un Developer '{name}' vivo en la sesión — "
                f"deténlo antes de relanzarlo."
            )
    else:
        name = _next_developer_name(session)
    return register_agent(
        name=name,
        role=DEVELOPER_ROLE,
        prompt=build_developer_prompt(project_path),
        runtime=runtime,
        session=session,
        project_path=project_path,
        socket_name=socket_name,
    )


register_role(RoleConfig(
    role=DEVELOPER_ROLE,
    governance_filename="DEVELOPER.md",
    prompt=DEVELOPER_PROMPT,
    prompt_builder=build_developer_prompt,
    register_fn=register_developer,
    persistent=False,
))
