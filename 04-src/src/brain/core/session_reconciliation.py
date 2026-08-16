"""Reconciliación de sesiones tmux reales con el registro en memoria al
arrancar el proceso (FB-031, T-FB031-US02-02): resuelve el caso motivador
real (reinicio del backend con agentes vivos, ver
`02-backlog/epics/FB-031-reconciliacion-de-agentes-al-arrancar.md`) —
sin esto, `session.agents` arranca vacío mientras las sesiones tmux
siguen respirando, y `GET /agents` no las ve hasta que alguien las
relanza a mano.

## Por qué vive en `core/`, no en `agents/` ni en `api/`

Coordina piezas de varios subsistemas (`tmux.list_sessions`,
`runtime.parse_session_name`/`RuntimeInstance`, `agents.get_role` para el
`prompt_builder`) sobre una `DevelopmentSession` de `core/` — el mismo
paralelismo que ya tiene `session_registry.py` (dueño de la sesión) con
este módulo (dueño de repoblarla). Import de `brain.agents` hecho de
forma PEREZOSA dentro de la función (no a nivel de módulo): `agents/
developer.py` y `agents/arquitecto.py` ya importan `brain.core.
session_lifecycle`, así que un import a nivel de módulo aquí crearía un
ciclo — mismo patrón ya aplicado en `runtime/generic.py`
(`parse_session_name`) para el mismo motivo."""

import uuid
from pathlib import Path

from brain.core.session_lifecycle import assign_agent, list_agents
from brain.models import Agent, DevelopmentSession
from brain.runtime import RuntimeInstance, parse_session_name, sanitize_session_name_part
from brain.runtime.agent_runtime_registry import (
    get_runtime_instance_for_agent,
    register_runtime_instance_for_agent,
)
from brain.runtime.claude_code import register_claude_code_runtime
from brain.tmux.manager import DEFAULT_SOCKET_NAME, list_sessions


def reconcile_session_agents(
    session: DevelopmentSession, socket_name: str = DEFAULT_SOCKET_NAME
) -> tuple[list[Agent], list[dict]]:
    """Reengancha a `session` cada sesión tmux real de `socket_name` cuyo
    nombre normalizado (`parse_session_name`, FB-030/US-FB030-01)
    pertenece al proyecto de `session` (`session.project_id`, que es el
    mismo valor que `project_path` — `Project.id` es el path completo,
    ver `workspace/discovery.py`) y todavía no está representada en
    `session.agents`.

    Devuelve `(reconciled, ignored)`:
    - `reconciled`: lista de `Agent` reenganchados en esta llamada (vacía
      si no había ninguno nuevo) — usada solo para trazabilidad/logging
      por el llamador, `session.agents` ya queda actualizado por efecto
      lateral igual que el resto de funciones de asignación de este
      paquete (`assign_agent`).
    - `ignored` (T-FB037-US02-01): lista de `{"session_name": str,
      "reason": str}` — una entrada por cada sesión tmux del socket que
      NO terminó reenganchada, con el motivo (`"ya_reconciliada"`:
      sesión que session.agents ya representaba antes de esta llamada;
      `"nombre_no_reconocido"`: no pasa `parse_session_name`;
      `"otro_proyecto"`: normalizada pero de un proyecto distinto;
      `"rol_invalido"`: rol sin `prompt_builder` registrado;
      `"error_reenganche: <mensaje>"`: excepción puntual durante el
      reenganche, ver tolerancia a fallo más abajo). Puramente aditivo
      para trazabilidad — no cambia qué sesiones se reenganchan ni cómo.

    ## Tolerancia a fallo puntual (punto 4 de la Task, criterio explícito)

    Si reenganchar una sesión concreta falla (p. ej. `parse_session_name`
    devuelve un resultado inesperado, o el rol ya no tiene
    `prompt_builder` registrado), esa sesión se ignora y se continúa con
    el resto — un fallo puntual no debe tumbar el arranque completo del
    proceso ni impedir que las demás sesiones sí se reenganchen.

    ## Runtime del agente reenganchado: limitación conocida y documentada

    El nombre de sesión tmux normalizado no codifica qué `Runtime`
    concreto (Claude Code vs. OpenCode) lanzó originalmente el proceso —
    esa elección es libre por parte de quien lanza el agente
    (`launch_agent`, `agents/launch.py`, recibe `runtime_type` como
    parámetro explícito, no fijo por rol) y no queda registrada en
    ninguna parte alcanzable tras perder el proceso que lo sabía. No se
    intenta adivinarlo inspeccionando el pane (fuera del alcance de esta
    Task, ningún criterio de aceptación lo pide) — se reconstruye siempre
    con `register_claude_code_runtime()` como valor por defecto
    documentado. El proceso tmux real ya vivo no se ve afectado (nunca se
    relanza, `create_session` no se invoca aquí), así que esto solo
    afecta al metadato `model`/`runtime_id` que expone `GET /agents`, no
    a la operatividad real del agente reenganchado.
    """
    from brain.agents.roles import get_role

    project_path = session.project_id
    project_name_for_session = (
        sanitize_session_name_part(Path(project_path).name) if project_path else ""
    )

    already_present_session_names = {
        instance.session_name
        for instance in (
            get_runtime_instance_for_agent(agent.id) for agent in list_agents(session)
        )
        if instance is not None
    }

    reconciled: list[Agent] = []
    ignored: list[dict] = []
    for tmux_session_name in list_sessions(socket_name=socket_name):
        if tmux_session_name in already_present_session_names:
            ignored.append({"session_name": tmux_session_name, "reason": "ya_reconciliada"})
            continue

        try:
            parsed = parse_session_name(tmux_session_name)
            if parsed is None:
                ignored.append({"session_name": tmux_session_name, "reason": "nombre_no_reconocido"})
                continue
            if parsed.project_name != project_name_for_session:
                ignored.append({"session_name": tmux_session_name, "reason": "otro_proyecto"})
                continue

            role_config = get_role(parsed.role)
            if role_config is None or role_config.prompt_builder is None:
                ignored.append({"session_name": tmux_session_name, "reason": "rol_invalido"})
                continue

            agent_name = parsed.role.capitalize()
            if parsed.instance is not None:
                agent_name = f"{agent_name}-{parsed.instance}"

            runtime = register_claude_code_runtime()
            agent = Agent(
                id=str(uuid.uuid4()),
                name=agent_name,
                role=parsed.role,
                prompt=role_config.prompt_builder(project_path),
                runtime_id=runtime.id,
                status="idle",
            )

            assign_agent(session, agent)
            register_runtime_instance_for_agent(
                agent.id,
                RuntimeInstance(runtime=runtime, session_name=tmux_session_name),
            )
            reconciled.append(agent)
        except Exception as error:
            # Tolerancia a fallo puntual (punto 4 de la Task): una sesión
            # que no se puede reenganchar no debe impedir reenganchar el
            # resto, ni tumbar el arranque del proceso.
            ignored.append({
                "session_name": tmux_session_name,
                "reason": f"error_reenganche: {error}",
            })
            continue

    return reconciled, ignored
