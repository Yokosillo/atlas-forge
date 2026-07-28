from brain.agents import register_critic, register_developer
from brain.agents.critic import CRITIC_ROLE
from brain.agents.developer import DEVELOPER_ROLE
from brain.models import Agent, DevelopmentSession
from brain.runtime import RuntimeInstance, register_claude_code_runtime, register_opencode_runtime
from brain.tmux.manager import DEFAULT_SOCKET_NAME

_CLAUDE_CODE_TYPE = register_claude_code_runtime().type
_OPENCODE_TYPE = register_opencode_runtime().type

_REGISTER_AGENT_BY_ROLE = {
    DEVELOPER_ROLE: register_developer,
    CRITIC_ROLE: register_critic,
}


class AgentLaunchError(ValueError):
    """No se puede lanzar el agente con la combinación indicada."""


def launch_agent(
    role: str,
    runtime_type: str,
    model: str | None,
    session: DevelopmentSession,
    project_path: str,
    socket_name: str = DEFAULT_SOCKET_NAME,
) -> tuple[Agent, RuntimeInstance]:
    """Lanza el agente `role` sobre `runtime_type` (con `model` si se
    indica) en la sesión de desarrollo activa `session`.

    Valida la combinación antes de lanzar nada: sesión `active`, `role`
    reconocido, `runtime_type` reconocido, y `model` solo si el runtime
    elegido lo soporta (Claude Code no; OpenCode sí — T-FB002-US01-01).
    Cualquier rechazo se señala con `AgentLaunchError` (motivo explícito).

    Reutiliza `register_developer`/`register_critic` (FB-005), que a su
    vez usan `register_agent_with_reuse`: si el rol ya está lanzado en
    `session`, se devuelve el agente existente sin relanzar su runtime.

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

    if role not in _REGISTER_AGENT_BY_ROLE:
        raise AgentLaunchError(
            f"No se puede lanzar el agente: rol '{role}' no reconocido. "
            f"Roles disponibles: {sorted(_REGISTER_AGENT_BY_ROLE)}."
        )

    if runtime_type == _CLAUDE_CODE_TYPE:
        if model is not None:
            raise AgentLaunchError(
                "No se puede lanzar el agente: Claude Code no admite "
                "indicar un modelo."
            )
        runtime = register_claude_code_runtime()
    elif runtime_type == _OPENCODE_TYPE:
        runtime = register_opencode_runtime(model=model)
    else:
        raise AgentLaunchError(
            f"No se puede lanzar el agente: runtime '{runtime_type}' no "
            f"reconocido. Runtimes disponibles: "
            f"{[_CLAUDE_CODE_TYPE, _OPENCODE_TYPE]}."
        )

    register_agent_for_role = _REGISTER_AGENT_BY_ROLE[role]
    return register_agent_for_role(
        session, runtime, project_path, socket_name=socket_name
    )
