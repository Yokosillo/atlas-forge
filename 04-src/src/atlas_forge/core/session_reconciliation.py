"""Reconciliación de sesiones tmux reales con el registro en memoria al
arrancar el proceso (AF-031, T-AF031-US02-02): resuelve el caso motivador
real (reinicio del backend con agentes vivos, ver
`02-backlog/epics/AF-031-reconciliacion-de-agentes-al-arrancar.md`) —
sin esto, `session.agents` arranca vacío mientras las sesiones tmux
siguen respirando, y `GET /agents` no las ve hasta que alguien las
relanza a mano.

## Por qué vive en `core/`, no en `agents/` ni en `api/`

Coordina piezas de varios subsistemas (`tmux.list_sessions`,
`runtime.parse_session_name`/`RuntimeInstance`, `agents.get_role` para el
`prompt_builder`) sobre una `DevelopmentSession` de `core/` — el mismo
paralelismo que ya tiene `session_registry.py` (dueño de la sesión) con
este módulo (dueño de repoblarla). Import de `atlas_forge.agents` hecho de
forma PEREZOSA dentro de la función (no a nivel de módulo): `agents/
developer.py` y `agents/arquitecto.py` ya importan `atlas_forge.core.
session_lifecycle`, así que un import a nivel de módulo aquí crearía un
ciclo — mismo patrón ya aplicado en `runtime/generic.py`
(`parse_session_name`) para el mismo motivo."""

import uuid
from pathlib import Path
from typing import Any

from atlas_forge.core.session_lifecycle import assign_agent, list_agents
from atlas_forge.models import Agent, DevelopmentSession
from atlas_forge.runtime import RuntimeInstance, parse_session_name, sanitize_session_name_part
from atlas_forge.runtime.agent_runtime_registry import (
    get_runtime_instance_for_agent,
    register_runtime_instance_for_agent,
)
from atlas_forge.runtime.claude_code import register_claude_code_runtime
from atlas_forge.tmux.manager import (
    DEFAULT_SOCKET_NAME,
    capture_pane_lines,
    is_alive,
    list_sessions,
)


def _infer_runtime_and_model_for_session(
    session_name: str, socket_name: str = DEFAULT_SOCKET_NAME
) -> tuple[Any, str | None]:
    """Infiera el runtime real de una sesión tmux inspeccionando su pane
    (US-AF031-03, T-AF031-US03-01): resuelve el bug confirmado de que
    `GET /agents` mostraba `runtime_id: "claude-code"` para un agente que
    en realidad seguía corriendo OpenCode tras reiniciar `atlas-forge-api`.

    Heurística determinista de primer nivel (mismo enfoque ya usado en
    US-AF030-04/US-AF024-21): si el pane está vivo y muestra la barra de
    estado de OpenCode (`"Build · "`), el agente es OpenCode — se devuelve
    un `Runtime` OpenCode y, si el nombre extraído tras el patrón coincide
    con el `name` de una entrada del catálogo de modelos, ese id real como
    modelo (para que `GET /agents` devuelva un modelo concreto y
    consistente con un lanzamiento normal); en caso contrario `None`
    (nunca un valor inventado, criterio 2 de la US).

    Si el pane no muestra ningún patrón reconocible (agente recién
    lanzado sin salida aún, formato de CLI cambiado, o es Claude Code),
    se conserva el comportamiento documentado: `claude-code` por defecto
    y modelo `None` (criterio 3 — no se rompe el caso ya cubierto)."""
    from atlas_forge.agent_model import _MODEL_STATUS_PATTERN, _parse_model_from_pane
    from atlas_forge.runtime.opencode import register_opencode_runtime

    try:
        if not is_alive(session_name, socket_name=socket_name):
            return register_claude_code_runtime(), None
        lines = capture_pane_lines(session_name, socket_name=socket_name)
    except Exception:
        return register_claude_code_runtime(), None

    for line in lines:
        if _MODEL_STATUS_PATTERN in line:
            display_name = _parse_model_from_pane(lines)
            # La barra de estado de OpenCode muestra el NOMBRE de pantalla
            # ("DeepSeek V4 Flash DeepSeek"), no el id real. Se mapea a un
            # id del catálogo (`provider/model`) para que `GET /agents`
            # devuelva un modelo concreto; si no hay match con confianza,
            # modelo `None` (criterio 2).
            model_id = _catalog_id_for_display_name(display_name)
            return register_opencode_runtime(model=model_id), model_id
    return register_claude_code_runtime(), None


