import uuid

from brain.core.session_lifecycle import list_agents
from brain.models import Agent, DevelopmentSession, Job


class JobCreationError(ValueError):
    """No se puede crear el Job con los datos indicados."""


def create_job(
    description: str,
    agent: Agent,
    session: DevelopmentSession,
    previous_job: Job | None = None,
) -> Job:
    """Crea un `Job` manual asociado a `session` y a `agent`.

    Valida que la sesión esté `active` y que `agent` pertenezca a ella y
    esté `idle` antes de crear el Job — cualquier rechazo se señala con
    `JobCreationError` (motivo explícito), nunca una excepción no
    controlada.

    Si se indica `previous_job` (encadenamiento manual, T-FB008-US02-01,
    caso de uso principal: pasar el resultado de Developer como entrada
    del Job de Critic), se valida que esté `completed` y con resultado no
    vacío, y su resultado se incluye de forma LITERAL (sin transformación
    ni resumen) como parte de la descripción del nuevo Job. No hay ninguna
    lógica de Pipeline ni de encadenamiento automático — es el
    desarrollador quien decide manualmente crear este segundo Job pasando
    `previous_job`.
    """
    if session.status != "active":
        raise JobCreationError(
            f"No se puede crear un Job: la sesión está en estado "
            f"'{session.status}', debe estar 'active'."
        )

    if agent not in list_agents(session):
        raise JobCreationError(
            f"No se puede crear un Job: el agente '{agent.name}' no "
            f"pertenece a la sesión de desarrollo activa."
        )

    if agent.status != "idle":
        raise JobCreationError(
            f"No se puede crear un Job: el agente '{agent.name}' está en "
            f"estado '{agent.status}', debe estar 'idle'."
        )

    final_description = description
    if previous_job is not None:
        if previous_job.status != "completed" or not previous_job.result:
            raise JobCreationError(
                f"No se puede encadenar el Job '{previous_job.id}': está en "
                f"estado '{previous_job.status}', debe estar 'completed' y "
                f"con un resultado registrado."
            )
        final_description = (
            f"{description}\n\n"
            f"--- Resultado del Job anterior (literal, sin modificar) ---\n"
            f"{previous_job.result}"
        )

    return Job(
        id=str(uuid.uuid4()),
        session_id=session.id,
        agent_id=agent.id,
        description=final_description,
        status="created",
    )
