"""Cliente HTTP del backend (T-FB016-US01-06): las pantallas de la TUI
(`WorkspaceScreen` no incluida — ver más abajo) dejan de invocar
directamente `brain.core.session_registry`/`brain.agents.registry`/
`brain.dispatcher.*` y pasan a hablar con `brain-api` (T-FB016-US01-01 a
-05) por HTTP, exactamente el mismo API que consumirá la app Android
(FB-017) — la TUI se convierte en un cliente más, no en el dueño del
estado de dominio (ver docstring de módulo de
`brain.api.app` y el propio Objetivo de esta Task).

## Por qué la TUI nunca arranca `brain-api` por su cuenta

Ya decidido explícitamente en `02-backlog/epics/FB-016-api-backend.md`
("Alcance v1 — Siempre vivo, arrancado con la VM"): "el backend es un
servicio de sistema (systemd)... los clientes (TUI, app) se conectan a él
ya en marcha — **nunca lo arrancan ellos mismos**". No es una decisión de
esta Task, es la consecuencia directa de que la TUI deje de gestionar su
propio estado: si arrancara su propio `brain-api` a demanda, cada
instancia de la TUI volvería a tener un backend distinto entre sí,
reproduciendo el mismo problema que esta Task existe para resolver.
`BackendUnavailableError` se propaga tal cual hasta la pantalla, que debe
mostrar un mensaje claro — nunca fallar en silencio ni degradar a un
comportamiento local sin backend (el arranque automático real vía systemd
es T-FB016-US01-09, otra Task).

## Qué SÍ sigue siendo local (no migrado)

- `WorkspaceScreen` (descubrimiento/selección de proyecto activo,
  `brain.workspace.discovery`/`brain.workspace.active_project`, FB-001):
  no está en la lista del criterio de aceptación de esta Task
  (`brain.core.session_registry`/`brain.agents.registry`/
  `brain.dispatcher.*`) y no hay ningún endpoint de selección de proyecto
  construido en FB-016 v1 (`GET /project` es de solo lectura) — es
  configuración local del propio cliente sobre el sistema de ficheros,
  no estado de sesión/agentes/Jobs compartido entre procesos.
- `list_available_agent_options` (`brain.agents.agent_options`): un
  catálogo estático de combinaciones agente/runtime posibles, sin tocar
  ningún registro de estado — no hay endpoint HTTP para esto porque no
  hace falta, no es información que dependa del proceso backend.

## Mecanismo

`requests` (ya dependencia del proyecto desde Scribe, FB-014) en vez de
`httpx`: el cliente de la TUI hace llamadas síncronas bloqueantes, mismo
patrón ya usado en `_dispatch_job_in_background` (`JobsScreen`,
`@work(thread=True)`) — no se introduce una segunda librería HTTP solo
para este cliente."""

import requests

DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"
_DEFAULT_TIMEOUT_SECONDS = 10.0
# Un despacho de Job real puede tardar bastante (espera a que el agente
# termine, mismo timeout por defecto que dispatch_job en el dominio) — un
# timeout corto de request cortaría la conexión antes de que el backend
# termine de responder, aunque el despacho en sí siga en curso del lado
# del servidor.
_JOB_DISPATCH_TIMEOUT_SECONDS = 60.0


class BackendUnavailableError(RuntimeError):
    """No se pudo contactar con `brain-api` (no está corriendo, la URL
    configurada es incorrecta, o no responde a tiempo) — nunca se degrada
    en silencio a un comportamiento local sin backend."""


