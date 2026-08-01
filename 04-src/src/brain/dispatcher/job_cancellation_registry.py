import threading

# Mismo problema de concurrencia ya resuelto en `plan_registry.py` para la
# idempotencia de aprobación de planes (T-FB016-US01-08): `dispatch_job`
# corre en el hilo del threadpool de FastAPI que atiende `POST /jobs`, y
# necesita recibir una señal desde OTRO hilo (el que atiende
# `POST /jobs/{id}/cancel`) sin que ninguno de los dos tenga que
# coordinarse por fuera de este registro.
#
# Aquí la primitiva correcta no es `threading.Lock` (exclusión mutua) sino
# `threading.Event`: no se protege una sección crítica, se señaliza un
# hecho binario de una vez ("cancela ya") de un hilo a otro, y el hilo que
# espera (`_wait_for_report`, dispatcher/job_dispatch.py) ya hace polling
# por diseño — comprobar `event.is_set()` en cada ciclo existente no
# requiere reescribir su lógica de espera.
#
# Igual que `_PlanRegistry`, los `Event` se crean de forma perezosa (un
# `job_id` sin cancelación solicitada nunca necesita una entrada) y bajo un
# lock propio que protege solo la creación de la entrada, no el uso del
# `Event` en sí (los `Event` ya son thread-safe).


class _JobCancellationRegistry:
    def __init__(self) -> None:
        self._events: dict[str, threading.Event] = {}
        self._events_guard = threading.Lock()

    def _get_event(self, job_id: str) -> threading.Event:
        with self._events_guard:
            if job_id not in self._events:
                self._events[job_id] = threading.Event()
            return self._events[job_id]

    def request_cancellation(self, job_id: str) -> None:
        self._get_event(job_id).set()

    def is_cancellation_requested(self, job_id: str) -> bool:
        return self._get_event(job_id).is_set()

    def clear(self, job_id: str) -> None:
        with self._events_guard:
            self._events.pop(job_id, None)


_registry = _JobCancellationRegistry()


def request_job_cancellation(job_id: str) -> None:
    """Señaliza que `job_id` debe cancelarse en cuanto `_wait_for_report`
    compruebe el evento en su próximo ciclo de polling."""
    _registry.request_cancellation(job_id)


def is_job_cancellation_requested(job_id: str) -> bool:
    return _registry.is_cancellation_requested(job_id)


def clear_job_cancellation(job_id: str) -> None:
    """Limpia la entrada de `job_id` tras resolverse el despacho (cancelado
    o no) — evita acumular `Event` de Jobs ya terminados indefinidamente."""
    _registry.clear(job_id)


def _reset_registry_for_tests() -> None:
    global _registry
    _registry = _JobCancellationRegistry()
