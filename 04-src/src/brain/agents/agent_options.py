from dataclasses import dataclass

from brain.agent_model import get_available_model_entries
from brain.agents.roles import list_roles
from brain.model_preferences import load_model_preferences


@dataclass(frozen=True)
class AgentLaunchOption:
    """Una combinacion disponible de rol + modelo para elegir antes de
    lanzar (T-FB022-US11-01). No incluye logica de lanzamiento — solo
    describe que se puede elegir.

    El runtime se resuelve internamente desde el catalogo de modelos, no se
    pide como input separado al usuario."""

    agent_role: str
    model_id: str
    model_name: str
    runtime_type: str
    runtime_name: str
    supports_model: bool


def list_available_agent_options() -> list[AgentLaunchOption]:
    """Catalogo de combinaciones rol x modelo disponibles para elegir
    desde la interfaz.

    Construye el producto cartesiano de roles registrados x modelos
    habilitados (segun `model_preferences.json`). El runtime de cada
    combinacion se resuelve internamente del catalogo de modelos
    (`models.yml`), no se expone como dimension separada.

    Los valores de `runtime_type`/`runtime_name` provienen del propio
    catalogo — si un modelo esta asociado a `claude_code`:
    `supports_model=False` con el nombre de runtime "Claude Code"; si
    esta asociado a `opencode`: `supports_model=True` con "OpenCode"."""
    agent_roles = list_roles()
    models = get_available_model_entries()
    prefs = load_model_preferences()
    enabled_ids = prefs["enabled_model_ids"]
    all_enabled = not enabled_ids

    def _runtime_display_name(runtime_type: str) -> str:
        return {"opencode": "OpenCode", "claude_code": "Claude Code", "codex": "Codex"}.get(
            runtime_type, runtime_type
        )

    options: list[AgentLaunchOption] = []
    for model in models:
        if not all_enabled and model["id"] not in enabled_ids:
            continue
        supports = model["runtime"] == "opencode"
        for role in agent_roles:
            options.append(
                AgentLaunchOption(
                    agent_role=role,
                    model_id=model["id"],
                    model_name=model["name"],
                    runtime_type=model["runtime"],
                    runtime_name=_runtime_display_name(model["runtime"]),
                    supports_model=supports,
                )
            )
    return options
