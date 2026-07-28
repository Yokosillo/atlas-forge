"""Histórico consultable de Jobs por sesión (T-FB002-US03-03, FB-002
Dashboard): `Job` (FB-008) no está asociado a `DevelopmentSession` como
colección consultable — a diferencia de `Agent`, que sí vive en
`session.agents` (`assign_agent`/`list_agents`, FB-003), no existe hoy
ningún mecanismo que permita listar "los Jobs de esta sesión". La
pantalla Jobs (T-FB002-US03-01/02) necesita ese histórico para mostrarlo
sin perderlo al navegar a otra pantalla y volver.

## Decisión: registro nuevo, no modificar `create_job`/`DevelopmentSession`

Se evaluaron dos opciones:
- Modificar `create_job` (`brain/dispatcher/job_creation.py`, FB-008 v1,
  ya cerrado y probado) para que registre el Job en `session.agents` o
  un campo nuevo de `DevelopmentSession`. Se descarta: acoplaría una
  función de dominio ya aprobada de otra Epic (FB-008) a un consumidor
  concreto (la pantalla Jobs de FB-002) que hoy es el único llamador de
  `create_job` en producción, pero no tiene por qué serlo siempre —
  cualquier futuro llamador de `create_job` (p. ej. el Dispatcher
  automático de FB-008 v2) heredaría este registro sin haberlo pedido.
- Registro nuevo en memoria de proceso, indexado por `session_id`,
  poblado por quien crea el Job (la pantalla Jobs) — mismo patrón ya
  establecido para `_AgentRuntimeRegistry`
  (`runtime/agent_runtime_registry.py`, T-FB002-US03-00) y
  `_JobCountRegistry` (`dispatcher/job_count_registry.py`,
  T-FB008-US03-02). Elegido: mantiene `create_job` sin cambios, y el
  registro vive en `dispatcher/` (junto a los otros dos registros de
  esta capa) porque opera sobre `Job`, un concepto de FB-008.

Igual que los otros dos registros, incluye `_reset_registry_for_tests()`
para que los tests no dependan del orden de ejecución de otros tests.
"""

from brain.models import Job


class _JobHistoryRegistry:
    def __init__(self) -> None:
        self._jobs_by_session: dict[str, list[Job]] = {}

    def record(self, session_id: str, job: Job) -> None:
        self._jobs_by_session.setdefault(session_id, []).append(job)

    def list_for_session(self, session_id: str) -> list[Job]:
        return list(self._jobs_by_session.get(session_id, []))


_registry = _JobHistoryRegistry()


def record_job(session_id: str, job: Job) -> None:
    """Añade `job` al histórico de `session_id`, ordenado por creación
    (orden de inserción — no se reordena ni se deduplica)."""
    _registry.record(session_id, job)


def list_jobs_for_session(session_id: str) -> list[Job]:
    """Consulta el histórico de Jobs de `session_id`, ordenados por
    creación. Lista vacía si la sesión no tiene ningún Job registrado
    (nunca lanza excepción)."""
    return _registry.list_for_session(session_id)


def _reset_registry_for_tests() -> None:
    """Reinicia el registro interno. Uso exclusivo de la suite de tests
    (mismo patrón que `agent_runtime_registry`/`job_count_registry`),
    para que cada test parta de un estado limpio sin depender del orden
    de ejecución de otros tests."""
    global _registry
    _registry = _JobHistoryRegistry()
