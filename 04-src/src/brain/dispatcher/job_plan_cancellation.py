"""Cancelar un `JobPlan` en curso (T-FB008-US08-01, US-FB008-08): mecanismo
de dominio que un futuro endpoint HTTP (`POST /plans/{id}/cancel`,
T-FB016-US01-17, fuera del alcance de esta Task) invocará desde OTRA
petición concurrente a la que aprobó y está despachando el plan.

Reutiliza el mecanismo de cancelación de Job individual ya construido en
T-FB008-US05-01 (`job_cancellation.request_cancellation`) para el paso
`agent` que esté `running` en el momento de cancelar — no reinventa la
señalización, la invoca sobre el `Job` que
`job_plan_cancellation_registry` tenga registrado como activo del plan."""

import time

from brain.dispatcher.job_cancellation import (
    JobCancellationRejectedError,
    request_cancellation as request_job_cancellation,
)
from brain.dispatcher.job_plan_cancellation_registry import (
    request_job_plan_cancellation,
)
from brain.models import JobPlan

# `dispatch_plan` marca `step.status = "running"` ANTES de resolver el
# agente/runtime y crear el `Job` real (`_dispatch_agent_step` — resolver
# el agente por role, su runtime registrado, y `create_job`, todo ocurre
# después) — dos ventanas de carrera reales, aunque breves, entre "el paso
# ya se ve running desde fuera" y "hay un Job real que cancelar":
#   1. El `Job` todavía no se ha registrado como activo del plan
#      (`request_job_plan_cancellation` devuelve `None`).
#   2. El `Job` ya está registrado pero `dispatch_job` aún no ha ejecutado
#      `mark_running` sobre él (`request_job_cancellation` lo rechaza por
#      no estar `running` todavía).
# Ninguna de las dos implica E/S de red ni espera humana — son
# operaciones en memoria/tmux locales, se resuelven en milisegundos — así
# que un polling corto y acotado cubre ambas sin introducir una espera
# perceptible en el caso común (Job ya activo y running: cero reintentos).
_CANCELLATION_RETRY_TIMEOUT_SECONDS = 3.0
_CANCELLATION_RETRY_POLL_INTERVAL_SECONDS = 0.02


class JobPlanCancellationRejectedError(ValueError):
    """No se puede cancelar el plan en su estado actual."""


def request_cancellation(plan: JobPlan) -> None:
    """Solicita la cancelación de `plan`. Solo válido si `plan.status` es
    `approved` (en curso de despacho o a punto de estarlo) Y quedan pasos
    `pending` por despachar — cancelar un plan `proposed` (aún no
    aprobado), `rejected`/`blocked`/`cancelled` (ya terminado), o
    `approved` pero sin ningún paso `pending` (el despacho ya terminó con
    éxito — `JobPlan` no tiene un estado `completed` propio, ver
    `job_plan_lifecycle.py`: un plan íntegramente despachado permanece
    `approved`, así que "ya terminó" se detecta por sus pasos, no por
    `plan.status`) se rechaza con un mensaje explícito y sin ningún efecto
    secundario.

    Si en el momento de cancelar hay un paso 'agent' `running`, reenvía la
    cancelación al `Job` de ese paso (`job_cancellation.request_cancellation`,
    T-FB008-US05-01) — el agente involucrado queda `idle`, no se mata su
    sesión tmux, exactamente igual que cancelar un Job suelto."""
    if plan.status != "approved":
        raise JobPlanCancellationRejectedError(
            f"No se puede cancelar el plan: está en estado '{plan.status}', "
            f"debe estar 'approved'."
        )

    if plan.steps and not any(step.status == "pending" or step.status == "running" for step in plan.steps):
        raise JobPlanCancellationRejectedError(
            "No se puede cancelar el plan: no quedan pasos pendientes de "
            "despachar (todos ya están 'completed' o en otro estado "
            "terminal)."
        )

    has_running_step = any(step.status == "running" for step in plan.steps)

    deadline = time.monotonic() + _CANCELLATION_RETRY_TIMEOUT_SECONDS
    while True:
        active_job = request_job_plan_cancellation(plan)

        if active_job is None:
            # Si ya no hay ningún paso marcado 'running', no habrá ningún
            # Job que registrar — nada más que hacer, la señal del plan
            # (ya activada arriba, dentro de request_job_plan_cancellation)
            # es la que detendrá el bucle de dispatch_plan.
            if not has_running_step or time.monotonic() >= deadline:
                return
            time.sleep(_CANCELLATION_RETRY_POLL_INTERVAL_SECONDS)
            continue

        try:
            request_job_cancellation(active_job)
            return
        except JobCancellationRejectedError:
            if active_job.status != "created" or time.monotonic() >= deadline:
                # O bien el Job ya terminó (completed/failed) por su
                # cuenta justo entre que dispatch_plan lo desregistra y
                # esta comprobación — no es un error de la cancelación
                # del plan en sí, la señal del plan (ya activada arriba)
                # sigue siendo la que detiene el bucle antes del
                # siguiente paso — o se agotó el margen de gracia para la
                # ventana `created -> running`, que no debería ocurrir en
                # la práctica.
                return
            time.sleep(_CANCELLATION_RETRY_POLL_INTERVAL_SECONDS)
