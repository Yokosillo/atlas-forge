"""Ciclo completo de dominio de un `JobPlan` (T-AF008-US04-04,
US-AF008-04): construir → presentar/aprobar → despachar → consultar
progreso, encadenado en una única función, sin pasar por ninguna interfaz
(TUI/API) — esa exposición es responsabilidad de T-AF016-US01-05 (endpoints/
WebSocket) y T-AF017-US01-04 (pantalla en la app), ver la corrección de
alcance en el propio fichero de esta Task. No se añade lógica nueva de
dominio aquí: esta función solo secuencia las tres ya construidas
(`build_job_plan_for_story`, `present_plan_for_approval`, `dispatch_plan`),
tal como haría cualquier llamador real (futura ruta de AF-016).

## Por qué `approved` es un parámetro, no una pregunta interactiva

Esta Task cierra el valor de dominio, explícitamente sin interfaz (ver
Descripción, punto 3: "no se escribe ningún widget ni pantalla"). La
decisión humana de aprobar/rechazar el plan ya existe como capacidad
(`present_plan_for_approval`); quien la recoja de verdad (TUI, API, CLI)
la pasará aquí ya resuelta como `bool`. Este módulo no inventa un mecanismo
de entrada de usuario."""

from pathlib import Path

from atlas_forge.dispatcher.job_plan_approval import present_plan_for_approval
from atlas_forge.dispatcher.job_plan_builder import (
    DEFAULT_TASKS_DIR,
    build_job_plan_for_story,
)
from atlas_forge.dispatcher.job_plan_dispatch import dispatch_plan
from atlas_forge.models import DevelopmentSession, JobPlan
from atlas_forge.tmux.manager import DEFAULT_SOCKET_NAME


def run_job_plan(
    story_id: str,
    session: DevelopmentSession,
    approved: bool,
    socket_name: str = DEFAULT_SOCKET_NAME,
    tasks_dir: Path | str = DEFAULT_TASKS_DIR,
) -> JobPlan:
    """Construye el plan de `story_id`, lo presenta para una única
    aprobación humana (`approved`), y si se aprueba lo despacha completo.

    `tasks_dir` se propaga tal cual a `build_job_plan_for_story` (mismo
    default que esa función, el backlog real del producto) — expuesto aquí
    solo para permitir testear el flujo completo de extremo a extremo sin
    depender del backlog real (T-AF008-US04-04).

    Si `approved` es `False`, el plan queda `rejected` y `dispatch_plan`
    nunca se invoca — ningún Job de ese plan se despacha (criterio de
    aceptación de T-AF008-US04-02/03, reconfirmado aquí en el flujo
    completo). Devuelve siempre el `JobPlan` resultante, en el estado en
    que haya quedado (`rejected`, `approved` con todos los pasos
    completados, o `blocked` si un paso intermedio falló) — usar
    `get_plan_progress(plan)` sobre el valor devuelto para inspeccionar el
    detalle por paso."""
    plan = build_job_plan_for_story(story_id, tasks_dir=tasks_dir)
    present_plan_for_approval(plan, approved=approved)

    if plan.status == "approved":
        dispatch_plan(plan, session, socket_name=socket_name)

    return plan
