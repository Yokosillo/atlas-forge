"""Aprobación humana de un `JobPlan` completo (T-AF008-US04-02,
US-AF008-04). La aprobación es siempre sobre el plan entero — no existe,
deliberadamente, ninguna función que apruebe un `JobPlanStep` individual
(criterio de aceptación de la Task). Cómo se presenta el plan al
desarrollador (TUI, CLI, futura app) queda fuera de esta Task: aquí solo
vive la función de dominio."""

from atlas_forge.dispatcher.job_plan_lifecycle import transition_job_plan
from atlas_forge.models import JobPlan


def present_plan_for_approval(plan: JobPlan, approved: bool) -> JobPlan:
    """Recoge la única decisión humana posible sobre `plan`: aprobarlo
    completo (`approved=True`) o rechazarlo (`approved=False`). No muta
    nada salvo `plan.status`; devuelve el mismo `plan` ya transicionado
    para permitir encadenar la llamada. Sobre un plan que no está en
    `proposed` (ya aprobado o rechazado antes) lanza
    `InvalidJobPlanTransitionError` (`job_plan_lifecycle`) — no hay forma
    de "reabrir" un plan ya decidido, hace falta construir uno nuevo
    (T-AF008-US04-01)."""
    transition_job_plan(plan, "approved" if approved else "rejected")
    return plan
