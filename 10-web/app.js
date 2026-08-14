/* Factory Brain — interfaz web (FB-021), arranque, contexto de sesión y
 * navegación operativa condicionada al contexto (T-FB021-US02-01
 * conectividad; T-FB021-US02-02 proyecto activo; T-FB021-US02-03
 * navegación condicionada al contexto resuelto).
 *
 * Flujo de arranque (`index.html`, `app.js` se carga al final del body):
 *   1. `checkConnectivity()` invoca `getHealth()` ANTES de renderizar
 *      cualquier contenido operativo.
 *   2. Sin backend: guía de onboarding PASO 1 ("No hay conexión con el
 *      backend") con botón "Reintentar" que reutiliza el MISMO mecanismo
 *      de T-FB021-US02-01 (no un flujo duplicado). No se renderiza NINGÚN
 *      enlace a secciones operativas.
 *   3. Con backend pero sin proyecto activo: guía PASO 2 ("No has elegido
 *      un proyecto todavía") con botón "Elegir proyecto" que abre el
 *      MISMO selector de T-FB021-US02-02. Tampoco se renderizan enlaces a
 *      secciones.
 *   4. Con contexto resuelto (backend + proyecto activo): se muestra la
 *      navegación operativa (pestañas Agentes/Jobs/Plan/Scripts) + barra
 *      de contexto persistente con "Cambiar proyecto".
 *
 * Cambiar de proyecto voluntariamente (con contexto YA resuelto) usa un
 * TONO distinto al del arranque inicial (punto 3, criterio de aceptación):
 *   - `pickerReason === "initial"`  -> "Elige tu primer proyecto" (onboarding).
 *   - `pickerReason === "change"`   -> "Selecciona otro proyecto" (normal,
 *     no suena a onboarding) — mismo matiz que `can_return_to_dashboard`
 *     en la TUI (`brain/tui/screens/workspace.py`).
 *
 * Estado de secciones (punto 5): el modelo de cada sección
 * (Agentes/Jobs/Plan/Scripts) vive en `state.sections[<sección>]` — NO en
 * un módulo JS que se reinicialice al cambiar de sección. Al navegar entre
 * secciones sin recargar la página, la sección ya cargada se re-renderiza
 * desde esa caché (no se vuelve a llamar al backend), de modo que el estado
 * no se pierde igual que con una recarga completa.
 *
 * Sección Jobs (T-FB021-US04-01): a diferencia de Plan/Scripts (cargados
 * una vez), el estado de Jobs se recompone SIEMPRE desde `GET /jobs` + el
 * canal `WS /ws/jobs` (que se conecta al entrar en la pestaña y refleja
 * `created`/`running`/`completed`/`failed` sin polling) — nunca desde una
 * variable que se pierda al navegar entre secciones sin recargar la página
 * (punto 6). El botón "Cancelar Job" solo se habilita cuando el evento
 * `created` del WebSocket expone el `job_id` real: `POST /jobs` es
 * bloqueante y no lo devuelve hasta que el Job termina (punto 5).
 */