class BackendClient:
    """Envoltura fina sobre las llamadas HTTP al backend — cada método
    corresponde a exactamente un endpoint ya construido en
    T-FB016-US01-01 a -05, sin añadir lógica de dominio nueva aquí."""

    def __init__(
        self, base_url: str = DEFAULT_BACKEND_URL, timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        try:
            response = requests.request(
                method,
                f"{self._base_url}{path}",
                timeout=kwargs.pop("timeout", self._timeout_seconds),
                **kwargs,
            )
        except requests.RequestException as error:
            raise BackendUnavailableError(
                f"No se pudo contactar con el backend en '{self._base_url}': {error}"
            ) from error
        return response

    def get_session(self) -> dict | None:
        """`GET /session` — `None` explícito si no hay sesión activa (404),
        nunca lanza por ese caso (es un estado válido, no un error)."""
        response = self._request("GET", "/session")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    def get_agents(self) -> list[dict]:
        """`GET /agents` — lista vacía si no hay sesión activa (404), en
        vez de propagar el 404 como excepción: para la TUI, "sin sesión
        activa" y "sesión activa sin agentes" se muestran igual (ninguna
        pantalla distingue hoy entre ambos casos en su listado)."""
        response = self._request("GET", "/agents")
        if response.status_code == 404:
            return []
        response.raise_for_status()
        return response.json()

    def launch_agent(self, role: str, runtime_type: str, model: str | None) -> dict:
        """`POST /agents` — devuelve el agente lanzado, o lanza
        `requests.HTTPError` con el `detail` del backend (mismo mensaje
        de motivo ya construido por el dominio, propagado por
        T-FB016-US01-02) si la combinación es inválida (400) o no hay
        sesión/proyecto activo (404)."""
        response = self._request(
            "POST",
            "/agents",
            json={"role": role, "runtime_type": runtime_type, "model": model},
        )
        response.raise_for_status()
        return response.json()

    def stop_agent(self, agent_id: str) -> dict:
        """`POST /agents/{agent_id}/stop` (T-FB016-US01-03)."""
        response = self._request("POST", f"/agents/{agent_id}/stop")
        response.raise_for_status()
        return response.json()

    def get_jobs(self) -> list[dict]:
        """`GET /jobs` — mismo criterio que `get_agents`: lista vacía si
        no hay sesión activa, en vez de propagar el 404."""
        response = self._request("GET", "/jobs")
        if response.status_code == 404:
            return []
        response.raise_for_status()
        return response.json()

    def create_and_dispatch_job(
        self, agent_id: str, description: str, previous_job_id: str | None = None
    ) -> dict:
        """`POST /jobs` — bloqueante, como ya lo es `dispatch_job` en el
        dominio: la respuesta solo llega cuando el Job ya terminó."""
        response = self._request(
            "POST",
            "/jobs",
            json={
                "agent_id": agent_id,
                "description": description,
                "previous_job_id": previous_job_id,
            },
            timeout=_JOB_DISPATCH_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()

    def cancel_job(self, job_id: str) -> dict:
        """`POST /jobs/{job_id}/cancel` (T-FB016-US01-15, T-FB019-US01-02):
        cancela un Job `running` — el agente involucrado queda `idle`
        (nunca se mata su sesión tmux). Cliente HTTP con el timeout por
        defecto (no el de despacho largo): la propia espera de
        confirmación del backend ya está acotada a unos segundos
        (`_CANCEL_CONFIRMATION_TIMEOUT_SECONDS`, `brain/api/routes.py`),
        no al timeout de un despacho completo."""
        response = self._request("POST", f"/jobs/{job_id}/cancel")
        response.raise_for_status()
        return response.json()

    def cancel_plan(self, plan_id: str) -> dict:
        """`POST /plans/{plan_id}/cancel` (T-FB016-US01-17,
        T-FB019-US01-02) — mismo criterio de timeout que `cancel_job`."""
        response = self._request("POST", f"/plans/{plan_id}/cancel")
        response.raise_for_status()
        return response.json()

    def get_plans(self) -> list[dict]:
        """`GET /plans` (T-FB016-US01-14) — todos los planes registrados
        en el proceso actual, sin sesión activa requerida (el registro de
        planes es global por proceso, no por sesión — ver docstring de
        `brain.api.plan_registry`). Nunca lanza por lista vacía: "sin
        ningún plan solicitado todavía" es un estado válido, mismo
        criterio que `get_agents`/`get_jobs`."""
        response = self._request("GET", "/plans")
        response.raise_for_status()
        return response.json()

    def get_plan(self, plan_id: str) -> dict:
        """`GET /plans/{plan_id}` — progreso de un plan concreto ya
        conocido por su id."""
        response = self._request("GET", f"/plans/{plan_id}")
        response.raise_for_status()
        return response.json()

    def approve_plan(self, plan_id: str) -> dict:
        """`POST /plans/{plan_id}/approve` (T-FB008-US04-02/03) —
        bloqueante: despacha la secuencia completa de Jobs del plan antes
        de responder, mismo timeout extendido que `create_and_dispatch_job`
        (un plan de varios pasos puede tardar bastante más que un único
        Job)."""
        response = self._request(
            "POST", f"/plans/{plan_id}/approve", timeout=_JOB_DISPATCH_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        return response.json()

    def reject_plan(self, plan_id: str) -> dict:
        """`POST /plans/{plan_id}/reject` — no despacha ningún Job, no
        necesita el timeout extendido."""
        response = self._request("POST", f"/plans/{plan_id}/reject")
        response.raise_for_status()
        return response.json()

    def get_scripts(self) -> list[dict]:
        """`GET /scripts` (T-FB001-US03-03) — lista vacía si no hay sesión
        activa, mismo criterio ya aplicado en `get_agents`/`get_jobs`."""
        response = self._request("GET", "/scripts")
        if response.status_code == 404:
            return []
        response.raise_for_status()
        return response.json()

    def run_script(self, script_id: str) -> dict:
        """`POST /scripts/{script_id}/run` (T-FB001-US03-03) — devuelve el
        resultado estructurado (`success`/`exit_code`/`stdout`/`stderr`/
        `error_message`) tal cual, sea el script válido, desconocido, o
        fallido: el endpoint nunca traduce esos casos a un código HTTP de
        error (ver docstring de `post_script_run`,
        `brain/api/routes.py`)."""
        response = self._request(
            "POST", f"/scripts/{script_id}/run", timeout=_JOB_DISPATCH_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        return response.json()


def error_detail(error: Exception) -> str:
    """Extrae el `detail` del cuerpo JSON de una respuesta HTTP de error
    (`requests.HTTPError`) — mismo mensaje de motivo ya construido por el
    dominio y propagado por la API (T-FB016-US01-02/03), nunca un texto
    reinventado por la pantalla que lo muestra. Compartida entre
    `AgentsScreen`/`JobsScreen` para no duplicar esta traducción."""
    response = getattr(error, "response", None)
    if response is not None:
        try:
            return response.json().get("detail", str(error))
        except ValueError:
            pass
    return str(error)
