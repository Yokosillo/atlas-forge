"""Crear un Job y registrarlo en el histórico de la sesión como una única
operación (T-FB016-US01-04): hasta ahora, `create_job` (FB-008 v1) y
`record_job` (`job_history_registry`, T-FB002-US03-03) eran dos llamadas
separadas que el único consumidor real, `JobsScreen` (la pantalla Jobs de
la TUI), encadenaba manualmente — cualquier llamador nuevo (esta Task, la
API) tendría que acordarse de hacer las dos llamadas por su cuenta o el
histórico quedaría desincronizado en silencio (un Job creado pero invisible
en `GET /jobs`/la pantalla Jobs).

Esta función no es la extracción de una pieza acoplada a la TUI —
`list_jobs_for_session`/`record_job` ya viven en `brain.dispatcher` desde
T-FB002-US03-03, no en `brain.tui` — es cerrar el hueco de que crear un Job
y registrarlo en el histórico eran dos pasos manuales en vez de una sola
operación reutilizable por cualquier consumidor (API y, tras
T-FB016-US01-06, también la TUI migrada)."""

from brain.dispatcher.job_creation import create_job
from brain.dispatcher.job_history_registry import record_job
from brain.models import Agent, DevelopmentSession, Job


def create_and_record_job(
    description: str,
    agent: Agent,
    session: DevelopmentSession,
    previous_job: Job | None = None,
) -> Job:
    """Crea un Job (`create_job`, sin reimplementar su validación) y lo
    registra de inmediato en el histórico de `session` (`record_job`) —
    mismo Job que devuelve `create_job`, ahora también consultable con
    `list_jobs_for_session`. Si `create_job` rechaza la combinación
    (`JobCreationError`), no se registra nada."""
    job = create_job(description, agent, session, previous_job=previous_job)
    record_job(session.id, job)
    return job