(function () {
  "use strict";

  var ROOT = document.getElementById("app-root");

  // ---------------------------------------------------------------- helpers
  function h(tag, className, textContent) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (textContent !== undefined) node.textContent = textContent;
    return node;
  }

  function button(text, className) {
    var b = h("button", className || "clickable", text);
    b.type = "button";
    return b;
  }

  function clearRoot() {
    ROOT.textContent = "";
    ROOT.style.display = "block";
  }

  function showError(message, retry) {
    clearRoot();
    var wrapper = h("div", "connectivity");
    wrapper.appendChild(h("h2", null, "No se pudo completar la operación"));
    wrapper.appendChild(h("p", null, message || ""));
    if (retry) {
      var b = button("Reintentar");
      b.addEventListener("click", retry);
      wrapper.appendChild(b);
    }
    ROOT.appendChild(wrapper);
  }

  // ------------------------------------------------------- routing (T-FB024)
  // Cada sección operativa tiene una URL propia bajo /ui/ (`/ui/roles`,
  // `/ui/arquitecto`...) en vez de vivir solo en `state.section` en memoria
  // — así recargar la página o compartir el enlace mantiene la sección
  // activa, y los botones atrás/adelante del navegador funcionan. El
  // backend sirve `index.html` para cualquier subruta de /ui/ que no sea
  // un asset real (ver `app.py::_SPAStaticFiles`), así que esto es
  // puramente de enrutado en el cliente: no hay servidor de rutas nuevo.
  var DEFAULT_SECTION = "backlog";
  var ROUTE_SECTIONS = ["backlog", "roles", "arquitecto", "plan", "scripts", "acciones", "agents", "jobs", "models"];

  function sectionFromPath(pathname) {
    // "/ui/roles" -> "roles"; "/ui/" o "/ui" -> sección por defecto.
    var trimmed = (pathname || "").replace(/^\/ui\/?/, "").replace(/\/$/, "");
    if (trimmed && ROUTE_SECTIONS.indexOf(trimmed) !== -1) return trimmed;
    return DEFAULT_SECTION;
  }

  function pathForSection(key) {
    return "/ui/" + key;
  }

  // --------------------------------------------------------------- state
  var state = {
    connected: false, // getHealth respondió OK
    projects: [], // candidatos descubiertos (GET /projects)
    active: null, // proyecto activo (GET /project) o null si no hay
    contextError: null,
    // Navegación entre secciones operativas (solo visible con contexto
    // resuelto). `sections` guarda el estado ya cargado de cada sección
    // para NO perderlo al navegar entre ellas sin recargar (punto 5).
    // Valor inicial resuelto desde la URL real (T-FB024), no un literal
    // fijo — así recargar la página respeta la sección en la que estabas.
    section: sectionFromPath(window.location.pathname),
    sections: { agents: null, jobs: null, plan: null, scripts: null, backlog: null, models: null, roles: null },
    showPicker: false,
    pickerReason: "initial", // "initial" (onboarding) | "change" (voluntario)
    pendingSelection: null,
    pendingBacklogCount: 0, // T-FB024-US01-02: numero de Epics/US con TODO>0
  };

  var SECTION_LOADERS = {
    jobs: function () {
      return BackendClient.getJobs();
    },
    plan: function () {
      return BackendClient.getPlans();
    },
    scripts: function () {
      return BackendClient.getScripts();
    },
  };

  // ------------------------------------------------------------------
  // Sección ROLES (T-FB024-US08-01): los 4 roles con nombre, descripción
  // Pantalla AGENTES unificada (US-FB024-11, reescritura completa).
  // Una fila por instancia de cada rol de gobierno: Arquitecto, Developer×N,
  // Auditor-OSS, UX, Tester (Documentador queda fuera). Mismos 4 campos
  // (nombre, estado, tiempo desde última orden, modelo) y mismas acciones
  // para todos, sin excepción por rol. El polling de GET /agents mantiene
  // las filas actualizadas sin recargar la página.
  var rolesSection = {
    bodyWrap: null,
    state: null, // null | "loading" | "ready" | "unavailable"
    error: null,
    defaults: {}, // {role: model_id} desde GET /models/preferences
    models: [], // [{id, name, runtime, enabled}]
    agentsList: null, // última lista de GET /agents
    stale: false,
    listError: null,
    pollTimer: null,
    actionMessage: null,
    // Edición del modelo por defecto (inline, solo para Arquitecto sintético).
    editingRole: null,
    modelIndex: 0,
    saving: false,
    saveError: null,
    // Cambio de modelo por instancia lanzada (prompt + GET/PUT agents/{id}/model).
    modelChangeAgentId: null,
    modelChangePending: null,
    modelChangeError: null,
    modelOptions: null,
    // Selector de modelo para agentes lanzados (modal inline con <select>).
    modelSelectAgentId: null,
    // Modal fallback de "Copiar comando de conexión" si clipboard.writeText falla.
    detalleAgent: null,
    detalleCopied: false,
    // "Revisar si está bloqueado": single-flight del POST /jobs al Arquitecto.
    reviewingBlockedAgentId: null,
    reviewBlockedError: null,
  };

  // ------------------------------------------------------------------
  // Sección AGENTES (T-FB021-US03-01). A diferencia de Jobs/Plan/Scripts
  // (cargados una vez y cacheados en `state.sections`), la lista de agentes
  // se refresca por POLLING cada [POLL_INTERVAL_MILLIS] mientras la pestaña
  // está visible — mismo intervalo/criterio que
  // `AgentsViewModel.POLL_INTERVAL_MILLIS` (Android, 3s): no existe canal
  // WebSocket de estado de agente en FB-016 (solo `job_status` en
  // `WS /ws/jobs`), por lo que el polling ligero es el mecanismo.
  //
  // El estado de la sección vive en `agentsSection` (no en un módulo que se
  // reinicialice): `list` es la última lista vista y `stale` indica que el
  // último ciclo de polling falló pero la lista se conserva (criterio 2).
  var POLL_INTERVAL_MILLIS = 3000;

  // Paleta fija de estado — misma que `colorForAgentStatus` (Android):
  // colores independientes de cualquier tema, verificados a >=3:1 de
  // contraste (WCAG 1.4.11) sobre los fondos claro (#FAFDFD/#FFFFFF) y
  // oscuro (#191C1C). El color es un indicador COMPLEMENTARIO del texto de
  // estado, nunca su sustituto (criterio 4).
  var AGENT_STATUS_COLORS = {
    idle: "#2E7D32", // verde (Green 800) — disponible
    working: "#EF6C00", // ámbar/naranja (Orange 800) — ocupado
    stopped: "#757575", // gris (Grey 600) — inactivo a propósito
    unavailable: "#D32F2F", // rojo (Red 700) — fallo no solicitado
  };

  function agentStatusColor(status) {
    return AGENT_STATUS_COLORS[status] || "#757575";
  }

  // Estado de la sección Agentes: la lista (con su señal de "desactualizada")
  // y el catálogo de lanzamiento (estado de carga propio e independiente del
  // polling — punto 6: el catálogo `GET /agents/options` se resuelve UNA sola
  // vez y el formulario no se muestra mientras está cargando).
  var agentsSection = {
    list: null, // null = sin lista todavía | array = última lista vista
    stale: false,
    listError: null,
    showStopped: false,
    catalogState: null, // null=sin empezar | "loading" | "ready" | "unavailable"
    catalog: null,
    catalogError: null,
    optionIndex: 0,
    modelInput: "",
    taskInput: "",
    launching: false,
    actionMessage: null,
    bodyWrap: null,
    pollTimer: null,
    // Confirmación de "Detener" (segunda pulsación, T-FB021-US03-02).
    stopPendingFor: null, // agent_id con confirmación pendiente | null
    stopPendingHasJob: false,
    stoppingAgentId: null, // parada en vuelo (single-flight); el botón se deshabilita
    // Pane de actividad (T-FB021-US03-02): null=cerrado | "loading" |
    // "open" | "unavailable".
    paneState: null,
    paneAgentId: null,
    paneAgentName: null,
    paneContent: null,
    paneMessage: null,
    // Cambio de modelo (T-FB021-US07-01): confirmacion de segunda pulsacion
    // y single-flight, mismo idioma que el resto de la web.
    modelChangeAgentId: null, // agente cuyo cambio esta en curso | null
    modelChangePending: null, // {agent_id, model} con confirmacion pendiente | null
    modelChangeError: null, // mensaje de error tras intento de cambio | null
    modelOptions: null, // catalogo de modelos disponibles, cacheado por agente
    launchPending: false, // T-FB024-US04-01: confirmacion antes de lanzar
  };

  // ------------------------------------------------------------------
  // Sección JOBS (T-FB021-US04-01). El estado de la sección vive en
  // `jobsSection` (no en un módulo que se reinicialice): `list` es el
  // histórico recompuesto desde `GET /jobs` y `pendingCreatedJob` el Job
  // en curso. La lista se recalcula SIEMPRE desde `GET /jobs`/el canal
  // `WS /ws/jobs` (punto 6): navegar a otra sección y volver recompone
  // desde el mismo backend, no se pierde nada (mismo criterio que la TUI).
  //
  // `WS /ws/jobs` empuja eventos `job_status` con `created` (publicado por
  // `POST /jobs` ANTES de despachar — expone el `job_id` real antes de que
  // el POST bloqueante responda) y el evento final `completed`/`failed`
  // después (ver `routes.py::post_jobs` y `app.py::ws_jobs`). `running`
  // no se publica por el canal en el backend actual, pero un Job en ese
  // estado sí aparece en `GET /jobs`; el manejo de mensajes lo acepta por
  // si el canal llegara a emitirlo.
  var WS_RECONNECT_DELAY_MILLIS = 3000;

  var jobsSection = {
    // Histórico vivo: null = sin cargar | array = última lista vista.
    list: null,
    stale: false,
    listError: null,
    // Job seleccionado en el histórico para ver su detalle completo (punto
    // 2 de T-FB021-US04-02): id basado, persiste a través de la
    // recomposición desde GET /jobs.
    selectedJobId: null,
    // Formulario de creación (punto 3): agentes destinatarios (de los ya
    // lanzados, T-FB021-US03-01), descripción y Job previo opcional.
    agents: null, // null = sin cargar | array = agentes lanzados (sin stopped)
    agentsError: null,
    agentIndex: 0,
    descriptionInput: "",
    previousJobId: null, // job_id encadenado | null
    formError: null,
    // Despacho en curso (punto 4): `createInFlight` (single-flight) es el
    // guard de la petición `POST /jobs`; `pendingCreatedJob` se rellena con
    // el `job_id` REAL cuando llega el evento `created` por WS — es la
    // señal que habilita "Cancelar Job" (punto 5).
    createInFlight: false,
    pendingCreatedJob: null, // { id, agentId, description, status } | null
    progressMessage: null,
    // Cancelar (segunda pulsación, mismo patrón que la TUI).
    cancelPendingFor: null, // job_id con confirmación pendiente | null
    cancellingJobId: null, // cancelación en vuelo (single-flight)
    // Canal WS: null = desconectado | ReconnectingWebSocket activo.
    ws: null,
    wsStatus: null, // null | "connecting" | "connected" | "reconnecting"
    bodyWrap: null,
  };

  // Sección PLAN (T-FB021-US05-01): solicitud del plan del Critic, vista
  // completa y aprobación/rechazo — paridad con `PlanScreen`/`PlanViewModel`.
  // `currentPlan` es el plan mostrado (plan_id + goal + status + steps); el
  // filtro de `WS /ws/plans` (punto 3) descarta todo evento cuyo `plan_id`
  // no coincida con `currentPlanId`.
  var plansSection = {
    bodyWrap: null,
    // Plan mostrado actualmente: null = ninguno (formulario visible).
    currentPlan: null, // { plan_id, goal, status, steps } | null
    currentPlanId: null, // filtro de eventos WS (punto 3)
    goalInput: "",
    goalSelectIndex: 0,
    // T-FB024-US04-02: historias TODO del backlog como opciones del selector.
    todoStories: null, // null = sin cargar | array = [{id, epic}]
    todoStoriesLoading: false,
    todoStoriesError: null,
    requesting: false, // single-flight POST /plans
    requestError: null,
    // Aprobar (punto 5): confirmación previa con el número de pasos en la
    // ETIQUETA del propio botón (mismo patrón anti-reflow de Cancelar/Detener)
    // + single-flight de la llamada real (punto 7).
    approvePending: false,
    approving: false,
    rejecting: false, // single-flight POST /plans/{id}/reject (punto 7)
    // Cancelar (T-FB021-US05-02): SOLO se ofrece mientras el plan está
    // `approved` y quedan pasos `pending`/`running` (misma condición que
    // el dominio `request_cancellation`). Confirmación de 2ª pulsación en
    // la ETIQUETA del botón (mismo patrón anti-reflow que Cancelar
    // Job/Detener) + single-flight de la llamada real (punto 3).
    cancelPendingFor: null, // plan_id con confirmación pendiente | null
    cancellingPlanId: null, // cancelación en vuelo (single-flight)
    // Histórico (T-FB021-US05-02): lista desde `GET /plans` (incluye los
    // ya decididos — el backend no purga ninguno, mismo criterio que
    // `GET /jobs`) + detalle de uno concreto vía `GET /plans/{id}`.
    history: null, // null = sin cargar | array = planes de la sesión
    historyError: null,
    historyStale: false,
    selectedPlanId: null, // plan del histórico con detalle desplegado | null
    historyDetail: null, // detalle cargado vía GET /plans/{id} | null
    historyDetailError: null,
    actionError: null,
    // Canal WS /ws/plans (mismo wrapper reutilizado de T-FB021-US04-01).
    ws: null,
    wsStatus: null, // null | "connecting" | "connected" | "reconnecting"
  };

  // Sección SCRIPTS (T-FB021-US06-01): catálogo combinado (genérico +
  // particular, `GET /scripts`) con indicador de origen, ejecución con un
  // clic (`POST /scripts/{id}/run`), resultado completo (success/stdout/
  // stderr/error_message) y presentación legible de `backlog_status`
  // (punto 4, mismo shape de T-FB018-US02-04). `runningScriptId` es el
  // single-flight de la ejecución (punto 5).
  var scriptsSection = {
    bodyWrap: null,
    // Catálogo combinado: null = sin cargar | array = última lista vista.
    list: null,
    listError: null,
    stale: false,
    // Mensaje para el script `commit` (punto 2): botón deshabilitado hasta
    // tener mensaje no vacío (mismo criterio que Android/TUI).
    commitMessage: "",
    // Single-flight (punto 5): script en ejecución | null.
    runningScriptId: null,
    // Último resultado (punto 3): { scriptId, success, exit_code, stdout,
    // stderr, error_message, data, prose } | null.
    lastResult: null,
    runError: null,
    _expandedCommandId: null,
  };

  // ------------------------------------------------------------- BACKLOG
  // (T-FB020-US04-01). Mismo patrón de expandir-en-el-sitio ya usado en
  // Jobs/Plan (histórico con detalle desplegable al clic, sin navegar a
  // otra pantalla) — no un `Screen`/estado de navegación por pantallas
  // como Android/TUI: lista de Epics -> clic expande sus User Stories
  // (`GET /backlog/{epic_id}`) -> clic en una US expande su detalle
  // completo (`GET /backlog/{item_id}`) + el formulario de "Lanzar
  // desarrollo", todo dentro de la MISMA lista, sin recargar la página.
  //
  // `report` se recompone SIEMPRE desde `GET /backlog` al entrar en la
  // pestaña (mismo criterio que Jobs/Plan/Scripts: nunca se pierde al
  // navegar entre secciones, vive en `backlogSection`, no en la caché
  // genérica `state.sections`) — resuelve la recontextualización por
  // cambio de proyecto activo "gratis", igual que el resto de secciones
  // (no hay filtro de proyecto en el cliente: el backend ya sirve el
  // backlog del proyecto activo).
  var backlogSection = {
    bodyWrap: null,
    // Listado raíz: null = sin cargar | array = última lista vista (`by_epic`).
    report: null,
    reportError: null,
    stale: false,
    // Epic actualmente expandida en el listado (id `FB-xxx` derivado del
    // label libre) — su detalle se pide con `GET /backlog/{epic_id}` de
    // forma perezosa (solo al expandir, mismo criterio que
    // `togglePlanHistoryDetail`).
    selectedEpicId: null,
    epicDetail: null,
    epicDetailError: null,
    // User Story actualmente expandida DENTRO de la Epic expandida — su
    // detalle se pide con `GET /backlog/{item_id}`.
    selectedItemId: null,
    itemDetail: null,
    itemDetailError: null,
    // Formulario "Lanzar desarrollo" (solo visible para el detalle de una
    // User Story, T-FB020-US02-02): agentes Developer ya lanzados
    // (mismo catálogo que Agentes/Jobs, filtrado a role === "developer"),
    // single-flight de la propia llamada, y el resultado/`detail` real
    // del backend ante un rechazo (400 sin Tasks TODO, 404 agente
    // inválido) — nunca un mensaje genérico (criterio de aceptación
    // explícito, mismo patrón que T-FB021-US04-01).
    developerAgents: null,
    developerAgentsError: null,
    developerAgentIndex: 0,
    launchingDevelopment: false,
    launchError: null,
    launchResult: null,
    viewMode: "flat", // "flat" | "by_fase"
    // T-FB024-US09-02: historial de jobs para la US abierta en detalle.
    usJobs: null,
    usJobsError: null,
    // T-FB024-US09-03: formulario manual de Job en detalle de US.
    manualJobAgents: null,
    manualJobAgentsError: null,
    manualJobAgentIndex: 0,
    manualJobDescription: "",
    creatingManualJob: false,
    manualJobError: null,
    manualJobResult: null,
    // T-FB026-US04-02: análisis de hilos de desarrollo.
    threadsInFlight: false,
    threadsResult: null,
    threadsError: null,
  };

  // Sección MODELOS (T-FB022-US10-02): catálogo con habilitado/deshabilitado
  // y defaults por rol, consumiendo GET/PUT /models/preferences.
  var modelsSection = {
    bodyWrap: null,
    // Estado de carga: null=sin empezar | "loading" | "ready" | "unavailable".
    state: null,
    error: null,
    // Catálogo completo del backend: [{id, name, runtime, enabled}, ...].
    models: null,
    defaults: {}, // {role: model_id}
    dirty: false, // cambios locales no guardados
    saving: false, // single-flight PUT
    saveError: null,
  };

  // --------------------------------------------------------- FB-025 Hilo 3
  var accionesSection = {
    bodyWrap: null,
    inFlight: null, // action_id en vuelo o null
    result: null,   // {action, status, result} o {action, success, stdout, ...}
    error: null,
  };

  // --------------------------------------------------------- FB-028
  // Barra de estado persistente del Arquitecto (US-FB028-01): polling 3s
  // del agente Arquitecto, modelo y botón lanzar/detener visibles en todas
  // las pestañas. El estado solo se refresca si hay proyecto activo.
  var ARQUITECTO_POLL_MILLIS = 3000;

  var arquitectoState = {
    agent: null,    // agente Arquitecto lanzado (de GET /agents) o null
    stale: false,
    error: null,
    pollTimer: null,
    launchPending: false,
    stopPending: false,
    defaultModel: null, // modelo default para arquitecto desde GET /models/preferences
    modelPreferencesReady: false,
  };

  // Pestaña Arquitecto (US-FB028-02): órdenes deterministas, prompt libre
  // e historial de últimas 10 respuestas.
  var ORDENES_ARQUITECTO = [
    { id: "generar-us", label: "Generar User Stories", desc: "Toma una Epic y la desglosa en User Stories.", needsSelect: "epic", promptPrefix: "Desglosa la siguiente Epic en User Stories:" },
    { id: "desgranar-tasks", label: "Desgranar en Tasks", desc: "Toma una User Story y genera sus Tasks.", needsSelect: "us", promptPrefix: "Genera las Tasks para la siguiente User Story:" },
    { id: "emitir-veredicto", label: "Emitir veredicto", desc: "Revisa el trabajo del Developer sobre una US en progreso y emite veredicto estructurado.", needsSelect: "us_in_progress", promptPrefix: "Revisa el trabajo del Developer sobre esta User Story y emite tu veredicto:" },
    { id: "auditar-consistencia", label: "Auditar consistencia", desc: "Revisa todo el backlog buscando US sin Epic, Tasks sin US, formatos rotos y dependencias circulares.", needsSelect: null, promptPrefix: "Audita la consistencia del backlog completo del proyecto. Busca: User Stories sin Epic, Tasks sin User Story, formatos rotos en cualquier fichero del backlog, y dependencias circulares. Genera un informe con los hallazgos." },
    { id: "informe-progreso", label: "Informe de progreso", desc: "Genera un resumen del pipeline: US en cada estado, bloqueos y cuellos de botella.", needsSelect: null, promptPrefix: "Genera un informe completo del estado del pipeline de desarrollo. Incluye: cuántas User Stories hay en cada estado (TODO, in_progress, DONE), qué bloqueos existen (dependencias sin resolver), y qué cuellos de botella detectas. Resume también el estado de cada Epic." },
  ];

  var arquitectoTabState = {
    bodyWrap: null,
    activeJobId: null,
    activeOrderId: null,
    jobResult: null,
    selectedEpicId: null,
    selectedUSId: null,
    promptText: "",
    promptConfirmPending: false,
    history: null,       // últimas 10 Jobs del Arquitecto
    historyError: null,
    backoffDelay: 1000,  // polling backoff para Job en curso
  };


  // ------------------------------------------------------------- render
  // Decisión central: qué renderizar según el contexto.
  //   - selector abierto            -> lista de proyectos (tono por origen)
  //   - sin conexión                -> guía paso 1 (conectividad)
  //   - conectado sin proyecto      -> guía paso 2 (proyecto)
  //   - conectado + proyecto activo -> navegación operativa (4 secciones)
  // El selector (initial o change) debe abrirse SIEMPRE que `showPicker`,
  // también cuando ya hay un proyecto activo (cambio voluntario desde la
  // barra de contexto): por eso va primero, antes de `renderOperational`.
  function render() {
    if (state.showPicker || !state.connected || !state.active) {
      stopArquitectoPolling();
      stopRolesPolling();
    }
    if (state.showPicker) {
      renderProjectPicker();
    } else if (!state.connected) {
      renderConnectivityGuide();
    } else if (!state.active) {
      renderProjectStep();
    } else {
      renderOperational();
    }
    renderPendingWarning();
  }

  // --------------------------------------------- paso 1: sin backend (US02-01)
  function renderConnectivityGuide() {
    clearRoot();
    var wrapper = h("div", "onboarding");
    wrapper.appendChild(h("h2", null, "No hay conexión con el backend"));
    wrapper.appendChild(
      h(
        "p",
        null,
        "Factory Brain necesita hablar con el backend antes de poder mostrar " +
          "agentes, Jobs o el plan del Critic. Comprueba que el servicio esté en " +
          "marcha y vuelve a intentarlo."
      )
    );
    if (state.contextError) {
      wrapper.appendChild(h("p", "error-detail", "Detalle: " + state.contextError));
    }
    // CTA directo al MISMO mecanismo de reintento de T-FB021-US02-01
    // (checkConnectivity), sin duplicar el flujo.
    var retry = button("Reintentar");
    retry.addEventListener("click", checkConnectivity);
    wrapper.appendChild(retry);
    ROOT.appendChild(wrapper);
  }

  // ------------------------------------------- paso 2: sin proyecto (US02-02)
  function renderProjectStep() {
    clearRoot();
    var wrapper = h("div", "onboarding");
    wrapper.appendChild(h("h2", null, "No has elegido un proyecto todavía"));
    wrapper.appendChild(
      h(
        "p",
        null,
        "Ya hay conexión con el backend. Elige sobre qué proyecto quieres " +
          "trabajar para acceder a Agentes, Jobs, Plan y Scripts."
      )
    );
    // CTA directo al MISMO selector de T-FB021-US02-02 (openProjectPicker).
    var cta = button("Elegir proyecto");
    cta.addEventListener("click", function () {
      openProjectPicker("initial");
    });
    wrapper.appendChild(cta);
    ROOT.appendChild(wrapper);
  }

  // ---------------------------------------------------- selector de proyecto
  // Tono según el origen (punto 3): arranque inicial vs cambio voluntario.
  function renderProjectPicker() {
    clearRoot();
    var wrapper = h("div", "onboarding");
    var isInitial = state.pickerReason === "initial";
    wrapper.appendChild(
      h("h2", null, isInitial ? "Elige tu primer proyecto" : "Selecciona otro proyecto")
    );
    wrapper.appendChild(
      h(
        "p",
        null,
        isInitial
          ? "Lista de proyectos descubiertos en el backend. Elige uno para continuar."
          : "Tienes un proyecto activo ahora mismo; selecciona otro si quieres cambiar."
      )
    );
    if (state.contextError) {
      wrapper.appendChild(h("p", "error-detail", "Aviso: " + state.contextError));
    }
    if (!state.projects || state.projects.length === 0) {
      wrapper.appendChild(h("p", null, "No se descubrió ningún proyecto en este workspace."));
    } else {
      var list = h("ul", "project-list");
      state.projects.forEach(function (project) {
        var li = h("li");
        var item = button(project.name, "project-option");
        var isActive = state.active && state.active.id === project.id;
        item.textContent = project.name + (isActive ? " (activo)" : "");
        item.addEventListener("click", function () {
          requestSelectProject(project);
        });
        li.appendChild(item);
        list.appendChild(li);
      });
      wrapper.appendChild(list);
    }
    // Vuelta atrás al paso anterior sin cambiar nada: `render()` decide
    // el destino según el contexto (paso 2 de la guía en arranque inicial,
    // vista operativa en un cambio voluntario).
    var back = button("Cancelar");
    back.addEventListener("click", function () {
      state.showPicker = false;
      render();
    });
    wrapper.appendChild(back);
    ROOT.appendChild(wrapper);
  }

  // ---------------------------------------------- navegación operativa (4)
  function renderOperational() {
    clearRoot();

    // Barra de contexto persistente: proyecto activo + acceso a cambiarlo
    // (mismo criterio de T-FB021-US02-02).
    var toolbar = h("div", "context-bar");
    var name = state.active && state.active.name ? state.active.name : "ninguno";
    toolbar.appendChild(h("span", "context-chip", "Proyecto activo: " + name));
    var changeBtn = button("Cambiar proyecto");
    changeBtn.addEventListener("click", function () {
      openProjectPicker("change");
    });
    toolbar.appendChild(changeBtn);
    ROOT.appendChild(toolbar);

    // Barra de estado del Arquitecto (US-FB028-01): segunda linea bajo
    // proyecto activo, visible en todas las pestañas.
    var arqBar = h("div", "arquitecto-bar");
    arquitectoState._barEl = arqBar;
    ROOT.appendChild(arqBar);
    startArquitectoPolling();
    renderArquitectoBar();

    // Menú/pestañas simples entre las 4 secciones operativas (punto 1):
    // enlaces/botones que cambian qué sección del DOM se muestra, sin
    // recargar la página.
    var nav = h("nav", "section-nav");
    ["backlog", "roles", "arquitecto", "plan", "scripts", "acciones"].forEach(function (key) {
      var tab = button(SECTION_LABEL(key), "section-tab");
      if (key === "backlog" && state.pendingBacklogCount > 0) {
        tab.appendChild(h("span", "backlog-pending-badge", String(state.pendingBacklogCount)));
      }
      if (key === state.section) tab.className += " active";
      tab.addEventListener("click", function () {
        switchSection(key);
      });
      nav.appendChild(tab);
    });
    ROOT.appendChild(nav);

    // Cuerpo de la sección activa.
    renderSectionContent();
  }

  function SECTION_LABEL(key) {
    return { roles: "Agentes", agents: "Agentes", jobs: "Jobs", plan: "Plan", scripts: "Scripts", backlog: "Backlog", models: "Modelos", acciones: "Acciones", arquitecto: "Arquitecto" }[key];
  }

  // Barra de estado del Arquitecto (US-FB028-01): segunda linea bajo
  // proyecto activo con indicador de estado, rol y modelo. Sin boton de
  // accion: Lanzar/Detener del Arquitecto se gestiona en la pantalla Agentes.
  function renderArquitectoBar() {
    var bar = arquitectoState._barEl;
    if (!bar) return;
    bar.textContent = "";

    var arq = arquitectoState.agent;
    var isActive = arq && arq.status !== "stopped";
    var isWorking = arq && arq.status === "working";

    // Indicador de estado
    var dot = h("span", "arq-status-dot");
    if (isWorking) {
      dot.className += " arq-status-dot-working";
    } else if (isActive) {
      dot.className += " arq-status-dot-active";
    }
    bar.appendChild(dot);

    // Nombre del rol
    bar.appendChild(h("span", "arq-role-name", "Arquitecto"));

    // Modelo
    if (isActive && arq.model) {
      bar.appendChild(h("span", "arq-model", arq.model));
    } else if (arquitectoState.defaultModel) {
      bar.appendChild(h("span", "arq-model", arquitectoState.defaultModel));
    } else {
      bar.appendChild(h("span", "arq-model arq-model-none", "sin modelo"));
    }

    // Estado
    var statusText = "";
    if (arquitectoState.error) {
      statusText = arquitectoState.error;
    } else if (arquitectoState.launchPending) {
      statusText = "lanzando…";
    } else if (isWorking) {
      statusText = "trabajando";
    } else if (isActive) {
      statusText = "activo";
    } else {
      statusText = "inactivo";
    }
    bar.appendChild(h("span", "arq-status-text", statusText));
  }

  // `fromHistory`: true cuando la llamada viene del listener `popstate`
  // (el usuario pulsó atrás/adelante) — en ese caso la URL YA es la
  // correcta y no debe volver a empujarse al historial (evitaría poder
  // navegar hacia atrás nunca, cada "atrás" generaría una entrada nueva).
  function switchSection(key, fromHistory) {
    if (key !== state.section && state.section === "agents") {
      // Al salir de la pestaña Agentes se para el polling (no se hacen
      // llamadas de fondo sin pantalla visible); al volver se reanuda.
      // El estado de cambio de modelo se limpia al salir (mismo criterio
      // que el pane de actividad, que persiste mientras se esta en la
      // seccion pero se cierra al cambiar).
      stopAgentsPolling();
      agentsSection.modelChangePending = null;
      agentsSection.modelChangeError = null;
      agentsSection.modelChangeAgentId = null;
      agentsSection.modelOptions = null;
      agentsSection.launchPending = false;
    }
    if (key !== state.section && state.section === "roles") {
      stopRolesPolling();
      rolesSection.editingRole = null;
      rolesSection.modelIndex = 0;
      rolesSection.saveError = null;
      rolesSection.modelChangeAgentId = null;
      rolesSection.modelChangePending = null;
      rolesSection.modelChangeError = null;
      rolesSection.modelOptions = null;
      rolesSection.detalleAgent = null;
      rolesSection.detalleCopied = false;
      rolesSection.reviewingBlockedAgentId = null;
      rolesSection.reviewBlockedError = null;
    }
    if (key !== state.section && state.section === "jobs") {
      // Al salir de la pestaña Jobs se cierra el WebSocket (no se mantiene
      // una conexión de fondo sin pantalla visible); al volver se reabre.
      // El estado propio de la sección no se pierde: vive en `jobsSection`.
      stopJobsWebSocket();
    }
    if (key !== state.section && state.section === "plan") {
      // Mismo criterio que Jobs: al salir de la pestaña Plan se cierra el
      // canal `WS /ws/plans` y se resetea la carga del backlog; el estado
      // vive en `plansSection`.
      stopPlansWebSocket();
      plansSection.todoStories = null;
    }
    if (key !== state.section && state.section === "arquitecto") {
      arquitectoTabState.activeJobId = null;
      arquitectoTabState.activeOrderId = null;
      arquitectoTabState.jobResult = null;
      arquitectoTabState.promptText = "";
      arquitectoTabState.promptConfirmPending = false;
    }
    state.section = key;
    if (!fromHistory) {
      history.pushState({ section: key }, "", pathForSection(key));
    }
    renderOperational();
  }

  // Botones atrás/adelante del navegador: `popstate` dispara con el
  // `state` que se pasó a `pushState` (o `null` en la entrada inicial de
  // carga de página, de ahí el fallback a `sectionFromPath`).
  window.addEventListener("popstate", function (event) {
    if (!state.connected || !state.active) return; // aún no hay vista operativa que navegar
    var key = (event.state && event.state.section) || sectionFromPath(window.location.pathname);
    switchSection(key, true);
  });

  // ----------------------------------------------------- contenido sección
  function renderSectionContent() {
    var content = h("div", "section-content");
    content.appendChild(h("h3", null, SECTION_LABEL(state.section)));

    // Roles tiene su propio renderizado con estado (catálogo de 4 roles
    // con modelo y descripción, T-FB024-US08-01): no pasa por la caché.
    if (state.section === "roles") {
      ROOT.appendChild(content);
      renderRolesInto(content);
      return;
    }
    // Agentes tiene su propio renderizado con estado (polling + catálogo +
    // formulario): no pasa por la carga/caché única de Jobs/Plan/Scripts.
    if (state.section === "agents") {
      ROOT.appendChild(content);
      renderAgentsInto(content);
      return;
    }
    // Jobs también tiene su propio renderizado con estado (formulario +
    // WebSocket `WS /ws/jobs` + histórico recompuesto desde `GET /jobs`):
    // no pasa por la carga/caché única de Plan/Scripts.
    if (state.section === "jobs") {
      ROOT.appendChild(content);
      renderJobsInto(content);
      return;
    }
    // Plan también tiene su propio renderizado con estado (formulario de
    // solicitud + WebSocket `WS /ws/plans` + recuperación de un plan
    // `proposed` pendiente desde `GET /plans`): no pasa por la caché única.
    if (state.section === "plan") {
      ROOT.appendChild(content);
      renderPlansInto(content);
      return;
    }
    // Scripts también tiene su propio renderizado con estado (catálogo
    // combinado + ejecución con single-flight + resultado completo,
    // T-FB021-US06-01): no pasa por la caché única de `renderSectionData`.
    if (state.section === "scripts") {
      ROOT.appendChild(content);
      renderScriptsInto(content);
      return;
    }
    // Backlog también tiene su propio renderizado con estado (listado de
    // Epics + detalle expandido en el sitio + formulario de "Lanzar
    // desarrollo", T-FB020-US04-01): no pasa por la caché única.
    if (state.section === "backlog") {
      ROOT.appendChild(content);
      renderBacklogInto(content);
      return;
    }
    if (state.section === "models") {
      ROOT.appendChild(content);
      renderModelsInto(content);
      return;
    }
    if (state.section === "arquitecto") {
      ROOT.appendChild(content);
      renderArquitectoInto(content);
      return;
    }
    if (state.section === "acciones") {
      ROOT.appendChild(content);
      renderAccionesInto(content);
      return;
    }

    var cached = state.sections[state.section];
    if (cached !== null) {
      // Ya cargada en una navegación anterior: re-render desde la caché,
      // SIN volver a llamar al backend (el estado no se pierde, punto 5).
      content.appendChild(renderSectionData(state.section, cached));
    } else {
      content.appendChild(h("p", "section-note", "Cargando " + SECTION_LABEL(state.section) + "…"));
      loadSectionInto(state.section, content);
    }
    ROOT.appendChild(content);
  }

  function loadSectionInto(key, contentEl) {
    SECTION_LOADERS[key]()
      .then(function (data) {
        state.sections[key] = data;
        // Si el usuario ya se movió a otra sección mientras cargaba, no
        // tocar el DOM actual.
        if (state.section !== key) return;
        contentEl.textContent = "";
        contentEl.appendChild(renderSectionData(key, data));
      })
      .catch(function (error) {
        state.sections[key] = { error: buildErrorMessage(error) };
        if (state.section !== key) return;
        contentEl.textContent = "";
        contentEl.appendChild(renderSectionData(key, state.sections[key]));
      });
  }

  // Renderizado puro de cada sección (sin estado mutable aquí). La sección
  // Agentes NO pasa por aquí (tiene su propio renderizado en `renderAgentsInto`).
  function renderSectionData(key, data) {
    var box = h("div", "section-data");
    if (data && data.error) {
      box.appendChild(h("p", "error-detail", "Error: " + data.error));
      return box;
    }
    if (key === "jobs") {
      if (!data || data.length === 0) {
        box.appendChild(h("p", "section-note", "No hay Jobs en la sesión."));
        return box;
      }
      data.forEach(function (job) {
        box.appendChild(h("p", "section-line", job.id + " · " + job.status + " · " + (job.description || "")));
      });
    } else if (key === "plan") {
      if (!data || data.length === 0) {
        box.appendChild(h("p", "section-note", "No hay planes solicitados todavía."));
        return box;
      }
      data.forEach(function (plan) {
        box.appendChild(h("p", "section-line", plan.plan_id + " · " + plan.status + " · " + plan.goal));
      });
    } else if (key === "scripts") {
      // T-FB021-US06-01: Scripts tiene su PROPIO renderizado con estado
      // (catálogo + ejecución + resultado); este caso solo se alcanza si
      // por algún camino no contemplado se invoca `renderSectionData`
      // para scripts — se mantiene como respaldo legible sin romper.
      if (!data || data.length === 0) {
        box.appendChild(h("p", "section-note", "No hay scripts catalogados en la sesión."));
        return box;
      }
      data.forEach(function (script) {
        box.appendChild(h("p", "section-line", script.name + " (" + (script.origin || "particular") + ")"));
      });
    }
    return box;
  }

  // ------------------------------------------------------------- AGENTES
  // (T-FB021-US03-01). Polling 3s + filtro de detenidos + formulario de
  // lanzamiento con catálogo propio. Ver `agentsSection` arriba.

  // Entrada de la sección: crea el contenedor, arranca el polling y la
  // carga única del catálogo, y renderiza.
  function renderAgentsInto(content) {
    agentsSection.bodyWrap = h("div", "agents-body");
    content.appendChild(agentsSection.bodyWrap);
    startAgentsPolling();
    ensureAgentsCatalog();
    renderAgentsBody();
  }

  // Polling periódico (3s). El intervalo se para solo al salir de la
  // pestaña (ver `switchSection`); mientras está en otro sección no hace
  // ninguna llamada.
  function startAgentsPolling() {
    if (agentsSection.pollTimer) return;
    agentsSection.pollTimer = setInterval(function () {
      if (state.section !== "agents") {
        stopAgentsPolling();
        return;
      }
      pollAgents();
    }, POLL_INTERVAL_MILLIS);
    pollAgents();
  }

  function stopAgentsPolling() {
    if (agentsSection.pollTimer) {
      clearInterval(agentsSection.pollTimer);
      agentsSection.pollTimer = null;
    }
  }

  // Un fallo puntual de un ciclo de polling no borra la última lista ya
  // vista (criterio 2): si ya había lista, se conserva marcada `stale`
  // (aviso "puede que esta lista esté desactualizada") en vez de
  // sustituirla por un error genérico o vaciarla — mismo criterio que
  // `nextStateAfterPollFailure` (Android). Solo cuando nunca hubo lista
  // (primer arranque) se muestra el error de conexión.
  async function pollAgents() {
    try {
      var agents = await BackendClient.getAgents();
      agentsSection.list = agents;
      agentsSection.stale = false;
      agentsSection.listError = null;
    } catch (error) {
      if (agentsSection.list !== null) {
        agentsSection.stale = true;
      } else {
        agentsSection.listError = buildErrorMessage(error);
        agentsSection.stale = false;
      }
    }
    if (state.section === "agents") renderAgentsBody();
  }

  // Catálogo `GET /agents/options`: estado de carga PROPIO e independiente
  // del polling de agentes (punto 6). Se resuelve UNA sola vez (no se
  // repite en cada ciclo). Mientras carga, el formulario de lanzamiento no
  // se muestra en absoluto (evita un desplegable vacío u obsoleto). Un
  // catálogo vacío es un caso distinto de "no se pudo cargar": ambos se
  // tratan explícitamente, sin asumir `options[0]` como seguro (incidente
  // real T-FB017-US01-10: un 404 de esta ruta tiraba la app).
  function ensureAgentsCatalog() {
    if (agentsSection.catalogState) return; // ya empezado/resuelto
    agentsSection.catalogState = "loading";
    renderAgentsBody();
    BackendClient.getAgentOptions()
      .then(function (options) {
        agentsSection.catalogState = "ready";
        agentsSection.catalog = options || [];
        renderAgentsBody();
      })
      .catch(function (error) {
        agentsSection.catalogState = "unavailable";
        agentsSection.catalogError = buildErrorMessage(error);
        renderAgentsBody();
      });
  }

  // --------------------------------------------------- FB-028 Arquitecto
  // Polling 3s del estado del Arquitecto (US-FB028-01): busca el agente
  // con role=arquitecto en GET /agents y actualiza la barra de estado.
  // Arranca al activar proyecto y se para al cambiarlo.

  function ensureArquitectoModelPreferences() {
    if (arquitectoState.modelPreferencesReady) return;
    BackendClient.getModelsPreferences()
      .then(function (result) {
        arquitectoState.defaultModel = (result.defaults && result.defaults.arquitecto) || null;
        arquitectoState.modelPreferencesReady = true;
        renderArquitectoBar();
      })
      .catch(function () {
        arquitectoState.modelPreferencesReady = true;
      });
  }

  function startArquitectoPolling() {
    if (arquitectoState.pollTimer) return;
    ensureArquitectoModelPreferences();
    arquitectoState.pollTimer = setInterval(pollArquitecto, ARQUITECTO_POLL_MILLIS);
    pollArquitecto();
  }

  function stopArquitectoPolling() {
    if (arquitectoState.pollTimer) {
      clearInterval(arquitectoState.pollTimer);
      arquitectoState.pollTimer = null;
    }
    arquitectoState.agent = null;
    arquitectoState.stale = false;
    arquitectoState.error = null;
    arquitectoState.launchPending = false;
    arquitectoState.stopPending = false;
    arquitectoState.modelPreferencesReady = false;
    arquitectoState.defaultModel = null;
  }

  async function pollArquitecto() {
    if (!state.active) return;
    try {
      var agents = await BackendClient.getAgents();
      var arq = null;
      if (Array.isArray(agents)) {
        for (var i = 0; i < agents.length; i++) {
          if (agents[i].role === "arquitecto" && agents[i].status !== "stopped") {
            arq = agents[i];
            break;
          }
        }
      }
      arquitectoState.agent = arq;
      arquitectoState.stale = false;
      arquitectoState.error = null;
    } catch (error) {
      if (arquitectoState.agent !== null || arquitectoState.stale) {
        arquitectoState.stale = true;
      } else {
        arquitectoState.error = buildErrorMessage(error);
      }
    }
    renderArquitectoBar();
    if (state.section === "arquitecto") renderArquitectoBody();
  }

  function launchArquitecto() {
    if (arquitectoState.launchPending || arquitectoState.stopPending) return;
    if (!arquitectoState.defaultModel) return;
    arquitectoState.launchPending = true;
    renderArquitectoBar();
    // Claude Code no admite el campo `model` en POST /agents: cuando el
    // modelo por defecto es claude-code, se manda `runtime_type` sin modelo.
    // Para el resto de modelos se usa `model_id` (mismo criterio que el
    // formulario de lanzamiento legacy).
    var arqPayload = { role: "arquitecto" };
    if (arquitectoState.defaultModel === "claude-code") {
      arqPayload.runtime_type = "claude-code";
    } else {
      arqPayload.model_id = arquitectoState.defaultModel;
    }
    BackendClient.launchAgent(arqPayload)
      .then(function (agent) {
        arquitectoState.launchPending = false;
        arquitectoState.agent = agent;
        arquitectoState.error = null;
        renderArquitectoBar();
        renderArquitectoBody();
        if (state.section === "roles") renderRolesBody();
      })
      .catch(function (error) {
        arquitectoState.launchPending = false;
        arquitectoState.error = buildErrorMessage(error);
        renderArquitectoBar();
        if (state.section === "roles") renderRolesBody();
      });
  }

  function stopArquitecto() {
    if (!arquitectoState.agent || arquitectoState.launchPending) return;
    if (!arquitectoState.stopPending) {
      arquitectoState.stopPending = true;
      renderArquitectoBar();
      return;
    }
    arquitectoState.stopPending = false;
    var agentId = arquitectoState.agent.id;
    arquitectoState.launchPending = true;
    renderArquitectoBar();
    BackendClient.stopAgent(agentId)
      .then(function () {
        arquitectoState.launchPending = false;
        arquitectoState.agent = null;
        arquitectoState.error = null;
        renderArquitectoBar();
        renderArquitectoBody();
        if (state.section === "roles") renderRolesBody();
      })
      .catch(function (error) {
        arquitectoState.launchPending = false;
        arquitectoState.error = buildErrorMessage(error);
        renderArquitectoBar();
        if (state.section === "roles") renderRolesBody();
      });
  }

  // Cuerpo completo de la sección: cabecera con toggle, mensaje de acción,
  // lista y formulario de lanzamiento.
  function renderAgentsBody() {
    var wrap = agentsSection.bodyWrap;
    if (!wrap) return;
    wrap.textContent = "";

    var header = h("div", "agents-header");
    header.appendChild(h("span", "agents-title", "Agentes"));
    var toggle = button(
      agentsSection.showStopped ? "Ocultar detenidos" : "Mostrar detenidos"
    );
    toggle.addEventListener("click", function () {
      agentsSection.showStopped = !agentsSection.showStopped;
      renderAgentsBody();
    });
    header.appendChild(toggle);
    wrap.appendChild(header);

    if (agentsSection.actionMessage) {
      wrap.appendChild(h("p", "agent-message", agentsSection.actionMessage));
    }

    if (agentsSection.modelChangeError) {
      wrap.appendChild(h("p", "agent-error", agentsSection.modelChangeError));
    }

    renderAgentsPanePanel(wrap);
    renderAgentsList(wrap);
    renderAgentsLaunchForm(wrap);
  }

  // Filtro "Mostrar/Ocultar detenidos" (criterio 3): por defecto se ocultan
  // los `stopped`. DECISIÓN DOCUMENTADA: la TUI no filtra (muestra todos),
  // pero se replica el criterio de Android (`visibleAgentsFor`) en la web —
  // un agente `stopped` no vuelve a `idle` (sin transición de salida, ver
  // `brain/agents/lifecycle.py`) y solo puede relanzarse desde cero; ocultarlo
  // por defecto evita que ocupe espacio sin utilidad, y el toggle + el conteo
  // de ocultos permiten consultarlo siempre. Es estado de presentación puro,
  // no afecta a ninguna llamada al backend.
  function visibleAgentsFor(agents) {
    if (agentsSection.showStopped) return agents;
    return agents.filter(function (agent) {
      return agent.status !== "stopped";
    });
  }

  function renderAgentsList(wrap) {
    if (agentsSection.list === null) {
      if (agentsSection.listError) {
        wrap.appendChild(
          h("p", "agent-error", "No se pudo contactar con el backend: " + agentsSection.listError)
        );
      } else {
        wrap.appendChild(h("p", "section-note", "Cargando agentes…"));
      }
      return;
    }

    if (agentsSection.stale) {
      wrap.appendChild(
        h(
          "p",
          "stale-note",
          "Puede que esta lista esté desactualizada (sin conexión con el backend)."
        )
      );
    }

    var visible = visibleAgentsFor(agentsSection.list);
    var hidden = agentsSection.list.length - visible.length;

    if (visible.length === 0) {
      wrap.appendChild(
        h(
          "p",
          "section-note",
          hidden > 0
            ? "Agentes lanzados: ninguno visible (" +
                hidden +
                ' detenido(s) oculto(s) — usa "Mostrar detenidos").'
            : "Agentes lanzados: ninguno"
        )
      );
      return;
    }

    visible.forEach(function (agent) {
      var card = h("div", "agent-card");
      card.appendChild(h("div", "agent-name", agent.name + " (" + agent.role + ")"));
      var statusRow = h("div", "agent-status-row");
      var dot = h("span", "status-dot");
      dot.style.backgroundColor = agentStatusColor(agent.status);
      statusRow.appendChild(dot);
      // El color es complementario, NUNCA sustituto: el estado siempre va
      // en texto (criterio 4).
      statusRow.appendChild(h("span", "status-text", "Estado: " + agent.status));
      card.appendChild(statusRow);
      if (agent.model) {
        card.appendChild(h("div", "agent-model", "Modelo: " + agent.model));
      } else {
        card.appendChild(h("div", "agent-model", "Modelo: " + runtimeDisplayName(agent.runtime_id)));
      }
      card.appendChild(renderAgentActions(agent));
      wrap.appendChild(card);
    });

    if (hidden > 0) {
      // El conteo de ocultos se indica SIEMPRE que hay agentes `stopped`
      // ocultos, no solo cuando la lista queda vacía (criterio 3).
      wrap.appendChild(
        h(
          "p",
          "section-note agents-hidden-count",
          hidden + ' detenido(s) oculto(s) — usa "Mostrar detenidos" para verlos.'
        )
      );
    }
  }

  // --------------------------------------------------------- acciones por
  // agente (T-FB021-US03-02): "Ver actividad" (pane), "Cambiar modelo"
  // (T-FB021-US07-01, solo para OpenCode) y "Detener" (confirmacion de
  // segunda pulsacion).
  function renderAgentActions(agent) {
    var actions = h("div", "agent-actions");

    var paneBtn = button("Ver actividad");
    paneBtn.addEventListener("click", function () {
      viewAgentPane(agent);
    });
    actions.appendChild(paneBtn);

    // Cambiar modelo (T-FB021-US07-01): solo para agentes OpenCode en
    // ejecucion (no stopped). Mismo patron de confirmacion de segunda
    // pulsacion y single-flight que el resto de la seccion.
    if (agent.runtime_id === "opencode" && agent.status !== "stopped") {
      var isChanging = agentsSection.modelChangeAgentId === agent.id;
      var isPending = agentsSection.modelChangePending && agentsSection.modelChangePending.agent_id === agent.id;
      var changeLabel;

      if (isChanging) {
        changeLabel = "Cambiando modelo…";
      } else if (isPending) {
        changeLabel = "¿Seguro? Cambiar a " + agentsSection.modelChangePending.model;
      } else {
        changeLabel = "Cambiar modelo";
      }
      var changeBtn = button(changeLabel, "agent-model-change");
      if (isChanging) changeBtn.disabled = true;
      changeBtn.addEventListener("click", function () {
        requestModelChange(agent);
      });
      actions.appendChild(changeBtn);
    }

    // Un agente `stopped` no se puede volver a detener: sin botón
    // (mismo criterio que Android/TUI).
    if (agent.status !== "stopped") {
      var isThisStopping = agentsSection.stoppingAgentId === agent.id;
      var isThisPending = agentsSection.stopPendingFor === agent.id;
      var stopLabel;
      if (isThisStopping) {
        stopLabel = "Deteniendo…";
      } else if (isThisPending) {
        // Punto 3: el aviso combinado se escribe en la ETIQUETA del propio
        // botón que se pulsa (nunca en un elemento de texto aparte que
        // pueda crecer y desplazar el layout entre el primer y el segundo
        // clic). Texto exacto, mismo que la TUI.
        stopLabel = agentsSection.stopPendingHasJob
          ? "¿Seguro? Tiene un Job en curso — se interrumpirá. Confirmar detener"
          : "¿Seguro? Confirmar detener";
      } else {
        stopLabel = "Detener";
      }
      var stopBtn = button(stopLabel, "agent-stop");
      if (isThisStopping) stopBtn.disabled = true;
      stopBtn.addEventListener("click", function () {
        requestStop(agent);
      });
      actions.appendChild(stopBtn);
    }

    return actions;
  }

  // Conjunto de `agent_id` con algún Job actualmente `running` (punto 2):
  // mismo cálculo que `agentsWithRunningJob` (Android) /
  // `_agents_with_running_job` (TUI), derivado de `GET /jobs` sin ningún
  // endpoint nuevo.
  function agentsWithRunningJob(jobs) {
    return (jobs || [])
      .filter(function (job) {
        return job.status === "running";
      })
      .map(function (job) {
        return job.agent_id;
      });
  }

  // Detener con confirmación de "segunda pulsación" (decisión documentada:
  // mismo mecanismo idiomático ya validado en la TUI para este producto,
  // en vez de un `confirm()` nativo del navegador — consistencia visual
  // entre clientes y aviso combinado en la etiqueta del botón).
  //   1er clic  -> se pide confirmar (etiqueta del botón). Si `GET /jobs`
  //                falla al calcular el aviso de Job en curso, se degrada a
  //                "sin aviso" sin tumbar el refresco de la lista (que es
  //                la información primaria, punto 2).
  //   2º clic   -> se ejecuta la parada real.
  function requestStop(agent) {
    if (agentsSection.stoppingAgentId) return; // single-flight
    if (agentsSection.stopPendingFor !== agent.id) {
      agentsSection.stopPendingFor = agent.id;
      agentsSection.stopPendingHasJob = false;
      renderAgentsBody();
      BackendClient.getJobs()
        .then(function (jobs) {
          agentsSection.stopPendingHasJob =
            agentsWithRunningJob(jobs).indexOf(agent.id) >= 0;
          if (agentsSection.stopPendingFor === agent.id && state.section === "agents") {
            renderAgentsBody();
          }
        })
        .catch(function () {
          // Degradación: sin aviso de Job en curso en este ciclo.
          if (agentsSection.stopPendingFor === agent.id && state.section === "agents") {
            renderAgentsBody();
          }
        });
      return;
    }
    executeStop(agent);
  }

  // Parada real (`POST /agents/{id}/stop`). Single-flight (punto 5): si ya
  // hay una parada en vuelo, la segunda invocación se descarta de inmediato
  // (no se detiene dos veces ni se hacen dos peticiones reales).
  function executeStop(agent) {
    if (agentsSection.stoppingAgentId) return;
    agentsSection.stopPendingFor = null;
    agentsSection.stoppingAgentId = agent.id;
    agentsSection.actionMessage = null;
    renderAgentsBody();
    BackendClient.stopAgent(agent.id)
      .then(function (stopped) {
        agentsSection.stoppingAgentId = null;
        agentsSection.actionMessage =
          "Agente '" + stopped.name + "' detenido (" + stopped.status + ").";
        renderAgentsBody();
        return pollAgents();
      })
      .catch(function (error) {
        agentsSection.stoppingAgentId = null;
        agentsSection.actionMessage = buildErrorMessage(error);
        renderAgentsBody();
      });
  }

  // ------------------------------------------------- cambio de modelo
  // (T-FB021-US07-01): confirmacion de segunda pulsacion + single-flight,
  // mismo idioma que el resto de la web. El agente debe ser OpenCode y no
  // estar stopped.
  function requestModelChange(agent) {
    if (agentsSection.modelChangeAgentId) return; // single-flight
    if (!agentsSection.modelChangePending || agentsSection.modelChangePending.agent_id !== agent.id) {
      // Primer clic: mostrar selector de modelos.
      agentsSection.modelChangePending = null;
      agentsSection.modelChangeError = null;
      renderModelSelector(agent);
      return;
    }
    // Segundo clic: ejecutar el cambio.
    var model = agentsSection.modelChangePending.model;
    executeModelChange(agent, model);
  }

  function renderModelSelector(agent) {
    // Si ya tenemos las opciones cacheadas, las mostramos directamente.
    if (agentsSection.modelOptions) {
      showModelPicker(agent, agentsSection.modelOptions);
      return;
    }
    // Cargar opciones via API.
    agentsSection.modelChangeAgentId = agent.id; // bloquea el boton mientras carga
    renderAgentsBody();
    BackendClient.getAgentAvailableModels(agent.id)
      .then(function (result) {
        agentsSection.modelChangeAgentId = null;
        if (!result.supports_model) {
          agentsSection.modelChangeError = "Este agente no admite cambio de modelo.";
          renderAgentsBody();
          return;
        }
        agentsSection.modelOptions = result.models;
        showModelPicker(agent, result.models);
      })
      .catch(function (error) {
        agentsSection.modelChangeAgentId = null;
        agentsSection.modelChangeError = buildErrorMessage(error);
        renderAgentsBody();
      });
  }

  function showModelPicker(agent, models) {
    if (!models || models.length === 0) {
      agentsSection.modelChangeError = "No hay modelos disponibles para este agente.";
      renderAgentsBody();
      return;
    }
    // Usar confirmacion nativa como selector (mismo patron que la seccion
    // Scripts para seleccionar script). Si hay un solo modelo, se usa
    // directamente sin preguntar.
    var chosen;
    if (models.length === 1) {
      chosen = models[0];
    } else {
      chosen = prompt(
        "Elige un modelo para " + agent.name + ":\n\n" +
        models.map(function (m, i) { return (i + 1) + ". " + m; }).join("\n") +
        "\n\nEscribe el nombre exacto del modelo:"
      );
    }
    if (!chosen) {
      agentsSection.modelChangePending = null;
      renderAgentsBody();
      return;
    }
    // Verificar que el valor esta en la lista.
    var found = models.filter(function (m) { return m === chosen.trim(); });
    if (found.length === 0) {
      agentsSection.modelChangeError = "El modelo '" + chosen + "' no esta en la lista de opciones.";
      agentsSection.modelChangePending = null;
      renderAgentsBody();
      return;
    }
    // Fijar pendiente de confirmacion.
    agentsSection.modelChangePending = { agent_id: agent.id, model: chosen.trim() };
    agentsSection.modelChangeError = null;
    renderAgentsBody();
  }

  function executeModelChange(agent, model) {
    if (agentsSection.modelChangeAgentId) return;
    agentsSection.modelChangePending = null;
    agentsSection.modelChangeAgentId = agent.id;
    agentsSection.modelChangeError = null;
    renderAgentsBody();
    BackendClient.setAgentModel(agent.id, model)
      .then(function (result) {
        agentsSection.modelChangeAgentId = null;
        agentsSection.modelOptions = null; // invalidar cache para siguiente cambio
        if (result.changed) {
          agentsSection.actionMessage = "Modelo cambiado a " + model + ".";
        } else {
          agentsSection.modelChangeError = "No se pudo cambiar el modelo. El agente puede no estar respondiendo a las teclas.";
        }
        renderAgentsBody();
        return pollAgents();
      })
      .catch(function (error) {
        agentsSection.modelChangeAgentId = null;
        agentsSection.modelOptions = null;
        agentsSection.modelChangeError = buildErrorMessage(error);
        renderAgentsBody();
      });
  }

  // ------------------------------------------------- pane de actividad
  // (punto 4): vista de SOLO lectura del contenido crudo del pane de tmux
  // (`GET /agents/{id}/pane`), con scroll si es largo. Un agente `stopped`
  // (o sin runtime) muestra el MOTIVO REAL devuelto por el backend (404 con
  // `detail`), nunca un "not found" genérico — mismo bug ya corregido en
  // Android (T-FB017-US01-08), evitado desde el inicio aquí.
  function viewAgentPane(agent) {
    if (agentsSection.paneState === "loading") return; // single-flight
    agentsSection.paneState = "loading";
    agentsSection.paneAgentId = agent.id;
    agentsSection.paneAgentName = agent.name;
    agentsSection.paneContent = null;
    agentsSection.paneMessage = null;
    renderAgentsBody();
    BackendClient.getAgentPane(agent.id)
      .then(function (result) {
        agentsSection.paneState = "open";
        agentsSection.paneContent = result && result.content ? result.content : "";
        renderAgentsBody();
      })
      .catch(function (error) {
        agentsSection.paneState = "unavailable";
        agentsSection.paneMessage = buildErrorMessage(error);
        renderAgentsBody();
      });
  }

  function closeAgentPane() {
    agentsSection.paneState = null;
    renderAgentsBody();
  }

  // Panel del pane (inline dentro del cuerpo de la sección, no un dialog
  // nativo): persiste a través de los re-renders del polling porque su
  // estado vive en `agentsSection`.
  function renderAgentsPanePanel(wrap) {
    if (!agentsSection.paneState) return;
    var box = h("div", "pane-panel");
    box.appendChild(
      h("div", "pane-title", "Actividad de " + agentsSection.paneAgentName)
    );
    if (agentsSection.paneState === "loading") {
      box.appendChild(h("p", "section-note", "Consultando la sesión…"));
    } else if (agentsSection.paneState === "unavailable") {
      box.appendChild(h("p", "agent-error", agentsSection.paneMessage));
    } else {
      box.appendChild(
        h("div", "pane-view", agentsSection.paneContent ? agentsSection.paneContent : "(pane vacío)")
      );
    }
    var close = button("Cerrar");
    close.addEventListener("click", closeAgentPane);
    box.appendChild(close);
    wrap.appendChild(box);
  }

  // Formulario de lanzamiento. Reglas (punto 5): desplegable con el
  // catálogo, campo de modelo SOLO si el runtime elegido lo admite (si no,
  // deshabilitado — mismo criterio que `enabled = selected.supports_model`,
  // Android), campo opcional de tarea inicial multilínea.
  function renderAgentsLaunchForm(wrap) {
    wrap.appendChild(h("div", "launch-title", "Lanzar agente"));

    if (agentsSection.catalogState === null || agentsSection.catalogState === "loading") {
      wrap.appendChild(h("p", "section-note", "Cargando catálogo de agentes…"));
      return;
    }
    if (agentsSection.catalogState === "unavailable") {
      wrap.appendChild(
        h(
          "p",
          "agent-error",
          "No se pudo cargar el catálogo de agentes: " +
            (agentsSection.catalogError || "error desconocido")
        )
      );
      return;
    }
    if (!agentsSection.catalog || agentsSection.catalog.length === 0) {
      // Catálogo vacío: caso distinto de "no se pudo cargar". No se asume
      // `options[0]` (incidente T-FB017-US01-10).
      wrap.appendChild(
        h("p", "agent-error", "No hay ninguna combinación de agente/runtime disponible para lanzar.")
      );
      return;
    }
    renderAgentsFormFields(wrap);
  }

  function renderAgentsFormFields(wrap) {
    var catalog = agentsSection.catalog;
    if (agentsSection.optionIndex >= catalog.length) agentsSection.optionIndex = 0;
    var option = catalog[agentsSection.optionIndex];

    var form = h("div", "launch-form");

    // Dropdown de combinaciones rol x modelo (T-FB022-US11-02):
    // el runtime no se muestra ni se pide — esta resuelto internamente.
    var select = document.createElement("select");
    select.className = "clickable launch-select";
    catalog.forEach(function (opt, idx) {
      var o = document.createElement("option");
      o.setAttribute("value", String(idx));
      var label = roleLabel(opt.agent_role) + " sobre " + opt.model_name;
      if (!opt.supports_model) label += " (no admite modelo)";
      o.textContent = label;
      select.appendChild(o);
    });
    select.selectedIndex = agentsSection.optionIndex;
    select.addEventListener("change", function () {
      agentsSection.optionIndex = parseInt(select.value, 10) || 0;
      // Limpiar modelInput al cambiar de opcion — el modelo ya viene fijado.
      agentsSection.modelInput = "";
      agentsSection.launchPending = false;
      renderAgentsBody();
    });
    form.appendChild(select);

    // El modelo ya esta implicito en la opcion elegida (rol x modelo).
    // No se muestra campo de modelo separado — el runtime se resuelve
    // internamente desde el catalogo.

    var taskArea = document.createElement("textarea");
    taskArea.className = "clickable";
    taskArea.value = agentsSection.taskInput;
    taskArea.placeholder = "Tarea inicial (opcional) — se despachará como un Job al lanzar el agente.";
    taskArea.addEventListener("input", function () {
      agentsSection.taskInput = taskArea.value;
    });
    form.appendChild(taskArea);

    // Single-flight (criterio 8): `launching` descarta una segunda
    // invocación mientras la primera sigue en vuelo (mismo criterio que
    // `SingleFlightAction`, Android); el botón además queda deshabilitado.
    // T-FB024-US04-01: confirmación de segunda pulsación antes de lanzar.
    var launchLabel;
    if (agentsSection.launching) {
      launchLabel = "Lanzando…";
    } else if (agentsSection.launchPending) {
      launchLabel = "¿Seguro? Confirmar lanzamiento";
    } else {
      launchLabel = "Lanzar";
    }
    var launchBtn = button(launchLabel);
    if (agentsSection.launching) {
      launchBtn.disabled = true;
    }
    launchBtn.addEventListener("click", launchAgents);
    form.appendChild(launchBtn);

    wrap.appendChild(form);
  }

  // Etiqueta de rol capitalizada (mismo criterio que `roleLabel`, Android):
  // `GET /agents/options` devuelve `agent_role` tal cual ("developer"/
  // "critic"), el runtime ya viene capitalizado.
  function roleLabel(role) {
    if (!role) return role;
    return role.charAt(0).toUpperCase() + role.slice(1);
  }

  // Nombre visible del runtime a partir de su id (T-FB024-US04-03).
  function runtimeDisplayName(runtimeId) {
    if (runtimeId === "claude-code") return "Claude Code";
    if (runtimeId === "opencode") return "OpenCode";
    return runtimeId || "(no disponible)";
  }

  // Lanzar (`POST /agents`). Single-flight: si ya hay una petición en
  // vuelo, la segunda invocación se descarta de inmediato (no se encola,
  // no se despacha un segundo agente). T-FB024-US04-01: confirmación de
  // segunda pulsación antes de ejecutar.
  function launchAgents() {
    if (agentsSection.launching) return;
    if (!agentsSection.launchPending) {
      agentsSection.launchPending = true;
      renderAgentsBody();
      return;
    }
    var option = agentsSection.catalog[agentsSection.optionIndex];
    if (!option) return;

    agentsSection.launching = true;
    agentsSection.launchPending = false;
    agentsSection.actionMessage = null;
    // Re-render inmediato: el botón queda deshabilitado ("Lanzando…")
    // mientras la petición está en vuelo, además del descarte del segundo
    // clic por el single-flight.
    renderAgentsBody();

    var payload = { role: option.agent_role, model_id: option.model_id };
    if (agentsSection.taskInput.trim()) {
      payload.initial_job_description = agentsSection.taskInput.trim();
    }

    BackendClient.launchAgent(payload)
      .then(function (result) {
        agentsSection.launching = false;
        agentsSection.launchPending = false;
        agentsSection.actionMessage = launchFeedbackMessageFor(result);
        renderAgentsBody();
        // Refleja el nuevo agente sin esperar al siguiente ciclo de polling.
        return pollAgents();
      })
      .catch(function (error) {
        agentsSection.launching = false;
        agentsSection.launchPending = false;
        agentsSection.actionMessage = buildErrorMessage(error);
        renderAgentsBody();
      });
  }

  // Feedback tras lanzar (mismo criterio que `launchFeedbackMessageFor`,
  // Android): sin Job (no se informó tarea inicial) el mensaje habitual;
  // con Job (tarea inicial despachada automáticamente), se comunica su
  // estado real sin ocultar que el agente quedó registrado y disponible.
  function launchFeedbackMessageFor(result) {
    var agent = result && result.agent ? result.agent : result;
    if (!agent) return "Agente lanzado.";
    var job = result && result.agent ? result.job : null;
    var msg = "Agente '" + agent.name + "' (" + agent.role + ") operativo, estado: " + agent.status + ".";
    if (!job) return msg;
    switch (job.status) {
      case "completed":
        return msg + " Tarea inicial despachada y completada.";
      case "failed":
        return msg + " La tarea inicial falló: " + (job.result || "sin detalle") + ". El agente queda registrado y disponible.";
      default:
        return msg + " Tarea inicial en estado '" + job.status + "'.";
    }
  }

  // ------------------------------------------------------------- JOBS
  // (T-FB021-US04-01). Formulario de creación + seguimiento en tiempo
  // real por `WS /ws/jobs` + histórico recompuesto desde `GET /jobs`.
  // Ver `jobsSection` arriba.

  // Entrada de la sección: contenedor propio, conexión WS y recomposición
  // del histórico desde `GET /jobs` (punto 6 — nunca se re-renderiza solo
  // desde una caché que se pierda al navegar).
  function renderJobsInto(content) {
    jobsSection.bodyWrap = h("div", "jobs-body");
    content.appendChild(jobsSection.bodyWrap);
    connectJobsWebSocket();
    refreshJobsAgents();
    refreshJobs();
    renderJobsBody();
  }

  function stopJobsWebSocket() {
    if (jobsSection.ws) {
      jobsSection.ws.stop();
      jobsSection.ws = null;
    }
  }

  // URL del canal WS desde la base del backend (mismo host/puerto, solo
  // cambia el esquema `http` -> `ws`): same-origin si la web se sirve
  // desde el propio backend (T-FB021-US01-01), o desde `setBaseUrl`.
  function jobsWsUrl() {
    var base = BackendClient.getBaseUrl() || "";
    if (!base && window && window.location && window.location.origin) {
      base = window.location.origin;
    }
    return base.replace(/^http/, "ws") + "/ws/jobs";
  }

  function connectJobsWebSocket() {
    if (jobsSection.ws) return; // single connect
    var socket = new ReconnectingWebSocket(jobsWsUrl(), {
      reconnectDelayMillis: WS_RECONNECT_DELAY_MILLIS,
      onmessage: handleJobsWsMessage,
      onopen: function () {
        if (jobsSection.ws !== socket) return;
        jobsSection.wsStatus = "connected";
        if (state.section === "jobs") renderJobsBody();
      },
      onclose: function () {
        if (jobsSection.ws !== socket) return;
        jobsSection.wsStatus = "reconnecting";
        if (state.section === "jobs") renderJobsBody();
      },
    });
    jobsSection.ws = socket;
    jobsSection.wsStatus = "connecting";
    socket.start();
    if (state.section === "jobs") renderJobsBody();
  }

  // Mensaje del canal: `{"event": "job_status", id, agent_id, description,
  // status, result}` (punto 4). `created` expone el `job_id` real ANTES de
  // que el `POST /jobs` bloqueante responda — es la señal que habilita
  // "Cancelar Job" (punto 5).
  function handleJobsWsMessage(event) {
    if (state.section !== "jobs") return;
    var payload;
    try {
      payload = JSON.parse(event.data);
    } catch (_err) {
      return; // mensaje no JSON del transporte: se ignora
    }
    if (!payload || payload.event !== "job_status" || !payload.id) return;

    var isTerminal =
      payload.status === "completed" ||
      payload.status === "failed" ||
      payload.status === "cancelled";

    if (isTerminal) {
      // Solo se da por terminado el Job que tenemos en curso (el canal es
      // global: el final de otro despacho no debe limpiar el nuestro).
      if (jobsSection.pendingCreatedJob && jobsSection.pendingCreatedJob.id === payload.id) {
        jobsSection.pendingCreatedJob = null;
        jobsSection.cancelPendingFor = null;
        jobsSection.cancellingJobId = null;
        jobsSection.progressMessage = terminalJobMessage(payload);
      }
      // El histórico se recompone desde `GET /jobs` (punto 6), nunca solo
      // desde el evento.
      refreshJobs();
      renderJobsBody();
      return;
    }

    // created/running
    if (jobsSection.pendingCreatedJob) {
      if (jobsSection.pendingCreatedJob.id !== payload.id) return; // no es nuestro Job
      jobsSection.pendingCreatedJob.status = payload.status;
      jobsSection.progressMessage = inFlightJobMessage(payload);
    } else if (jobsSection.createInFlight) {
      // Primer evento tras "Enviar": se adopta el `job_id` real.
      jobsSection.pendingCreatedJob = {
        id: payload.id,
        agentId: payload.agent_id,
        description: payload.description,
        status: payload.status,
      };
      jobsSection.progressMessage = inFlightJobMessage(payload);
    }
    renderJobsBody();
  }

  function agentLabel(agentId) {
    var found = null;
    for (var i = 0; i < (jobsSection.agents || []).length; i++) {
      if (jobsSection.agents[i].id === agentId) {
        found = jobsSection.agents[i];
        break;
      }
    }
    return found ? found.name : agentId;
  }

  function inFlightJobMessage(job) {
    return (
      "Job en curso con " +
      agentLabel(job.agent_id) +
      " (" +
      job.status +
      "): " +
      (job.description || "")
    );
  }

  function terminalJobMessage(job) {
    if (job.status === "completed") return "Job completado: " + (job.result || "sin resultado");
    if (job.status === "cancelled") return "Job cancelado: " + (job.result || "sin detalle");
    return "Job falló (" + job.status + "): " + (job.result || "sin detalle");
  }

  // Recomposición del histórico desde `GET /jobs` (punto 6). Un fallo
  // puntual conserva la última lista vista marcada `stale` (mismo criterio
  // que el polling de agentes): solo sin lista previa se muestra el error.
  function refreshJobs() {
    return BackendClient.getJobs()
      .then(function (jobs) {
        jobsSection.list = jobs;
        jobsSection.stale = false;
        jobsSection.listError = null;
        if (state.section === "jobs") renderJobsBody();
      })
      .catch(function (error) {
        if (jobsSection.list !== null) {
          jobsSection.stale = true;
        } else {
          jobsSection.listError = buildErrorMessage(error);
        }
        if (state.section === "jobs") renderJobsBody();
      });
  }

  // Agentes destinatarios del formulario (punto 3): los ya lanzados, sin
  // los `stopped` (un agente detenido no tiene runtime — `POST /jobs`
  // devolvería 400). Se recompone desde `GET /agents` al entrar.
  function refreshJobsAgents() {
    jobsSection.agentsError = null;
    BackendClient.getAgents()
      .then(function (agents) {
        jobsSection.agents = (agents || []).filter(function (agent) {
          return agent.status !== "stopped";
        });
        if (jobsSection.agentIndex >= jobsSection.agents.length) jobsSection.agentIndex = 0;
        if (state.section === "jobs") renderJobsBody();
      })
      .catch(function (error) {
        jobsSection.agents = [];
        jobsSection.agentsError = buildErrorMessage(error);
        if (state.section === "jobs") renderJobsBody();
      });
  }

  function renderJobsBody() {
    var wrap = jobsSection.bodyWrap;
    if (!wrap || state.section !== "jobs") return;
    wrap.textContent = "";
    renderJobsWsStatus(wrap);
    renderJobsProgress(wrap);
    renderJobsForm(wrap);
    renderJobsHistory(wrap);
  }

  function renderJobsWsStatus(wrap) {
    if (!jobsSection.wsStatus) return;
    var text;
    if (jobsSection.wsStatus === "connected") {
      text = "Canal de eventos en tiempo real: conectado.";
    } else if (jobsSection.wsStatus === "connecting") {
      text = "Conectando al canal de eventos…";
    } else {
      text = "Canal de eventos caído; se reconecta automáticamente (sin perder lo mostrado).";
    }
    wrap.appendChild(h("p", "ws-status-note", text));
  }

  function renderJobsProgress(wrap) {
    var inFlight = jobsSection.pendingCreatedJob;
    if (!inFlight && !jobsSection.progressMessage) return;
    var box = h("div", "job-progress");
    box.appendChild(h("div", "job-progress-title", inFlight ? "Job en curso" : "Resultado del Job"));
    if (inFlight) {
      box.appendChild(
        h("p", "section-line", "Job " + inFlight.id + " · estado " + inFlight.status)
      );
    }
    if (jobsSection.progressMessage) {
      box.appendChild(h("p", "job-progress-message", jobsSection.progressMessage));
    }
    renderCancelButton(box);
    wrap.appendChild(box);
  }

  // "Cancelar Job" SOLO se muestra/habilita cuando el evento `created` del
  // WebSocket ya expuso el `job_id` real (punto 5) — el `POST /jobs` es
  // bloqueante y no sirve para saber qué cancelar mientras el Job corre.
  function renderCancelButton(box) {
    var job = jobsSection.pendingCreatedJob;
    if (!job || !job.id) return;
    var isCancelling = jobsSection.cancellingJobId === job.id;
    var isPending = jobsSection.cancelPendingFor === job.id;
    var label;
    if (isCancelling) {
      label = "Cancelando…";
    } else if (isPending) {
      // Confirmación en la ETIQUETA del propio botón (misma lección que la
      // TUI: un texto aparte que crezca desplazaría el botón entre el
      // primer y el segundo clic).
      label = "¿Seguro? Confirmar cancelación";
    } else {
      label = "Cancelar Job";
    }
    var btn = button(label, "job-cancel");
    if (isCancelling) btn.disabled = true;
    btn.addEventListener("click", requestCancelJob);
    box.appendChild(btn);
  }

  function requestCancelJob() {
    var job = jobsSection.pendingCreatedJob;
    if (!job || !job.id) return;
    if (jobsSection.cancellingJobId) return; // single-flight
    if (jobsSection.cancelPendingFor !== job.id) {
      jobsSection.cancelPendingFor = job.id;
      renderJobsBody();
      return;
    }
    executeCancelJob();
  }

  function executeCancelJob() {
    var job = jobsSection.pendingCreatedJob;
    if (!job || !job.id) return;
    if (jobsSection.cancellingJobId) return;
    jobsSection.cancelPendingFor = null;
    jobsSection.cancellingJobId = job.id;
    jobsSection.progressMessage = "Cancelando Job…";
    renderJobsBody();
    BackendClient.cancelJob(job.id)
      .then(function (cancelled) {
        jobsSection.cancellingJobId = null;
        jobsSection.pendingCreatedJob = null;
        jobsSection.cancelPendingFor = null;
        jobsSection.progressMessage = terminalJobMessage(cancelled);
        renderJobsBody();
        return refreshJobs();
      })
      .catch(function (error) {
        jobsSection.cancellingJobId = null;
        jobsSection.progressMessage = buildErrorMessage(error);
        renderJobsBody();
      });
  }

  function renderJobsForm(wrap) {
    wrap.appendChild(h("div", "jobs-form-title", "Crear Job"));

    if (jobsSection.agents === null) {
      wrap.appendChild(h("p", "section-note", "Cargando agentes…"));
      return;
    }
    if (jobsSection.agentsError) {
      wrap.appendChild(h("p", "agent-error", jobsSection.agentsError));
      return;
    }
    if (jobsSection.agents.length === 0) {
      wrap.appendChild(
        h(
          "p",
          "agent-error",
          "No hay ningún agente lanzado en la sesión. Lanza un agente desde la pestaña Agentes antes de crear un Job."
        )
      );
      return;
    }

    var form = h("div", "jobs-form");

    form.appendChild(h("div", "field-label", "Agente destinatario"));
    var agentSelect = document.createElement("select");
    agentSelect.className = "clickable launch-select";
    jobsSection.agents.forEach(function (agent, idx) {
      var o = document.createElement("option");
      o.setAttribute("value", String(idx));
      o.textContent = agent.name + " (" + agent.role + ")";
      agentSelect.appendChild(o);
    });
    agentSelect.selectedIndex = jobsSection.agentIndex;
    agentSelect.addEventListener("change", function () {
      jobsSection.agentIndex = parseInt(agentSelect.value, 10) || 0;
      renderJobsBody();
    });
    form.appendChild(agentSelect);

    form.appendChild(h("div", "field-label", "Describe la tarea"));
    var descArea = document.createElement("textarea");
    descArea.className = "clickable";
    descArea.value = jobsSection.descriptionInput;
    descArea.placeholder = "Describe la tarea que debe realizar el agente.";
    descArea.addEventListener("input", function () {
      jobsSection.descriptionInput = descArea.value;
    });
    form.appendChild(descArea);

    // Job previo opcional (encadenamiento Developer → Critic, punto 3):
    // SOLO se ofrece como candidato un Job `completed` con resultado — el
    // único estado que `create_job(..., previous_job=...)` acepta encadenar
    // (igual que Android, que solo muestra la acción cuando
    // `job.status == "completed"`).
    form.appendChild(h("div", "field-label", "Encadenar a un Job previo (opcional)"));
    var prevSelect = document.createElement("select");
    prevSelect.className = "clickable launch-select";
    var noneOpt = document.createElement("option");
    noneOpt.setAttribute("value", "");
    noneOpt.textContent = "Sin encadenar";
    prevSelect.appendChild(noneOpt);
    var prevCount = 0;
    (jobsSection.list || []).forEach(function (job) {
      if (job.status !== "completed" || !job.result) return;
      prevCount++;
      var o = document.createElement("option");
      o.setAttribute("value", job.id);
      o.textContent =
        job.id +
        " · " +
        job.status +
        " · " +
        String(job.description || "").split("\n")[0].slice(0, 60);
      prevSelect.appendChild(o);
    });
    if (prevCount === 0) {
      prevSelect.appendChild(
        h(
          "option",
          "",
          "No hay ningún Job completado con resultado que encadenar"
        )
      );
      prevSelect.disabled = true;
    }
    prevSelect.value = jobsSection.previousJobId || "";
    prevSelect.addEventListener("change", function () {
      jobsSection.previousJobId = prevSelect.value || null;
    });
    form.appendChild(prevSelect);

    // Single-flight (mismo criterio que lanzar agente): `createInFlight`
    // descarta una segunda invocación mientras el POST bloqueante sigue en
    // vuelo; el botón además queda deshabilitado.
    var submit = button("Enviar", "job-submit");
    if (jobsSection.createInFlight) {
      submit.disabled = true;
      submit.textContent = "Enviando…";
    }
    submit.addEventListener("click", submitJob);
    form.appendChild(submit);

    if (jobsSection.formError) {
      form.appendChild(h("p", "agent-error", jobsSection.formError));
    }

    wrap.appendChild(form);
  }

  function submitJob() {
    if (jobsSection.createInFlight) return; // single-flight
    var agent = jobsSection.agents[jobsSection.agentIndex];
    if (!agent) {
      jobsSection.formError = "Elige un agente destinatario.";
      renderJobsBody();
      return;
    }
    var description = jobsSection.descriptionInput.trim();
    if (!description) {
      jobsSection.formError = "Escribe una descripción antes de enviar.";
      renderJobsBody();
      return;
    }

    jobsSection.createInFlight = true;
    jobsSection.formError = null;
    jobsSection.pendingCreatedJob = null;
    jobsSection.cancelPendingFor = null;
    jobsSection.cancellingJobId = null;
    jobsSection.progressMessage = "Despachando Job…";
    renderJobsBody();

    var payload = { agent_id: agent.id, description: description };
    // Solo se encadena si el Job previo señalado existe y está `completed`
    // con resultado (misma restricción que el dominio
    // `create_job(..., previous_job=...)`). Excluye explícitamente los
    // estados `failed`/`cancelled`/`running`.
    var prevJob = (jobsSection.list || []).filter(function (j) {
      return j.id === jobsSection.previousJobId;
    })[0];
    if (prevJob && prevJob.status === "completed" && prevJob.result) {
      payload.previous_job_id = prevJob.id;
    }

    BackendClient.createAndDispatchJob(payload)
      .then(function (job) {
        jobsSection.createInFlight = false;
        jobsSection.pendingCreatedJob = null;
        jobsSection.cancelPendingFor = null;
        jobsSection.cancellingJobId = null;
        jobsSection.progressMessage = terminalJobMessage(job);
        renderJobsBody();
        return refreshJobs();
      })
      .catch(function (error) {
        jobsSection.createInFlight = false;
        jobsSection.pendingCreatedJob = null;
        jobsSection.cancelPendingFor = null;
        jobsSection.cancellingJobId = null;
        jobsSection.progressMessage = buildErrorMessage(error);
        renderJobsBody();
      });
  }

  function renderJobsHistory(wrap) {
    wrap.appendChild(h("div", "jobs-history-title", "Histórico de Jobs de la sesión"));
    if (jobsSection.list === null) {
      wrap.appendChild(h("p", "section-note", "Cargando histórico…"));
      return;
    }
    if (jobsSection.listError) {
      wrap.appendChild(h("p", "agent-error", jobsSection.listError));
      return;
    }
    if (jobsSection.stale) {
      wrap.appendChild(
        h(
          "p",
          "stale-note",
          "Puede que este histórico esté desactualizado (sin conexión con el backend)."
        )
      );
    }
    if (jobsSection.list.length === 0) {
      wrap.appendChild(h("p", "section-note", "Todavía no se ha creado ningún Job en esta sesión."));
      return;
    }
    jobsSection.list.forEach(function (job) {
      var selected = jobsSection.selectedJobId === job.id;
      var summary = String(job.description || "").split("\n")[0];
      var card = h("div", "job-card" + (selected ? " job-card-selected" : ""));
      // Cabecera clicable de la tarjeta: pulsa para abrir/plegar el detalle
      // completo (punto 2) — mismo patrón que el diálogo de detalle de
      // Android (`JobHistoryList`). El detalle vive DENTRO de la tarjeta,
      // no en un elemento que desplace el layout.
      var line = h(
        "div",
        "job-line" +
          " job-status-" +
          (job.status === "completed"
            ? "ok"
            : job.status === "failed" || job.status === "cancelled"
              ? "ko"
              : "run") +
          (selected ? " job-line-selected" : ""),
        "[" + job.status + "] " + job.agent_id + " — " + (summary || "")
      );
      line.tabIndex = 0;
      line.setAttribute("role", "button");
      line.setAttribute(
        "aria-expanded",
        selected ? "true" : "false"
      );
      line.addEventListener("click", function () {
        jobsSection.selectedJobId = selected ? null : job.id;
        renderJobsBody();
      });
      card.appendChild(line);
      card.appendChild(
        h("div", "job-hint", selected ? "▲ Plegar detalle" : "▼ Ver detalle")
      );
      if (selected) {
        var detail = h("div", "job-detail");
        detail.appendChild(h("div", "job-detail-field", "ID: " + job.id));
        detail.appendChild(h("div", "job-detail-field", "Agente: " + job.agent_id));
        detail.appendChild(h("div", "job-detail-field", "Estado: " + job.status));
        if (job.description) {
          detail.appendChild(h("div", "job-detail-label", "Descripción"));
          detail.appendChild(h("div", "job-detail-text", String(job.description)));
        }
        if (job.result) {
          detail.appendChild(h("div", "job-detail-label", "Resultado"));
          // Resultado completo, sin truncar, con scroll si es largo
          // (criterio de aceptación explícito).
          detail.appendChild(h("div", "job-detail-text", String(job.result)));
        } else {
          detail.appendChild(
            h("div", "job-detail-field", "Resultado: — (el Job aún no tiene resultado)")
          );
        }
        // "Usar como Job previo" SOLO si `completed` y con resultado — el
        // único estado que `create_job(..., previous_job=...)` acepta
        // encadenar (ver `dispatcher/job_creation.py`). Mismo criterio que
        // Android: el botón solo existe cuando `job.status == "completed"`.
        if (job.status === "completed" && job.result) {
          var prevBtn = button("Usar como Job previo", "job-use-prev");
          prevBtn.addEventListener("click", function () {
            jobsSection.previousJobId = job.id;
            renderJobsBody();
          });
          detail.appendChild(prevBtn);
        }
        card.appendChild(detail);
      }
      wrap.appendChild(card);
    });
  }

  // --------------------------------------------------------------- PLAN
  // (T-FB021-US05-01). Solicitud (`POST /plans`), vista completa de los
  // pasos tal como los devuelve el backend (punto 4), aprobación con
  // confirmación del número de pasos / rechazo (punto 5), canal
  // `WS /ws/plans` filtrado por `plan_id` (punto 3) y recuperación de un
  // plan `proposed` pendiente al cargar la pantalla (punto 6).

  // Entrada de la sección: contenedor propio, conexión WS y carga del
  // histórico desde `GET /plans` (que también recupera un plan `proposed`
  // pendiente, punto 6 de US05-01, y puebla la lista del punto 2 de
  // US05-02 — una sola llamada, no dos). Recargar la página (F5) borra el
  // estado en memoria, así que sin esto un plan sin decidir quedaría
  // invisible tras un refresh.
  function renderPlansInto(content) {
    plansSection.bodyWrap = h("div", "plans-body");
    content.appendChild(plansSection.bodyWrap);
    connectPlansWebSocket();
    refreshPlansHistory();
    loadTodoStories();
    renderPlansBody();
  }

  function stopPlansWebSocket() {
    if (plansSection.ws) {
      plansSection.ws.stop();
      plansSection.ws = null;
    }
  }

  function plansWsUrl() {
    var base = BackendClient.getBaseUrl() || "";
    if (!base && window && window.location && window.location.origin) {
      base = window.location.origin;
    }
    return base.replace(/^http/, "ws") + "/ws/plans";
  }

  // Punto 6: recupera el plan `proposed` MÁS RECIENTE de la sesión al abrir
  // la pantalla (solo si no hay ya un plan cargado en memoria). Si hay más
  // de uno `proposed`, se usa el último de la lista (orden de registro, el
  // más reciente). Se invoca sobre la lista que `refreshPlansHistory` ya
  // obtuvo de `GET /plans` (una sola llamada por entrada, no dos): si la
  // lista no trae ningún `proposed`, no se toca nada.
  function recoverPendingPlanFrom(plans) {
    if (plansSection.currentPlanId) return; // ya hay un plan mostrado
    var pending = null;
    (plans || []).forEach(function (plan) {
      if (plan.status === "proposed") pending = plan;
    });
    if (pending && !plansSection.currentPlanId) {
      plansSection.currentPlanId = pending.plan_id;
      plansSection.currentPlan = pending;
    }
  }

  function connectPlansWebSocket() {
    if (plansSection.ws) return; // single connect
    var socket = new ReconnectingWebSocket(plansWsUrl(), {
      reconnectDelayMillis: WS_RECONNECT_DELAY_MILLIS,
      onmessage: handlePlansWsMessage,
      onopen: function () {
        if (plansSection.ws !== socket) return;
        plansSection.wsStatus = "connected";
        if (state.section === "plan") renderPlansBody();
      },
      onclose: function () {
        if (plansSection.ws !== socket) return;
        plansSection.wsStatus = "reconnecting";
        if (state.section === "plan") renderPlansBody();
      },
    });
    plansSection.ws = socket;
    plansSection.wsStatus = "connecting";
    socket.start();
    if (state.section === "plan") renderPlansBody();
  }

  // Mensaje del canal: `{"event": "plan_progress", plan_id, goal, status,
  // steps}`. Punto 3 (bug real corregido en Android, `handlePlanProgressEvent`):
  // `WS /ws/plans` puede emitir eventos de MÚLTIPLES planes registrados en el
  // proceso (cada `POST /plans` registra uno nuevo sin descartar los
  // anteriores) — cualquier evento cuyo `plan_id` no coincida con el plan
  // mostrado se DESCARTA, para que el progreso de un plan ajeno nunca
  // sobrescriba el que esta pantalla muestra.
  function handlePlansWsMessage(event) {
    if (state.section !== "plan") return;
    var payload;
    try {
      payload = JSON.parse(event.data);
    } catch (_err) {
      return; // mensaje no JSON del transporte: se ignora
    }
    if (!payload || payload.event !== "plan_progress" || !payload.plan_id) return;
    // Filtro por plan_id: descartar el progreso de cualquier otro plan.
    if (payload.plan_id !== plansSection.currentPlanId) return;
    var previousStatus = plansSection.currentPlan && plansSection.currentPlan.status;
    plansSection.currentPlan = payload;
    renderPlansBody();
    // El histórico de la sesión refleja los estados terminales sin esperar
    // a una recarga ni a una acción local (T-FB021-US05-02, punto 2): si el
    // plan actual llega a `cancelled`/`blocked`, se refresca la lista.
    if (
      previousStatus !== payload.status &&
      (payload.status === "cancelled" || payload.status === "blocked")
    ) {
      refreshPlansHistory();
    }
  }

  function renderPlansBody() {
    var wrap = plansSection.bodyWrap;
    if (!wrap || state.section !== "plan") return;
    wrap.textContent = "";
    renderPlansWsStatus(wrap);
    renderPlansForm(wrap);
    renderPlanDetails(wrap);
    renderPlansHistory(wrap);
  }

  function renderPlansWsStatus(wrap) {
    if (!plansSection.wsStatus) return;
    var statusText = {
      connecting: "Conectando al canal de planes…",
      connected: "Canal de planes en tiempo real: conectado",
      reconnecting: "Canal de planes caído — reconectando…",
    }[plansSection.wsStatus];
    if (statusText) wrap.appendChild(h("p", "ws-status-note", statusText));
  }

  // T-FB024-US04-02: carga las User Stories en TODO desde el backlog para
  // poblar el selector del formulario de Plan.
  function loadTodoStories() {
    if (plansSection.todoStories !== null && !plansSection.todoStoriesError) return;
    plansSection.todoStoriesLoading = true;
    BackendClient.getBacklog()
      .then(function (report) {
        var epicsWithTodo = (report.by_epic || []).filter(function (epic) {
          return epic.user_stories && epic.user_stories.TODO > 0;
        });
        if (epicsWithTodo.length === 0) {
          plansSection.todoStories = [];
          plansSection.todoStoriesLoading = false;
          renderPlansBody();
          return;
        }
        var fetched = 0;
        var stories = [];
        epicsWithTodo.forEach(function (epic) {
          var epicId = epicIdFromLabel(epic.epic);
          if (!epicId) {
            fetched++;
            if (fetched === epicsWithTodo.length) finish();
            return;
          }
          BackendClient.getBacklogItem(epicId)
            .then(function (detail) {
              (detail.user_stories || []).forEach(function (us) {
                if (us.state === "TODO") {
                  stories.push({ id: us.id, epic: epicId, state: us.state });
                }
              });
            })
            .catch(function () {
              // fallo puntual al cargar una epic concreta: se ignora
            })
            .finally(function () {
              fetched++;
              if (fetched === epicsWithTodo.length) finish();
            });
        });
        function finish() {
          plansSection.todoStories = stories;
          plansSection.todoStoriesLoading = false;
          if (state.section === "plan") renderPlansBody();
        }
      })
      .catch(function (error) {
        plansSection.todoStoriesLoading = false;
        plansSection.todoStoriesError = buildErrorMessage(error);
        if (state.section === "plan") renderPlansBody();
      });
  }

  // Punto 1: formulario para pedir un plan (`POST /plans`, campo `goal`
  // con el identificador de la User Story). Single-flight en el envío
  // (mismo criterio que enviar Job/lanzar agente).
  // T-FB024-US04-02: `goal` es un selector poblado con las Stories TODO
  // del backlog (no texto libre sin validar).
  function renderPlansForm(wrap) {
    var form = h("div", "plans-form");
    form.appendChild(h("div", "field-label", "Pedir un plan al Critic"));

    // T-FB024-US04-02: selector de User Stories TODO en vez de texto libre.
    if (plansSection.todoStories === null || plansSection.todoStoriesLoading) {
      form.appendChild(h("p", "section-note", "Cargando User Stories del backlog…"));
    } else if (plansSection.todoStoriesError) {
      form.appendChild(h("p", "agent-error", "No se pudo cargar el catálogo de User Stories."));
      // Fallback: entrada de texto libre si la carga falló.
      var fallbackInput = document.createElement("input");
      fallbackInput.type = "text";
      fallbackInput.className = "clickable";
      fallbackInput.placeholder = "Identificador de User Story (p. ej. US-FB008-04)";
      fallbackInput.value = plansSection.goalInput;
      fallbackInput.addEventListener("input", function () {
        plansSection.goalInput = fallbackInput.value;
      });
      form.appendChild(fallbackInput);
    } else if (plansSection.todoStories.length === 0) {
      form.appendChild(h("p", "section-note", "No hay User Stories en TODO en el backlog."));
    } else {
      var select = document.createElement("select");
      select.className = "clickable launch-select";
      if (plansSection.goalSelectIndex >= plansSection.todoStories.length) plansSection.goalSelectIndex = 0;
      plansSection.todoStories.forEach(function (story, idx) {
        var o = document.createElement("option");
        o.setAttribute("value", String(idx));
        o.textContent = story.id + " (" + (story.epic || "") + ") — TODO";
        select.appendChild(o);
      });
      select.selectedIndex = plansSection.goalSelectIndex;
      select.addEventListener("change", function () {
        plansSection.goalSelectIndex = parseInt(select.value, 10) || 0;
        renderPlansBody();
      });
      form.appendChild(select);
    }

    var submit = button("Solicitar plan", "plan-submit");
    if (plansSection.requesting) {
      submit.disabled = true;
      submit.textContent = "Solicitando…";
    }
    submit.addEventListener("click", requestPlan);
    form.appendChild(submit);

    if (plansSection.requestError) {
      form.appendChild(h("p", "agent-error", plansSection.requestError));
    }
    wrap.appendChild(form);
  }

  // Punto 2/5/6/7: cuerpo del plan. Solo se muestra si hay un plan cargado
  // (solicitado o recuperado de `GET /plans`).
  function renderPlanDetails(wrap) {
    var plan = plansSection.currentPlan;
    if (!plan) {
      wrap.appendChild(
        h("p", "section-note", "Ningún plan solicitado todavía. Escribe un identificador de User Story arriba.")
      );
      return;
    }

    var cardEl = h("div", "plan-card");
    wrap.appendChild(cardEl);

    cardEl.appendChild(h("div", "plan-goal", "Objetivo: " + (plan.goal || "")));
    cardEl.appendChild(
      h("div", "plan-status " + planStatusClass(plan.status), "Estado del plan: " + planStatusLabel(plan.status))
    );

    // Punto 4: los pasos tal cual los devuelve el backend, sin resumir ni
    // reformular (mismo criterio ya aplicado en ambos clientes).
    (plan.steps || []).forEach(function (step, index) {
      var stepCard = h("div", "plan-step");
      stepCard.appendChild(
        h("div", "plan-step-title", "Paso " + (index + 1) + ": " + String(step.description || ""))
      );
      stepCard.appendChild(h("div", "plan-step-field", "Mecanismo: " + String(step.mechanism || "")));
      stepCard.appendChild(
        h("div", "plan-step-field", "Estado: " + planStatusLabel(step.status))
      );
      cardEl.appendChild(stepCard);
    });

    if (plansSection.actionError) {
      cardEl.appendChild(h("p", "agent-error", plansSection.actionError));
    }

    // T-FB021-US05-02: "Cancelar plan" SOLO mientras el plan está en curso
    // de despacho — estado `approved` con al menos un paso `pending`/
    // `running` (la MISMA condición que el dominio `request_cancellation`
    // exige para aceptar `POST /plans/{id}/cancel`). Un plan íntegramente
    // despachado permanece `approved` (no hay estado `completed` de plan,
    // ver `job_plan_lifecycle.py`), así que "quedan pasos por despachar" se
    // detecta por sus pasos, no por `plan.status`.
    var hasPendingOrRunning = (plan.steps || []).some(function (step) {
      return step.status === "pending" || step.status === "running";
    });
    if (plan.status === "approved" && hasPendingOrRunning) {
      cardEl.appendChild(renderCancelPlanActions(plan));
      return;
    }

    if (plan.status !== "proposed") return;

    var actions = h("div", "plan-actions");
    // Punto 5: Aprobar con confirmación previa que muestra el número de
    // pasos (en la etiqueta del propio botón, patrón anti-reflow) + punto 7
    // single-flight: mientras la petición está en vuelo no se dispara una
    // segunda llamada real.
    var approveLabel;
    if (plansSection.approving) {
      approveLabel = "Aprobando…";
    } else if (plansSection.approvePending) {
      approveLabel =
        "¿Aprobar plan completo? Se despacharán " +
        (plan.steps || []).length +
        " pasos automáticamente. Confirmar aprobación";
    } else {
      approveLabel = "Aprobar plan completo";
    }
    var approveBtn = button(approveLabel, "plan-approve");
    if (plansSection.approving) approveBtn.disabled = true;
    approveBtn.addEventListener("click", requestApprove);
    actions.appendChild(approveBtn);

    // Rechazar: sin confirmación (sin efecto destructivo, punto 5). Single-flight.
    var rejectLabel = plansSection.rejecting ? "Rechazando…" : "Rechazar";
    var rejectBtn = button(rejectLabel, "plan-reject");
    if (plansSection.rejecting) rejectBtn.disabled = true;
    rejectBtn.addEventListener("click", requestReject);
    actions.appendChild(rejectBtn);

    cardEl.appendChild(actions);
  }

  function requestPlan() {
    if (plansSection.requesting) return; // single-flight
    // T-FB024-US04-02: el goal se toma del selector de TODO stories (si
    // está disponible), o del input de texto libre como fallback.
    var goal;
    if (plansSection.todoStories && plansSection.todoStories.length > 0) {
      var selected = plansSection.todoStories[plansSection.goalSelectIndex];
      if (!selected) {
        plansSection.requestError = "Elige una User Story antes de pedir el plan.";
        renderPlansBody();
        return;
      }
      goal = selected.id;
    } else {
      goal = plansSection.goalInput.trim();
      if (!goal) {
        plansSection.requestError = "Escribe un identificador de User Story antes de pedir el plan.";
        renderPlansBody();
        return;
      }
    }
    plansSection.requesting = true;
    plansSection.requestError = null;
    plansSection.actionError = null;
    plansSection.approvePending = false;
    renderPlansBody();

    BackendClient.requestPlan({ goal: goal })
      .then(function (plan) {
        plansSection.requesting = false;
        plansSection.currentPlanId = plan.plan_id;
        plansSection.currentPlan = plan;
        renderPlansBody();
        return refreshPlansHistory();
      })
      .catch(function (error) {
        plansSection.requesting = false;
        plansSection.requestError = buildErrorMessage(error);
        renderPlansBody();
      });
  }

  // 1er clic -> confirmación con el nº de pasos en la etiqueta; 2º clic ->
  // llamada real. Mientras la petición está en vuelo, cualquier otro clic
  // se descarta (punto 7).
  function requestApprove() {
    var planId = plansSection.currentPlanId;
    if (!planId) return;
    if (plansSection.approving || plansSection.rejecting) return; // single-flight
    if (!plansSection.approvePending) {
      plansSection.approvePending = true;
      renderPlansBody();
      return;
    }
    executeApprove();
  }

  function executeApprove() {
    var planId = plansSection.currentPlanId;
    if (!planId || plansSection.approving) return;
    plansSection.approvePending = false;
    plansSection.approving = true;
    plansSection.actionError = null;
    renderPlansBody();

    BackendClient.approvePlan(planId)
      .then(function (plan) {
        plansSection.approving = false;
        plansSection.currentPlan = plan;
        renderPlansBody();
        return refreshPlansHistory();
      })
      .catch(function (error) {
        plansSection.approving = false;
        plansSection.actionError = buildErrorMessage(error);
        renderPlansBody();
      });
  }

  function requestReject() {
    var planId = plansSection.currentPlanId;
    if (!planId) return;
    if (plansSection.approving || plansSection.rejecting) return; // single-flight
    plansSection.rejecting = true;
    plansSection.actionError = null;
    renderPlansBody();

    BackendClient.rejectPlan(planId)
      .then(function (plan) {
        plansSection.rejecting = false;
        plansSection.currentPlan = plan;
        renderPlansBody();
        return refreshPlansHistory();
      })
      .catch(function (error) {
        plansSection.rejecting = false;
        plansSection.actionError = buildErrorMessage(error);
        renderPlansBody();
      });
  }

  // ----------------------------------------------------- cancelar plan
  // (T-FB021-US05-02, punto 1). Confirmación de SEGUNDA pulsación en la
  // ETIQUETA del propio botón (mismo riesgo de reflow ya corregido en
  // US03-02/US04-02: el aviso crece en la etiqueta, nunca en un elemento
  // aparte que desplace el layout entre el primer y el segundo clic) +
  // single-flight de la llamada real (punto 3).
  function renderCancelPlanActions(plan) {
    var actions = h("div", "plan-actions");
    var isThisCancelling = plansSection.cancellingPlanId === plan.plan_id;
    var isThisPending = plansSection.cancelPendingFor === plan.plan_id;
    var label;
    if (isThisCancelling) {
      label = "Cancelando…";
    } else if (isThisPending) {
      label = "¿Seguro? Se detendrá el despacho de los pasos restantes. Confirmar cancelación";
    } else {
      label = "Cancelar plan";
    }
    var cancelBtn = button(label, "plan-cancel");
    if (isThisCancelling) cancelBtn.disabled = true;
    cancelBtn.addEventListener("click", function () {
      requestCancelPlan(plan.plan_id);
    });
    actions.appendChild(cancelBtn);
    return actions;
  }

  // 1er clic -> confirmación en la etiqueta; 2º clic -> llamada real.
  // Mientras la petición está en vuelo, cualquier otro clic se descarta
  // (punto 3, mismo criterio de `SingleFlightAction` que en los otros
  // dos clientes).
  function requestCancelPlan(planId) {
    if (!planId) return;
    if (plansSection.cancellingPlanId) return; // single-flight
    if (plansSection.cancelPendingFor !== planId) {
      plansSection.cancelPendingFor = planId;
      renderPlansBody();
      return;
    }
    executeCancelPlan(planId);
  }

  function executeCancelPlan(planId) {
    if (!planId || plansSection.cancellingPlanId) return;
    plansSection.cancelPendingFor = null;
    plansSection.cancellingPlanId = planId;
    plansSection.actionError = null;
    renderPlansBody();

    BackendClient.cancelPlan(planId)
      .then(function (plan) {
        plansSection.cancellingPlanId = null;
        plansSection.currentPlan = plan;
        renderPlansBody();
        return refreshPlansHistory();
      })
      .catch(function (error) {
        plansSection.cancellingPlanId = null;
        plansSection.actionError = buildErrorMessage(error);
        renderPlansBody();
      });
  }

  // ----------------------------------------------------- histórico
  // (T-FB021-US05-02, punto 2). Lista completa desde `GET /plans` —
  // incluye los planes ya decididos (aprobados/rechazados/cancelados), que
  // el backend NO purga (mismo criterio que `GET /jobs`); el detalle de un
  // plan concreto se consulta al desplegarlo vía `GET /plans/{id}`. Además
  // cumple el punto 6 de US05-01 (recuperar un `proposed` pendiente) sobre
  // la MISMA lista — una única llamada a `GET /plans` al entrar en la
  // pantalla, no dos. Un fallo de red es SILENCIOSO para la recuperación
  // del pendiente (la pantalla se comporta como si no hubiera plan) y para
  // el histórico conserva la última lista vista marcada `stale` (mismo
  // criterio que Jobs).
  function refreshPlansHistory() {
    return BackendClient.getPlans()
      .then(function (plans) {
        plansSection.history = plans || [];
        plansSection.historyStale = false;
        plansSection.historyError = null;
        recoverPendingPlanFrom(plans);
        if (state.section === "plan") renderPlansBody();
      })
      .catch(function (error) {
        if (plansSection.history !== null) {
          plansSection.historyStale = true;
        } else {
          plansSection.historyError = buildErrorMessage(error);
        }
        if (state.section === "plan") renderPlansBody();
      });
  }

  // Despliegue del detalle de un plan del histórico: 1ª pulsación -> se
  // consulta `GET /plans/{id}` y se muestra completo (sin resumir, punto 4);
  // 2ª pulsación -> se pliega. La selección persiste a través de los
  // re-renders porque vive en `plansSection`.
  function togglePlanHistoryDetail(plan) {
    if (plansSection.selectedPlanId === plan.plan_id) {
      plansSection.selectedPlanId = null;
      plansSection.historyDetail = null;
      plansSection.historyDetailError = null;
      renderPlansBody();
      return;
    }
    plansSection.selectedPlanId = plan.plan_id;
    plansSection.historyDetail = null;
    plansSection.historyDetailError = null;
    renderPlansBody();

    BackendClient.getPlan(plan.plan_id)
      .then(function (detail) {
        if (plansSection.selectedPlanId !== plan.plan_id) return;
        plansSection.historyDetail = detail;
        renderPlansBody();
      })
      .catch(function (error) {
        if (plansSection.selectedPlanId !== plan.plan_id) return;
        plansSection.historyDetailError = buildErrorMessage(error);
        renderPlansBody();
      });
  }

  function renderPlansHistory(wrap) {
    wrap.appendChild(h("div", "plans-history-title", "Histórico de planes de la sesión"));
    if (plansSection.history === null) {
      if (plansSection.historyError) {
        wrap.appendChild(h("p", "agent-error", plansSection.historyError));
      } else {
        wrap.appendChild(h("p", "section-note", "Cargando histórico…"));
      }
      return;
    }
    if (plansSection.historyStale) {
      wrap.appendChild(
        h(
          "p",
          "stale-note",
          "Puede que este histórico esté desactualizado (sin conexión con el backend)."
        )
      );
    }
    if (plansSection.history.length === 0) {
      wrap.appendChild(h("p", "section-note", "Todavía no se ha solicitado ningún plan en esta sesión."));
      return;
    }
    plansSection.history.forEach(function (plan) {
      var selected = plansSection.selectedPlanId === plan.plan_id;
      var summary = String(plan.goal || "");
      var card = h("div", "plan-history-card" + (selected ? " plan-history-selected" : ""));
      var line = h(
        "div",
        "plan-history-line" +
          " plan-status-" +
          (plan.status === "blocked" || plan.status === "cancelled" ? "ko" : "run") +
          (selected ? " plan-line-selected" : ""),
        "[" + plan.status + "] " + (summary || plan.plan_id) + " · " + plan.plan_id
      );
      line.tabIndex = 0;
      line.setAttribute("role", "button");
      line.setAttribute("aria-expanded", selected ? "true" : "false");
      line.addEventListener("click", function () {
        togglePlanHistoryDetail(plan);
      });
      card.appendChild(line);
      card.appendChild(
        h("div", "job-hint", selected ? "▲ Plegar detalle" : "▼ Ver detalle")
      );
      if (selected) {
        card.appendChild(renderPlanHistoryDetail(plan));
      }
      wrap.appendChild(card);
    });
  }

  // Detalle completo de un plan del histórico (punto 4: pasos tal cual los
  // devuelve el backend, sin resumir ni reformular).
  function renderPlanHistoryDetail(plan) {
    var box = h("div", "plan-history-detail");
    if (plansSection.historyDetailError) {
      box.appendChild(h("p", "agent-error", plansSection.historyDetailError));
      return box;
    }
    var detail = plansSection.historyDetail || plan;
    box.appendChild(h("div", "plan-goal", "Objetivo: " + (detail.goal || "")));
    box.appendChild(
      h("div", "plan-status " + planStatusClass(detail.status), "Estado del plan: " + planStatusLabel(detail.status))
    );
    (detail.steps || []).forEach(function (step, index) {
      var stepCard = h("div", "plan-step");
      stepCard.appendChild(
        h("div", "plan-step-title", "Paso " + (index + 1) + ": " + String(step.description || ""))
      );
      stepCard.appendChild(h("div", "plan-step-field", "Mecanismo: " + String(step.mechanism || "")));
      stepCard.appendChild(
        h("div", "plan-step-field", "Estado: " + planStatusLabel(step.status))
      );
      box.appendChild(stepCard);
    });
    return box;
  }

  // Distingue `blocked` del resto de estados (mismo criterio que
  // `planStatusLabel` de `PlanScreen.kt`): el resto se muestran tal cual,
  // sin reformular (punto 4).
  function planStatusLabel(status) {
    if (status === "blocked") return "BLOQUEADO (fallo intermedio, no se despachan más pasos)";
    return status;
  }

  // Clase de color del estado global del plan: los terminales con matiz
  // negativo (`blocked`/`cancelled`/`rejected`) se muestran en rojo (ko),
  // el resto (`proposed`/`approved`/`pending`) en azul (run).
  function planStatusClass(status) {
    if (status === "blocked" || status === "cancelled" || status === "rejected") {
      return "plan-status-ko";
    }
    return "plan-status-run";
  }

  // ------------------------------------------------------------- SCRIPTS
  // (T-FB021-US06-01). Catálogo combinado (`GET /scripts`) con origen,
  // ejecución con un clic (`POST /scripts/{id}/run`), resultado completo y
  // presentación legible de `backlog_status`. Ver `scriptsSection` arriba.

  // Script del catálogo genérico que pide parámetro `message` (punto 2) y
  // cuyo resultado estructurado se presenta con formato (punto 4) — mismo
  // criterio que `SCRIPT_WITH_MESSAGE_PARAM`/`BACKLOG_STATUS_SCRIPT` en
  // Android (`ScriptsScreen.kt`).
  var SCRIPT_WITH_MESSAGE_PARAM = "commit";
  var BACKLOG_STATUS_SCRIPT = "backlog_status";

  // Entrada de la sección: contenedor propio y carga del catálogo
  // combinado desde `GET /scripts` (recompuesto cada vez que se entra,
  // mismo criterio que Jobs — los scripts particulares pueden cambiar).
  function renderScriptsInto(content) {
    scriptsSection.bodyWrap = h("div", "scripts-body");
    content.appendChild(scriptsSection.bodyWrap);
    refreshScripts();
    renderScriptsBody();
  }

  // Carga del catálogo combinado. Un fallo puntual conserva la última lista
  // vista marcada `stale` (mismo criterio que Jobs/Agentes); solo sin lista
  // previa se muestra el error.
  function refreshScripts() {
    return BackendClient.getScripts()
      .then(function (scripts) {
        scriptsSection.list = scripts || [];
        scriptsSection.stale = false;
        scriptsSection.listError = null;
        if (state.section === "scripts") renderScriptsBody();
      })
      .catch(function (error) {
        if (scriptsSection.list !== null) {
          scriptsSection.stale = true;
        } else {
          scriptsSection.listError = buildErrorMessage(error);
        }
        if (state.section === "scripts") renderScriptsBody();
      });
  }

  function renderScriptsBody() {
    var wrap = scriptsSection.bodyWrap;
    if (!wrap || state.section !== "scripts") return;
    wrap.textContent = "";
    renderScriptsCatalog(wrap);
    renderScriptResult(wrap);
  }

  // Brain)" y "Proyecto" — el origen no se mezcla en una lista
  // indistinguible (mismo criterio de Android `ScriptsScreen`).
  function renderScriptsCatalog(wrap) {
    wrap.appendChild(h("div", "scripts-title", "Catálogo de scripts"));
    if (scriptsSection.list === null) {
      if (scriptsSection.listError) {
        wrap.appendChild(h("p", "agent-error", scriptsSection.listError));
      } else {
        wrap.appendChild(h("p", "section-note", "Cargando catálogo…"));
      }
      return;
    }
    if (scriptsSection.stale) {
      wrap.appendChild(
        h(
          "p",
          "stale-note",
          "Puede que este catálogo esté desactualizado (sin conexión con el backend)."
        )
      );
    }

    var generic = (scriptsSection.list || []).filter(function (script) {
      return script.origin === "generic";
    });
    var particular = (scriptsSection.list || []).filter(function (script) {
      return script.origin === "particular";
    });

    if (scriptsSection.list.length === 0) {
      wrap.appendChild(
        h("p", "section-note", "No hay scripts catalogados en la sesión.")
      );
      return;
    }

    if (generic.length > 0) {
      wrap.appendChild(h("div", "scripts-group-title", "Genéricos (Factory Brain)"));
      wrap.appendChild(h("p", "section-note", "Scripts disponibles en cualquier proyecto del workspace."));
      generic.forEach(function (script) {
        wrap.appendChild(renderScriptCard(script));
      });
    }
    if (particular.length > 0) {
      wrap.appendChild(h("div", "scripts-group-title", "Proyecto"));
      wrap.appendChild(h("p", "section-note", "Scripts específicos de este proyecto."));
      particular.forEach(function (script) {
        wrap.appendChild(renderScriptCard(script));
      });
    }
  }

  // Tarjeta de un script: nombre + descripción (particulares) + campo de
  // mensaje SOLO para `commit` + botón "Ejecutar" (punto 2): deshabilitado
  // hasta tener mensaje no vacío para commit, y siempre que haya una
  // ejecución en vuelo (single-flight, punto 5).
  function renderScriptCard(script) {
    var needsMessage = script.id === SCRIPT_WITH_MESSAGE_PARAM;
    var isRunning = scriptsSection.runningScriptId === script.id;
    var busy = scriptsSection.runningScriptId !== null;

    var card = h("div", "script-card");
    var header = h("div", "script-card-header");
    header.appendChild(h("span", "script-name", script.name || script.id));
    var origin = script.origin === "generic" ? "Genérico" : "Proyecto";
    header.appendChild(h("span", "script-origin script-origin-" + (script.origin === "generic" ? "generic" : "particular"), origin));
    card.appendChild(header);

    if (script.description) {
      card.appendChild(h("div", "script-description", String(script.description)));
    }

    // Comando expandible: visible solo al pulsar "Ver comando".
    if (script.command) {
      var expanded = scriptsSection._expandedCommandId === script.id;
      var toggleLabel = expanded ? "▼ Ocultar comando" : "▶ Ver comando";
      var toggleBtn = button(toggleLabel, "script-expand-toggle");
      toggleBtn.addEventListener("click", function () {
        scriptsSection._expandedCommandId = expanded ? null : script.id;
        renderScriptsBody();
      });
      card.appendChild(toggleBtn);
      if (expanded) {
        card.appendChild(h("div", "script-command", String(script.command)));
      }
    }

    if (needsMessage) {
      var field = h("div", "script-field-label", "Mensaje del commit");
      card.appendChild(field);
      var commitInput = document.createElement("input");
      commitInput.type = "text";
      commitInput.className = "clickable";
      commitInput.value = scriptsSection.commitMessage;
      commitInput.placeholder = "Mensaje del commit (obligatorio)";
      commitInput.addEventListener("input", function () {
        scriptsSection.commitMessage = commitInput.value;
        var btn = card.querySelector(".script-run");
        if (btn) btn.disabled = !commitInput.value.trim() || scriptsSection.runningScriptId !== null;
      });
      card.appendChild(commitInput);
    }

    var runLabel = isRunning ? "Ejecutando…" : "Ejecutar";
    var runBtn = button(runLabel, "script-run");
    var disabled = busy || (needsMessage && !scriptsSection.commitMessage.trim());
    if (disabled) runBtn.disabled = true;
    runBtn.addEventListener("click", function () {
      runScript(script);
    });
    card.appendChild(runBtn);
    return card;
  }

  // Ejecución de un script (punto 2/3/5). Single-flight: `runningScriptId`
  // descarta una segunda invocación mientras la petición anterior sigue en
  // vuelo; el botón además queda deshabilitado (mismo criterio que
  // `SingleFlightAction` en Android `ScriptsViewModel`).
  function runScript(script) {
    if (scriptsSection.runningScriptId) return; // single-flight
    var message = script.id === SCRIPT_WITH_MESSAGE_PARAM ? scriptsSection.commitMessage.trim() : null;
    if (script.id === SCRIPT_WITH_MESSAGE_PARAM && !message) {
      scriptsSection.runError = "Escribe un mensaje para el commit antes de ejecutar.";
      renderScriptsBody();
      return;
    }
    scriptsSection.runningScriptId = script.id;
    scriptsSection.runError = null;
    scriptsSection.lastResult = null;
    renderScriptsBody();

    BackendClient.runScript(script.id, message)
      .then(function (result) {
        scriptsSection.runningScriptId = null;
        scriptsSection.lastResult = { scriptId: script.id, result: result };
        renderScriptsBody();
        return refreshScripts();
      })
      .catch(function (error) {
        scriptsSection.runningScriptId = null;
        scriptsSection.runError = buildErrorMessage(error);
        renderScriptsBody();
      });
  }

  // Resultado completo del último script ejecutado (punto 3): success +
  // exit_code + stdout/stderr/error_message, sin ocultar el fallo. Para
  // `backlog_status` exitoso, `data` se presenta estructurado (punto 4) y
  // `prose` se añade como síntesis cuando está disponible.
  function renderScriptResult(wrap) {
    if (scriptsSection.runError) {
      var errBox = h("div", "script-result");
      errBox.appendChild(h("p", "agent-error", scriptsSection.runError));
      wrap.appendChild(errBox);
      return;
    }
    if (scriptsSection.runningScriptId) {
      wrap.appendChild(h("p", "section-note", "Ejecutando…"));
      return;
    }
    var last = scriptsSection.lastResult;
    if (!last) return;

    var result = last.result || {};
    var box = h("div", "script-result");
    var ok = result.success === true;
    var label;
    if (ok) {
      label = "Éxito (exit code " + (result.exit_code === undefined || result.exit_code === null ? "—" : result.exit_code) + ")";
    } else if (result.exit_code !== undefined && result.exit_code !== null) {
      label = "Falló (exit code " + result.exit_code + ")";
    } else {
      // El script nunca llegó a ejecutarse (id desconocido, manifiesto
      // roto, timeout) — se refleja el motivo real, sin romper la pantalla.
      label = "No se pudo ejecutar: " + (result.error_message || "sin detalle");
    }
    box.appendChild(h("div", "script-result-title", label));

    var output;
    if (ok && last.scriptId === BACKLOG_STATUS_SCRIPT && result.data) {
      output = formatBacklogStatus(result.data);
      if (result.prose) {
        output += "\n\nSíntesis en prosa:\n" + String(result.prose);
      }
    } else {
      var parts = [];
      if (result.stdout !== undefined && result.stdout !== null && String(result.stdout) !== "") {
        parts.push(String(result.stdout));
      }
      if (result.stderr !== undefined && result.stderr !== null && String(result.stderr) !== "") {
        parts.push(String(result.stderr));
      }
      if (!ok && result.error_message) {
        parts.push("Error: " + String(result.error_message));
      }
      output = parts.join("\n");
    }
    if (output) {
      box.appendChild(h("div", "script-output", output));
    }
    wrap.appendChild(box);
  }

  // Presentación legible del informe estructurado de backlog-status
  // (punto 4, T-FB018-US02-04): conteo por Epic, Tasks LISTA, Tasks
  // BLOQUEADA con su dependencia y cadena de mayor apalancamiento — el
  // usuario no tiene que leer el JSON crudo. Mismo shape que
  // `formatBacklogStatus` (Android) / `_format_backlog_status` (TUI),
  // con la sección de bloqueadas que el shape expone.
  function formatBacklogStatus(data) {
    if (!data) return "";
    if (data.empty) {
      return "El backlog está vacío (aún no hay US/Tasks).";
    }
    var lines = ["Estado del backlog:"];
    var total = data.total || {};
    lines.push(
      "  Total: " + (total.items === undefined ? 0 : total.items) +
        " items · " + (total.errors === undefined ? 0 : total.errors) +
        " errores de parseo"
    );
    var us = total.user_stories || {};
    if (Object.keys(us).length > 0) {
      lines.push("  US: " + Object.keys(us).sort().map(function (k) { return k + "=" + us[k]; }).join(", "));
    }
    var tasks = total.tasks || {};
    if (Object.keys(tasks).length > 0) {
      lines.push("  Task: " + Object.keys(tasks).sort().map(function (k) { return k + "=" + tasks[k]; }).join(", "));
    }

    lines.push("\nConteo por Epic:");
    (data.by_epic || []).forEach(function (epic) {
      var epicLine = "  " + epic.epic;
      if (epic.user_stories && Object.keys(epic.user_stories).length > 0) {
        epicLine += " · US: " + Object.keys(epic.user_stories).sort().map(function (k) { return k + "=" + epic.user_stories[k]; }).join(", ");
      }
      if (epic.tasks && Object.keys(epic.tasks).length > 0) {
        epicLine += " · Task: " + Object.keys(epic.tasks).sort().map(function (k) { return k + "=" + epic.tasks[k]; }).join(", ");
      }
      lines.push(epicLine);
    });

    lines.push("\nTasks LISTA (listas para empezar):");
    var lista = data.items_lista || [];
    if (lista.length > 0) {
      lista.forEach(function (entry) {
        lines.push("  " + entry.id);
      });
    } else {
      lines.push("  (ninguna)");
    }

    lines.push("\nTasks BLOQUEADA (con dependencia pendiente):");
    var bloqueada = data.items_bloqueada || [];
    if (bloqueada.length > 0) {
      bloqueada.forEach(function (entry) {
        var pending = (entry.blocking_dependencies || [])
          .map(function (dep) {
            return dep.id + (dep.state ? " [" + dep.state + "]" : " (no existe)");
          })
          .join(", ");
        lines.push("  " + entry.id + " ← espera a " + pending);
      });
    } else {
      lines.push("  (ninguna)");
    }

    lines.push("\nCadena de mayor apalancamiento (próximo foco):");
    var chain = data.max_leverage_chain || [];
    if (chain.length > 0) {
      lines.push("  " + chain.map(function (entry) { return entry.id; }).join(" → "));
    } else {
      lines.push("  (ninguna)");
    }

    return lines.join("\n");
  }

  // ------------------------------------------------------------- BACKLOG
  // (T-FB020-US04-01). Consume `GET /backlog`/`GET /backlog/{item_id}`/
  // `POST /backlog/{story_id}/launch-development` (T-FB020-US01-01/
  // US02-01, ambos `DONE`) — SIN cambios de backend. Patrón de
  // expandir-en-el-sitio (mismo criterio que Jobs/Plan: nunca navega a
  // otra pantalla), lista de Epics -> expandir muestra sus User Stories
  // -> expandir una US muestra su detalle completo + "Lanzar desarrollo".
  // Ver `backlogSection` (declarado arriba) para el shape completo del
  // estado.

  // Identificador de Epic (`FB-xxx`) a partir de la etiqueta libre
  // `**Epic:**` de una US/Task (p. ej. "FB-020 · Gestión de Backlog
  // (alcance v1)" -> "FB-020") — mismo criterio que `epicIdFromLabel`
  // (Android)/`_epic_id_from_label` (TUI): el PREFIJO, no el string
  // completo (distintas Tasks/US de la MISMA Epic real traen sufijos
  // distintos, verificado sobre el backlog real de este proyecto:
  // `FB-008` con 8 variantes). `null` si el label no sigue la
  // convención (p. ej. el caso real "(ninguna — infraestructura de
  // proyecto)").
  function epicIdFromLabel(epicLabel) {
    var match = /^(FB-\d{3,})/.exec(String(epicLabel || "").trim());
    return match ? match[1] : null;
  }

  // Entrada de la sección: contenedor propio, recompone SIEMPRE desde
  // `GET /backlog` al entrar (mismo criterio que Jobs/Plan/Scripts —
  // nunca se pierde el estado de navegación entre pestañas porque vive
  // en `backlogSection`, pero los DATOS se refrescan cada vez, punto 6:
  // recontextualización por cambio de proyecto activo "gratis").
  function renderBacklogInto(content) {
    backlogSection.bodyWrap = h("div", "backlog-body");
    content.appendChild(backlogSection.bodyWrap);
    refreshBacklogReport();
    renderBacklogBody();
  }

  // Recomposición del listado raíz desde `GET /backlog`. A diferencia de
  // Jobs/Agentes (donde un 404 es "sin sesión" -> lista vacía), aquí un
  // 404 real (sin proyecto activo) SÍ es un error a mostrar — mismo
  // criterio ya fijado en Android/TUI y en el propio backend
  // (T-FB020-US01-01). Un fallo puntual con lista previa ya vista
  // conserva esa lista marcada `stale` (mismo criterio que Jobs/Plan).
  function refreshBacklogReport() {
    return BackendClient.getBacklog()
      .then(function (report) {
        backlogSection.report = report;
        backlogSection.stale = false;
        backlogSection.reportError = null;
        if (state.section === "backlog") renderBacklogBody();
      })
      .catch(function (error) {
        if (backlogSection.report !== null) {
          backlogSection.stale = true;
        } else {
          backlogSection.reportError = buildErrorMessage(error);
        }
        if (state.section === "backlog") renderBacklogBody();
      });
  }

  function renderBacklogBody() {
    var wrap = backlogSection.bodyWrap;
    if (!wrap || state.section !== "backlog") return;
    wrap.textContent = "";
    renderBacklogViewToggle(wrap);
    if (backlogSection.viewMode === "by_fase") {
      renderBacklogByFase(wrap);
    } else {
      renderBacklogEpicList(wrap);
    }
  }

  function renderBacklogViewToggle(wrap) {
    if (backlogSection.report === null || backlogSection.report.empty) return;
    var header = h("div", "context-bar");
    var flatBtn = button("Lista", "backlog-view-toggle");
    if (backlogSection.viewMode === "flat") flatBtn.className += " active";
    flatBtn.addEventListener("click", function () {
      backlogSection.viewMode = "flat";
      renderBacklogBody();
    });
    header.appendChild(flatBtn);
    var faseBtn = button("Por Fase", "backlog-view-toggle");
    if (backlogSection.viewMode === "by_fase") faseBtn.className += " active";
    faseBtn.addEventListener("click", function () {
      backlogSection.viewMode = "by_fase";
      renderBacklogBody();
    });
    header.appendChild(faseBtn);
    wrap.appendChild(header);
  }

  function renderBacklogByFase(wrap) {
    var byEpic = backlogSection.report.by_epic || [];
    var groups = {};
    byEpic.forEach(function (epic) {
      var fase = epic.fase || "SIN_ASIGNAR";
      if (!groups[fase]) groups[fase] = [];
      groups[fase].push(epic);
    });
    var ordered = Object.keys(groups).sort();
    ordered.forEach(function (fase) {
      var groupWrap = h("div", "backlog-fase-group");
      groupWrap.appendChild(h("div", "backlog-fase-title", fase));
      groups[fase].forEach(function (epic) {
        renderBacklogEpicCard(groupWrap, epic);
      });
      wrap.appendChild(groupWrap);
    });
  }

  // Listado raíz de Epics (criterio de aceptación 1/2): conteo por
  // estado, igual que Android/TUI (T-FB020-US01-02). Cada fila expande/
  // colapsa su detalle de User Stories in-place (criterio de aceptación
  // 2), sin navegar a otra pantalla.
  function renderBacklogEpicList(wrap) {
    if (backlogSection.report === null) {
      if (backlogSection.reportError) {
        wrap.appendChild(h("p", "agent-error", backlogSection.reportError));
      } else {
        wrap.appendChild(h("p", "section-note", "Cargando backlog…"));
      }
      return;
    }
    if (backlogSection.stale) {
      wrap.appendChild(
        h("p", "stale-note", "Puede que este backlog esté desactualizado (sin conexión con el backend).")
      );
    }
    var byEpic = backlogSection.report.by_epic || [];
    if (backlogSection.report.empty || byEpic.length === 0) {
      wrap.appendChild(h("p", "section-note", "El backlog está vacío (aún no hay Epics/User Stories)."));
      return;
    }
    var realEpics = byEpic.filter(function (e) { return epicIdFromLabel(e.epic) !== null; });
    var orphanItems = byEpic.filter(function (e) { return epicIdFromLabel(e.epic) === null; });
    realEpics.forEach(function (epic) {
      renderBacklogEpicCard(wrap, epic);
    });
    if (orphanItems.length > 0) {
      var orphanHeader = h("div", "job-detail-label", "(sin epic)");
      orphanHeader.style.opacity = "0.55";
      wrap.appendChild(orphanHeader);
      orphanItems.forEach(function (epic) {
        renderBacklogEpicCard(wrap, epic);
      });
    }
  }

  function renderBacklogEpicCard(wrap, epic) {
      var epicId = epicIdFromLabel(epic.epic);
      var selected = epicId !== null && backlogSection.selectedEpicId === epicId;
      var todoCount = (epic.user_stories && epic.user_stories.TODO || 0) + (epic.tasks && epic.tasks.TODO || 0);
      var doneClass = todoCount === 0 ? " backlog-epic-done" : " backlog-epic-active";
      var card = h("div", "job-card" + doneClass + (selected ? " job-card-selected" : ""));
      var summaryParts = [epic.epic];
      var usSummary = stateCountsSummary(epic.user_stories);
      if (usSummary) summaryParts.push("US: " + usSummary);
      var taskSummary = stateCountsSummary(epic.tasks);
      if (taskSummary) summaryParts.push("Task: " + taskSummary);
      var line = h("div", "job-line" + (selected ? " job-line-selected" : ""), summaryParts.join(" · "));
      line.tabIndex = 0;
      line.setAttribute("role", "button");
      line.setAttribute("aria-expanded", selected ? "true" : "false");
      if (epicId === null) {
        // Caso real verificado sobre el backlog de este proyecto: el
        // label libre "(ninguna — infraestructura de proyecto)" no
        // sigue la convención `FB-xxx` — no hay ningún `item_id` de Epic
        // que pedir, no hay nada que expandir para esta fila (mismo
        // criterio que Android/TUI: se ignora el tap, no es un error).
        card.appendChild(line);
        wrap.appendChild(card);
        return;
      }
      line.addEventListener("click", function () {
        toggleEpicDetail(epicId);
      });
      card.appendChild(line);
      renderHeatmapBar(card, epic);
      card.appendChild(h("div", "job-hint", selected ? "▲ Plegar detalle" : "▼ Ver detalle"));
      if (selected) {
        card.appendChild(renderEpicDetail());
      }
      wrap.appendChild(card);
  }

  // Texto "estado=count, estado=count" ordenado por estado — mismo
  // formato ya usado en Android/TUI para el resumen agregado por Epic.
  function stateCountsSummary(counts) {
    if (!counts) return "";
    var keys = Object.keys(counts).sort();
    if (keys.length === 0) return "";
    return keys.map(function (k) { return k + "=" + counts[k]; }).join(", ");
  }

  // Despliegue del detalle de una Epic (criterio de aceptación 2): 1ª
  // pulsación -> se consulta `GET /backlog/{epic_id}` y se muestra
  // completo; 2ª pulsación -> se pliega. Mismo patrón que
  // `togglePlanHistoryDetail` (lazy fetch + guard de respuesta obsoleta:
  // si el usuario ya cambió de selección antes de que la petición
  // resuelva, la respuesta se descarta).
  function toggleEpicDetail(epicId) {
    if (backlogSection.selectedEpicId === epicId) {
      backlogSection.selectedEpicId = null;
      backlogSection.epicDetail = null;
      backlogSection.epicDetailError = null;
      backlogSection.threadsResult = null;
      backlogSection.threadsError = null;
      closeItemDetail();
      renderBacklogBody();
      return;
    }
    backlogSection.selectedEpicId = epicId;
    backlogSection.epicDetail = null;
    backlogSection.epicDetailError = null;
    backlogSection.threadsResult = null;
    backlogSection.threadsError = null;
    closeItemDetail();
    renderBacklogBody();

    BackendClient.getBacklogItem(epicId)
      .then(function (detail) {
        if (backlogSection.selectedEpicId !== epicId) return;
        backlogSection.epicDetail = detail;
        renderBacklogBody();
      })
      .catch(function (error) {
        if (backlogSection.selectedEpicId !== epicId) return;
        backlogSection.epicDetailError = buildErrorMessage(error);
        renderBacklogBody();
      });
  }

  function closeItemDetail() {
    backlogSection.selectedItemId = null;
    backlogSection.itemDetail = null;
    backlogSection.itemDetailError = null;
    backlogSection.launchError = null;
    backlogSection.launchResult = null;
    backlogSection.usJobs = null;
    backlogSection.usJobsError = null;
    backlogSection.manualJobAgents = null;
    backlogSection.manualJobError = null;
    backlogSection.manualJobResult = null;
  }

  // Aviso explícito de sección mal formada (criterio de aceptación 5,
  // mismo patrón que `ParseWarningBanner`/Android y las líneas `⚠ ...`
  // de la TUI): el resto del detalle disponible se muestra igual, esto
  // solo añade el aviso visible encima.
  function renderParseWarning(wrap, detail) {
    if (!detail || !detail.parse_warning) return;
    wrap.appendChild(h("p", "stale-note", "⚠ " + detail.parse_warning));
  }

  // Detalle de la Epic expandida (criterio de aceptación 2): objetivo +
  // desglose de sus User Stories con estado — tocar una US expande su
  // detalle completo (criterio de aceptación 3), sin navegar.
  function renderEpicDetail() {
    var box = h("div", "job-detail");
    if (backlogSection.epicDetailError) {
      box.appendChild(h("p", "agent-error", backlogSection.epicDetailError));
      return box;
    }
    if (backlogSection.epicDetail === null) {
      box.appendChild(h("p", "section-note", "Cargando…"));
      return box;
    }
    var detail = backlogSection.epicDetail;
    renderParseWarning(box, detail);
    box.appendChild(h("div", "job-detail-field", "Objetivo: " + (detail.objetivo || "(sin objetivo declarado)")));

    var userStories = detail.user_stories || [];
    box.appendChild(h("div", "job-detail-label", "User Stories:"));
    if (userStories.length === 0) {
      box.appendChild(h("div", "job-detail-field", "(ninguna)"));
      return box;
    }
    userStories.forEach(function (userStory) {
      var selected = backlogSection.selectedItemId === userStory.id;
      var todoClass = userStory.state === "DONE" ? " backlog-epic-done" : " backlog-epic-active";
      var itemCard = h("div", "job-card" + todoClass + (selected ? " job-card-selected" : ""));
      var itemLine = h(
        "div",
        "job-line" + (selected ? " job-line-selected" : ""),
        userStory.id + " (" + userStory.state + ")"
      );
      itemLine.tabIndex = 0;
      itemLine.setAttribute("role", "button");
      itemLine.setAttribute("aria-expanded", selected ? "true" : "false");
      itemLine.addEventListener("click", function () {
        toggleItemDetail(userStory.id);
      });
      itemCard.appendChild(itemLine);
      itemCard.appendChild(h("div", "job-hint", selected ? "▲ Plegar detalle" : "▼ Ver detalle"));
      if (selected) {
        itemCard.appendChild(renderItemDetail());
      }
      box.appendChild(itemCard);
    });

    // FB-026: botón "Generar hilos de desarrollo" en la Epic, con N
    // (agentes disponibles) configurable — corrección 2026-08-06,
    // auditoría de cierre de Fase 1.0 (antes fijo a 2 sin override).
    var threadControls = h("div", "accion-controls");
    var numAgentsInput = document.createElement("input");
    numAgentsInput.type = "number";
    numAgentsInput.min = "1";
    numAgentsInput.value = String(backlogSection.threadsNumAgents || 2);
    numAgentsInput.className = "accion-num-agents";
    numAgentsInput.title = "Número de agentes disponibles";
    numAgentsInput.addEventListener("change", function () {
      var parsed = parseInt(numAgentsInput.value, 10);
      backlogSection.threadsNumAgents = parsed >= 1 ? parsed : 1;
    });
    threadControls.appendChild(numAgentsInput);

    var threadBtn = button(
      backlogSection.threadsInFlight ? "Analizando hilos…" : "Generar hilos de desarrollo",
      "accion-run"
    );
    if (backlogSection.threadsInFlight) threadBtn.disabled = true;
    threadBtn.addEventListener("click", function () {
      if (backlogSection.threadsInFlight) return;
      analyzeEpicThreads(detail.id, backlogSection.threadsNumAgents || 2);
    });
    threadControls.appendChild(threadBtn);
    box.appendChild(threadControls);

    if (backlogSection.threadsError) {
      box.appendChild(h("p", "agent-error", backlogSection.threadsError));
    }

    if (backlogSection.threadsResult) {
      renderThreadsResult(box);
    }

    return box;
  }

  function analyzeEpicThreads(epicId, numAgents) {
    backlogSection.threadsInFlight = true;
    backlogSection.threadsError = null;
    backlogSection.threadsResult = null;
    renderBacklogBody();

    BackendClient.analyzeEpicThreads(epicId, numAgents)
      .then(function (result) {
        backlogSection.threadsInFlight = false;
        backlogSection.threadsResult = result;
        renderBacklogBody();
      })
      .catch(function (error) {
        backlogSection.threadsInFlight = false;
        backlogSection.threadsError = buildErrorMessage(error);
        renderBacklogBody();
      });
  }

  function renderThreadsResult(box) {
    var r = backlogSection.threadsResult;
    if (!r) return;

    var resultBox = h("div", "accion-result");
    resultBox.appendChild(h("h4", "accion-result-title", "Hilos de desarrollo · " + r.epic));
    resultBox.appendChild(h("p", null,
      r.num_tasks + " tareas en " + r.num_threads + " hilos" +
      (r.num_crosses > 0 ? ", " + r.num_crosses + " cruces" : "")
    ));

    var threads = r.threads || [];
    threads.forEach(function (thread) {
      var threadBox = h("div", "job-detail-field");
      threadBox.appendChild(h("strong", null, thread.id + " (nivel " + thread.start_level + ", " + thread.task_count + " tareas):"));
      var taskList = h("div", null);
      taskList.style.marginLeft = "1em";
      (thread.tasks || []).forEach(function (tid) {
        taskList.appendChild(h("div", null, tid));
      });
      threadBox.appendChild(taskList);
      resultBox.appendChild(threadBox);
    });

    var crosses = r.crosses || [];
    if (crosses.length > 0) {
      var crossBox = h("div", "job-detail-label", "Cruces:");
      crosses.forEach(function (c) {
        crossBox.appendChild(h("div", "job-detail-field",
          c.from_task + " (" + c.from_thread + ") → " + c.to_task + " (" + c.to_thread + ")"
        ));
      });
      resultBox.appendChild(crossBox);
    }

    if (r.report_path) {
      resultBox.appendChild(h("div", "job-hint", "Informe persistido: " + r.report_path));
    }

    box.appendChild(resultBox);
  }

  // Despliegue del detalle completo de una User Story/Task (criterio de
  // aceptación 3): mismo patrón lazy-fetch + guard de respuesta obsoleta
  // que `toggleEpicDetail`. Al abrir el detalle de una User Story, se
  // carga también el catálogo de agentes Developer para el formulario
  // "Lanzar desarrollo" (criterio de aceptación 4).
  function toggleItemDetail(itemId) {
    if (backlogSection.selectedItemId === itemId) {
      closeItemDetail();
      renderBacklogBody();
      return;
    }
    backlogSection.selectedItemId = itemId;
    backlogSection.itemDetail = null;
    backlogSection.itemDetailError = null;
    backlogSection.launchError = null;
    backlogSection.launchResult = null;
    renderBacklogBody();

    BackendClient.getBacklogItem(itemId)
      .then(function (detail) {
        if (backlogSection.selectedItemId !== itemId) return;
        backlogSection.itemDetail = detail;
        renderBacklogBody();
        if (detail.kind === "US") {
          refreshDeveloperAgents();
          loadJobsForUS(itemId);
        }
      })
      .catch(function (error) {
        if (backlogSection.selectedItemId !== itemId) return;
        backlogSection.itemDetailError = buildErrorMessage(error);
        renderBacklogBody();
      });
  }

  // Detalle completo de una User Story/Task (criterio de aceptación 3):
  // objetivo, criterios de aceptación, y — solo para una User Story — la
  // lista de sus Tasks con estado + el formulario "Lanzar desarrollo"
  // (criterio de aceptación 4).
  function renderItemDetail() {
    var box = h("div", "job-detail");
    if (backlogSection.itemDetailError) {
      box.appendChild(h("p", "agent-error", backlogSection.itemDetailError));
      return box;
    }
    if (backlogSection.itemDetail === null) {
      box.appendChild(h("p", "section-note", "Cargando…"));
      return box;
    }
    var detail = backlogSection.itemDetail;
    renderParseWarning(box, detail);
    box.appendChild(h("div", "job-detail-field", "Estado: " + (detail.state || "desconocido")));
    if (detail.epic) {
      box.appendChild(h("div", "job-detail-field", "Epic: " + detail.epic));
    }
    box.appendChild(h("div", "job-detail-field", "Objetivo: " + (detail.objetivo || "(sin objetivo declarado)")));
    box.appendChild(
      h(
        "div",
        "job-detail-field",
        "Criterios de aceptación: " + (detail.criterios_aceptacion || "(sin criterios declarados)")
      )
    );

    // Solo presente para una User Story (`kind === "US"`) — una Task no
    // trae este campo (backend: `build_item_detail`,
    // `brain/backlog/detail.py`). "Lanzar desarrollo" es también
    // exclusivo de una User Story, mismo criterio: el endpoint
    // `POST /backlog/{story_id}/launch-development` solo acepta ids de
    // User Story.
    if (detail.kind === "US") {
      var dependencies = detail.dependencies || [];
      if (dependencies.length > 0) {
        box.appendChild(h("div", "job-detail-label", "Dependencias:"));
        dependencies.forEach(function (dep) {
          var depState = dep.state || "desconocido";
          var depClass = depState === "DONE" ? "job-status-ok" : "job-status-run";
          box.appendChild(h("div", "job-detail-field " + depClass, dep.id + " — " + depState));
        });
      }
      var tasks = detail.tasks || [];
      box.appendChild(h("div", "job-detail-label", "Tasks:"));
      if (tasks.length === 0) {
        if (detail.state === "DONE") {
          box.appendChild(h("div", "job-detail-field", "Todas las tareas completadas"));
        } else {
          box.appendChild(h("div", "job-detail-field", "El Arquitecto no ha desgranado esta Story todavía"));
        }
      } else {
        tasks.forEach(function (task) {
          box.appendChild(h("div", "job-detail-field", task.id + " — " + task.state));
        });
      }
      box.appendChild(renderLaunchDevelopmentForm(detail.id));

      // T-FB024-US09-02: historial de ejecuciones de esta US.
      box.appendChild(renderUSJobHistory());

      // T-FB024-US09-03: formulario manual de creacion de Job.
      box.appendChild(renderManualJobForm(detail.id));
    }
    return box;
  }

  // Catálogo de agentes Developer ya lanzados (criterio de aceptación 4:
  // "mismo catálogo que la sección Agentes/Jobs") — recompuesto cada vez
  // que se abre el detalle de una User Story, mismo criterio que
  // `refreshJobsAgents`, filtrado a `role === "developer"` (mismo
  // criterio que `BacklogViewModel.refreshDeveloperAgents`, Android).
  function refreshDeveloperAgents() {
    backlogSection.developerAgentsError = null;
    BackendClient.getAgents()
      .then(function (agents) {
        backlogSection.developerAgents = (agents || []).filter(function (agent) {
          return agent.role === "developer";
        });
        if (backlogSection.developerAgentIndex >= backlogSection.developerAgents.length) {
          backlogSection.developerAgentIndex = 0;
        }
        if (state.section === "backlog") renderBacklogBody();
      })
      .catch(function (error) {
        backlogSection.developerAgents = [];
        backlogSection.developerAgentsError = buildErrorMessage(error);
        if (state.section === "backlog") renderBacklogBody();
      });
  }

  function renderHeatmapBar(card, epic) {
    var degree = typeof epic.unblock_degree === "number" ? epic.unblock_degree : 0;
    var pct = Math.round(degree * 100);
    var color;
    if (degree >= 0.8) color = "#2e7d32";
    else if (degree >= 0.5) color = "#ef6c00";
    else color = "#d32f2f";
    var bar = h("div", "backlog-heat-bar");
    var fill = h("div", "backlog-heat-fill");
    fill.style.width = pct + "%";
    fill.style.background = color;
    bar.appendChild(fill);
    card.appendChild(bar);
  }

  function findBlockingDependencies() {
    var detail = backlogSection.itemDetail;
    if (!detail || !detail.dependencies) return [];
    return detail.dependencies.filter(function (dep) {
      return dep.state !== "DONE";
    });
  }

  // T-FB024-US09-02: carga los Jobs del histórico de la sesión y filtra
  // los que conciernen a esta US (la descripción contiene el US id).
  function loadJobsForUS(usId) {
    backlogSection.usJobs = null;
    backlogSection.usJobsError = null;
    BackendClient.getJobs()
      .then(function (jobs) {
        backlogSection.usJobs = (jobs || []).filter(function (job) {
          return String(job.description || "").indexOf(usId) >= 0;
        });
        if (state.section === "backlog") renderBacklogBody();
      })
      .catch(function (error) {
        backlogSection.usJobsError = buildErrorMessage(error);
        if (state.section === "backlog") renderBacklogBody();
      });
  }

  // T-FB024-US09-03: carga los agentes activos (sin stopped) de la sesion
  // para el formulario manual de Job.
  function loadManualJobAgents() {
    backlogSection.manualJobAgents = null;
    backlogSection.manualJobAgentsError = null;
    BackendClient.getAgents()
      .then(function (agents) {
        backlogSection.manualJobAgents = (agents || []).filter(function (agent) {
          return agent.status !== "stopped";
        });
        if (backlogSection.manualJobAgentIndex >= backlogSection.manualJobAgents.length) {
          backlogSection.manualJobAgentIndex = 0;
        }
        if (state.section === "backlog") renderBacklogBody();
      })
      .catch(function (error) {
        backlogSection.manualJobAgents = [];
        backlogSection.manualJobAgentsError = buildErrorMessage(error);
        if (state.section === "backlog") renderBacklogBody();
      });
  }

  // Formulario "Lanzar desarrollo" (criterio de aceptación 4, consume
  // `POST /backlog/{story_id}/launch-development`, T-FB020-US02-01): el
  // backend resuelve el contexto completo (objetivo + Tasks TODO), aquí
  // solo se elige el agente Developer destinatario y se despacha — sin
  // escribir ninguna descripción a mano.
  function renderLaunchDevelopmentForm(storyId) {
    var form = h("div", "jobs-form");
    form.appendChild(h("div", "jobs-form-title", "Lanzar desarrollo"));

    if (backlogSection.developerAgents === null) {
      form.appendChild(h("p", "section-note", "Cargando agentes…"));
      return form;
    }
    if (backlogSection.developerAgentsError) {
      form.appendChild(h("p", "agent-error", backlogSection.developerAgentsError));
      return form;
    }
    if (backlogSection.developerAgents.length === 0) {
      form.appendChild(
        h(
          "p",
          "agent-error",
          "No hay ningún agente Developer lanzado en la sesión activa. Lanza uno desde la pestaña Agentes antes de lanzar el desarrollo."
        )
      );
      return form;
    }

    form.appendChild(h("div", "field-label", "Agente Developer destinatario"));
    var select = document.createElement("select");
    select.className = "clickable launch-select";
    backlogSection.developerAgents.forEach(function (agent, idx) {
      var o = document.createElement("option");
      o.setAttribute("value", String(idx));
      o.textContent = agent.name + " (" + agent.role + ")";
      select.appendChild(o);
    });
    select.selectedIndex = backlogSection.developerAgentIndex;
    select.addEventListener("change", function () {
      backlogSection.developerAgentIndex = parseInt(select.value, 10) || 0;
      renderBacklogBody();
    });
    form.appendChild(select);

    var blockingDeps = findBlockingDependencies();
    var isBlocked = blockingDeps.length > 0;

    var launchBtn = button("Lanzar desarrollo", "backlog-launch");
    if (isBlocked || backlogSection.launchingDevelopment) {
      launchBtn.disabled = true;
      launchBtn.textContent = backlogSection.launchingDevelopment ? "Lanzando…" : "Lanzar desarrollo";
    }
    if (!isBlocked) {
      launchBtn.addEventListener("click", function () {
        dispatchLaunchDevelopment(storyId);
      });
    }
    form.appendChild(launchBtn);

    if (isBlocked) {
      var blockerNames = blockingDeps.map(function (dep) {
        return dep.id + " (" + dep.state + ")";
      }).join(", ");
      form.appendChild(h("p", "agent-error", "Bloqueada por: " + blockerNames));
    }

    if (backlogSection.launchError) {
      // Criterio de aceptación explícito: el motivo REAL del backend
      // (400 sin Tasks TODO, 404 agente inválido) — `buildErrorMessage`
      // ya surge del `detail` verbatim de `BackendRequestError`, nunca
      // un mensaje genérico (mismo patrón que T-FB021-US04-01).
      form.appendChild(h("p", "agent-error", backlogSection.launchError));
    }
    if (backlogSection.launchResult) {
      form.appendChild(
        h(
          "p",
          "section-note",
          "Job despachado (" + backlogSection.launchResult.status + ") — visible en la pestaña Jobs."
        )
      );
    }
    return form;
  }

  // T-FB024-US09-02: historial de ejecuciones de la US expandida.
  function renderUSJobHistory() {
    var box = h("div", "job-detail");
    box.appendChild(h("div", "job-detail-label", "Historial de ejecuciones"));

    if (backlogSection.usJobsError) {
      box.appendChild(h("p", "agent-error", backlogSection.usJobsError));
      return box;
    }
    var jobs = backlogSection.usJobs;
    if (jobs === null) {
      box.appendChild(h("p", "section-note", "Cargando…"));
      return box;
    }
    if (jobs.length === 0) {
      box.appendChild(h("p", "section-note", "Sin ejecuciones registradas."));
      return box;
    }

    jobs.forEach(function (job) {
      var statusColor = job.status === "completed" ? "ok" : job.status === "failed" || job.status === "cancelled" ? "ko" : "run";
      var line = h("div", "job-line job-status-" + statusColor, "[" + job.status + "] " + (job.agent_id || "") + " — " + String(job.description || "").split("\n")[0].slice(0, 80));
      box.appendChild(line);
      if (job.result) {
        box.appendChild(h("div", "job-result", String(job.result).slice(0, 500)));
      }
    });
    return box;
  }

  // T-FB024-US09-03: formulario manual de creacion de Job como accion
  // secundaria en el detalle de la US.
  function renderManualJobForm(usId) {
    var form = h("div", "jobs-form");
    form.appendChild(h("div", "jobs-form-title", "Crear Job manual"));

    // Si el usuario no ha pulsado aun para cargar los agentes, mostrar solo
    // el boton de "Mostrar formulario".
    if (backlogSection.manualJobAgents === null) {
      var showBtn = button("Mostrar formulario de creación manual");
      showBtn.addEventListener("click", function () {
        loadManualJobAgents();
      });
      form.appendChild(showBtn);
      return form;
    }

    if (backlogSection.manualJobAgentsError) {
      form.appendChild(h("p", "agent-error", "No se pudieron cargar los agentes: " + backlogSection.manualJobAgentsError));
      return form;
    }
    if (backlogSection.manualJobAgents.length === 0) {
      form.appendChild(h("p", "section-note", "No hay ningún agente activo en la sesión. Lanza un agente y vuelve a intentarlo."));
      return form;
    }

    form.appendChild(h("div", "field-label", "Agente destinatario"));
    var select = document.createElement("select");
    select.className = "clickable launch-select";
    backlogSection.manualJobAgents.forEach(function (agent, idx) {
      var o = document.createElement("option");
      o.setAttribute("value", String(idx));
      o.textContent = agent.name + " (" + agent.role + ")";
      select.appendChild(o);
    });
    select.selectedIndex = backlogSection.manualJobAgentIndex;
    select.addEventListener("change", function () {
      backlogSection.manualJobAgentIndex = parseInt(select.value, 10) || 0;
      renderBacklogBody();
    });
    form.appendChild(select);

    form.appendChild(h("div", "field-label", "Describe la tarea"));
    var descArea = document.createElement("textarea");
    descArea.className = "clickable";
    descArea.value = backlogSection.manualJobDescription;
    descArea.placeholder = "Describe la tarea que debe realizar el agente.";
    descArea.addEventListener("input", function () {
      backlogSection.manualJobDescription = descArea.value;
    });
    form.appendChild(descArea);

    var submit = button(backlogSection.creatingManualJob ? "Enviando…" : "Crear Job");
    if (backlogSection.creatingManualJob) submit.disabled = true;
    submit.addEventListener("click", function () {
      submitManualJob();
    });
    form.appendChild(submit);

    if (backlogSection.manualJobError) {
      form.appendChild(h("p", "agent-error", backlogSection.manualJobError));
    }
    if (backlogSection.manualJobResult) {
      form.appendChild(
        h("p", "section-note", "Job " + backlogSection.manualJobResult.id + " despachado (" + backlogSection.manualJobResult.status + ").")
      );
    }
    return form;
  }

  function submitManualJob() {
    if (backlogSection.creatingManualJob) return;
    var agent = backlogSection.manualJobAgents[backlogSection.manualJobAgentIndex];
    if (!agent) {
      backlogSection.manualJobError = "Elige un agente destinatario.";
      renderBacklogBody();
      return;
    }
    var description = backlogSection.manualJobDescription.trim();
    if (!description) {
      backlogSection.manualJobError = "Escribe una descripción antes de enviar.";
      renderBacklogBody();
      return;
    }
    backlogSection.creatingManualJob = true;
    backlogSection.manualJobError = null;
    backlogSection.manualJobResult = null;
    renderBacklogBody();

    BackendClient.createAndDispatchJob({ agent_id: agent.id, description: description })
      .then(function (job) {
        backlogSection.creatingManualJob = false;
        backlogSection.manualJobResult = job;
        backlogSection.manualJobDescription = "";
        renderBacklogBody();
        // Recargar el historial de jobs para la US.
        var usId = backlogSection.selectedItemId;
        if (usId) loadJobsForUS(usId);
      })
      .catch(function (error) {
        backlogSection.creatingManualJob = false;
        backlogSection.manualJobError = buildErrorMessage(error);
        renderBacklogBody();
      });
  }

  // Despacho single-flight (criterio de aceptación explícito de
  // T-FB020-US02-02, reutilizado aquí: "un segundo clic mientras la
  // petición anterior sigue en vuelo no despacha un segundo Job") —
  // mismo guard hand-rolled que el resto de acciones de esta web
  // (`launching`/`createInFlight`/`runningScriptId`): primera línea
  // descarta la reentrada, el guard se fija ANTES de la llamada real y
  // se limpia en `.then()`/`.catch()`. Tras el éxito, el Job despachado
  // ya es consultable en la pestaña Jobs (`GET /jobs`) sin ningún cambio
  // adicional aquí — mismo mecanismo que un Job normal.
  function dispatchLaunchDevelopment(storyId) {
    if (backlogSection.launchingDevelopment) return;
    var agent = backlogSection.developerAgents[backlogSection.developerAgentIndex];
    if (!agent) return;
    backlogSection.launchingDevelopment = true;
    backlogSection.launchError = null;
    backlogSection.launchResult = null;
    renderBacklogBody();
    BackendClient.launchDevelopment(storyId, agent.id)
      .then(function (job) {
        backlogSection.launchingDevelopment = false;
        backlogSection.launchResult = job;
        renderBacklogBody();
      })
      .catch(function (error) {
        backlogSection.launchingDevelopment = false;
        backlogSection.launchError = buildErrorMessage(error);
        renderBacklogBody();
      });
  }

  // --------------------------------------------------------------- AGENTES
  // US-FB024-11 (reescritura completa): pantalla unificada — una fila por
  // instancia de cada rol de gobierno (Arquitecto, Developer×N,
  // Auditor-OSS, UX, Tester). Mismos 4 campos (nombre, estado, tiempo desde
  // última orden, modelo) y mismas acciones para todos los roles, sin
  // excepción. Se refresca por polling 3s de GET /agents sin recargar la
  // página. El modelo por defecto de cada rol se carga desde
  // GET /models/preferences (mismo endpoint que la pestaña Modelos).

  // ── entrada de la sección ──────────────────────────────────────────────

  function renderRolesInto(content) {
    rolesSection.bodyWrap = content;
    if (rolesSection.state === null) {
      loadRolesPreferences();
      content.appendChild(h("p", "section-note", "Cargando catálogo de modelos…"));
    } else if (rolesSection.state === "loading") {
      content.appendChild(h("p", "section-note", "Cargando catálogo de modelos…"));
    } else if (rolesSection.state === "unavailable") {
      content.appendChild(h("p", "agent-error", rolesSection.error));
    } else {
      renderRolesBody();
    }
    startRolesPolling();
  }

  // ── carga de modelos por defecto ───────────────────────────────────────

  function loadRolesPreferences() {
    rolesSection.state = "loading";
    BackendClient.getModelsPreferences()
      .then(function (result) {
        rolesSection.state = "ready";
        rolesSection.models = result.models || [];
        rolesSection.defaults = result.defaults || {};
        renderRolesBody();
      })
      .catch(function (error) {
        rolesSection.state = "unavailable";
        rolesSection.error = buildErrorMessage(error);
        renderRolesBody();
      });
  }

  // ── polling de agentes (3s) ────────────────────────────────────────────

  function startRolesPolling() {
    if (rolesSection.pollTimer) return;
    rolesSection.pollTimer = setInterval(function () {
      if (state.section !== "roles") { stopRolesPolling(); return; }
      pollRolesAgents();
    }, POLL_INTERVAL_MILLIS);
    pollRolesAgents();
  }

  function stopRolesPolling() {
    if (rolesSection.pollTimer) { clearInterval(rolesSection.pollTimer); rolesSection.pollTimer = null; }
  }

  async function pollRolesAgents() {
    try {
      var agents = await BackendClient.getAgents();
      rolesSection.agentsList = agents;
      rolesSection.stale = false;
      rolesSection.listError = null;
    } catch (error) {
      if (rolesSection.agentsList !== null) {
        rolesSection.stale = true;
      } else {
        rolesSection.listError = buildErrorMessage(error);
        rolesSection.stale = false;
      }
    }
    if (state.section === "roles") renderRolesBody();
  }

  // ── renderizado principal ──────────────────────────────────────────────

  function renderRolesBody() {
    var wrap = rolesSection.bodyWrap;
    if (!wrap) return;
    wrap.textContent = "";
    if (rolesSection.state !== "ready") return;

    if (rolesSection.actionMessage) {
      wrap.appendChild(h("p", "agent-message", rolesSection.actionMessage));
    }
    if (rolesSection.modelChangeError) {
      wrap.appendChild(h("p", "agent-error", rolesSection.modelChangeError));
    }
    if (rolesSection.reviewBlockedError) {
      wrap.appendChild(h("p", "agent-error", rolesSection.reviewBlockedError));
    }
    if (rolesSection.stale) {
      wrap.appendChild(h("p", "stale-note", "Puede que esta lista esté desactualizada (sin conexión con el backend)."));
    }
    if (rolesSection.listError && rolesSection.agentsList === null) {
      wrap.appendChild(h("p", "agent-error", rolesSection.listError));
    }

    // Barra de acciones global (fuera de las tarjetas de agente): mensajes
    // de error de revisión de bloqueo y cambio de modelo.
    if (rolesSection.reviewBlockedError) {
      wrap.appendChild(h("p", "agent-error", rolesSection.reviewBlockedError));
    }

    var rows = buildUnifiedRows();
    rows.forEach(function (row) { renderUnifiedRow(wrap, row); });

    if (rolesSection.detalleAgent) { renderDetalleFallbackModal(wrap); }
  }

  // ── construcción de filas unificadas ────────────────────────────────────

  function buildUnifiedRows() {
    var agents = rolesSection.agentsList || [];
    var rows = [];

    // Arquitecto: la barra superior (pollArquitecto) es la única fuente de verdad.
    // Se reutiliza su estado para que la barra y esta pantalla muestren siempre
    // exactamente lo mismo, sin desincronización.
    var arqAgent = arquitectoState.agent;
    if (arqAgent) {
      rows.push(arqAgent);
    } else {
      // Sintético "detenido" (no "unregistered"): el rol arquitecto SÍ está
      // registrado en el backend, solo no tiene instancia lanzada todavía.
      // Así su botón Lanzar queda habilitado y la pantalla Agentes es el
      // único punto para lanzar/detener al Arquitecto (la barra superior ya
      // no tiene botón de acción).
      rows.push(syntheticRow("arquitecto", "stopped"));
    }

    // Developer: todas las instancias (vivas y detenidas) desde GET /agents.
    var devAgents = agents.filter(function (a) { return a.role === "developer"; });
    if (devAgents.length === 0) {
      // Sin ninguna instancia (proyecto nuevo o backend reiniciado): fila
      // sintética "detenida" para poder lanzar la primera instancia. El rol
      // developer sí está registrado en el backend, a diferencia de
      // auditor_oss/ux/tester, así que su botón Lanzar queda habilitado.
      rows.push(syntheticRow("developer", "stopped"));
    } else {
      devAgents.forEach(function (a) { rows.push(a); });
    }

    // Roles aún no registrados en el backend: una fila sintética cada uno.
    rows.push(syntheticRow("auditor_oss"));
    rows.push(syntheticRow("ux"));
    rows.push(syntheticRow("tester"));

    return rows;
  }

  function syntheticRow(role, status) {
    var nameMap = { arquitecto: "Arquitecto", developer: "Developer", auditor_oss: "Auditor-OSS", ux: "UX", tester: "Tester" };
    return {
      _synthetic: true,
      id: null,
      name: nameMap[role] || role,
      role: role,
      status: status || "unregistered",
      runtime_id: null,
      model: null,
      last_command_at: null,
    };
  }

  // ── renderizado de UNA fila unificada ───────────────────────────────────

  function renderUnifiedRow(wrap, agent) {
    var isWorking = agent.status === "working";
    var isStopped = agent.status === "stopped";
    var isUnregistered = agent.status === "unregistered";
    var isLive = agent.id && !isStopped && !isUnregistered;
    var isArquitecto = agent.role === "arquitecto";
    var isSyntheticArquitecto = agent._synthetic && isArquitecto;

    var card = h("div", "agent-card");

    // Bloque de texto: nombre, estado, tiempo desde ultima orden, modelo
    var info = h("div", "agent-info");

    // 1. Nombre
    info.appendChild(h("div", "agent-name", agent.name));

    // 2. Estado (texto claro, no crudo)
    var statusLabel;
    if (isUnregistered) {
      statusLabel = "no disponible";
    } else if (isStopped) {
      statusLabel = "detenido";
    } else if (isWorking) {
      statusLabel = "trabajando";
    } else if (agent.status === "idle") {
      statusLabel = "activo";
    } else {
      statusLabel = agent.status;
    }
    var statusRow = h("div", "agent-status-row");
    var dot = h("span", "status-dot");
    dot.style.backgroundColor = agentStatusColor(agent.status);
    statusRow.appendChild(dot);
    statusRow.appendChild(h("span", "status-text", "Estado: " + statusLabel));
    info.appendChild(statusRow);

    // 3. Tiempo desde la última orden
    info.appendChild(h("div", "agent-model", formatLastCommand(agent.last_command_at)));

    // 4. Modelo actual
    var modelLabel;
    if (agent.model) {
      modelLabel = agent.model;
    } else if (isLive) {
      modelLabel = runtimeDisplayName(agent.runtime_id);
    } else if (isSyntheticArquitecto) {
      modelLabel = rolesSection.defaults.arquitecto || "sin modelo";
    } else {
      modelLabel = "sin modelo";
    }
    info.appendChild(h("div", "agent-model", "Modelo: " + modelLabel));

    card.appendChild(info);

    // --- ACCIONES (bloque derecho, en la misma fila que agent-info) ---
    var actions = h("div", "agent-actions");

    // (a) Cambiar modelo
    actions.appendChild(renderCambiarModeloBtn(agent));

    // (b) Lanzar / Detener (un único botón que alterna)
    actions.appendChild(renderLanzarDetenerBtn(agent));

    // (c) Copiar comando de conexión
    actions.appendChild(renderCopiarComandoBtn(agent));

    // (d) Revisar si está bloqueado (solo si está trabajando)
    if (isWorking) {
      actions.appendChild(renderRevisarBloqueadoBtn(agent));
    }

    card.appendChild(actions);

    // Selector de modelo inline para agentes lanzados (fila completa debajo)
    if (rolesSection.modelSelectAgentId === agent.id && rolesSection.modelOptions) {
      var selectWrap = h("div", "agent-model-select-row");
      card.appendChild(selectWrap);
      renderModelSelectInline(selectWrap, agent);
    }

    // Editor inline de modelo por defecto (fila completa debajo)
    if (rolesSection.editingRole === agent.role) {
      var editorWrap = h("div", "agent-editor-row");
      card.appendChild(editorWrap);
      renderDefaultModelEditorInline(editorWrap, agent.role);
    }

    wrap.appendChild(card);
  }

  // ── función auxiliar: tiempo desde la última orden ─────────────────────

  function formatLastCommand(lastCommandAt) {
    if (!lastCommandAt) return "Tiempo desde última orden: sin dato";
    try {
      var then = new Date(lastCommandAt).getTime();
      var now = Date.now();
      var diffSec = Math.floor((now - then) / 1000);
      if (diffSec < 0) return "Tiempo desde última orden: sin dato";
      if (diffSec < 60) return "Tiempo desde última orden: ahora";
      var mins = Math.floor(diffSec / 60);
      if (mins === 1) return "Tiempo desde última orden: hace 1 min";
      if (mins < 60) return "Tiempo desde última orden: hace " + mins + " min";
      var hours = Math.floor(mins / 60);
      if (hours === 1) return "Tiempo desde última orden: hace 1 h";
      return "Tiempo desde última orden: hace " + hours + " h";
    } catch (_e) {
      return "Tiempo desde última orden: sin dato";
    }
  }

  // ── botón Cambiar modelo ────────────────────────────────────────────────

  function renderCambiarModeloBtn(agent) {
    var isLive = agent.id && agent.status !== "stopped" && agent.status !== "unregistered";

    var isChanging = agent.id && rolesSection.modelChangeAgentId === agent.id;
    var isPending = agent.id && rolesSection.modelChangePending && rolesSection.modelChangePending.agent_id === agent.id;
    var label;
    if (isChanging) {
      label = "Cambiando modelo…";
    } else if (isPending) {
      label = "Confirmar: " + rolesSection.modelChangePending.model;
    } else {
      label = "Cambiar modelo";
    }
    var b = button(label, "agent-model-change");
    if (isChanging) b.disabled = true;
    if (isLive) {
      b.addEventListener("click", function () { requestModelChangeLive(agent); });
    } else {
      b.addEventListener("click", function () {
        rolesSection.editingRole = agent.role;
        rolesSection.modelIndex = 0;
        rolesSection.saveError = null;
        renderRolesBody();
      });
    }
    return b;
  }

  function requestModelChangeLive(agent) {
    if (rolesSection.modelChangeAgentId) return;
    if (!rolesSection.modelChangePending || rolesSection.modelChangePending.agent_id !== agent.id) {
      rolesSection.modelChangePending = null;
      rolesSection.modelChangeError = null;
      rolesSection.modelChangeAgentId = agent.id;
      renderRolesBody();
      BackendClient.getAgentAvailableModels(agent.id)
        .then(function (result) {
          rolesSection.modelChangeAgentId = null;
          if (!result.supports_model) {
            rolesSection.modelChangeError = "Este agente no admite cambio de modelo.";
            renderRolesBody();
            return;
          }
          var models = result.models;
          if (!models || models.length === 0) {
            rolesSection.modelChangeError = "No hay modelos disponibles para este agente.";
            renderRolesBody();
            return;
          }
          var chosen;
          if (models.length === 1) {
            chosen = models[0].id;
          } else {
            rolesSection.modelOptions = models;
            rolesSection.modelSelectAgentId = agent.id;
            renderRolesBody();
            return;
          }
          rolesSection.modelChangePending = { agent_id: agent.id, model: chosen };
          rolesSection.modelChangeError = null;
          renderRolesBody();
        })
        .catch(function (error) {
          rolesSection.modelChangeAgentId = null;
          rolesSection.modelChangeError = buildErrorMessage(error);
          renderRolesBody();
        });
      return;
    }
    executeModelChangeLive(agent, rolesSection.modelChangePending.model);
  }

  function executeModelChangeLive(agent, model) {
    if (rolesSection.modelChangeAgentId) return;
    rolesSection.modelChangePending = null;
    rolesSection.modelChangeAgentId = agent.id;
    rolesSection.modelChangeError = null;
    renderRolesBody();
    BackendClient.setAgentModel(agent.id, model)
      .then(function (result) {
        rolesSection.modelChangeAgentId = null;
        rolesSection.modelOptions = null;
        if (result.changed) {
          rolesSection.actionMessage = "Modelo de " + agent.name + " cambiado a " + model + ".";
        } else {
          rolesSection.modelChangeError = "No se pudo cambiar el modelo. El agente puede no estar respondiendo.";
        }
        renderRolesBody();
        return pollRolesAgents();
      })
      .catch(function (error) {
        rolesSection.modelChangeAgentId = null;
        rolesSection.modelOptions = null;
        rolesSection.modelChangeError = buildErrorMessage(error);
        renderRolesBody();
      });
  }

  // ── botón Lanzar / Detener ──────────────────────────────────────────────

  function renderLanzarDetenerBtn(agent) {
    var isLive = agent.id && agent.status !== "stopped" && agent.status !== "unregistered";
    var isUnregistered = agent.status === "unregistered";
    var isStopped = agent.status === "stopped";
    var showDetener = isLive;
    var showLanzar = !isLive;

    // Arquitecto: si está activo (idle/working), mostrar "Detener" usando
    // stopArquitecto con confirmación (mismo flujo que antes usaba la barra
    // superior, ahora único punto de control desde la pestaña Agentes).
    if (agent.role === "arquitecto") {
      if (showDetener) {
        if (arquitectoState.stopPending) {
          var stopConfirm = button("Confirmar detener", "arq-btn-stop-confirm");
          stopConfirm.addEventListener("click", stopArquitecto);
          return stopConfirm;
        }
        var stopBtn = button("Detener", "arq-btn-stop");
        stopBtn.addEventListener("click", stopArquitecto);
        return stopBtn;
      }
      if (arquitectoState.launchPending) {
        var lp = button("Lanzando…"); lp.disabled = true; return lp;
      }
      // ¿es sintético (no está lanzado) o stopped?
      var launchBtn = button(isUnregistered ? "Lanzar" : "Lanzar");
      if (isUnregistered || !arquitectoState.defaultModel) {
        launchBtn.disabled = true;
        if (isUnregistered) launchBtn.title = "rol no disponible todavía: pendiente de registrar en el backend";
        else launchBtn.title = "Asigna un modelo para Arquitecto en la pestaña Modelos";
      } else {
        launchBtn.addEventListener("click", launchArquitecto);
      }
      return launchBtn;
    }

    // Developer: Detener directo (con confirmación inline si activo) o Lanzar.
    if (showDetener) {
      var devStop = button("Detener", "agent-stop");
      devStop.addEventListener("click", function () { stopDevAgent(agent); });
      return devStop;
    }

    // Stopped o unregistered
    var devLaunch = button("Lanzar");
    if (isUnregistered) {
      devLaunch.disabled = true;
      devLaunch.title = "rol no disponible todavía: pendiente de registrar en el backend";
    } else if (isStopped) {
      devLaunch.addEventListener("click", function () { launchStoppedDev(agent); });
    }
    return devLaunch;
  }

  function stopDevAgent(agent) {
    if (!agent.id) return;
    BackendClient.stopAgent(agent.id)
      .then(function () {
        rolesSection.actionMessage = agent.name + " detenido.";
        return pollRolesAgents();
      })
      .catch(function (error) {
        rolesSection.actionMessage = buildErrorMessage(error);
        renderRolesBody();
      });
  }

  function launchStoppedDev(agent) {
    var payload = { role: "developer" };
    if (agent.model && agent.model !== "claude-code") {
      payload.model_id = agent.model;
    } else if (agent.runtime_id) {
      payload.runtime_type = agent.runtime_id;
    } else {
      payload.runtime_type = "opencode";
    }
    BackendClient.launchAgent(payload)
      .then(function (result) {
        rolesSection.actionMessage = launchFeedbackMessageFor(result);
        return pollRolesAgents();
      })
      .catch(function (error) {
        rolesSection.actionMessage = buildErrorMessage(error);
        renderRolesBody();
      });
  }

  // ── botón Copiar comando de conexión ────────────────────────────────────

  function renderCopiarComandoBtn(agent) {
    var isLive = agent.id && agent.status !== "stopped" && agent.status !== "unregistered";
    var canCopy = isLive && agent.runtime_id;

    var btn = button(rolesSection.detalleCopied && rolesSection.detalleAgent === agent ? "Copiado ✓" : "Copiar comando de conexión");
    btn.disabled = !canCopy;
    if (!canCopy) {
      btn.title = "no disponible: el agente no tiene sesión activa";
      return btn;
    }
    var comando = "tmux -L factory-brain attach -t " + agent.runtime_id + "-" + agent.id;
    btn.addEventListener("click", function () {
      if (rolesSection.detalleCopied) return;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(comando).then(function () {
          rolesSection.detalleAgent = agent;
          rolesSection.detalleCopied = true;
          renderRolesBody();
          setTimeout(function () {
            if (rolesSection.detalleAgent === agent) { rolesSection.detalleAgent = null; rolesSection.detalleCopied = false; }
            if (state.section === "roles") renderRolesBody();
          }, 2500);
        }).catch(function () {
          // Fallback: modal con texto ya seleccionado para copiar a mano.
          rolesSection.detalleAgent = agent;
          rolesSection.detalleCopied = false;
          renderRolesBody();
        });
      } else {
        rolesSection.detalleAgent = agent;
        rolesSection.detalleCopied = false;
        renderRolesBody();
      }
    });
    return btn;
  }

  // Modal fallback de copia manual cuando clipboard.writeText falla.
  function renderDetalleFallbackModal(wrap) {
    var agent = rolesSection.detalleAgent;
    if (!agent) return;
    var comando = "tmux -L factory-brain attach -t " + agent.runtime_id + "-" + agent.id;

    var overlay = h("div", "modal-overlay");
    var box = h("div", "modal");
    box.appendChild(h("h3", null, "Copiar comando de conexión — " + agent.name));

    var inst = h("p", "section-note", "No se pudo copiar automáticamente al portapapeles. El comando está seleccionado: pulsa Ctrl+C o Cmd+C para copiarlo manualmente.");
    box.appendChild(inst);

    var ta = document.createElement("textarea");
    ta.readOnly = true;
    ta.className = "clickable";
    ta.value = comando;
    ta.style.width = "100%";
    ta.style.minHeight = "60px";
    ta.style.resize = "vertical";
    box.appendChild(ta);

    var closeBtn = button("Cerrar");
    closeBtn.addEventListener("click", function () {
      rolesSection.detalleAgent = null;
      rolesSection.detalleCopied = false;
      renderRolesBody();
    });
    box.appendChild(closeBtn);

    overlay.appendChild(box);
    wrap.appendChild(overlay);
    // Autoseleccionar el textarea una vez montado el DOM.
    setTimeout(function () { ta.select(); ta.focus(); }, 10);
  }

  // ── botón Revisar si está bloqueado ─────────────────────────────────────

  function renderRevisarBloqueadoBtn(agent) {
    var arqLive = arquitectoState.agent && arquitectoState.agent.status !== "stopped";
    var isReviewing = rolesSection.reviewingBlockedAgentId === agent.id;
    var label = isReviewing ? "Revisando…" : "Revisar si está bloqueado";
    var btn = button(label, "agent-model-change");
    btn.disabled = !arqLive || isReviewing;
    if (isReviewing) btn.disabled = true;
    if (!arqLive && !isReviewing) {
      btn.title = "Lanza el Arquitecto primero para poder pedirle una revisión";
    }
    btn.addEventListener("click", function () {
      if (isReviewing || !arqLive) return;
      requestReviewBlocked(agent);
    });
    return btn;
  }

  function requestReviewBlocked(agent) {
    if (rolesSection.reviewingBlockedAgentId) return;
    var arq = arquitectoState.agent;
    if (!arq) return;

    rolesSection.reviewingBlockedAgentId = agent.id;
    rolesSection.reviewBlockedError = null;
    renderRolesBody();

    // REGLA DURA (00-gobierno/ARQUITECTO.md, "Texto plano al mandar
    // instrucciones a un agente"): la descripción del Job NUNCA puede
    // contener backticks ni caracteres especiales de shell (incidente
    // real confirmado 2026-08-09). Se usa texto plano sin marcar.
    var description =
      "Revisa si el agente " + agent.name + " (rol " + agent.role + ", id " + agent.id + ") " +
      "esta bloqueado. Revisa su pane con GET /agents/" + agent.id + "/pane y emite un veredicto " +
      "estructurado indicando si esta atascado (y por que) o progresando con normalidad.";

    BackendClient.createAndDispatchJob({ agent_id: arq.id, description: description })
      .then(function (job) {
        rolesSection.reviewingBlockedAgentId = null;
        rolesSection.actionMessage =
          "Revisión de " + agent.name + " enviada al Arquitecto (Job " + job.id + ", estado: " + job.status + ").";
        renderRolesBody();
        return pollRolesAgents();
      })
      .catch(function (error) {
        rolesSection.reviewingBlockedAgentId = null;
        rolesSection.reviewBlockedError = buildErrorMessage(error);
        renderRolesBody();
      });
  }

  // ── editor inline de modelo por defecto (solo Arquitecto sintético) ─────

  function renderModelSelectInline(wrap, agent) {
    var models = rolesSection.modelOptions;
    if (!models || models.length === 0) return;

    var sel = document.createElement("select");
    sel.className = "clickable launch-select";
    sel.style.margin = "6px 0";
    models.forEach(function (m) {
      var o = document.createElement("option");
      o.value = m.id;
      o.textContent = m.name + " (" + m.id + ")";
      sel.appendChild(o);
    });
    wrap.appendChild(sel);

    var actionsRow = h("div", "agent-actions");

    var confirmBtn = button("Confirmar cambio");
    confirmBtn.addEventListener("click", function () {
      var selectedModel = sel.value;
      rolesSection.modelSelectAgentId = null;
      rolesSection.modelOptions = null;
      rolesSection.modelChangePending = { agent_id: agent.id, model: selectedModel };
      rolesSection.modelChangeError = null;
      renderRolesBody();
    });
    actionsRow.appendChild(confirmBtn);

    var cancelBtn = button("Cancelar", "agent-model-change");
    cancelBtn.addEventListener("click", function () {
      rolesSection.modelSelectAgentId = null;
      rolesSection.modelOptions = null;
      rolesSection.modelChangePending = null;
      renderRolesBody();
    });
    actionsRow.appendChild(cancelBtn);

    wrap.appendChild(actionsRow);
  }

  function renderDefaultModelEditorInline(wrap, role) {
    var enabledModels = rolesSection.models.filter(function (m) { return m.enabled; });
    var defaultModel = rolesSection.defaults[role];

    var sel = document.createElement("select");
    sel.className = "clickable launch-select";
    sel.style.margin = "6px 0";
    var noneOpt = document.createElement("option");
    noneOpt.value = "";
    noneOpt.textContent = "— sin default —";
    sel.appendChild(noneOpt);
    enabledModels.forEach(function (model, idx) {
      var o = document.createElement("option");
      o.value = String(idx);
      o.textContent = model.name + " (" + model.runtime + ")";
      if (defaultModel === model.id) o.selected = true;
      sel.appendChild(o);
    });
    sel.addEventListener("change", function () {
      rolesSection.modelIndex = parseInt(sel.value, 10) || 0;
    });
    wrap.appendChild(sel);

    var actionsRow = h("div", "agent-actions");

    var saveBtn = button(rolesSection.saving ? "Guardando…" : "Guardar modelo");
    if (rolesSection.saving) saveBtn.disabled = true;
    saveBtn.addEventListener("click", function () { saveRoleModel(role); });
    actionsRow.appendChild(saveBtn);

    var cancelBtn = button("Cancelar", "agent-model-change");
    cancelBtn.addEventListener("click", function () {
      rolesSection.editingRole = null;
      rolesSection.modelIndex = 0;
      rolesSection.saveError = null;
      renderRolesBody();
    });
    actionsRow.appendChild(cancelBtn);

    wrap.appendChild(actionsRow);

    if (rolesSection.saveError) {
      wrap.appendChild(h("p", "agent-error", rolesSection.saveError));
    }
  }

  function saveRoleModel(role) {
    if (rolesSection.saving) return;
    var enabledModels = rolesSection.models.filter(function (m) { return m.enabled; });
    var modelId;
    if (rolesSection.modelIndex >= 0 && rolesSection.modelIndex < enabledModels.length) {
      modelId = enabledModels[rolesSection.modelIndex].id;
    } else {
      modelId = undefined;
    }

    var newDefaults = {};
    Object.keys(rolesSection.defaults).forEach(function (r) {
      newDefaults[r] = rolesSection.defaults[r];
    });
    if (modelId) {
      newDefaults[role] = modelId;
    } else {
      delete newDefaults[role];
    }

    rolesSection.saving = true;
    rolesSection.saveError = null;
    renderRolesBody();

    BackendClient.updateModelsPreferences({ default_model_by_role: newDefaults })
      .then(function (result) {
        rolesSection.saving = false;
        rolesSection.editingRole = null;
        rolesSection.defaults = result.default_model_by_role || {};
        // Si se cambió el default del Arquitecto, sincronizar la barra
        // superior y el botón "Lanzar" para que reflejen el cambio
        // inmediatamente (sin esperar al siguiente ciclo de polling).
        if (role === "arquitecto") {
          arquitectoState.defaultModel = rolesSection.defaults.arquitecto || null;
          renderArquitectoBar();
        }
        renderRolesBody();
      })
      .catch(function (error) {
        rolesSection.saving = false;
        rolesSection.saveError = buildErrorMessage(error);
        renderRolesBody();
      });
  }

  // ----------------------------------------------- seccion MODELOS (US10-02)
  function renderModelsInto(content) {
    modelsSection.bodyWrap = content;
    if (modelsSection.state === null) {
      loadModelsPreferences();
      content.appendChild(h("p", "section-note", "Cargando catálogo de modelos…"));
      return;
    }
    if (modelsSection.state === "loading") {
      content.appendChild(h("p", "section-note", "Cargando catálogo de modelos…"));
      return;
    }
    if (modelsSection.state === "unavailable") {
      content.appendChild(h("p", "agent-error", modelsSection.error));
      return;
    }
    renderModelsBody();
  }

  function loadModelsPreferences() {
    modelsSection.state = "loading";
    BackendClient.getModelsPreferences()
      .then(function (result) {
        modelsSection.state = "ready";
        modelsSection.models = result.models || [];
        modelsSection.defaults = result.defaults || {};
        modelsSection.dirty = false;
        renderModelsBody();
      })
      .catch(function (error) {
        modelsSection.state = "unavailable";
        modelsSection.error = buildErrorMessage(error);
        renderModelsBody();
      });
  }

  function renderModelsBody() {
    var wrap = modelsSection.bodyWrap;
    if (!wrap) return;
    wrap.textContent = "";

    if (modelsSection.state !== "ready") return;

    var form = h("div", "jobs-form");

    // Tabla de modelos con checkbox de habilitado.
    form.appendChild(h("div", "jobs-form-title", "Modelos disponibles"));
    if (modelsSection.models.length === 0) {
      form.appendChild(h("p", "section-note", "El catálogo de modelos está vacío."));
    } else {
      modelsSection.models.forEach(function (model, idx) {
        var row = h("div", "model-row");
        var label = document.createElement("label");
        label.className = "model-checkbox-label";
        var cb = document.createElement("input");
        cb.type = "checkbox";
        cb.checked = model.enabled;
        cb.addEventListener("change", function () {
          modelsSection.models[idx].enabled = cb.checked;
          modelsSection.dirty = true;
          renderModelsBody();
        });
        label.appendChild(cb);
        label.appendChild(document.createTextNode(" " + model.name + " (" + model.runtime + ")"));
        row.appendChild(label);
        form.appendChild(row);
      });
    }

    // Defaults por rol.
    form.appendChild(h("div", "jobs-form-title", "Modelo por defecto (opcional)"));
    var roles = ["arquitecto", "developer", "tester"];
    var enabledModels = modelsSection.models.filter(function (m) { return m.enabled; });
    roles.forEach(function (role) {
      var row = h("div", "model-row");
      var label = h("span", "model-role-label", roleCaption(role) + ": ");
      var select = document.createElement("select");
      select.className = "clickable";
      var opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "— sin default —";
      select.appendChild(opt);
      enabledModels.forEach(function (model) {
        var o = document.createElement("option");
        o.value = model.id;
        o.textContent = model.name;
        if (modelsSection.defaults[role] === model.id) {
          o.selected = true;
        }
        select.appendChild(o);
      });
      select.addEventListener("change", function () {
        modelsSection.defaults[role] = select.value || undefined;
        if (!select.value) delete modelsSection.defaults[role];
        modelsSection.dirty = true;
        renderModelsBody();
      });
      row.appendChild(label);
      row.appendChild(select);
      form.appendChild(row);
    });

    // Botón de guardar.
    var saveBtn = button("Guardar preferencias");
    if (modelsSection.saving) {
      saveBtn.disabled = true;
      saveBtn.textContent = "Guardando…";
    }
    saveBtn.addEventListener("click", saveModelsPreferences);
    form.appendChild(saveBtn);

    if (modelsSection.saveError) {
      form.appendChild(h("p", "agent-error", modelsSection.saveError));
    }

    if (!modelsSection.dirty && !modelsSection.saving) {
      form.appendChild(h("p", "section-note", "Sin cambios pendientes."));
    }

    wrap.appendChild(form);
  }

  function roleCaption(role) {
    return role.charAt(0).toUpperCase() + role.slice(1);
  }

  function saveModelsPreferences() {
    if (modelsSection.saving) return;
    modelsSection.saving = true;
    modelsSection.saveError = null;
    renderModelsBody();

    var payload = {
      enabled_model_ids: modelsSection.models
        .filter(function (m) { return !m.enabled; })
        .length === 0
        ? []
        : modelsSection.models
            .filter(function (m) { return m.enabled; })
            .map(function (m) { return m.id; }),
      default_model_by_role: modelsSection.defaults,
    };

    BackendClient.updateModelsPreferences(payload)
      .then(function (result) {
        modelsSection.saving = false;
        modelsSection.dirty = false;
        modelsSection.defaults = result.default_model_by_role || {};
        renderModelsBody();
      })
      .catch(function (error) {
        modelsSection.saving = false;
        modelsSection.saveError = buildErrorMessage(error);
        renderModelsBody();
      });
  }

  // ------------------------------------------------------------- FB-025
  // Acciones transversales de proyecto (US-FB025-01 a US-FB025-07):
  // botones directos que despachan Jobs al Arquitecto o ejecutan scripts
  // deterministas, sin pasar por el modo conversacional del Arquitecto.

  var ACCIONES = [
    { id: "documentar", label: "Documentar todo", desc: "Revisa que la documentación en 01-documentacion/ esté al día con el código real. Propone cambios, no escribe directamente." },
    { id: "analizar-arquitectura", label: "Analizar arquitectura", desc: "Análisis de arquitectura con evidencia de código real. Informe para decisión humana." },
    { id: "sugerir-ideas", label: "Sugerir ideas para el backlog", desc: "Propone ideas candidatas de Epics/User Stories a partir del estado actual del proyecto. No escribe a 02-backlog/." },
    { id: "testear", label: "Testear todo", desc: "Ejecuta la suite completa de tests del proyecto. Resultado determinista (pasa/falla), sin corrección automática." },
    { id: "auditar-ux", label: "Auditar UX de la web", desc: "Lanza una auditoría UX headless de la interfaz web con opencode run --auto (sin tmux). Sigue el protocolo de 00-gobierno/UX.md." },
    { id: "indexar", label: "Indexar proyecto (Scribe)", desc: "Genera un índice temático del proyecto usando el modelo local de Ollama. Sin gastar tokens de los agentes principales." },
  ];

  function renderAccionesInto(content) {
    accionesSection.bodyWrap = content;
    content.appendChild(h("p", "section-note", "Cada botón despacha la acción directamente, sin pasar por el modo conversacional del Arquitecto."));

    ACCIONES.forEach(function (accion) {
      var card = h("div", "accion-card");
      var header = h("div", "accion-card-header");
      header.appendChild(h("span", "accion-label", accion.label));
      card.appendChild(header);
      card.appendChild(h("div", "accion-desc", accion.desc));

      var isRunning = accionesSection.inFlight === accion.id;
      var runBtn = button(isRunning ? "Ejecutando…" : "Ejecutar", "accion-run");
      if (accionesSection.inFlight !== null) runBtn.disabled = true;
      runBtn.addEventListener("click", function () {
        dispatchAccion(accion.id);
      });
      card.appendChild(runBtn);
      content.appendChild(card);
    });

    if (accionesSection.result && accionesSection.inFlight === null) {
      renderAccionResult(content);
    }
    if (accionesSection.error) {
      var errBox = h("div", "accion-result");
      errBox.appendChild(h("p", "agent-error", accionesSection.error));
      content.appendChild(errBox);
    }
  }

  function dispatchAccion(actionId) {
    if (accionesSection.inFlight) return;
    accionesSection.inFlight = actionId;
    accionesSection.error = null;
    accionesSection.result = null;
    renderAccionesBody();

    BackendClient.runProjectAction(actionId)
      .then(function (result) {
        accionesSection.inFlight = null;
        accionesSection.result = result;
        renderAccionesBody();
      })
      .catch(function (error) {
        accionesSection.inFlight = null;
        accionesSection.error = buildErrorMessage(error);
        renderAccionesBody();
      });
  }

  function renderAccionesBody() {
    var wrap = accionesSection.bodyWrap;
    if (!wrap || state.section !== "acciones") return;
    wrap.textContent = "";
    ACCIONES.forEach(function (accion) {
      var card = h("div", "accion-card");
      var header = h("div", "accion-card-header");
      header.appendChild(h("span", "accion-label", accion.label));
      card.appendChild(header);
      card.appendChild(h("div", "accion-desc", accion.desc));

      var isRunning = accionesSection.inFlight === accion.id;
      var runBtn = button(isRunning ? "Ejecutando…" : "Ejecutar", "accion-run");
      if (accionesSection.inFlight !== null) runBtn.disabled = true;
      runBtn.addEventListener("click", function () {
        dispatchAccion(accion.id);
      });
      card.appendChild(runBtn);
      wrap.appendChild(card);
    });
    if (accionesSection.error) {
      var errBox = h("div", "accion-result");
      errBox.appendChild(h("p", "agent-error", accionesSection.error));
      wrap.appendChild(errBox);
    }
    if (accionesSection.result) {
      renderAccionResult(wrap);
    }
  }

  function renderAccionResult(wrap) {
    var r = accionesSection.result;
    if (!r) return;
    var box = h("div", "accion-result");
    if (r.action === "testear") {
      box.appendChild(h("h4", "accion-result-title", "Resultado de testear todo"));
      var exitBadge = r.success ? h("span", "accion-exit-success", "PASA") : h("span", "accion-exit-fail", "FALLA");
      box.appendChild(h("p", null, exitBadge));
      if (r.exit_code !== null && r.exit_code !== undefined) {
        box.appendChild(h("p", null, "Exit code: " + r.exit_code));
      }
      if (r.stdout) {
        var pre = h("pre", "accion-stdout", r.stdout);
        box.appendChild(pre);
      }
      if (r.stderr) {
        var preErr = h("pre", "accion-stderr", r.stderr);
        box.appendChild(h("p", "accion-stderr-label", "Stderr:"));
        box.appendChild(preErr);
      }
      if (r.error_message) {
        box.appendChild(h("p", "agent-error", r.error_message));
      }
    } else {
      var labelMap = { documentar: "Documentar todo", "analizar-arquitectura": "Analizar arquitectura", "sugerir-ideas": "Sugerir ideas para el backlog", "auditar-ux": "Auditar UX de la web", "indexar": "Indexar proyecto (Scribe)" };
      box.appendChild(h("h4", "accion-result-title", "Resultado de " + (labelMap[r.action] || r.action)));
      box.appendChild(h("p", null, "Job: " + (r.job_id || "—") + " | Estado: " + (r.status || "—")));
      if (r.result) {
        var pre = h("pre", "accion-stdout", r.result);
        box.appendChild(pre);
      }
    }
    wrap.appendChild(box);
  }

  async function checkConnectivity() {
    clearRoot();
    ROOT.textContent = "Comprobando conectividad...";
    try {
      await BackendClient.getHealth();
      state.connected = true;
      await loadContext();
    } catch (error) {
      state.connected = false;
      state.contextError = buildErrorMessage(error);
      render();
    }
  }

  async function loadContext() {
    try {
      var active = await BackendClient.getProject();
      var projects = await BackendClient.getProjects();
      state.projects = projects;
      state.active = active;
      state.contextError = null;
      loadPendingBacklogCount();
      render();
    } catch (error) {
      state.contextError = buildErrorMessage(error);
      render();
    }
  }

  function loadPendingBacklogCount() {
    BackendClient.getBacklog()
      .then(function (report) {
        var count = 0;
        (report.by_epic || []).forEach(function (epic) {
          count += (epic.user_stories && epic.user_stories.TODO || 0)
                 + (epic.tasks && epic.tasks.TODO || 0);
        });
        state.pendingBacklogCount = count;
        render();
      })
      .catch(function () {
        state.pendingBacklogCount = 0;
      });
  }

  function buildErrorMessage(error) {
    if (error && error.message) return error.message;
    return String(error);
  }

  // -------------------------------------------------- abrir selector (US02-02)
  function openProjectPicker(reason) {
    state.pickerReason = reason || "initial";
    state.showPicker = true;
    render();
  }

  // -------------------------------------------------- seleccionar proyecto
  function requestSelectProject(project) {
    state.pendingSelection = null;
    BackendClient.getAgents()
      .then(function (agents) {
        var stillRunning = (agents || []).filter(function (a) {
          return a.status !== "stopped";
        }).length;
        if (stillRunning > 0) {
          // El aviso se dibuja sobre la vista operativa (contexto resuelto),
          // por eso se cierra el selector antes de mostrar el modal.
          state.showPicker = false;
          state.pendingSelection = { project: project, activeAgentsCount: stillRunning };
          render();
        } else {
          selectProject(project);
        }
      })
      .catch(function (error) {
        showError(buildErrorMessage(error), loadContext);
      });
  }

  function confirmPendingSelection() {
    var pending = state.pendingSelection;
    state.pendingSelection = null;
    if (pending) selectProject(pending.project);
  }

  function cancelPendingSelection() {
    state.pendingSelection = null;
    render();
  }

  function renderPendingWarning() {
    if (!state.pendingSelection) return;
    var overlay = document.createElement("div");
    overlay.className = "modal-overlay";
    var box = h("div", "modal");
    box.appendChild(h("h3", null, "Cambiar de proyecto"));
    var count = state.pendingSelection.activeAgentsCount;
    box.appendChild(
      h(
        "p",
        null,
        "Hay " + count + " agente(s) activo(s) en la sesión actual. Cambiar a '" +
          state.pendingSelection.project.name +
          "' los detendrá. ¿Continuar?"
      )
    );
    var ok = button("Cambiar de todos modos");
    ok.addEventListener("click", confirmPendingSelection);
    var cancel = button("Cancelar");
    cancel.addEventListener("click", cancelPendingSelection);
    var actions = h("div", "modal-actions");
    actions.appendChild(cancel);
    actions.appendChild(ok);
    box.appendChild(actions);
    overlay.appendChild(box);
    ROOT.appendChild(overlay);
  }

  function selectProject(project) {
    stopArquitectoPolling();
    clearRoot();
    ROOT.textContent = "Seleccionando proyecto…";
    BackendClient.selectProject(project.id)
      .then(function () {
        state.showPicker = false;
        state.pendingSelection = null;
        // Al cambiar de proyecto se resetea el contexto; las secciones
        // operativas se vuelven a cargar para la nueva sesión (sus datos
        // dependen del proyecto activo).
        state.sections = { agents: null, jobs: null, plan: null, scripts: null, backlog: null, roles: null };
        return loadContext();
      })
      .catch(function (error) {
        state.showPicker = false;
        state.pendingSelection = null;
        showError(buildErrorMessage(error), function () {
          state.pendingSelection = null;
          render();
        });
      });
  }

  // ------------------------------------------------- FB-028 Pestaña Arquitecto
  // (US-FB028-02): 5 órdenes deterministas, prompt libre e historial de
  // últimas 10 respuestas del Arquitecto.

  function renderArquitectoInto(content) {
    arquitectoTabState.bodyWrap = content;
    loadArquitectoHistory();
    renderArquitectoBody();
  }

  function renderArquitectoBody() {
    var wrap = arquitectoTabState.bodyWrap;
    if (!wrap) return;
    if (state.section !== "arquitecto") return;
    wrap.textContent = "";

    var arq = arquitectoState.agent;
    var isActive = arq && arq.status !== "stopped";

    if (!isActive) {
      wrap.appendChild(h("p", "section-note", "El Arquitecto no está activo. Lánzalo desde la pestaña Agentes para enviarle órdenes."));
    }

    renderArquitectoOrders(wrap);
    renderArquitectoPrompt(wrap);
    renderArquitectoResult(wrap);
    renderArquitectoHistory(wrap);
  }

  function renderArquitectoOrders(wrap) {
    var arq = arquitectoState.agent;
    var isActive = arq && arq.status !== "stopped";
    var busy = arquitectoTabState.activeJobId !== null;

    wrap.appendChild(h("div", "scripts-group-title", "Órdenes"));

    ORDENES_ARQUITECTO.forEach(function (order) {
      var card = h("div", "script-card");
      var header = h("div", "script-card-header");
      header.appendChild(h("span", "script-name", order.label));
      card.appendChild(header);
      card.appendChild(h("div", "script-description", order.desc));

      if (order.needsSelect) {
        var select = document.createElement("select");
        select.className = "clickable launch-select";
        select.style.margin = "6px 0";
        select.disabled = !isActive || busy;

        var placeholder = document.createElement("option");
        placeholder.value = "";
        placeholder.textContent = order.needsSelect === "epic" ? "— elige una Epic —" :
                                  order.needsSelect === "us_in_progress" ? "— elige una US en progreso —" :
                                  "— elige una User Story —";
        select.appendChild(placeholder);

        if (order.needsSelect === "epic") {
          (arquitectoTabState._epics || []).forEach(function (epic) {
            var o = document.createElement("option");
            o.value = epic.id;
            o.textContent = epic.title || epic.id;
            if (arquitectoTabState.selectedEpicId === epic.id) o.selected = true;
            select.appendChild(o);
          });
          select.addEventListener("change", function () {
            arquitectoTabState.selectedEpicId = select.value || null;
          });
        } else if (order.needsSelect === "us") {
          (arquitectoTabState._usList || []).forEach(function (us) {
            var o = document.createElement("option");
            o.value = us.id;
            o.textContent = (us.title || us.id);
            if (arquitectoTabState.selectedUSId === us.id) o.selected = true;
            select.appendChild(o);
          });
          select.addEventListener("change", function () {
            arquitectoTabState.selectedUSId = select.value || null;
          });
        } else if (order.needsSelect === "us_in_progress") {
          (arquitectoTabState._usInProgress || []).forEach(function (us) {
            var o = document.createElement("option");
            o.value = us.id;
            o.textContent = (us.title || us.id);
            if (arquitectoTabState.selectedUSId === us.id) o.selected = true;
            select.appendChild(o);
          });
          select.addEventListener("change", function () {
            arquitectoTabState.selectedUSId = select.value || null;
          });
        }
        card.appendChild(select);
      }

      var runLabel = busy && arquitectoTabState.activeOrderId === order.id ? "Ejecutando…" : "Ejecutar";
      var runBtn = button(runLabel, "script-run");
      var disabled = !isActive || busy || (order.needsSelect && !(
        order.needsSelect === "epic" ? arquitectoTabState.selectedEpicId :
        arquitectoTabState.selectedUSId
      ));
      if (disabled) runBtn.disabled = true;
      runBtn.addEventListener("click", function () {
        dispatchArquitectoOrder(order);
      });
      card.appendChild(runBtn);

      wrap.appendChild(card);
    });
  }

  function renderArquitectoPrompt(wrap) {
    var arq = arquitectoState.agent;
    var isActive = arq && arq.status !== "stopped";
    var busy = arquitectoTabState.activeJobId !== null;

    wrap.appendChild(h("div", "scripts-group-title", "Prompt libre"));

    var card = h("div", "script-card");
    var textarea = document.createElement("textarea");
    textarea.className = "launch-select";
    textarea.placeholder = "Escribe un prompt para el Arquitecto…";
    textarea.value = arquitectoTabState.promptText;
    textarea.rows = 4;
    textarea.disabled = !isActive || busy;
    textarea.addEventListener("input", function () {
      arquitectoTabState.promptText = textarea.value;
    });
    card.appendChild(textarea);

    if (arquitectoTabState.promptConfirmPending) {
      var confirmBox = h("div", "agent-message");
      confirmBox.appendChild(h("p", null, "Envía este prompt al Arquitecto:"));
      confirmBox.appendChild(h("p", "script-command", arquitectoTabState.promptText));
      var confirmBtn = button("Confirmar envío");
      confirmBtn.addEventListener("click", function () {
        dispatchArquitectoPrompt();
      });
      var cancelBtn = button("Cancelar");
      cancelBtn.addEventListener("click", function () {
        arquitectoTabState.promptConfirmPending = false;
        renderArquitectoBody();
      });
      confirmBox.appendChild(cancelBtn);
      confirmBox.appendChild(confirmBtn);
      card.appendChild(confirmBox);
    }

    var sendBtn = button("Enviar");
    sendBtn.className += " script-run";
    if (!isActive || busy || !arquitectoTabState.promptText.trim()) sendBtn.disabled = true;
    sendBtn.addEventListener("click", function () {
      arquitectoTabState.promptConfirmPending = true;
      renderArquitectoBody();
    });
    card.appendChild(sendBtn);

    wrap.appendChild(card);
  }

  function renderArquitectoResult(wrap) {
    if (!arquitectoTabState.activeJobId) return;
    if (!arquitectoTabState.jobResult) return;

    var panel = h("div", "script-result");
    panel.appendChild(h("div", "script-result-title", "Resultado"));

    var result = arquitectoTabState.jobResult;
    if (result.status === "running") {
      panel.appendChild(h("p", "section-note", "El Arquitecto está procesando la orden…"));
    } else if (result.status === "completed") {
      panel.appendChild(h("p", "job-status-ok", "Completado"));
    } else if (result.status === "failed") {
      panel.appendChild(h("p", "agent-error", "Falló: " + (result.result || "sin detalles")));
    }

    if (result.result) {
      var out = h("div", "script-output");
      out.textContent = String(result.result);
      panel.appendChild(out);
    }
    wrap.appendChild(panel);
  }

  function renderArquitectoHistory(wrap) {
    wrap.appendChild(h("div", "scripts-group-title", "Últimas respuestas"));

    if (arquitectoTabState.history === null) {
      if (arquitectoTabState.historyError) {
        wrap.appendChild(h("p", "agent-error", arquitectoTabState.historyError));
      } else {
        wrap.appendChild(h("p", "section-note", "Cargando historial…"));
      }
      return;
    }

    if (arquitectoTabState.history.length === 0) {
      wrap.appendChild(h("p", "section-note", "El Arquitecto aún no ha procesado ninguna orden."));
      return;
    }

    arquitectoTabState.history.forEach(function (job) {
      var card = h("div", "job-card");
      var line = h("div", "job-line");
      var prefix = job.status === "running" ? "⟳ " : job.status === "completed" ? "✓ " : "✗ ";
      line.textContent = prefix + (job.description || "Sin descripción");
      card.appendChild(line);

      var meta = h("div", "job-hint");
      var timestamp = job.created_at ? new Date(job.created_at).toLocaleString() : "fecha desconocida";
      meta.textContent = timestamp + " · " + job.status;
      card.appendChild(meta);

      if (job.result) {
        var preview = String(job.result).split("\n").slice(0, 2).join("\n");
        var previewEl = h("div", "job-result");
        previewEl.style.maxHeight = "60px";
        previewEl.textContent = preview;
        card.appendChild(previewEl);

        var expanded = arquitectoTabState._expandedJobId === job.id;
        var toggleBtn = button(expanded ? "▲ Ocultar" : "▼ Ver completo", "script-expand-toggle");
        toggleBtn.addEventListener("click", function () {
          arquitectoTabState._expandedJobId = expanded ? null : job.id;
          renderArquitectoBody();
        });
        card.appendChild(toggleBtn);

        if (expanded) {
          var full = h("div", "job-result");
          full.textContent = String(job.result);
          card.appendChild(full);
        }
      }

      wrap.appendChild(card);
    });
  }

  function loadArquitectoHistory() {
    BackendClient.getBacklog()
      .then(function (backlog) {
        var epics = (backlog && backlog.epics) ? backlog.epics : [];
        arquitectoTabState._epics = epics.map(function (e) { return { id: e.id, title: e.title }; });

        var allUS = [];
        var inProgressUS = [];
        epics.forEach(function (epic) {
          if (epic.user_stories_list) {
            epic.user_stories_list.forEach(function (us) {
              allUS.push({ id: us.id, title: us.title });
              if (us.status === "in_progress") {
                inProgressUS.push({ id: us.id, title: us.title });
              }
            });
          }
        });
        arquitectoTabState._usList = allUS;
        arquitectoTabState._usInProgress = inProgressUS;
        renderArquitectoBody();
      })
      .catch(function () {
        arquitectoTabState._epics = [];
        arquitectoTabState._usList = [];
        arquitectoTabState._usInProgress = [];
        renderArquitectoBody();
      });

    BackendClient.getJobs()
      .then(function (jobs) {
        var arqJobs = (jobs || []).filter(function (j) {
          return j.role === "arquitecto" || (j.description && j.description.indexOf("[Arquitecto]") !== -1);
        });
        arqJobs.sort(function (a, b) {
          var ta = a.created_at ? new Date(a.created_at).getTime() : 0;
          var tb = b.created_at ? new Date(b.created_at).getTime() : 0;
          return tb - ta;
        });
        arquitectoTabState.history = arqJobs.slice(0, 10);
        arquitectoTabState.historyError = null;
        renderArquitectoBody();
      })
      .catch(function (error) {
        arquitectoTabState.history = [];
        arquitectoTabState.historyError = buildErrorMessage(error);
        renderArquitectoBody();
      });
  }

  function dispatchArquitectoOrder(order) {
    var arq = arquitectoState.agent;
    if (!arq || arquitectoTabState.activeJobId) return;

    var promptText;
    if (order.needsSelect) {
      var itemId = order.needsSelect === "epic" ? arquitectoTabState.selectedEpicId : arquitectoTabState.selectedUSId;
      if (!itemId) return;
      promptText = "[Arquitecto] " + order.promptPrefix + " " + itemId;
    } else {
      promptText = "[Arquitecto] " + order.promptPrefix;
    }

    _dispatchArquitectoJob(promptText, order.id);
  }

  function dispatchArquitectoPrompt() {
    var arq = arquitectoState.agent;
    if (!arq || arquitectoTabState.activeJobId) return;
    var text = "[Arquitecto] " + arquitectoTabState.promptText.trim();
    arquitectoTabState.promptConfirmPending = false;
    _dispatchArquitectoJob(text, null);
  }

  function _dispatchArquitectoJob(description, orderId) {
    var arq = arquitectoState.agent;
    if (!arq) return;

    arquitectoTabState.activeJobId = "pending";
    arquitectoTabState.activeOrderId = orderId;
    arquitectoTabState.jobResult = null;
    renderArquitectoBody();

    BackendClient.createAndDispatchJob({ agent_id: arq.id, description: description })
      .then(function (result) {
        arquitectoTabState.activeJobId = null;
        arquitectoTabState.activeOrderId = null;
        arquitectoTabState.jobResult = result;
        loadArquitectoHistory();
      })
      .catch(function (error) {
        arquitectoTabState.activeJobId = null;
        arquitectoTabState.activeOrderId = null;
        arquitectoTabState.jobResult = { status: "failed", result: buildErrorMessage(error) };
        loadArquitectoHistory();
      });
  }

  document.addEventListener("DOMContentLoaded", function () {
    checkConnectivity();
  });
})();