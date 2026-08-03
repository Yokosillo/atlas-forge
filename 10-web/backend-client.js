/* Factory Brain — cliente HTTP del backend (T-FB021-US01-02).
 *
 * Envoltura fina sobre `fetch` para la API REST de `brain-api` (FB-016):
 * una función por endpoint HTTP, agrupadas por dominio — mismo patrón ya
 * aplicado en `BackendClient.kt` (Android) y `backend_client.py` (TUI).
 *
 * NINGUNA lógica de decisión vive aquí (ni validación de negocio, ni
 * transformación de datos más allá de parsear el JSON): este fichero solo
 * construye peticiones HTTP, expone el resultado crudo (o el error) y deja
 * la interpretación de "qué significa" a las pantallas que lo usen.
 *
 * Carga: script clásico (NO módulo ES). Se expone el objeto global
 * `BackendClient` con un método por endpoint. Desde la consola del
 * navegador: `await BackendClient.getHealth()`.
 *
 * El resto de Tasks de la Epic (que sí construyen pantallas) reutilizan este
 * cliente en vez de duplicar `fetch` por su cuenta.
 */
(function () {
  "use strict";

  /* ------------------------------------------------------------------ */
  /* Errores: dos clases, mismo criterio que                           */
  /* `BackendUnavailableException`/`BackendRequestException` (Android) y */
  /* `BackendUnavailableError`/`requests.HTTPError` (TUI).               */
  /* ------------------------------------------------------------------ */

  /**
   * No se pudo contactar con el backend: fallo de red o CORS. El
   * navegador no llegó a recibir ninguna respuesta HTTP del servidor.
   */
  class BackendUnavailableError extends Error {
    constructor(message, options) {
      super(message, options);
      this.name = "BackendUnavailableError";
    }
  }

  /**
   * El backend respondió con un error HTTP (4xx/5xx). `status` (p. ej.
   * 404) y `detail` son el motivo real ya construido por el dominio, que
   * la UI debe mostrar sin reformular (criterio de aceptación explícito,
   * mismo criterio que el resto de clientes).
   */
  class BackendRequestError extends Error {
    constructor(status, detail, options) {
      super(typeof detail === "string" && detail !== "" ? detail : "Error del backend (HTTP " + status + ")", options);
      this.name = "BackendRequestError";
      this.status = status;
      this.detail = detail;
    }
  }

  /* ------------------------------------------------------------------ */
  /* Base URL configurable (no hardcodeada) — mismo criterio que         */
  /* `BackendConfig` (Android): la web puede servirse desde cualquier    */
  /* host/puerto de Tailscale, no debe asumir `localhost`.               */
  /*                                                                     */
  /* Por defecto, la URL base es el propio origen (`""`): como la web se  */
  /* sirve DESDE `brain-api` (`/ui`, T-FB021-US01-01), una petición al    */
  /* mismo origen es same-origin y NO dispara CORS. Para servir la web    */
  /* junto a un backend en otro host/puerto, configurar la URL base.     */
  /* ------------------------------------------------------------------ */
  var _baseUrl = "";

  function _trimSlashes(value) {
    return String(value).replace(/\/+$/, "");
  }

  /**
   * Configura la URL base del backend. `config.baseUrl` es opcional; si no
   * se pasa, se usa el propio origen (same-origin, sin CORS). */
  function setBaseUrl(config) {
    if (typeof config === "string") {
      _baseUrl = _trimSlashes(config);
      return;
    }
    if (config && typeof config.baseUrl === "string") {
      _baseUrl = _trimSlashes(config.baseUrl);
    }
  }

  function getBaseUrl() {
    return _baseUrl;
  }

  /** Une la base con el path, evitando doble `/`. */
  function _url(path) {
    if (path.startsWith("/")) {
      return _baseUrl + path;
    }
    return _baseUrl + "/" + path;
  }

  /**
   * Núcleo: ejecuta la petición `fetch` y traduce los errores:
   *   - fallo de red/CORS (fetch rechaza) -> lanza `BackendUnavailableError`.
   *   - respuesta 4xx/5xx                     -> lanza `BackendRequestError`
   *     con el `detail` real del backend.
   *   - respuesta OK                          -> resuelve con el cuerpo
   *     parseado (JSON de ser posible; texto crudo si no).
   *
   * `options.post` (objeto o `true`) indica que se envía un cuerpo JSON.
   * `options.empty404` (booleano) marca los casos en que un 404 es un estado
   * válido ("sin sesión activa", "sin proyecto") y se resuelve con
   * `options.notFoundValue` (por defecto `null`) en vez de lanzar. */
  async function request(method, path, options) {
    options = options || {};

    const headers = {};
    if (options.post === true) {
      headers["Content-Type"] = "application/json";
    }

    const fetchOptions = {
      method: method,
      headers: headers,
      credentials: "same-origin",
    };
    if (options.post === true) {
      fetchOptions.body = JSON.stringify(options.body === undefined ? {} : options.body);
    }

    let response;
    try {
      response = await fetch(_url(path), fetchOptions);
    } catch (networkError) {
      // fetch solo rechaza por red/CORS (fue el navegador no alcanzó al
      // servidor, no recibió respuesta HTTP). Es el caso "sin backend".
      throw new BackendUnavailableError(
        "No se pudo contactar con el backend en '" + (_baseUrl || "origen actual") + "': " + (networkError && networkError.message ? networkError.message : String(networkError))
      );
    }

    if (response.status === 404 && options.notFoundIsValid) {
      return options.notFoundValue === undefined ? null : options.notFoundValue;
    }

    if (!response.ok) {
      const detail = await _extractDetail(response);
      throw new BackendRequestError(response.status, detail);
    }

    return _readBody(response);
  }

  /** Lee el `detail` de un cuerpo de error: `{"detail": "..."}` o crudo. */
  async function _extractDetail(response) {
    const text = await readText(response);
    if (!text) {
      return null;
    }
    try {
      const parsed = JSON.parse(text);
      if (parsed && typeof parsed === "object" && parsed.detail !== undefined) {
        return parsed.detail;
      }
      return parsed;
    } catch (_err) {
      return text;
    }
  }

  /** Lee el cuerpo: JSON cuando se puede, texto crudo como fallback. */
  async function _readBody(response) {
    const text = await readText(response);
    if (!text) {
      return null;
    }
    try {
      return JSON.parse(text);
    } catch (_err) {
      return text;
    }
  }

  function readText(response) {
    // `response.text()` puede usarse una sola vez por respuesta; guardamos
    // el texto una vez y lo parseamos desde esa copia.
    return response.text();
  }

  /* ------------------------------------------------------------------ */
  /* Salud                                                                 */
  /* ------------------------------------------------------------------ */

  /** `GET /health` — estado del proceso backend (y clase/estado de sesión). */
  async function getHealth() {
    return request("GET", "/health");
  }

  /* ------------------------------------------------------------------ */
  /* Proyecto / Sesión                                                    */
  /* ------------------------------------------------------------------ */

  /** `GET /project` — proyecto activo, o `null` si no hay ninguno (404 = estado válido). */
  async function getProject() {
    return request("GET", "/project", { notFoundIsValid: true });
  }

  /** `GET /projects` — repositorios descubiertos en el workspace del backend. */
  async function getProjects() {
    return request("GET", "/projects");
  }

  /** `POST /project` — selecciona `projectId` como proyecto activo. */
  async function selectProject(projectId) {
    return request("POST", "/project", { post: true, body: { project_id: projectId } });
  }

  /** `GET /session` — sesión de desarrollo activa, o `null` si no hay (404 = estado válido). */
  async function getSession() {
    return request("GET", "/session", { notFoundIsValid: true });
  }

  /* ------------------------------------------------------------------ */
  /* Agentes                                                              */
  /* ------------------------------------------------------------------ */

  /** `GET /agents` — agentes de la sesión activa; vacío si no hay sesión (404). */
  async function getAgents() {
    return request("GET", "/agents", { notFoundIsValid: true, notFoundValue: [] });
  }

  /** `GET /agents/options` — combinaciones agente/runtime/modelo disponibles. */
  async function getAgentOptions() {
    return request("GET", "/agents/options");
  }

  /** `POST /agents` — lanza un agente con `{ role, runtime_type, model }`. */
  async function launchAgent(payload) {
    return request("POST", "/agents", { post: true, body: payload });
  }

  /** `POST /agents/{agent_id}/stop` — detiene un agente. */
  async function stopAgent(agentId) {
    return request("POST", "/agents/" + encodeURIComponent(agentId) + "/stop", { post: true });
  }

  /** `GET /agents/{agent_id}/pane` — contenido actual del pane de tmux del agente. */
  async function getAgentPane(agentId) {
    return request("GET", "/agents/" + encodeURIComponent(agentId) + "/pane");
  }

  /* ------------------------------------------------------------------ */
  /* Jobs                                                                 */
  /* ------------------------------------------------------------------ */

  /** `GET /jobs` — histórico de Jobs de la sesión activa; vacío si no hay sesión (404). */
  async function getJobs() {
    return request("GET", "/jobs", { notFoundIsValid: true, notFoundValue: [] });
  }

  /** `GET /jobs/{job_id}` — un Job concreto por su id. */
  async function getJob(jobId) {
    return request("GET", "/jobs/" + encodeURIComponent(jobId));
  }

  /** `POST /jobs` — crea y despacha un Job real; bloqueante (responde al terminar). */
  async function createAndDispatchJob(payload) {
    return request("POST", "/jobs", { post: true, body: payload });
  }

  /** `POST /jobs/{job_id}/cancel` — cancela un Job en estado `running`. */
  async function cancelJob(jobId) {
    return request("POST", "/jobs/" + encodeURIComponent(jobId) + "/cancel", { post: true });
  }

  /* ------------------------------------------------------------------ */
  /* Planes                                                               */
  /* ------------------------------------------------------------------ */

  /** `POST /plans` — solicita al Critic un plan para la User Story `{ goal }`. */
  async function requestPlan(payload) {
    return request("POST", "/plans", { post: true, body: payload });
  }

  /** `GET /plans` — todos los planes registrados del proceso. */
  async function getPlans() {
    return request("GET", "/plans");
  }

  /** `GET /plans/{plan_id}` — progreso actual de un plan concreto. */
  async function getPlan(planId) {
    return request("GET", "/plans/" + encodeURIComponent(planId));
  }

  /** `POST /plans/{plan_id}/approve` — aprueba y despacha la secuencia completa (bloqueante). */
  async function approvePlan(planId) {
    return request("POST", "/plans/" + encodeURIComponent(planId) + "/approve", { post: true });
  }

  /** `POST /plans/{plan_id}/reject` — rechaza el plan, sin despachar ningún Job. */
  async function rejectPlan(planId) {
    return request("POST", "/plans/" + encodeURIComponent(planId) + "/reject", { post: true });
  }

  /** `POST /plans/{plan_id}/cancel` — cancela un plan en curso. */
  async function cancelPlan(planId) {
    return request("POST", "/plans/" + encodeURIComponent(planId) + "/cancel", { post: true });
  }

  /* ------------------------------------------------------------------ */
  /* Scripts                                                              */
  /* ------------------------------------------------------------------ */

  /** `GET /scripts` — catálogo de scripts genéricos y particulares; vacío si no hay sesión (404). */
  async function getScripts() {
    return request("GET", "/scripts", { notFoundIsValid: true, notFoundValue: [] });
  }

  /** `POST /scripts/{script_id}/run` — ejecuta un script; `message` opcional. */
  async function runScript(scriptId, message) {
    const body = {};
    if (message !== undefined && message !== null) {
      body.message = message;
    }
    return request("POST", "/scripts/" + encodeURIComponent(scriptId) + "/run", {
      post: true,
      body: body,
    });
  }

  /* ------------------------------------------------------------------ */

  window.BackendClient = Object.freeze({
    BackendUnavailableError: BackendUnavailableError,
    BackendRequestError: BackendRequestError,
    setBaseUrl: setBaseUrl,
    getBaseUrl: getBaseUrl,
    getHealth: getHealth,
    getProject: getProject,
    getProjects: getProjects,
    selectProject: selectProject,
    getSession: getSession,
    getAgents: getAgents,
    getAgentOptions: getAgentOptions,
    launchAgent: launchAgent,
    stopAgent: stopAgent,
    getAgentPane: getAgentPane,
    getJobs: getJobs,
    getJob: getJob,
    createAndDispatchJob: createAndDispatchJob,
    cancelJob: cancelJob,
    requestPlan: requestPlan,
    getPlans: getPlans,
    getPlan: getPlan,
    approvePlan: approvePlan,
    rejectPlan: rejectPlan,
    cancelPlan: cancelPlan,
    getScripts: getScripts,
    runScript: runScript,
  });
})();