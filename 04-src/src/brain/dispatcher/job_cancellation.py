"""Cancelar un Job en curso (T-FB008-US05-01, US-FB008-05): mecanismo de
dominio que un futuro endpoint HTTP (`POST /jobs/{id}/cancel`,
T-FB016-US01-15, fuera del alcance de esta Task) invocará desde OTRA
petición concurrente a la que despachó el Job (`POST /jobs`,
`dispatch_job`, `job_dispatch.py`).

`request_job_cancellation` (este módulo) NO transiciona el `Job` a
`cancelled` directamente — solo valida que tenga sentido cancelarlo
(`running`) y señaliza la petición vía `job_cancellation_registry`
(`threading.Event` por `job.id`). Quien de verdad ejecuta la transición es
`dispatch_job`, en su propio hilo, en cuanto `_wait_for_report` detecta la
señal en su siguiente ciclo de polling — evita que dos hilos escriban
`job.status` a la vez sobre el mismo objeto `Job`.
"""

from brain.dispatcher.job_cancellation_registry import request_job_cancellation
from brain.models import Job


class JobCancellationRejectedError(ValueError):
    """No se puede cancelar el Job en su estado actual."""


def request_cancellation(job: Job) -> None:
    """Solicita la cancelación de `job`. Solo válido si `job.status` es
    `running` — cancelar un Job `completed`/`failed`/`cancelled` (o
    `created`, aún no despachado) se rechaza con un mensaje explícito y sin
    ningún efecto secundario (no toca el registro de señalización)."""
    if job.status != "running":
        raise JobCancellationRejectedError(
            f"No se puede cancelar el Job '{job.id}': está en estado "
            f"'{job.status}', debe estar 'running'."
        )
    request_job_cancellation(job.id)
