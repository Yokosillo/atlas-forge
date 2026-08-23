from typing import Any

from atlas_forge.models import Job

# Transiciones válidas del ciclo de vida v1 de Job (ver
# 02-backlog/epics/AF-008-dispatcher.md, "Alcance v1 (mínimo) — Dispatcher
# manual"). El estado `planned` del modelo conceptual completo de la Epic
# (v2, Pipeline con dependencias) no es alcanzable todavía.
#
# `cancelled` (T-AF008-US05-01, US-AF008-05): cancelación solicitada por el
# usuario mientras el Job está `running` — distinto de `failed` (el propio
# despacho detecta un problema, p. ej. timeout esperando el reporte del
# agente). Solo alcanzable desde `running` (no tiene sentido cancelar un
# Job que aún no se ha despachado, ni uno que ya terminó) y sin salida,
# mismo patrón que `completed`/`failed`.
_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "created": {"running"},
    "running": {"completed", "failed", "cancelled"},
    "completed": set(),
    "failed": set(),
    "cancelled": set(),
}


class InvalidJobTransitionError(ValueError):
    """La transición de estado solicitada no está permitida en v1."""


def _transition(job: Job, target_status: str) -> None:
    allowed_targets = _ALLOWED_TRANSITIONS.get(job.status, set())
    if target_status not in allowed_targets:
        raise InvalidJobTransitionError(
            f"No se puede transicionar de '{job.status}' a "
            f"'{target_status}'. Transiciones permitidas desde "
            f"'{job.status}': {sorted(allowed_targets) or 'ninguna'}."
        )
    job.status = target_status


def mark_running(job: Job) -> None:
    _transition(job, "running")


def mark_completed(job: Job, result: str) -> None:
    _transition(job, "completed")
    job.result = result


def mark_failed(job: Job, reason: str) -> None:
    _transition(job, "failed")
    job.result = reason


def mark_cancelled(job: Job, reason: str) -> None:
    _transition(job, "cancelled")
    job.result = reason


def get_job_state(job: Job) -> dict[str, Any]:
    """Consulta el estado y el resultado actuales del Job."""
    return {
        "id": job.id,
        "session_id": job.session_id,
        "agent_id": job.agent_id,
        "description": job.description,
        "status": job.status,
        "result": job.result,
    }
