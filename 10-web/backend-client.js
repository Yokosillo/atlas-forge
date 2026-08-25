/* Atlas Forge — cliente HTTP del backend (T-AF021-US01-02).
 *
 * Envoltura fina sobre `fetch` para la API REST de `atlas-forge-api` (AF-016):
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
  /* sirve DESDE `atlas-forge-api` (`/ui`, T-AF021-US01-01), una petición al    */
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

  /** Lee el `detail` de un cuerpo de error: `{"detail": "..."}` o crudo.
   *
   * Un script que falla devuelve 500 con un body de `ScriptRunResult`
   * (`success/exit_code/stdout/stderr/error_message/...`), sin campo
   * `detail`: se reduce a un mensaje legible para que la UI muestre la
   * CAUSA (error_message, y si falta su `stderr`), no un "HTTP 500" genérico.
   */
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
      if (parsed && typeof parsed === "object") {
        if (typeof parsed.error_message === "string") {
          return parsed.error_message || null;
        }
        if (typeof parsed.detail === "string") {
          return parsed.detail;
        }
        if (typeof parsed.stderr === "string" && parsed.stderr.trim()) {
          return parsed.stderr.trim();
        }
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

  /** `POST /agents/{agent_id}/release` — libera un agente caído/detenido
   * (unavailable/stopped), retirándolo de la sesión sin matar su runtime
   * (T-AF024-US11-16, backend T-AF005-US01-09). */
  async function releaseAgent(agentId) {
    return request("POST", "/agents/" + encodeURIComponent(agentId) + "/release", { post: true });
  }

  /** `GET /agents/{agent_id}/pane` — contenido actual del pane de tmux del agente. */
  async function getAgentPane(agentId) {
    return request("GET", "/agents/" + encodeURIComponent(agentId) + "/pane");
  }

  /** `GET /agents/{agent_id}/model` — modelo activo actual del agente. */
  async function getAgentModel(agentId) {
    return request("GET", "/agents/" + encodeURIComponent(agentId) + "/model");
  }

  /** `PUT /agents/{agent_id}/model` — cambia el modelo activo del agente. */
  async function setAgentModel(agentId, model) {
    return request("PUT", "/agents/" + encodeURIComponent(agentId) + "/model", {
      post: true, body: { model: model }
    });
  }

  /** `GET /agents/{agent_id}/available-models` — modelos disponibles. */
  async function getAgentAvailableModels(agentId) {
    return request("GET", "/agents/" + encodeURIComponent(agentId) + "/available-models");
  }

  /** `GET /agents/{agent_id}/status-model` — modelo activo real de un
   * agente Claude Code, leído bajo demanda vía /status del pane
   * (T-AF024-US11-05). A diferencia de getAgentModel (OpenCode, lectura
   * pasiva), el backend rechaza esta llamada con 400 si el agente está
   * `working` — nunca se debe invocar automáticamente. */
  async function getAgentStatusModel(agentId) {
    return request("GET", "/agents/" + encodeURIComponent(agentId) + "/status-model");
  }

  /** `POST /agents/{agent_id}/send-keys` — envía teclas literales al pane
   * del agente (T-AF024-US11-13). Se usa para enviar empujones sin crear
   * un Job formal. */
  async function sendAgentKeys(agentId, keys) {
    return request("POST", "/agents/" + encodeURIComponent(agentId) + "/send-keys", {
      post: true, body: { keys: keys }
    });
  }

  /* ------------------------------------------------------------------ */
  /* Modelos — preferencias (T-AF022-US10-01)                           */
  /* ------------------------------------------------------------------ */

  /** `GET /models/preferences` — catálogo completo con habilitado y defaults. */
  async function getModelsPreferences() {
    return request("GET", "/models/preferences");
  }

  /** `PUT /models/preferences` — actualiza habilitados y/o defaults. */
  async function updateModelsPreferences(payload) {
    return request("PUT", "/models/preferences", { post: true, body: payload });
  }

  /* ------------------------------------------------------------------ */
  /* Sistema — preferencias (US-AF024-12)                                */
  /* ------------------------------------------------------------------ */

  /** `GET /system/preferences` — catálogo de valores de sistema configurables (hoy solo `max_simultaneous_developers`). */
  async function getSystemPreferences() {
    return request("GET", "/system/preferences");
  }

  /** `PUT /system/preferences` — actualiza uno o más valores de sistema. */
  async function updateSystemPreferences(payload) {
    return request("PUT", "/system/preferences", { post: true, body: payload });
  }

  /** `POST /system/restart` — reinicia el servicio atlas-forge-api (T-AF037-US05-01). Fire-and-forget: responde 202 y el backend se cae; el llamador debe verificar la recuperación con polling. */
  async function restartSystem() {
    return request("POST", "/system/restart", { post: true });
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
  /* Acciones transversales de proyecto (AF-025)                          */
  /* ------------------------------------------------------------------ */

  /** `POST /project/actions/{action_id}` — despacha una acción transversal
   * de proyecto sin pasar por el modo conversacional del Arquitecto. Bloqueante como `createAndDispatchJob`.
   * Acciones disponibles: `documentar`, `analizar-arquitectura`, `sugerir-ideas`,
   * `testear`, `auditar-ux`, `indexar`. */
  async function runProjectAction(actionId) {
    return request("POST", "/project/actions/" + encodeURIComponent(actionId), { post: true });
  }

  /* ------------------------------------------------------------------ */
  /* Backlog (T-AF020-US01-01/T-AF020-US02-01, T-AF020-US04-01)          */
  /* ------------------------------------------------------------------ */

  /** `GET /backlog` — informe estructurado del backlog del proyecto activo
   * (conteo por Epic/estado). A diferencia de `getAgents`/`getJobs`, un
   * 404 (sin proyecto activo) SÍ se propaga como error — no es un estado
   * "lista vacía" (un backlog vacío con proyecto activo es un 200 real,
   * `empty: true`), mismo criterio ya aplicado en Android/TUI. */
  async function getBacklog() {
    return request("GET", "/backlog");
  }

  /** `GET /backlog/{item_id}` — detalle de una Epic (`item_id` con forma
   * `AF-xxx`)/User Story/Task concreta. Un `item_id` inexistente propaga
   * el 404 real del backend (motivo explícito, incluido el de un fallo de
   * parseo) — siempre un error real de navegación, nunca un estado
   * válido a silenciar. */
  async function getBacklogItem(itemId) {
    return request("GET", "/backlog/" + encodeURIComponent(itemId));
  }

  /** `GET /backlog/epic/{epic_id}/coverage` (T-AF036-US05-01) — cobertura
   * del alcance v1 declarado de una Epic frente a sus User Stories/Tasks
   * reales (detector aproximado). 404 (Epic sin fichero propio) propaga el
   * `detail` verbatim. En éxito devuelve `{declared_alcance, points, gaps,
   * approximate, message}` — o, si la Epic no declara la sección,
   * `{declared_alcance: null, message: "...no se puede calcular
   * cobertura", gaps: []}` (nunca un vacío ambiguo). */
  async function getEpicCoverage(epicId) {
    return request("GET", "/backlog/epic/" + encodeURIComponent(epicId) + "/coverage");
  }

  /** `GET /backlog/us/{us_id}/report` (T-AF036-US06-01) — informe de cierre
   * real de una User Story. El backend resuelve el fichero real dentro de
   * `07-informes/<us_id>/` por GLOB (el nombre no siempre coincide con
   * `<story_id>.md`). Devuelve `{exists: false, us_id}` si no hay informe
   * todavía (resultado válido, distinguible de un error real) o
   * `{exists: true, us_id, path, content}` con el contenido completo. */
  async function getUsClosingReport(usId) {
    return request("GET", "/backlog/us/" + encodeURIComponent(usId) + "/report");
  }

  /** `POST /backlog/epic` (T-AF036-US02-01) — crea una Epic nueva desde
   * cero con `{id, title, objetivo, fase}`. 400 (`id` con formato
   * inválido o contenido que no pasa el validador) / 409 (`id` duplicado)
   * propagan el `detail` verbatim del backend. Éxito: 201 con
   * `{id, title, path}` del fichero creado. */
  async function createEpic(payload) {
    return request("POST", "/backlog/epic", { post: true, body: payload });
  }

  /** `POST /backlog/epic/{epic_id}/us` (T-AF036-US02-02) — crea una User
   * Story nueva desde cero bajo la Epic `epicId`, con
   * `{id, title, objetivo, criterios_aceptacion, priority}`. `epicId`
   * viene siempre de la URL, nunca de `payload` (el backend lo resuelve
   * así — este cliente ni siquiera acepta un campo `epic_id` en el
   * payload). 404 (`epicId` sin fichero de Epic real) / 400 (`id` con
   * formato inválido, `priority` inválida, o contenido que no pasa el
   * validador) / 409 (`id` duplicado) propagan el `detail` verbatim del
   * backend. Éxito: 201 con `{id, title, epic_id, path}` del fichero
   * creado. */
  async function createUserStory(epicId, payload) {
    return request("POST", "/backlog/epic/" + encodeURIComponent(epicId) + "/us", {
      post: true, body: payload,
    });
  }

  async function createTask(usId, payload) {
    return request("POST", "/backlog/us/" + encodeURIComponent(usId) + "/task", {
      post: true, body: payload,
    });
  }

  /* ------------------------------------------------------------------ */
  /* Peticiones de creación desde descripción (T-AF036-US20-01/02/03)     */
  /* ------------------------------------------------------------------ */

  /** `POST /backlog/epic/from-description` (T-AF036-US20-01) — encola una
   * petición de creación de Epic desde descripción libre. Devuelve
   * `{request_id, tipo, status}`; la Epic se materializa cuando el
   * Arquitecto la procesa (T-AF036-US20-07/08), no en la petición. */
  async function createFromDescriptionEpic(description) {
    return request("POST", "/backlog/epic/from-description", { post: true, body: { description } });
  }

  /** `POST /backlog/epic/{epicId}/from-description-us` (T-AF036-US20-02) —
   * encola una petición de creación de User Story bajo `epicId`. */
  async function createFromDescriptionUserStory(epicId, description) {
    return request("POST", "/backlog/epic/" + encodeURIComponent(epicId) + "/from-description-us", { post: true, body: { description } });
  }

  /** `POST /backlog/us/{usId}/from-description-task` (T-AF036-US20-03) —
   * encola una petición de creación de Task bajo `usId`. */
  async function createFromDescriptionTask(usId, description) {
    return request("POST", "/backlog/us/" + encodeURIComponent(usId) + "/from-description-task", { post: true, body: { description } });
  }

  /** `POST /backlog/epic/{epic_id}/propose-stories` (T-AF036-US10-01) —
   * pipeline Epic→User Story: propone User Stories desde el alcance v1 de
   * la Epic, ejecuta validación + autoauditoría y, si se aprueban
   * (`validation_valid: true` y `self_audit.status: "APROBADO"`), las
   * escribe a disco. 404 (Epic inexistente) propaga el `detail` real. El
   * resultado trae SIEMPRE el detalle del pipeline
   * (`validation_valid`/`validation_errors`/`self_audit`) — un pipeline
   * no aprobado es un 200 con esos flags en `false`/no-APROBADO, nada
   * escrito a disco, no un error HTTP. */
  async function proposeStories(epicId) {
    return request("POST", "/backlog/epic/" + encodeURIComponent(epicId) + "/propose-stories", { post: true });
  }

  /** `POST /backlog/us/{us_id}/propose-tasks` (T-AF036-US10-01) — pipeline
   * User Story→Task: propone Tasks desde la US, ejecuta validación +
   * autoauditoría y, si se aprueban, las escribe a disco. 404 (US
   * inexistente) propaga el `detail` real. Mismo contrato de respuesta
   * que `proposeStories`: un pipeline no aprobado es un 200 con flags
   * no-aprobados, no un error HTTP. */
  async function proposeTasks(usId) {
    return request("POST", "/backlog/us/" + encodeURIComponent(usId) + "/propose-tasks", { post: true });
  }

  /** `POST /backlog/{story_id}/launch-development` — lanza el desarrollo
   * de la User Story `story_id` con contexto ya resuelto por el backend
   * (objetivo + Tasks `READY`), despachado al agente `agentId`. Bloqueante
   * como `createAndDispatchJob` (mismo motor de despacho). 400 (sin Tasks
   * `READY`)/404 (`story_id`/agente inválido) propagan el `detail` real. */
  async function launchDevelopment(storyId, agentId) {
    return request("POST", "/backlog/" + encodeURIComponent(storyId) + "/launch-development", {
      post: true,
      body: { agent_id: agentId },
    });
  }

  /** `POST /backlog/epic/{epic_id}/analyze-threads` — ejecuta el análisis
   * determinista de hilos de desarrollo para una Epic (AF-026).
   * Bloqueante, sin despachar Job al Arquitecto. `numAgents` (default 2,
   * corrección 2026-08-06) es el número de agentes disponibles para la
   * recomendación de reparto — configurable, nunca fijo. */
  async function analyzeEpicThreads(epicId, numAgents) {
    var query = "?num_agents=" + encodeURIComponent(numAgents || 2);
    return request("POST", "/backlog/epic/" + encodeURIComponent(epicId) + "/analyze-threads" + query, { post: true });
  }

  /* ------------------------------------------------------------------ */
  /* Cola de despacho (T-AF008-US10-01/-02/-03)                          */
  /* ------------------------------------------------------------------ */

  /** `POST /backlog/{task_id}/enqueue` — marca la Task `taskId` (debe
   * estar `READY`) como encolada para desarrollo, sin pasar por el flujo
   * de Plan/aprobación. 404 (Task inexistente)/400 (no está `TO_DO`)/409
   * (ya encolada) propagan el `detail` real del backend. */
  async function enqueueTask(taskId) {
    return request("POST", "/backlog/" + encodeURIComponent(taskId) + "/enqueue", { post: true });
  }

  /** `DELETE /backlog/{task_id}/enqueue` — retira `taskId` de la cola
   * antes de que el Dispatcher la haya tomado. 404 (nunca se encoló)/409
   * (ya despachada) propagan el `detail` real. */
  async function dequeueTask(taskId) {
    return request("DELETE", "/backlog/" + encodeURIComponent(taskId) + "/enqueue");
  }

  /** `GET /backlog/queue` — estado completo de la cola: `queued`
   * (ordenadas por prioridad), `dispatched`, `failed`. */
  async function getDispatchQueue() {
    return request("GET", "/backlog/queue");
  }

  /** `DELETE /backlog/queue/history` — borra el histórico de la cola
   * (entradas `completed`/`failed`), conservando las en curso
   * (`queued`/`dispatched`). Devuelve `{removed: N}`. */
  async function clearQueueHistory() {
    return request("DELETE", "/backlog/queue/history");
  }

  /** `DELETE /backlog/queue/completed` — borra TODAS las entradas
   * `completed` (DONE) de la cola, conservando `failed`/`queued`/`dispatched`
   * (T-AF042-US07-01). Devuelve `{removed: N}`. */
  async function clearCompleted() {
    return request("DELETE", "/backlog/queue/completed");
  }

  /** `DELETE /backlog/queue/entry/{task_id}` — borra SOLO la entrada
   * terminal (`completed`/`failed`) de `taskId`, conservando el resto de la
   * cola (T-AF036-US17-07/-09: el aspa ✕ por fila `done`). Devuelve
   * `{removed: 0|1}`. */
  async function deleteQueueEntry(taskId) {
    return request("DELETE", "/backlog/queue/entry/" + encodeURIComponent(taskId));
  }

  /** `POST /backlog/queue/entry/{task_id}/requeue` — reencola una entrada
   * `failed` devolviéndola a `queued` para que el Dispatcher la reintente
   * (T-AF036-US17-08). La task real pasa a `TO_DEVELOP` (si estaba `READY`). */
  async function requeueQueueEntry(taskId) {
    return request("POST", "/backlog/queue/entry/" + encodeURIComponent(taskId) + "/requeue");
  }

  /* ------------------------------------------------------------------ */
  /* Edición en línea de prioridad/estado (T-AF036-US08-01)              */
  /* ------------------------------------------------------------------ */

  /** `PUT /backlog/{item_id}/priority` — cambia la prioridad de una User
   * Story/Task ya existente directamente en su fichero real.
   * `newPriority` es una de `'Crítica'|'Alta'|'Media'|'Baja'`, o `null`
   * para "sin prioridad". 400 (valor inválido, o Epic) propaga el
   * `detail` real del backend. */
  async function setBacklogItemPriority(itemId, newPriority) {
    return request("PUT", "/backlog/" + encodeURIComponent(itemId) + "/priority", {
      post: true, body: { priority: newPriority }
    });
  }

  /** `PUT /backlog/{item_id}/fase` — cambia la fase de una Epic/User Story
   * ya existente directamente en su fichero real (T-AF036-US14-01).
   * `newFase` es texto libre, o `null` para "sin fase". 400 (contenido
   * resultante que no valida) propaga el `detail` real del backend. */
  async function setBacklogItemFase(itemId, newFase) {
    return request("PUT", "/backlog/" + encodeURIComponent(itemId) + "/fase", {
      post: true, body: { fase: newFase }
    });
  }

  /** `PUT /backlog/{item_id}/version` — cambia el campo `version` de una
   * Epic/User Story ya existente directamente en su fichero real
   * (T-AF036-US25-01). `newVersion` es una de `0.9`/`0.9.1`/`0.9.2`, o
   * `null` para "sin versión". 400 (valor inválido, o contenido resultante
   * que no valida) propaga el `detail` real del backend. */
  async function setBacklogItemVersion(itemId, newVersion) {
    return request("PUT", "/backlog/" + encodeURIComponent(itemId) + "/version", {
      post: true, body: { version: newVersion }
    });
  }

  /** `PUT /backlog/{item_id}/state` — cambia el estado de una User
   * Story/Task ya existente directamente en su fichero real.
   * `newState` es una de `'READY'|'TO_DEVELOP'|'IN_PROGRESS'|'IN_REVIEW'|'DONE'`.
   * Si el item es una User Story y `newState` es `'DONE'`, el backend
   * dispara la promoción automática de su Epic si corresponde
   * (`promoted_epics` en la respuesta). Si es una User Story y
   * `newState` es `'TO_DEVELOP'` (T-AF008-US14-04), el backend encola
   * automáticamente sus Tasks `READY` (`enqueued`/`skipped_already_queued`
   * en la respuesta). 400 (valor
   * inválido, o Epic) propaga el `detail` real del backend. */
  async function setBacklogItemState(itemId, newState) {
    return request("PUT", "/backlog/" + encodeURIComponent(itemId) + "/state", {
      post: true, body: { state: newState }
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
    releaseAgent: releaseAgent,
    getAgentPane: getAgentPane,
    getAgentModel: getAgentModel,
    getAgentStatusModel: getAgentStatusModel,
    setAgentModel: setAgentModel,
    getAgentAvailableModels: getAgentAvailableModels,
    sendAgentKeys: sendAgentKeys,
    getModelsPreferences: getModelsPreferences,
    updateModelsPreferences: updateModelsPreferences,
    getSystemPreferences: getSystemPreferences,
    updateSystemPreferences: updateSystemPreferences,
    restartSystem: restartSystem,
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
    runProjectAction: runProjectAction,
    getBacklog: getBacklog,
    getBacklogItem: getBacklogItem,
    getEpicCoverage: getEpicCoverage,
    getUsClosingReport: getUsClosingReport,
    createEpic: createEpic,
    createUserStory: createUserStory,
    createTask: createTask,
createFromDescriptionEpic: createFromDescriptionEpic,
    createFromDescriptionUserStory: createFromDescriptionUserStory,
    createFromDescriptionTask: createFromDescriptionTask,
    proposeStories: proposeStories,
    proposeTasks: proposeTasks,
    launchDevelopment: launchDevelopment,
    analyzeEpicThreads: analyzeEpicThreads,
    enqueueTask: enqueueTask,
    dequeueTask: dequeueTask,
    getDispatchQueue: getDispatchQueue,
    clearQueueHistory: clearQueueHistory,
    clearCompleted: clearCompleted,
    deleteQueueEntry: deleteQueueEntry,
    requeueQueueEntry: requeueQueueEntry,
    setBacklogItemPriority: setBacklogItemPriority,
    setBacklogItemFase: setBacklogItemFase,
    setBacklogItemVersion: setBacklogItemVersion,
    setBacklogItemState: setBacklogItemState,
  });
})();