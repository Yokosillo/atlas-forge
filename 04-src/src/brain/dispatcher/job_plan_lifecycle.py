"""Transiciones de estado de `JobPlan`, centralizadas en un único módulo
(mismo patrón que `job_lifecycle.py` para `Job`): `job_plan_approval.py`
(T-FB008-US04-02) y `job_plan_dispatch.py` (T-FB008-US04-03) comparten el
mismo ciclo de vida — `proposed -> approved/rejected`, y `approved ->
blocked` cuando un paso falla durante el despacho. Ninguno de los estados
terminales (`rejected`, `blocked`) admite transición posterior: hace falta
un `JobPlan` nuevo, no hay "reabrir" ni "reintentar" en este ciclo.

`cancelled` (T-FB008-US08-01, US-FB008-08): cancelación solicitada por el
usuario mientras el plan está `approved` (en curso de despacho) —
distinta de `blocked` (un paso falla por sí mismo durante el despacho).
Solo alcanzable desde `approved` y sin salida, mismo patrón que
`cancelled` en `job_lifecycle.py`."""

from brain.models import JobPlan

_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "proposed": {"approved", "rejected"},
    "approved": {"blocked", "cancelled"},
    "rejected": set(),
    "blocked": set(),
    "cancelled": set(),
}


class InvalidJobPlanTransitionError(ValueError):
    """La transición de estado solicitada no está permitida."""


def transition_job_plan(plan: JobPlan, target_status: str) -> None:
    allowed_targets = _ALLOWED_TRANSITIONS.get(plan.status, set())
    if target_status not in allowed_targets:
        raise InvalidJobPlanTransitionError(
            f"No se puede transicionar de '{plan.status}' a "
            f"'{target_status}'. Transiciones permitidas desde "
            f"'{plan.status}': {sorted(allowed_targets) or 'ninguna'}."
        )
    plan.status = target_status