def _catalog_id_for_display_name(display_name: str | None) -> str | None:
    """Mapa el nombre de pantalla extraído del pane de OpenCode a un id
    real del catálogo de modelos (US-AF031-03, criterio 2/4): si el
    nombre coincide (prefijo, case-insensitive) con el `name` de una
    entrada del catálogo, devuelve su `id`; si no, `None` — nunca se
    inventa un id. La barra de OpenCode antepone el proveedor tras el
    nombre ("DeepSeek V4 Flash DeepSeek"), por eso el match es por
    prefijo; se prueban primero los nombres más largos para que
    "DeepSeek V4 Flash Free" no sea tragado por "DeepSeek V4 Flash".
    Fallos de carga del catálogo no rompen la reconciliación (`None`)."""
    from atlas_forge.models_catalog import load_model_catalog

    if not display_name:
        return None
    try:
        catalog = load_model_catalog()
    except Exception:
        return None
    display_lower = display_name.lower()
    for entry in sorted(catalog, key=lambda e: len(e.name), reverse=True):
        if display_lower.startswith(entry.name.lower()):
            return entry.id
    return None


def reconcile_session_agents(
    session: DevelopmentSession, socket_name: str = DEFAULT_SOCKET_NAME
) -> tuple[list[Agent], list[dict]]:
    """Reengancha a `session` cada sesión tmux real de `socket_name` cuyo
    nombre normalizado (`parse_session_name`, AF-030/US-AF030-01)
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
    - `ignored` (T-AF037-US02-01): lista de `{"session_name": str,
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

    ## Runtime del agente reenganchado (US-AF031-03)

    El nombre de sesión tmux normalizado no codifica qué `Runtime`
    concreto (Claude Code vs. OpenCode) lanzó originalmente el proceso —
    esa elección es libre por parte de quien lanza el agente
    (`launch_agent`, `agents/launch.py`, recibe `runtime_type` como
    parámetro explícito, no fijo por rol) y no queda registrada en
    ninguna parte alcanzable tras perder el proceso que lo sabía. Para no
    mostrar siempre "Claude Code" en agentes que en realidad corren
    OpenCode (bug confirmado por el usuario, 2026-08-17), el reenganche
    inspecciona el pane real con una heurística determinista de primer
    nivel (`_infer_runtime_and_model_for_session`): si aparece la barra
    de estado de OpenCode (`"Build · "`), el agente se reconstruye como
    OpenCode (con su modelo si el texto extraído es un id `provider/model`
    plausible); si no hay ningún patrón reconocible, se conserva el
    comportamiento documentado (`register_claude_code_runtime()` por
    defecto). El proceso tmux real ya vivo no se ve afectado (nunca se
    relanza, `create_session` no se invoca aquí), así que esto solo afecta
    al metadato `model`/`runtime_id` que expone `GET /agents`, no a la
    operatividad real del agente reenganchado.
    """
    from atlas_forge.agents.roles import get_role

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

            # US-AF031-03: inferir el runtime REAL del pane (OpenCode vs.
            # el default documentado Claude Code) en vez de asumir siempre
            # `claude-code` — ver `_infer_runtime_and_model_for_session`.
            runtime, inferred_model = _infer_runtime_and_model_for_session(
                tmux_session_name, socket_name=socket_name
            )
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
