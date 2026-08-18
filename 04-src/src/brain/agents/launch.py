from brain.agents import register_developer
from brain.agents.roles import get_register_fn_for_role, list_roles
from brain.dispatcher.job_dispatch import dispatch_job
from brain.dispatcher.job_orchestration import create_and_record_job
from brain.models import Agent, DevelopmentSession, Job
from brain.runtime import (
    RuntimeInstance,
    register_claude_code_runtime,
    register_codex_runtime,
    register_opencode_runtime,
)
from brain.tmux.manager import DEFAULT_SOCKET_NAME

_CLAUDE_CODE_TYPE = register_claude_code_runtime().type
_OPENCODE_TYPE = register_opencode_runtime().type
_CODEX_TYPE = register_codex_runtime().type


class AgentLaunchError(ValueError):
    """No se puede lanzar el agente con la combinación indicada."""


def launch_agent(
    role: str,
    runtime_type: str,
    model: str | None,
    session: DevelopmentSession,
    project_path: str,
    socket_name: str = DEFAULT_SOCKET_NAME,
    developer_number: int | None = None,
) -> tuple[Agent, RuntimeInstance]:
    """Lanza el agente `role` sobre `runtime_type` (con `model` si se
    indica) en la sesión de desarrollo activa `session`.

    Valida la combinación antes de lanzar nada: sesión `active`, `role`
    reconocido, `runtime_type` reconocido. `model` es opcional para
    OpenCode y Claude Code (T-FB024-US11-13, 2026-08-17: Claude Code
    admite `--model` al arrancar, corrección de la premisa original de
    T-FB002-US01-01 que asumía lo contrario sin verificarlo). Cualquier
    rechazo se señala con `AgentLaunchError` (motivo explícito).

    Reutiliza `register_developer`/`register_arquitecto` (FB-005). Desde
    T-FB005-US01-04, no se comportan igual: `register_arquitecto` reutiliza
    el Arquitecto existente de `session` si ya hay uno
    (`register_agent_with_reuse`); `register_developer` crea SIEMPRE una
    instancia nueva (`register_agent` directo), permitiendo varios
    Developer simultáneos en la misma sesión — decisión explícita del
    usuario, acotada solo a Developer.

    `project_path` se recibe como parámetro explícito (no se resuelve
    internamente desde el proyecto activo persistido, FB-001): esta
    función solo coordina agente+runtime+sesión, y depender aquí de leer
    disco introduciría un acoplamiento oculto que el llamador no
    controlaría — es responsabilidad de quien invoque `launch_agent`
    (la futura interfaz, T-FB002-US01-04) resolver el proyecto activo y
    pasarlo explícitamente.
    """
    if session.status != "active":
        raise AgentLaunchError(
            f"No se puede lanzar el agente: la sesión está en estado "
            f"'{session.status}', debe estar 'active'."
        )

    if role not in (available := list_roles()):
        raise AgentLaunchError(
            f"No se puede lanzar el agente: rol '{role}' no reconocido. "
            f"Roles disponibles: {available}."
        )

    if runtime_type == _CLAUDE_CODE_TYPE:
        runtime = register_claude_code_runtime(model=model)
    elif runtime_type == _OPENCODE_TYPE:
        runtime = register_opencode_runtime(model=model)
    elif runtime_type == _CODEX_TYPE:
        runtime = register_codex_runtime(model=model)
    else:
        raise AgentLaunchError(
            f"No se puede lanzar el agente: runtime '{runtime_type}' no "
            f"reconocido. Runtimes disponibles: "
            f"{[_CLAUDE_CODE_TYPE, _OPENCODE_TYPE, _CODEX_TYPE]}."
        )

    register_agent_for_role = get_register_fn_for_role(role)
    if register_agent_for_role is None:
        raise AgentLaunchError(
            f"No se puede lanzar el agente: rol '{role}' no tiene función de "
            f"registro asociada."
        )
    if role == "developer":
        # T-FB005-US01-08 (2026-08-18): cada Developer es un slot
        # independiente con posición fija (Developer-1/2/3) en la interfaz
        # Web — el lanzamiento desde una fila concreta fija el número de la
        # instancia (`developer_number`), en vez de dejar que el conteo del
        # backend decida el nombre. Para el resto de roles el parámetro no
        # aplica y se ignora.
        return register_developer(
            session,
            runtime,
            project_path,
            socket_name=socket_name,
            developer_number=developer_number,
        )
    return register_agent_for_role(
        session, runtime, project_path, socket_name=socket_name
    )


def launch_agent_with_initial_job(
    role: str,
    runtime_type: str,
    model: str | None,
    session: DevelopmentSession,
    project_path: str,
    initial_job_description: str | None = None,
    socket_name: str = DEFAULT_SOCKET_NAME,
    developer_number: int | None = None,
    job_timeout_seconds: float = 30.0,
    job_poll_interval_seconds: float = 0.2,
) -> tuple[Agent, RuntimeInstance, Job | None]:
    """Lanza el agente (mismo mecanismo que `launch_agent`, sin cambiar su
    firma ni su retorno de 2-tupla — T-FB008-US06-01) y, si
    `initial_job_description` viene informado, crea y despacha su Job
    inicial inmediatamente tras el registro, en un solo paso.

    El despacho reutiliza EXACTAMENTE el mismo mecanismo que hoy usa
    `POST /jobs` (`create_and_record_job` + `dispatch_job` bloqueante),
    sin reimplementar nada: si `dispatch_job` falla (timeout esperando el
    reporte del agente, runtime que no responde, etc.) captura el fallo
    internamente y deja `job.status == "failed"` con el motivo en
    `job.result` — el agente permanece registrado y vuelve a `idle`, y el
    Job fallido queda en el histórico de la sesión, consultable igual que
    cualquier otro Job (criterio de aceptación explícito de la Task:
    un fallo de despacho NUNCA revierte el registro del agente).

    Publicación en `jobs_hub`: NO es responsabilidad de esta función de
    dominio — el dominio no conoce a sus observadores (ver
    `brain/api/events.py`); quien invoque este flujo combinado desde la
    capa de API publica los eventos de transición del Job, igual que ya
    hace `POST /jobs`.

    Si `initial_job_description` es `None`, el comportamiento es idéntico
    al de `launch_agent` sin ningún efecto secundario nuevo — el tercer
    elemento del retorno es `None` para que el llamador distinga
    unívocamente "no había Job inicial" de "el Job inicial falló" (en ese
    caso el Job devuelto sí está, en estado `failed`)."""

    agent, runtime_instance = launch_agent(
        role,
        runtime_type,
        model,
        session,
        project_path,
        socket_name=socket_name,
        developer_number=developer_number,
    )

    if initial_job_description is None:
        return agent, runtime_instance, None

    job = create_and_record_job(initial_job_description, agent, session)
    dispatch_job(
        job,
        agent,
        runtime_instance,
        timeout_seconds=job_timeout_seconds,
        poll_interval_seconds=job_poll_interval_seconds,
        socket_name=socket_name,
    )
    return agent, runtime_instance, job
