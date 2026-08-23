"""Lógica central pura de US-AF036-03 (T-AF036-US03-01): "aterrizar una
Epic en sus User Stories".

Módulo de dominio que encapsula la funcionalidad principal de la User
Story de forma INVOCABLE PROGRAMÁTICAMENTE y SIN dependencias de
infraestructura (nada de HTTP, persistencia ni I/O de ficheros): dado el
contexto ya cargado de una Epic, produce el plan completo de aterrizaje —
propuesta de User Stories + validación de formato + autoauditoría — para
que el llamador (capa HTTP, CLI o flujo de agente; ver T-AF036-US03-02)
decida qué hacer con él (escribir ficheros, exponer la respuesta, etc.).

No duplica lógica de negocio: compone las funciones puras ya existentes
de `atlas_forge.architect.propose_user_stories` (generación de la propuesta) y
`atlas_forge.architect.us_pipeline` (validación determinista de formato y
autoauditoría). Nada de lo que hay aquí lee ni escribe disco.
"""

from __future__ import annotations

from dataclasses import dataclass

from atlas_forge.architect.propose_user_stories import (
    EpicContext,
    ProposedUserStories,
    propose_user_stories_from_epic,
)
from atlas_forge.architect.us_pipeline import (
    USSelfAuditVerdict,
    USValidationResult,
    self_audit_proposal,
    validate_proposal,
)


@dataclass
class EpicLandingPlan:
    """Resultado puro de `plan_epic_landing`: la propuesta de User Stories
    para una Epic, junto con su validación de formato y su autoauditoría.

    Ninguno de estos campos implica haber escrito nada en disco — la
    decisión de aprobar/descartar y de persistir la toma el llamador a
    partir de `self_audit.status` y `can_approve_landing`."""

    proposal: ProposedUserStories
    validation: USValidationResult
    self_audit: USSelfAuditVerdict | None


def plan_epic_landing(epic: EpicContext) -> EpicLandingPlan:
    """Lógica central de US-AF036-03 (función pura).

    Dado el contexto de una Epic ya cargado (`EpicContext`, sin I/O aquí),
    genera la propuesta de User Stories (`propose_user_stories_from_epic`),
    valida el formato de cada Story con el validador determinista
    (`validate_proposal`) y aplica la autoauditoría (`self_audit_proposal`)
    — el mismo cálculo que hoy compone `POST /backlog/epic/{epic_id}/
    propose-stories`, encapsulado en un único punto de dominio invocable.

    No lanza por condiciones de negocio (Epic sin alcance v1, sin
    objetivo, alcance no parseable...): esas situaciones quedan reflejadas
    en `proposal.notes` y en `self_audit.status == "RECHAZADO"`, igual que
    el pipeline actual — nunca se propaga una excepción por un caso de
    negocio esperable."""
    proposal = propose_user_stories_from_epic(epic)
    validation = validate_proposal(proposal)
    self_audit = self_audit_proposal(proposal, validation)
    return EpicLandingPlan(
        proposal=proposal,
        validation=validation,
        self_audit=self_audit,
    )


def can_approve_landing(plan: EpicLandingPlan, auto_approve: bool = False) -> bool:
    """`True` si el plan puede aprobarse para escribirse (función pura).

    Mismo criterio que el pipeline actual: un veredicto `APROBADO` siempre
    aprueba; `APROBADO_CON_OBSERVACIONES` solo si `auto_approve` está
    activo; `RECHAZADO` nunca. El llamador usa esto para decidir si llama
    a la capa de escritura (T-AF036-US03-02)."""
    if plan.self_audit is None:
        return False
    status = plan.self_audit.status
    return status == "APROBADO" or (
        status == "APROBADO_CON_OBSERVACIONES" and auto_approve
    )
