"""Registro de `JobPlan` por identificador HTTP (T-AF016-US01-05).

`JobPlan` (dominio, US-AF008-04) no tiene `id` — no lo necesita ahí: el
Critic construye y despacha un plan de principio a fin en el mismo flujo
de dominio (`run_job_plan`), sin que nada necesite direccionarlo por
identidad después. La API sí necesita una identidad estable para que un
cliente pueda `POST /plans` (construir), y más tarde `POST
/plans/{plan_id}/approve` (una petición HTTP distinta, sin el objeto
`JobPlan` en memoria del lado del cliente) — ese `plan_id` es un concepto
de identidad de la capa de transporte, no del dominio, por eso vive aquí
(`atlas_forge/api/`) y no en `atlas_forge/dispatcher/` junto al resto de registros de
dominio (`job_history_registry`, `job_count_registry`).

## Lock por plan (T-AF016-US01-08)

FastAPI ejecuta los endpoints `def` síncronos (como `post_plan_approve`)
en un threadpool — dos peticiones HTTP casi simultáneas para el mismo
`plan_id` corren en hilos Python distintos. "Leer `plan.status` +
comparar contra las transiciones válidas + escribir el nuevo estado"
(`transition_job_plan`, `job_plan_lifecycle.py`) no es una operación
atómica como conjunto: el GIL serializa cada operación individual, pero
nada impide que dos hilos se intercalen entre la lectura y la escritura,
ambos viendo `"proposed"` antes de que ninguno haya escrito `"approved"`
— eso duplicaría el despacho de `dispatch_plan`. `get_plan_lock(plan_id)`
expone un `threading.Lock` por plan (creado perezosamente, mismo patrón
que el resto de registros de este proyecto) para que el endpoint pueda
delimitar la sección crítica real ("leer estado actual + transicionar")
sin necesitar un mecanismo de bloqueo distribuido — basta con un lock en
memoria de proceso, ya garantizado por ser un único proceso backend
(T-AF016-US01-01, criterio de aceptación explícito de esta Task)."""

import threading
import uuid

from atlas_forge.models import JobPlan


class _PlanRegistry:
    def __init__(self) -> None:
        self._plans: dict[str, JobPlan] = {}
        self._locks: dict[str, threading.Lock] = {}
        # Protege la creación perezosa de un lock por plan_id — sin esto,
        # dos hilos que piden el lock de un plan nuevo casi a la vez
        # podrían crear DOS objetos Lock distintos para el mismo
        # plan_id, dejando la exclusión mutua real sin efecto.
        self._locks_guard = threading.Lock()

    def register(self, plan: JobPlan) -> str:
        plan_id = str(uuid.uuid4())
        self._plans[plan_id] = plan
        return plan_id

    def get(self, plan_id: str) -> JobPlan | None:
        return self._plans.get(plan_id)

    def list_all(self) -> list[tuple[str, JobPlan]]:
        return list(self._plans.items())

    def get_lock(self, plan_id: str) -> threading.Lock:
        with self._locks_guard:
            if plan_id not in self._locks:
                self._locks[plan_id] = threading.Lock()
            return self._locks[plan_id]


_registry = _PlanRegistry()


def register_plan(plan: JobPlan) -> str:
    """Registra `plan` y devuelve el `plan_id` que lo identifica en la
    API a partir de ahora."""
    return _registry.register(plan)


def get_plan(plan_id: str) -> JobPlan | None:
    """Consulta el `JobPlan` asociado a `plan_id`, o `None` si no existe
    (nunca lanza excepción)."""
    return _registry.get(plan_id)


def list_plans() -> list[tuple[str, JobPlan]]:
    """Lista todos los planes registrados durante la vida del proceso
    (T-AF016-US01-14) — `(plan_id, JobPlan)` en orden de registro. Ninguno
    se elimina tras decidirse (`approved`/`rejected`/`blocked`/`cancelled`
    siguen apareciendo con su estado final), mismo criterio de "histórico
    completo, nunca purgado" ya aplicado a `job_history_registry`."""
    return _registry.list_all()


def get_plan_lock(plan_id: str) -> threading.Lock:
    """Devuelve el `Lock` asociado a `plan_id`, creándolo si es la
    primera vez que se pide — el mismo `plan_id` siempre resuelve al
    mismo objeto `Lock` (T-AF016-US01-08, ver docstring de módulo)."""
    return _registry.get_lock(plan_id)


def _reset_registry_for_tests() -> None:
    """Reinicia el registro interno. Uso exclusivo de la suite de tests
    (mismo patrón que el resto de registros del proyecto), para que cada
    test parta de un estado limpio sin depender del orden de ejecución de
    otros tests."""
    global _registry
    _registry = _PlanRegistry()
