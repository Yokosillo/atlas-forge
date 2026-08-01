import threading

from brain.models import Job, JobPlan

# Mismo problema y misma solución que `job_cancellation_registry.py` para
# `Job` (T-FB008-US05-01): `dispatch_plan` corre bloqueante dentro del hilo
# de la petición HTTP que aprobó el plan (`POST /plans/{id}/approve`) y
# necesita recibir una señal de "cancela ya" desde OTRO hilo (una futura
# `POST /plans/{id}/cancel`, T-FB016-US01-17) sin coordinarse por fuera de
# este registro — de nuevo la primitiva correcta es `threading.Event`
# (señalizar un hecho de un hilo a otro), no `threading.Lock`.
#
# Diferencia real con `Job`: `Job.id` es un campo de dominio (`job_id`
# identifica al Job de forma estable independientemente de qué capa lo
# consulte). `JobPlan` NO tiene ningún id de dominio — el único id que
# existe hoy (`plan_id`) es un concepto de la capa de transporte HTTP
# (`brain/api/plan_registry.py`, ver su docstring: "un concepto de
# identidad de la capa de transporte, no del dominio"). Introducir un id
# de dominio en `JobPlan` solo para este registro sería ampliar el modelo
# sin necesidad verificada (nada más lo usa) — en vez de eso, se indexa
# por `id(plan)` (identidad del objeto Python): válido porque el mismo
# objeto `JobPlan` se comparte por referencia entre la capa API y el
# dominio durante todo el ciclo de vida del despacho (igual que
# `plan.status` mutado por un hilo ya es visible al otro sin serialización
# de por medio) — exactamente la misma premisa por la que `dispatch_plan`
# puede mutar `plan.status`/`step.status` directamente y que se refleje en
# `get_plan_progress` consultado desde otro hilo.
#
# ## Job activo del plan
#
# Cancelar un plan con un paso `running` debe cancelar también ESE Job
# (criterio de aceptación de T-FB008-US08-01, reutilizando
# `T-FB008-US05-01`) — pero el `Job` de un paso "agent" es una variable
# local de `_dispatch_agent_step` (`job_plan_dispatch.py`), invisible
# desde el hilo que solicita la cancelación del plan. Este registro
# también guarda, por plan, una referencia al `Job` actualmente en curso
# (si lo hay) — `dispatch_plan` la registra justo antes de despachar cada
# paso "agent" y la limpia al terminar, mismo patrón de ciclo de vida que
# `job_cancellation_registry.clear_job_cancellation`.


class _JobPlanCancellationRegistry:
    def __init__(self) -> None:
        self._events: dict[int, threading.Event] = {}
        self._active_jobs: dict[int, Job] = {}
        self._guard = threading.Lock()

    def _get_event(self, plan: JobPlan) -> threading.Event:
        key = id(plan)
        with self._guard:
            if key not in self._events:
                self._events[key] = threading.Event()
            return self._events[key]

    def request_cancellation(self, plan: JobPlan) -> Job | None:
        """Señaliza la cancelación de `plan` y devuelve el `Job` que
        estuviera registrado como activo en ese instante (o `None`), para
        que el llamador pueda cancelarlo también."""
        self._get_event(plan).set()
        with self._guard:
            return self._active_jobs.get(id(plan))

    def is_cancellation_requested(self, plan: JobPlan) -> bool:
        return self._get_event(plan).is_set()

    def set_active_job(self, plan: JobPlan, job: Job) -> None:
        with self._guard:
            self._active_jobs[id(plan)] = job

    def clear_active_job(self, plan: JobPlan) -> None:
        with self._guard:
            self._active_jobs.pop(id(plan), None)

    def clear(self, plan: JobPlan) -> None:
        with self._guard:
            self._events.pop(id(plan), None)
            self._active_jobs.pop(id(plan), None)


_registry = _JobPlanCancellationRegistry()


def request_job_plan_cancellation(plan: JobPlan) -> Job | None:
    """Señaliza que `plan` debe cancelarse en cuanto `dispatch_plan`
    compruebe la señal antes de despachar su siguiente paso. Devuelve el
    `Job` del paso `running` en ese instante, si lo hay — el llamador
    (`job_plan_cancellation.request_cancellation`) es quien decide
    cancelarlo también, reutilizando `job_cancellation.request_cancellation`."""
    return _registry.request_cancellation(plan)


def is_job_plan_cancellation_requested(plan: JobPlan) -> bool:
    return _registry.is_cancellation_requested(plan)


def set_active_job_for_plan(plan: JobPlan, job: Job) -> None:
    """Registra `job` como el Job actualmente en curso de `plan` — llamado
    por `dispatch_plan` justo antes de despachar un paso 'agent'."""
    _registry.set_active_job(plan, job)


def clear_active_job_for_plan(plan: JobPlan) -> None:
    """Desregistra el Job activo de `plan` — llamado por `dispatch_plan`
    al terminar de despachar un paso 'agent' (con o sin éxito)."""
    _registry.clear_active_job(plan)


def clear_job_plan_cancellation(plan: JobPlan) -> None:
    """Limpia toda la entrada de `plan` (evento + Job activo) tras
    resolverse el despacho (cancelado o no) — evita acumular estado de
    planes ya terminados."""
    _registry.clear(plan)


def _reset_registry_for_tests() -> None:
    global _registry
    _registry = _JobPlanCancellationRegistry()
