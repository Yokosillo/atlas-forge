from dataclasses import dataclass

from brain.agents import CRITIC_ROLE, DEVELOPER_ROLE
from brain.runtime import register_claude_code_runtime, register_opencode_runtime


@dataclass(frozen=True)
class AgentLaunchOption:
    """Una combinación disponible de agente + runtime para elegir antes de
    lanzar (T-FB002-US01-02). No incluye lógica de lanzamiento — solo
    describe qué se puede elegir."""

    agent_role: str
    runtime_type: str
    runtime_name: str
    supports_model: bool


def list_available_agent_options() -> list[AgentLaunchOption]:
    """Catálogo de combinaciones agente/runtime disponibles para elegir
    desde la interfaz, indicando si el runtime admite indicar un modelo.

    Los valores de `runtime_type`/`runtime_name` se leen invocando los
    propios `register_*_runtime` (T-FB004), en vez de duplicar los
    strings aquí — si esos identificadores cambian, este catálogo no
    puede desincronizarse silenciosamente.
    """
    claude_code = register_claude_code_runtime()
    opencode = register_opencode_runtime()

    agent_roles = [DEVELOPER_ROLE, CRITIC_ROLE]
    runtimes = [
        (claude_code, False),  # Claude Code no admite indicar modelo (T-FB002-US01-01).
        (opencode, True),  # OpenCode admite `--model provider/model`.
    ]

    return [
        AgentLaunchOption(
            agent_role=agent_role,
            runtime_type=runtime.type,
            runtime_name=runtime.name,
            supports_model=supports_model,
        )
        for agent_role in agent_roles
        for runtime, supports_model in runtimes
    ]
