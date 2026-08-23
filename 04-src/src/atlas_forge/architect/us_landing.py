"""Lógica central pura de US-AF036-04 (T-AF036-US04-01): "aterrizar una
User Story en sus Tasks".

Módulo de dominio que encapsula la funcionalidad principal de la User
Story de forma INVOCABLE PROGRAMÁTICAMENTE y SIN dependencias de
infraestructura (nada de HTTP, persistencia ni I/O de ficheros): dado el
contexto ya cargado de una User Story (su `USReviewResult`, el id del
Epic y el título extraído), produce el plan completo de aterrizaje —
propuesta de Tasks + validación determinista de formato + autoauditoría —
para que el llamador (capa HTTP, CLI o flujo de agente; ver T-AF036-US04-02)
decida qué hacer con él (escribir ficheros, exponer la respuesta, etc.).

No duplica lógica de negocio: compone las funciones puras ya existentes
de `atlas_forge.architect.propose_tasks` (generación de la propuesta) y
`atlas_forge.architect.task_pipeline` (validación determinista de formato y
autoauditoría, vía `run_task_pipeline` sin `output_dir`, que nunca escribe
disco). Nada de lo que hay aquí lee ni escribe disco.
"""

from __future__ import annotations

from dataclasses import dataclass

from atlas_forge.architect.propose_tasks import (
    ProposedTasks,
    propose_tasks_from_review,
)
from atlas_forge.architect.review_user_story import USReviewResult
from atlas_forge.architect.task_pipeline import (
    TaskPipelineResult,
    TaskSelfAuditVerdict,
    TaskValidationResult,
    run_task_pipeline,
)


@dataclass
class USLandingPlan:
    """Resultado puro de `plan_us_landing`: la propuesta de Tasks para una
    User Story, junto con su validación de formato y su autoauditoría.

    Ninguno de estos campos implica haber escrito nada en disco — la
    decisión de aprobar/descartar y de persistir la toma el llamador a
    partir de `self_audit.status` y `can_approve_landing`."""

    proposal: ProposedTasks
    validation: TaskValidationResult
    self_audit: TaskSelfAuditVerdict | None


def plan_us_landing(
    review: USReviewResult,
    epic_id: str,
    us_title: str = "",
) -> USLandingPlan:
    """Lógica central de US-AF036-04 (función pura).

    Dado el contexto de una User Story ya cargado (`USReviewResult`, sin
    I/O aquí) más el id del Epic y el título de la Story, genera la
    propuesta de Tasks (`propose_tasks_from_review`), valida el formato de
    cada Task con el validador determinista y aplica la autoauditoría — el
    mismo cálculo que hoy compone `POST /backlog/us/{us_id}/propose-tasks`,
    encapsulado en un único punto de dominio invocable.

    No lanza por condiciones de negocio (US con huecos, no lista para
    desgranar, sin Tasks generadas...): esas situaciones quedan reflejadas
    en `proposal.notes` y en `self_audit.status == "RECHAZADO"`, igual que
    el pipeline actual — nunca se propaga una excepción por un caso de
    negocio esperable.

    Se ejecuta a través de `run_task_pipeline(proposal, output_dir="")`:
    sin `output_dir` el pipeline valida y audita pero nunca escribe disco,
    preservando exactamente el mismo criterio de aprobación que usa el
    endpoint real."""
    proposal = propose_tasks_from_review(review, epic_id, us_title)
    pipeline: TaskPipelineResult = run_task_pipeline(proposal, output_dir="")
    return USLandingPlan(
        proposal=pipeline.proposal,
        validation=pipeline.validation,
        self_audit=pipeline.self_audit,
    )


def can_approve_landing(plan: USLandingPlan, auto_approve: bool = False) -> bool:
    """`True` si el plan puede aprobarse para escribirse (función pura).

    Mismo criterio que el pipeline actual: un veredicto `APROBADO` siempre
    aprueba; `APROBADO_CON_OBSERVACIONES` solo si `auto_approve` está
    activo; `RECHAZADO` nunca. El llamador usa esto para decidir si llama
    a la capa de escritura (T-AF036-US04-02)."""
    if plan.self_audit is None:
        return False
    status = plan.self_audit.status
    return status == "APROBADO" or (
        status == "APROBADO_CON_OBSERVACIONES" and auto_approve
    )
