"""Superficie de interfaz mínima para elegir y lanzar un agente
(T-FB002-US01-04) — un comando CLI interactivo, no una TUI completa.
Cumple literalmente "desde la interfaz de Factory Brain" (US-FB002-01,
criterios 1 y 3) sin construir más superficie de la que esta Story
necesita. No existe todavía ninguna interfaz previa que reutilizar
(T-FB001-US03-03 no se abordó en este ciclo, confirmado explícitamente
antes de empezar esta Task) — esta es la primera.

La lógica de interacción (formatear el catálogo, interpretar la elección
del desarrollador, invocar `launch_agent` y formatear el resultado) está
separada de la lectura/escritura real de consola, para poder testear el
flujo completo sin un terminal interactivo real.
"""

from dataclasses import dataclass

from brain.dashboard.agent_options import AgentLaunchOption, list_available_agent_options
from brain.dashboard.launch import AgentLaunchError, launch_agent
from brain.models import Agent, DevelopmentSession
from brain.tmux.manager import DEFAULT_SOCKET_NAME


@dataclass(frozen=True)
class AgentChoice:
    """La elección del desarrollador antes de confirmar el lanzamiento."""

    agent_role: str
    runtime_type: str
    model: str | None = None


def format_catalog(options: list[AgentLaunchOption] | None = None) -> str:
    """Formatea el catálogo de combinaciones disponibles para mostrarlo al
    desarrollador (criterio de aceptación 1: ver agentes/runtimes/modelo)."""
    options = options if options is not None else list_available_agent_options()

    lines = ["Agentes y runtimes disponibles:"]
    for option in options:
        model_note = (
            "admite indicar modelo" if option.supports_model else "no admite modelo"
        )
        lines.append(
            f"  - {option.agent_role} sobre {option.runtime_name} "
            f"({option.runtime_type}, {model_note})"
        )
    return "\n".join(lines)


def confirm_launch(
    choice: AgentChoice,
    session: DevelopmentSession,
    project_path: str,
    socket_name: str = DEFAULT_SOCKET_NAME,
) -> str:
    """Confirma el lanzamiento de `choice` sobre `session` (criterios 2/3:
    confirmar y ver el agente operativo, o el motivo de rechazo).

    Devuelve un mensaje formateado listo para mostrar al desarrollador —
    nunca lanza excepción: cualquier rechazo de `launch_agent` se traduce
    a un mensaje claro, coherente con "sin lanzar nada a medias".
    """
    try:
        agent, runtime_instance = launch_agent(
            choice.agent_role,
            choice.runtime_type,
            choice.model,
            session,
            project_path,
            socket_name=socket_name,
        )
    except AgentLaunchError as error:
        return f"No se pudo lanzar el agente: {error}"

    return (
        f"Agente '{agent.name}' ({agent.role}) operativo sobre "
        f"'{runtime_instance.runtime.name}' (sesión tmux "
        f"'{runtime_instance.session_name}'), estado: {agent.status}."
    )
