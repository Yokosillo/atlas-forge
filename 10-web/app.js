/* Atlas Forge — interfaz web (AF-021), arranque, contexto de sesión y
 * navegación operativa condicionada al contexto (T-AF021-US02-01
 * conectividad; T-AF021-US02-02 proyecto activo; T-AF021-US02-03
 * navegación condicionada al contexto resuelto).
 *
 * Flujo de arranque (`index.html`, `app.js` se carga al final del body):
 *   1. `checkConnectivity()` invoca `getHealth()` ANTES de renderizar
 *      cualquier contenido operativo.
 *   2. Sin backend: guía de onboarding PASO 1 ("No hay conexión con el
 *      backend") con botón "Reintentar" que reutiliza el MISMO mecanismo
 *      de T-AF021-US02-01 (no un flujo duplicado). No se renderiza NINGÚN
 *      enlace a secciones operativas.
 *   3. Con backend pero sin proyecto activo: guía PASO 2 ("No has elegido
 *      un proyecto todavía") con botón "Elegir proyecto" que abre el
 *      MISMO selector de T-AF021-US02-02. Tampoco se renderizan enlaces a
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
 *     en la TUI (`atlas_forge/tui/screens/workspace.py`).
 *
 * Estado de secciones (punto 5): el modelo de cada sección
 * (Agentes/Jobs/Plan/Scripts) vive en `state.sections[<sección>]` — NO en
 * un módulo JS que se reinicialice al cambiar de sección. Al navegar entre
 * secciones sin recargar la página, la sección ya cargada se re-renderiza
 * desde esa caché (no se vuelve a llamar al backend), de modo que el estado
 * no se pierde igual que con una recarga completa.
 *
 * Sección Jobs (T-AF021-US04-01): a diferencia de Plan/Scripts (cargados
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

  // ------------------------------------------------------- routing (T-AF024)
  // Cada sección operativa tiene una URL propia bajo /ui/ (`/ui/roles`,
  // `/ui/arquitecto`...) en vez de vivir solo en `state.section` en memoria
  // — así recargar la página o compartir el enlace mantiene la sección
  // activa, y los botones atrás/adelante del navegador funcionan. El
  // backend sirve `index.html` para cualquier subruta de /ui/ que no sea
  // un asset real (ver `app.py::_SPAStaticFiles`), así que esto es
  // puramente de enrutado en el cliente: no hay servidor de rutas nuevo.
  var DEFAULT_SECTION = "backlog";
  // "agents" ya NO es una ruta válida (T-AF024-US11-12): esa sección
  // (agentsSection/renderAgentActions) era código inalcanzable desde la
  // navegación real (nunca tuvo pestaña visible) con un diseño ya
  // superado por US-AF005-07 — eliminada del fichero. Sin esta entrada,
  // visitar `/ui/agents` directamente cae al `DEFAULT_SECTION` en vez de
  // intentar cargar una sección que ya no existe.
  // "plan" (2026-08-18): mismo criterio que "agents" arriba — sin pestaña
  // visible desde la navegación (deprecated, ver `renderTabsAndBody`),
  // se retira también de las rutas directas para que `/ui/plan` caiga al
  // `DEFAULT_SECTION` en vez de mostrar una sección sin ningún enlace de
  // entrada real.
  // "acciones" (T-AF034-US01-02, 2026-08-24): la sección independiente se
  // fusiona con "scripts" en un único catálogo (scripts + acciones) — se
  // retira de las rutas directas para que `/ui/acciones` caiga al
  // `DEFAULT_SECTION` en vez de mostrar una sección sin enlace de entrada.
  var ROUTE_SECTIONS = ["backlog", "pipeline", "roles", "arquitecto", "scripts", "jobs", "models", "configuracion"];

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
    // Valor inicial resuelto desde la URL real (T-AF024), no un literal
    // fijo — así recargar la página respeta la sección en la que estabas.
    section: sectionFromPath(window.location.pathname),
    sections: { jobs: null, plan: null, scripts: null, backlog: null, models: null, roles: null, configuracion: null },
    showPicker: false,
    pickerReason: "initial", // "initial" (onboarding) | "change" (voluntario)
    pendingBacklogCount: 0, // T-AF024-US01-02: numero de Epics/US con TO_DO>0
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
  // Sección ROLES (T-AF024-US08-01): los 4 roles con nombre, descripción
  // Pantalla AGENTES unificada (US-AF024-11, reescritura completa).
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
    // Edición del modelo por defecto (inline). editingRole guarda el rol
    // (lo consume saveRoleModel); editingRowKey identifica la fila exacta
    // que abrió el editor — para instancias reales es el id del agente,
    // para filas sintéticas (id null) es "synthetic:<role>:<name>", de
    // modo que Developer-1/2/3 no abran el editor a la vez (US-AF024-11
    // criterio 11 y T-AF024-US11-03).
    editingRole: null,
    editingRowKey: null,
    modelIndex: 0,
    // T-AF024-US11-07: true en cuanto el usuario dispara `change` sobre el
    // <select> del editor abierto — mientras sea false, cualquier
    // reconstrucción del DOM (incluido un tick de polling) debe seguir
    // reflejando `defaultModel` (todavía no ha elegido nada distinto);
    // en cuanto es true, debe reflejar `modelIndex` (su elección en
    // curso), nunca volver a `defaultModel` aunque el polling reconstruya
    // el <select> mientras tanto.
    modelIndexDirty: false,
    // T-AF024-US12-02: agent_id de Developer con confirmación de
    // "Eliminar" pendiente (doble pulsación) | null. Mismo patrón que
    // `plansSection.cancelPendingFor`: el aviso crece en la etiqueta del
    // propio botón, sin desplazar el resto del layout entre el primer y
    // el segundo clic.
    devStopPendingFor: null,
    // T-AF021-US03-04: aviso "Job en curso" por agente (map `agent_id ->
    // texto`) mostrado junto a la confirmación de detención. Best-effort: se
    // llena de forma asíncrona desde `GET /jobs`; un fallo deja "" (sin
    // aviso) sin bloquear la detención.
    runningJobNotice: {},
    saving: false,
    saveError: null,
    // Límite de Developer simultáneos (US-AF024-12, GET /system/preferences)
    // — null hasta que responda el backend, buildUnifiedRows usa el default
    // local mientras tanto (ver DEFAULT_MAX_SIMULTANEOUS_DEVELOPERS).
    maxSimultaneousDevelopers: null,
    // "Despertar": single-flight del POST /agents/{id}/send-keys (empujón al pane).
    awakeningAgentId: null,
    awakenError: null,
    // T-AF024-US11-16: single-flight del POST /agents/{id}/release (Liberar
    // un Developer caído) — evita dobles envíos al pulsar el botón.
    releaseInFlight: false,
    // T-AF024-US11-13: modelo real de un agente Claude Code, leído UNA
    // sola vez (GET /agents/{id}/status-model) al montar su selector
    // inline de modelo — Claude Code no tiene lectura pasiva
    // (agent.model siempre null), así que sin esto la preselección
    // siempre caería en el primer modelo del catálogo en vez del real.
    statusModelByAgentId: {},
    // T-AF005-US07-03: runtime elegido por fila ANTES de lanzar
    // (`chosenRuntimeByRow[rowKey]` = "opencode"|"claude-code"|"codex") —
    // el runtime es una elección explícita y obligatoria para un agente
    // no lanzado (nunca se infiere en silencio del modelo); una vez lanzado
    // queda fijo (se muestra como texto, sin control de cambio en caliente).
    // Se guarda por `rowKeyFor(agent)` para que cada fila (Developer-1/2/3,
    // Arquitecto, UX, ...) tenga su propia elección.
    chosenRuntimeByRow: {},
    // T-AF024-US11-13 (2026-08-17, tercera revisión de esta Task): modelo
    // elegido por fila ANTES de lanzar, para OpenCode Y Claude Code (el
    // cambio en caliente queda bloqueado — ver renderCambiarModeloBtn).
    // Mismo patrón que chosenRuntimeByRow: id del catálogo, por rowKey.
    chosenModelByRow: {},
    // T-AF005-US07-03: cambio de modelo en caliente de un agente OpenCode
    // vivo (idle) — single-flight por `agent_id` en vuelo, con el
    // resultado/error del `PUT /agents/{id}/model` real.
    changeModelInFlight: null,
    changeModelError: null,
    // T-AF024-US11-12 (ajuste de diseño): selector de modelo INLINE para
    // un agente OpenCode vivo en idle, mismo patrón visual que
    // `renderRuntimeSelector` (dropdown directo en la fila, sin botón
    // previo que abrir) — `liveModelOptionsByAgentId[agent.id]` cachea el
    // catálogo ya cargado (`GET /agents/{id}/available-models`, evita
    // recargarlo en cada tick de polling); `liveModelIndexByAgentId`
    // guarda la selección en curso del <select> por agente, para no
    // perderla si el polling reconstruye la fila mientras el usuario
    // todavía no ha confirmado (mismo criterio que `modelIndexDirty` del
    // editor de modelo por defecto, T-AF024-US11-07).
    liveModelOptionsByAgentId: {},
    liveModelIndexByAgentId: {},
  };

  // ------------------------------------------------------------------
  // Sección AGENTES (pestaña "Agentes" real, `rolesSection`/
  // `renderUnifiedRow` — ver más abajo; T-AF024-US11-12 eliminó la
  // implementación paralela `agentsSection`/`renderAgentActions`, código
  // inalcanzable desde la navegación real). A diferencia de Jobs/Plan/
  // Scripts (cargados una vez y cacheados en `state.sections`), la lista
  // de agentes se refresca por POLLING cada [POLL_INTERVAL_MILLIS]
  // mientras la pestaña está visible — mismo intervalo/criterio que
  // `AgentsViewModel.POLL_INTERVAL_MILLIS` (Android, 3s): no existe canal
  // WebSocket de estado de agente en AF-016 (solo `job_status` en
  // `WS /ws/jobs`), por lo que el polling ligero es el mecanismo.
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
    limited: "#6A1B9A", // púrpura (Purple 800) — sin límite de sesión, T-AF024-US21-01
    // T-AF008-US18-04: auto-liberación "working sin Job en vuelo" -> fallo
    // operativo consultable (`failure_reason`), rojo claro para distinguirlo
    // del rojo de `unavailable`.
    failed: "#C62828", // rojo oscuro (Red 800) — fallo de supervisión
  };

  function agentStatusColor(status) {
    return AGENT_STATUS_COLORS[status] || "#757575";
  }

  // ------------------------------------------------------------------
  // Sección JOBS (T-AF021-US04-01). El estado de la sección vive en
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
    // 2 de T-AF021-US04-02): id basado, persiste a través de la
    // recomposición desde GET /jobs.
    selectedJobId: null,
    // Formulario de creación (punto 3): agentes destinatarios (de los ya
    // lanzados, T-AF021-US03-01), descripción y Job previo opcional.
    agents: null, // null = sin cargar | array = agentes lanzados (sin stopped)
    agentsError: null,
    agentIndex: 0,
    descriptionInput: "",
    previousJobId: null, // job_id encadenado | null
    // T-AF024-US15-02: Story TO_DO opcional a asociar al Job (`story_id`
    // en `POST /jobs`, T-AF024-US15-01) — índice sobre el mismo catálogo
    // compartido `plansSection.todoStories` (0 = "Sin Story asociada").
    storySelectIndex: 0,
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

  // Sección PLAN (T-AF021-US05-01): solicitud del plan del Arquitecto, vista
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
    // T-AF024-US04-02: historias TO_DO del backlog como opciones del selector.
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
    // Cancelar (T-AF021-US05-02): SOLO se ofrece mientras el plan está
    // `approved` y quedan pasos `pending`/`running` (misma condición que
    // el dominio `request_cancellation`). Confirmación de 2ª pulsación en
    // la ETIQUETA del botón (mismo patrón anti-reflow que Cancelar
    // Job/Detener) + single-flight de la llamada real (punto 3).
    cancelPendingFor: null, // plan_id con confirmación pendiente | null
    cancellingPlanId: null, // cancelación en vuelo (single-flight)
    // Histórico (T-AF021-US05-02): lista desde `GET /plans` (incluye los
    // ya decididos — el backend no purga ninguno, mismo criterio que
    // `GET /jobs`) + detalle de uno concreto vía `GET /plans/{id}`.
    history: null, // null = sin cargar | array = planes de la sesión
    historyError: null,
    historyStale: false,
    selectedPlanId: null, // plan del histórico con detalle desplegado | null
    historyDetail: null, // detalle cargado vía GET /plans/{id} | null
    historyDetailError: null,
    actionError: null,
    // Canal WS /ws/plans (mismo wrapper reutilizado de T-AF021-US04-01).
    ws: null,
    wsStatus: null, // null | "connecting" | "connected" | "reconnecting"
  };

  // Sección SCRIPTS (T-AF021-US06-01, fusionada con Acciones en
  // T-AF034-US01-02): catálogo combinado (`GET /scripts`) de Scripts
  // genéricos + particulares + Acciones transversales, con indicador de
  // origen, ejecución con un clic (`POST /scripts/{id}/run` para scripts y
  // `POST /project/actions/{id}` para acciones), resultado completo
  // (success/stdout/stderr/error_message — o el shape de resultado de una
  // acción) y presentación legible de `backlog_status` (punto 4, mismo
  // shape de T-AF018-US02-04). `runningEntryId` es el single-flight GLOBAL
  // de la ejecución (punto 5): una entrada en vuelo deshabilita las demás
  // tarjetas, ya sean scripts o acciones.
  var scriptsSection = {
    bodyWrap: null,
    // Catálogo combinado: null = sin cargar | array = última lista vista.
    list: null,
    listError: null,
    stale: false,
    // Mensaje para el script `commit` (punto 2): botón deshabilitado hasta
    // tener mensaje no vacío (mismo criterio que Android/TUI).
    commitMessage: "",
    // Single-flight global (punto 5): entrada (script o acción) en
    // ejecución | null.
    runningEntryId: null,
    // Último resultado de un SCRIPT (punto 3): { scriptId, success,
    // exit_code, stdout, stderr, error_message, data, prose } | null.
    lastResult: null,
    // Último resultado de una ACCIÓN (T-AF034-US01-02): { action, status,
    // result } o { action, success, stdout, ... } | null.
    lastActionResult: null,
    runError: null,
    _expandedCommandId: null,
  };

  // ------------------------------------------------------------- BACKLOG
  // (T-AF020-US04-01). Mismo patrón de expandir-en-el-sitio ya usado en
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
    // Epic actualmente expandida en el listado (id `AF-xxx` derivado del
    // label libre) — su detalle se pide con `GET /backlog/{epic_id}` de
    // forma perezosa (solo al expandir, mismo criterio que
    // `togglePlanHistoryDetail`).
    selectedEpicId: null,
    epicDetail: null,
    epicDetailError: null,
    // T-AF036-US27-03: modo de expansión del backlog — `"single"` (una Epic/US
    // expandida a la vez, comportamiento actual) o `"multi"` (varias a la vez).
    // Se carga desde `backlog_multiple_expansion` de Configuración; default
    // `"single"` si la preferencia aún no respondió. En `multi` se usan los
    // mapas paralelos de abajo; en `single` se mantienen los slots únicos.
    expansionMode: "single",
    expandedEpicIds: {}, // multi: epicId -> true
    epicDetails: {},     // multi: epicId -> { detail, error }
    expandedItemIds: {}, // multi: itemId -> true
    itemDetails: {},     // multi: itemId -> { detail, error }
    // User Story actualmente expandida DENTRO de la Epic expandida — su
    // detalle se pide con `GET /backlog/{item_id}`.
    selectedItemId: null,
    itemDetail: null,
    itemDetailError: null,
    // Formulario "Lanzar desarrollo" (solo visible para el detalle de una
    // User Story, T-AF020-US02-02): agentes Developer ya lanzados
    // (mismo catálogo que Agentes/Jobs, filtrado a role === "developer"),
    // single-flight de la propia llamada, y el resultado/`detail` real
    // del backend ante un rechazo (400 sin Tasks TO_DO, 404 agente
    // inválido) — nunca un mensaje genérico (criterio de aceptación
    // explícito, mismo patrón que T-AF021-US04-01).
    developerAgents: null,
    developerAgentsError: null,
    developerAgentIndex: 0,
    launchingDevelopment: false,
    launchError: null,
    launchResult: null,
    viewMode: "by_fase", // "flat" | "by_fase" — por defecto "Por Versión" (T-AF036-US26-06)
    // T-AF036-US26-07: el listado completo (flat) es una acción TEMPORAL, no
    // una vista persistente. `flatExpanded` es true solo mientras el usuario
    // tiene el listado completo abierto; al navegar/re-render vuelve a false
    // y la vista retorna a "Por Versión". `viewMode` se mantiene "by_fase".
    flatExpanded: false,
    // T-AF036-US01-01: barra de controles (buscador + filtro de estado +
    // filtro de prioridad), filtrando en cliente sobre `report` ya
    // cargado, sin llamada adicional al backend. `filterText` guarda el
    // valor YA debounced (200ms) que se usa para filtrar; `filterTextInput`
    // guarda el valor tecleado en crudo para que el `<input>` no pierda
    // caracteres mientras el debounce está pendiente. Los tres sobreviven
    // a un `refreshBacklogReport()` (viven aparte de `report`, se
    // reaplican sobre el `report` nuevo, mismo criterio que
    // `selectedEpicId`/`selectedItemId`).
    filterText: "",
    filterTextInput: "",
    filterTextDebounceTimer: null,
    filterState: "all", // "all" | "TO_DO" | "IN_PROGRESS" | "REVIEW" | "DONE" | "blocked"
    filterPriority: "all", // "all" | "Crítica" | "Alta" | "Media" | "Baja" | "none"
    // T-AF036-US26-02: filtro por VERSIÓN (Epic y US) — "all" | <versión> |
    // "SIN_VERSIÓN". Se construye dinámicamente a partir del informe (las
    // versiones son el conjunto {0.9, 0.9.1, 0.9.2} + SIN VERSIÓN). Vive en
    // `backlogSection`, igual que filterState/filterPriority, así que
    // sobrevive a `refreshBacklogReport()` (se reaplica sobre el `report` nuevo).
    filterVersion: "all",
    // T-AF036-US16-05: se retiró el panel "Próximo foco" (decisión de
    // producto 2026-08-19) y con él su estado local `backlogFocusCollapsed`.
    // T-AF022-US17-02: panel determinista "Bloqueadas" reintroducido —
    // colapsable por el usuario (mismo patrón que el panel retirado), con
    // estado local que sobrevive a `refreshBacklogReport()`.
    bloqueadasCollapsed: false,
    // T-AF022-US17-03: panel determinista "En curso" (items IN_PROGRESS con
    // indicador de en vuelo/huérfana) — colapsable, mismo patrón.
    enCursoCollapsed: false,
    // T-AF036-US01-04: Epics agrupadas bajo "Terminadas (N)", plegado por
    // defecto (T5 de la especificación UX) — booleano local, sin fetch.
    showDoneEpics: false,
    // T-AF036-US15-02: en la vista "Por Fase", estado de plegado por grupo
    // (clave = fase) de los bloques colapsables "Terminadas" y "Todas fuera
    // de roadmap" — ambos colapsados por defecto, mismos booleans por grupo.
    byFaseOpen: {},
    // T-AF036-US01-05: tarjeta "(sin epic)" expandida/plegada — solo hay
    // UNA entrada huérfana por informe (`by_epic` las colapsa todas bajo
    // el label literal "(sin epic)", `report.py:161`), así que un
    // booleano basta, sin necesitar un id real (no existe `epicId` que
    // guardar, ver `epicIdFromLabel`).
    orphanExpanded: false,
    // T-AF036-US01-04, T7: tras pulsar el badge "N bloqueadas" de una
    // Epic que aún no estaba expandida, el scroll a la primera US
    // bloqueada debe esperar a que `epicDetail` llegue (fetch async de
    // `toggleEpicDetail`) — este par guarda el `epicId` en vuelo y sus
    // items bloqueados para que, en cuanto el fetch resuelva y el DOM se
    // repinte, se dispare el scroll (y luego se limpian). `null` = no
    // hay scroll pendiente.
    pendingBlockedScrollEpicId: null,
    pendingBlockedScrollItems: null,
    // T-AF024-US09-03: formulario manual de Job en detalle de US.
    manualJobAgents: null,
    manualJobAgentsError: null,
    manualJobAgentIndex: 0,
    manualJobDescription: "",
    // T-AF024-US15-02: índice sobre el mismo catálogo compartido
    // `plansSection.todoStories` (0 = "Sin Story asociada", igual que
    // `jobsSection.storySelectIndex`) — se inicializa a la Story cuyo
    // detalle está abierto SI esa Story está en TO_DO (ver
    // `toggleItemDetail`), desmarcable si el humano quiere un Job suelto
    // sin veredicto automático.
    manualJobStorySelectIndex: 0,
    creatingManualJob: false,
    manualJobError: null,
    manualJobResult: null,
    // T-AF008-US10-03: encolar/desencolar una Task individual desde su
    // detalle — single-flight por `task_id` (guarda el id en vuelo, no
    // solo un booleano, mismo criterio ya usado por
    // `proposeStoriesInFlight`/`proposeTasksInFlight`) para no bloquear
    // otra Task mientras esta petición está en curso.
    enqueueTaskInFlight: null,
    enqueueTaskError: null,
    // T-AF008-US10-03: vista de cola — null = sin cargar todavía |
    // array = último snapshot de GET /backlog/queue ya cargado. Se
    // recarga tras cada acción de encolar/desencolar con éxito (mismo
    // criterio de refresco que el resto de esta pantalla), sin polling
    // periódico propio (igual que el resto de Backlog, T-AF036-US01-01:
    // "no hay setInterval sobre esta pantalla").
    dispatchQueue: null,
    dispatchQueueError: null,
    dispatchQueueCollapsed: false,
    // T-AF036-US12-01: timer del polling periódico del panel de la cola de
    // despacho (mientras la pestaña de Backlog está abierta) | null.
    dispatchQueuePollTimer: null,
    // T-AF036-US07-01: desplegable "Opciones avanzadas" del detalle de una
    // US (Lanzar desarrollo + Crear Job manual) — colapsado por defecto.
    // No persiste entre distintos items: se resetea a `true` al expandir
    // cualquier detalle nuevo (toggleItemDetail/toggleNestedTaskDetail),
    // "menos ruido por defecto" para cada detalle.
    advancedOptionsCollapsed: true,
    // T-AF008-US10-03: detalle de una Task individual expandida DENTRO
    // del detalle de su propia User Story — slot de estado SEPARADO de
    // `selectedItemId`/`itemDetail` (el de la propia US): antes de esta
    // Task, ninguna Task individual era clicable en la UI; reutilizar
    // el mismo slot global habría colapsado el detalle de la US padre
    // en cuanto se expandiera una de sus Tasks (ambos se pintan solo si
    // `selectedItemId === this.id`, un único slot no puede representar
    // "US expandida Y una de sus Tasks también expandida" a la vez).
    selectedNestedTaskId: null,
    nestedTaskDetail: null,
    nestedTaskDetailError: null,
    // T-AF036-US08-01: edición de prioridad/estado en línea — single-flight
    // por `item_id` (misma US/Task no puede tener dos PUT en vuelo a la
    // vez), `editItemErrorFor` guarda a qué item pertenece el último error
    // para no mostrarlo bajo una fila distinta a la que lo produjo.
    editItemInFlight: null,
    editItemError: null,
    editItemErrorFor: null,
    // T-AF036-US02-04: formulario "+ Nueva Epic" — `null` = cerrado |
    // objeto `{id, title, objetivo, fase, submitting, error}` = abierto
    // (mismo patrón de estado que los formularios de Jobs/Plan). Los
    // valores de los campos viven en el propio objeto para sobrevivir al
    // re-render de `renderBacklogBody()` (mismo criterio que
    // `manualJobDescription`/`filterTextInput`).
    newEpicForm: null,
    // T-AF036-US02-05: formulario inline "+ Nueva User Story" — mismo
    // patrón que `newEpicForm`, con `epicId` fijado desde el contexto
    // (la Epic expandida donde se pulsó el botón) en vez de un `<input>`
    // editable. Un único slot global (no uno por Epic): abrir el
    // formulario en una Epic distinta descarta cualquier formulario ya
    // abierto en otra, mismo criterio que el resto de esta pantalla
    // (`editingRowKey`, `selectedItemId`).
    newUserStoryForm: null,
    // T-AF036-US02-06: formulario inline "+ Nueva Task" — mismo patrón que
    // `newUserStoryForm`, con `us_id`/`epic_id` fijados desde el contexto
    // (la US expandida donde se pulsó el botón). Un único slot global
    // (no uno por US): abrir el formulario en una US distinta descarta
    // cualquier formulario ya abierto en otra.
    newTaskForm: null,
    // T-AF036-US10-01: botones "Proponer User Stories" (detalle de Epic)
    // y "Aterrizar en Tasks" (detalle de User Story) — single-flight por
    // id en vuelo, mismo criterio que `enqueueTaskInFlight`. El
    // error/resultado del pipeline viven en
    // slots globales que SOLO se pintan en el detalle que los generó
    // (se resetean al cambiar de detalle o al lanzar una petición nueva).
    proposeStoriesInFlight: null, // epic_id en vuelo | null
    proposeStoriesError: null,    // motivo verbatim del backend | null
    proposeStoriesResult: null,   // resumen del pipeline aprobado | null
    proposeTasksInFlight: null,   // us_id en vuelo | null
    proposeTasksError: null,      // motivo verbatim del backend | null
    proposeTasksResult: null,     // resumen del pipeline aprobado | null
    // T-AF036-US05-01: botón "Revisar cobertura" (detalle de Epic) —
    // single-flight por epic_id, mismo patrón que proposeStories. El
    // resultado (coverage) vive en un slot global que solo se pinta en el
    // detalle de la Epic que lo generó (se resetea al cambiar de detalle).
    coverageInFlight: null, // epic_id en vuelo | null
    coverageError: null,    // motivo verbatim del backend | null
    coverageResult: null,   // {declared_alcance, points, gaps, message} | null
    // T-AF036-US06-01: informe de cierre real de una User Story — se carga
    // automáticamente al expandir el detalle de una US (sin clic explícito),
    // con indicador de carga bajo el bloque de Tasks. `closingReportUsId`
    // guarda a qué US pertenece el estado (para no pintar el informe de una
    // US distinta mientras se abre otra); `closingReport` es la respuesta
    // del endpoint (`{exists, content}`) o null si aún no llegó;
    // `closingReportError` guarda el motivo verbatim de un error real,
    // distinguible del caso "informe ausente".
    closingReportUsId: null,
    closingReportLoading: false,
    closingReportError: null,
    closingReport: null,
    // Task del informe a la que hacer scroll (id de Task cerrada) — se
    // consume en el mismo render y se limpia.
    closingReportScrollTaskId: null,
  };

  // Sección PIPELINE (T-AF042-US01-01/-02, US-AF042-01): aloja el panel de
  // la cola de despacho, trasladado desde la pestaña Backlog. Guarda su
  // propio snapshot de `GET /backlog/queue` (los mismos campos que
  // `backlogSection`, que conserva su copia para las acciones de fila del
  // listado Backlog) y el estado colapsado/expandido, conservado entre
  // navegaciones. `bodyWrap` se asigna en `renderPipelineInto`.
  var pipelineSection = {
    bodyWrap: null,
    dispatchQueue: null,
    dispatchQueueError: null,
    dispatchQueueCollapsed: false,
    // T-AF042-US01-02: timer del polling periódico del panel de la cola
    // (mientras la sección Pipeline está abierta) | null.
    dispatchQueuePollTimer: null,
  };

  // Sección MODELOS (T-AF022-US10-02): catálogo con habilitado/deshabilitado
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

  // Sección CONFIGURACIÓN (US-AF024-12): catálogo abierto de preferencias
  // de sistema, consumiendo GET/PUT /system/preferences. Empieza con un
  // único valor (límite de Developer simultáneos), pero el formulario está
  // pensado para crecer sin rediseñarse — cada preferencia es una fila
  // propia, no un formulario de un campo.
  var configuracionSection = {
    bodyWrap: null,
    state: null, // null | "loading" | "ready" | "unavailable"
    error: null,
    maxSimultaneousDevelopers: null, // valor actual del backend
    maxSimultaneousDevelopersInput: "", // valor editado en el <input>, como texto
    dirty: false,
    // T-AF036-US27-02: modo de expansión del backlog ("single"/"multi") —
    // valor cargado y flag de modificación, mismo patrón que max developers.
    backlogMultipleExpansion: "single",
    backlogMultipleExpansionDirty: false,
    saving: false,
    saveError: null,
    // Reinicio del servicio (T-AF037-US05-02): confirmación de doble
    // pulsación, estado "Reiniciando…" y polling de recuperación.
    restartPendingFor: null, // true mientras espera la segunda pulsación
    restarting: false,
    restartMessage: null,
    restartError: null,
    restartPollTimer: null,
  };

  // --------------------------------------------------------- AF-028
  // Barra de estado persistente del Arquitecto (US-AF028-01): polling 3s
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
    catalog: [], // catálogo {id, name} para resolver nombres amigables en la barra (2026-08-18)
    // T-AF028-US01-01: modelo activo REAL del Arquitecto (Claude Code no lo
    // guarda pasivamente — se consulta bajo demanda vía
    // `GET /agents/{id}/status-model`, nunca mientras el agente está
    // `working`). `realModelAgentId` evita re-consultar el mismo agente.
    realModel: null,
    realModelPending: false,
    realModelAgentId: null,
  };

  // Pestaña Arquitecto (US-AF028-02): órdenes deterministas, prompt libre
  // e historial de últimas 10 respuestas.
  var ORDENES_ARQUITECTO = [
    { id: "generar-us", label: "Generar User Stories", desc: "Toma una Epic y la desglosa en User Stories.", needsSelect: "epic", promptPrefix: "Desglosa la siguiente Epic en User Stories:" },
    { id: "desgranar-tasks", label: "Desgranar en Tasks", desc: "Toma una User Story y genera sus Tasks.", needsSelect: "us", promptPrefix: "Genera las Tasks para la siguiente User Story:" },
    { id: "emitir-veredicto", label: "Emitir veredicto", desc: "Revisa el trabajo del Developer sobre una US en progreso y emite veredicto estructurado.", needsSelect: "us_in_progress", promptPrefix: "Revisa el trabajo del Developer sobre esta User Story y emite tu veredicto:" },
    { id: "auditar-consistencia", label: "Auditar consistencia", desc: "Revisa todo el backlog buscando US sin Epic, Tasks sin US, formatos rotos y dependencias circulares.", needsSelect: null, promptPrefix: "Audita la consistencia del backlog completo del proyecto. Busca: User Stories sin Epic, Tasks sin User Story, formatos rotos en cualquier fichero del backlog, y dependencias circulares. Genera un informe con los hallazgos." },
    { id: "informe-progreso", label: "Informe de progreso", desc: "Genera un resumen del pipeline: US en cada estado, bloqueos y cuellos de botella.", needsSelect: null, promptPrefix: "Genera un informe completo del estado del pipeline de desarrollo. Incluye: cuántas User Stories hay en cada estado (READY, TO_DEVELOP, IN_PROGRESS, IN_REVIEW, DONE), qué bloqueos existen (dependencias sin resolver), y qué cuellos de botella detectas. Resume también el estado de cada Epic." },
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
      stopDispatchQueuePolling();
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
        "Atlas Forge necesita hablar con el backend antes de poder mostrar " +
          "agentes, Jobs o el plan del Arquitecto. Comprueba que el servicio esté en " +
          "marcha y vuelve a intentarlo."
      )
    );
    if (state.contextError) {
      wrapper.appendChild(h("p", "error-detail", "Detalle: " + state.contextError));
    }
    // CTA directo al MISMO mecanismo de reintento de T-AF021-US02-01
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
    // CTA directo al MISMO selector de T-AF021-US02-02 (openProjectPicker).
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
    // (mismo criterio de T-AF021-US02-02).
    var toolbar = h("div", "context-bar");
    var name = state.active && state.active.name ? state.active.name : "ninguno";
    toolbar.appendChild(h("span", "context-chip", "Proyecto activo: " + name));
    var changeBtn = button("Cambiar proyecto");
    changeBtn.addEventListener("click", function () {
      openProjectPicker("change");
    });
    toolbar.appendChild(changeBtn);
    ROOT.appendChild(toolbar);

    // Barra de estado del Arquitecto (US-AF028-01): segunda linea bajo
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
    // "plan" (flujo de Plan con aprobación, POST /plans) queda DEPRECATED
    // (2026-08-18, decisión del usuario: sustituido por el pipeline único
    // Progresar → Dispatcher → Developer → Tester → Arquitecto) — se
    // retira de la navegación visible, sin borrar `renderPlansInto`/el
    // resto del código (el backend `POST /plans` tampoco se elimina, solo
    // deja de tener ningún enlace desde la web). El Job aislado
    // (`POST /jobs`, "Crear Job manual"/"Lanzar desarrollo") NO es esto —
    // se queda vigente y accesible, ver `renderAdvancedOptionsCollapsible`.
    ["backlog", "pipeline", "roles", "arquitecto", "scripts", "configuracion"].forEach(function (key) {
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
    return { roles: "Agentes", jobs: "Jobs", plan: "Plan", scripts: "Scripts", backlog: "Backlog", models: "Modelos", arquitecto: "Arquitecto", configuracion: "Configuración", pipeline: "Pipeline" }[key];
  }

  // Barra de estado del Arquitecto (US-AF028-01): segunda linea bajo
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

    // Runtime (2026-08-18, tras US-AF031-03: tras reconciliar el agente
    // recupera su runtime real, y la barra superior debe reflejarlo igual
    // que la fila de Agentes — antes solo se mostraba el modelo).
    if (isActive && arq.runtime_id) {
      bar.appendChild(h("span", "arq-runtime", "· " + runtimeDisplayName(arq.runtime_id)));
    }

    // Modelo (T-AF028-US01-01): se muestra el modelo activo REAL cuando es
    // consultable — el del agente (OpenCode, lectura pasiva) o el leído bajo
    // demanda para Claude Code (`arquitectoState.realModel`). Si no se puede
    // conocer (agente parado o consulta no disponible), cae al modelo por
    // defecto configurado como aproximación — nunca un valor inventado.
    var activeModel = isActive ? (arq.model || arquitectoState.realModel) : null;
    if (activeModel) {
      bar.appendChild(h("span", "arq-model", catalogModelName(activeModel)));
    } else if (arquitectoState.defaultModel) {
      bar.appendChild(h("span", "arq-model", arquitectoState.defaultModel));
    } else {
      bar.appendChild(h("span", "arq-model arq-model-none", "sin modelo"));
    }

    // Estado
    var statusText = "";
    if (arquitectoState.error) {
      statusText = translateArquitectoError(arquitectoState.error);
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
    if (key !== state.section && state.section === "roles") {
      stopRolesPolling();
      rolesSection.editingRole = null;
      rolesSection.editingRowKey = null;
      rolesSection.modelIndex = 0;
      rolesSection.modelIndexDirty = false;
      rolesSection.saveError = null;
      rolesSection.devStopPendingFor = null;
      rolesSection.awakeningAgentId = null;
      rolesSection.awakenError = null;
      rolesSection.liveModelOptionsByAgentId = {};
      rolesSection.liveModelIndexByAgentId = {};
      rolesSection.statusModelByAgentId = {};
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
    if (key !== state.section && state.section === "pipeline") {
      // T-AF042-US01-02: al salir de la sección Pipeline se detiene el
      // polling del panel de la cola de despacho (no queda timer huérfano).
      stopDispatchQueuePolling();
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
    // con modelo y descripción, T-AF024-US08-01): no pasa por la caché.
    if (state.section === "roles") {
      ROOT.appendChild(content);
      renderRolesInto(content);
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
    // T-AF021-US06-01): no pasa por la caché única de `renderSectionData`.
    if (state.section === "scripts") {
      ROOT.appendChild(content);
      renderScriptsInto(content);
      return;
    }
    // Backlog también tiene su propio renderizado con estado (listado de
    // Epics + detalle expandido en el sitio + formulario de "Lanzar
    // desarrollo", T-AF020-US04-01): no pasa por la caché única.
    if (state.section === "backlog") {
      ROOT.appendChild(content);
      renderBacklogInto(content);
      return;
    }
    // Pipeline (T-AF042-US01-01/-02): la cola de despacho, con su propio
    // renderizado con estado (carga + polling) — no pasa por la caché única.
    if (state.section === "pipeline") {
      ROOT.appendChild(content);
      renderPipelineInto(content);
      return;
    }
    if (state.section === "models") {
      ROOT.appendChild(content);
      renderModelsInto(content);
      return;
    }
    // Configuración también tiene su propio renderizado con estado
    // (catálogo abierto de preferencias de sistema, US-AF024-12): no pasa
    // por la caché única.
    if (state.section === "configuracion") {
      ROOT.appendChild(content);
      renderConfiguracionInto(content);
      return;
    }
    if (state.section === "arquitecto") {
      ROOT.appendChild(content);
      renderArquitectoInto(content);
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
  // Roles/Agentes NO pasa por aquí (tiene su propio renderizado en `renderRolesInto`).
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
      // T-AF021-US06-01: Scripts tiene su PROPIO renderizado con estado
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

  // --------------------------------------------------- AF-028 Arquitecto
  // Polling 3s del estado del Arquitecto (US-AF028-01): busca el agente
  // con role=arquitecto en GET /agents y actualiza la barra de estado.
  // Arranca al activar proyecto y se para al cambiarlo.

  function ensureArquitectoModelPreferences() {
    if (arquitectoState.modelPreferencesReady) return;
    BackendClient.getModelsPreferences()
      .then(function (result) {
        arquitectoState.defaultModel = (result.defaults && result.defaults.arquitecto) || null;
        arquitectoState.catalog = (result.models || []).map(function (m) {
          return { id: m.id, name: m.name };
        });
        arquitectoState.modelPreferencesReady = true;
        renderArquitectoBar();
        // T-AF024-US11-09 criterio 1: si el usuario ya está en la pantalla
        // Agentes cuando esto resuelve, el botón "Lanzar" (calculado sobre
        // arquitectoState.defaultModel en cada render) debe reflejar el
        // resultado real de inmediato, sin esperar al siguiente ciclo de
        // polling ni a una acción manual del usuario en esa pantalla.
        if (state.section === "roles") renderRolesBody();
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

  // T-AF028-US01-01: consulta bajo demanda del modelo activo REAL del
  // Arquitecto (Claude Code no lo expone pasivamente). Solo se dispara
  // cuando el agente está `idle` (NUNCA `working`), con runtime Claude Code,
  // y una sola vez por agente (`realModelAgentId`). Si la consulta no está
  // disponible o el agente está parado, se deja `realModel` en `null` y la
  // barra cae al modelo por defecto como aproximación (nunca un valor
  // inventado).
  function refreshArquitectoRealModel() {
    var arq = arquitectoState.agent;
    if (!arq || arq.status === "stopped" || arq.status === "unavailable") {
      arquitectoState.realModel = null;
      arquitectoState.realModelPending = false;
      arquitectoState.realModelAgentId = null;
      return;
    }
    if (
      arq.status === "idle" &&
      arq.runtime_id === "claude-code" &&
      arquitectoState.realModelAgentId !== arq.id &&
      !arquitectoState.realModelPending
    ) {
      arquitectoState.realModelPending = true;
      BackendClient.getAgentStatusModel(arq.id)
        .then(function (result) {
          arquitectoState.realModel = result.model || null;
          arquitectoState.realModelPending = false;
          arquitectoState.realModelAgentId = arq.id;
          renderArquitectoBar();
        })
        .catch(function () {
          arquitectoState.realModel = null;
          arquitectoState.realModelPending = false;
          arquitectoState.realModelAgentId = arq.id;
          renderArquitectoBar();
        });
    }
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
      refreshArquitectoRealModel();
    } catch (error) {
      if (arquitectoState.agent !== null || arquitectoState.stale) {
        arquitectoState.stale = true;
      } else {
        arquitectoState.error = buildErrorMessage(error);
      }
    }
    renderArquitectoBar();
    if (state.section === "arquitecto") renderArquitectoBody();
    // T-AF024-US11-09 criterio 1: la fila del Arquitecto en la pantalla
    // Agentes (rolesSection) depende de arquitectoState.agent, que este
    // poll acaba de actualizar — sin este refresco, el botón "Lanzar"
    // podía quedar desincronizado (habilitado/deshabilitado incorrecto)
    // hasta la próxima acción manual del usuario en esa pantalla.
    if (state.section === "roles") renderRolesBody();
  }

  function launchArquitecto(agent) {
    if (arquitectoState.launchPending || arquitectoState.stopPending) return;
    // T-AF005-US07-03: el runtime lo elige el usuario en la fila de la
    // pantalla Agentes (selector obligatorio). Sin runtime elegido, no se
    // lanza (criterio 1 de US-AF005-07).
    var chosenRuntime = agent ? chosenRuntimeForRow(agent) : "";
    if (!chosenRuntime) return;
    arquitectoState.launchPending = true;
    renderArquitectoBar();
    // El runtime mandado es SIEMPRE el elegido (nunca el inferido del
    // modelo, T-AF005-US07-02). El modelo solo se manda cuando el runtime
    // lo admite (OpenCode) y el default del rol es un modelo real (no
    // "claude-code", que es un runtime, no un modelo de OpenCode).
    var arqPayload = { role: "arquitecto", runtime_type: chosenRuntime };
    if (chosenRuntime === "opencode") {
      var defaultId = arquitectoState.defaultModel;
      if (defaultId && defaultId !== "claude-code") {
        arqPayload.model_id = defaultId;
      }
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
      // T-AF021-US03-04: consulta best-effort de Jobs en curso para avisarlo
      // junto a la confirmación (no cambia el mecanismo de detención).
      var arqAgent = arquitectoState.agent;
      if (arqAgent) {
        rolesSection.runningJobNotice[arqAgent.id] = "";
        refreshRunningJobNotice(arqAgent.id);
      }
      renderArquitectoBar();
      if (state.section === "roles") renderRolesBody();
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

  // Etiqueta de rol capitalizada (mismo criterio que `roleLabel`, Android):
  // `GET /agents/options` devuelve `agent_role` tal cual ("developer"/
  // "critic"), el runtime ya viene capitalizado.
  function roleLabel(role) {
    if (!role) return role;
    return role.charAt(0).toUpperCase() + role.slice(1);
  }

  // Nombre visible del runtime a partir de su id (T-AF024-US04-03).
  function runtimeDisplayName(runtimeId) {
    if (runtimeId === "claude-code") return "Claude Code";
    if (runtimeId === "opencode") return "OpenCode";
    return runtimeId || "(no disponible)";
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
  // (T-AF021-US04-01). Formulario de creación + seguimiento en tiempo
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
    // T-AF024-US15-02: mismo catálogo de Stories TO_DO que el selector del
    // flujo de Plan — cargado aquí también por si el usuario llega
    // directo a Jobs sin haber visitado Plan antes.
    loadTodoStories();
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
  // desde el propio backend (T-AF021-US01-01), o desde `setBaseUrl`.
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

    // Job previo opcional (encadenamiento Developer → Arquitecto, punto 3):
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

    // T-AF024-US15-02: Story TO_DO opcional a asociar al Job — mismo
    // selector (mismo catálogo `plansSection.todoStories`, cargado por
    // `loadTodoStories`) que ya usa el flujo de Plan, no un campo de texto
    // libre nuevo (criterio de aceptación explícito de la Task). Sin
    // `story_id`, el Job se comporta exactamente igual que hoy (criterio 1
    // de `US-AF024-15`): al cerrarse no dispara ningún veredicto
    // automático.
    form.appendChild(h("div", "field-label", "Asociar a una Story (opcional — dispara veredicto del Arquitecto al cerrar)"));
    if (plansSection.todoStoriesLoading) {
      form.appendChild(h("p", "section-note", "Cargando User Stories del backlog…"));
    } else if (plansSection.todoStoriesError) {
      form.appendChild(h("p", "agent-error", "No se pudo cargar el catálogo de User Stories — el Job se puede enviar igualmente, sin Story asociada."));
    } else {
      var storySelect = document.createElement("select");
      storySelect.className = "clickable launch-select";
      var noStoryOpt = document.createElement("option");
      noStoryOpt.setAttribute("value", "");
      noStoryOpt.textContent = "Sin Story asociada";
      storySelect.appendChild(noStoryOpt);
      var todoStories = plansSection.todoStories || [];
      // `value` 1-based (0 queda reservado a "Sin Story asociada" arriba)
      // — evita que la PRIMERA Story del catálogo (idx 0) sea
      // indistinguible de "ninguna elegida" al leer `storySelectIndex`.
      todoStories.forEach(function (story, idx) {
        var o = document.createElement("option");
        o.setAttribute("value", String(idx + 1));
        o.textContent = story.id + " (" + (story.epic || "") + ") — READY";
        storySelect.appendChild(o);
      });
      if (todoStories.length === 0) {
        storySelect.disabled = true;
        noStoryOpt.textContent = "No hay User Stories en READY en el backlog";
      }
      storySelect.selectedIndex = 0;
      if (jobsSection.storySelectIndex > 0 && jobsSection.storySelectIndex <= todoStories.length) {
        storySelect.selectedIndex = jobsSection.storySelectIndex;
      }
      storySelect.addEventListener("change", function () {
        jobsSection.storySelectIndex = parseInt(storySelect.value, 10) || 0;
      });
      form.appendChild(storySelect);
    }

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

    // T-AF024-US15-02: `storySelectIndex` 0 es "Sin Story asociada" — solo
    // se envía `story_id` si el usuario eligió una Story real del
    // catálogo TO_DO. Sin este campo, `POST /jobs` se comporta igual que
    // antes de `US-AF024-15` (criterio de aceptación 1).
    var todoStories = plansSection.todoStories || [];
    if (jobsSection.storySelectIndex > 0 && jobsSection.storySelectIndex <= todoStories.length) {
      var chosenStory = todoStories[jobsSection.storySelectIndex - 1];
      if (chosenStory) payload.story_id = chosenStory.id;
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
  // (T-AF021-US05-01). Solicitud (`POST /plans`), vista completa de los
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
    // a una recarga ni a una acción local (T-AF021-US05-02, punto 2): si el
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

  // T-AF024-US04-02: carga las User Stories en TO_DO desde el backlog para
  // poblar el selector del formulario de Plan.
  // T-AF024-US15-02: catálogo de User Stories TO_DO compartido entre el
  // selector del flujo de Plan (`renderPlansForm`), el del formulario de
  // Job manual/suelto en la pantalla Jobs (`renderJobsForm`) y el del
  // formulario de Job manual en el detalle de una US en Backlog
  // (`renderManualJobForm`) — mismo dato (`plansSection.todoStories`), una
  // sola carga real (`loadTodoStories` es idempotente: si ya hay datos o
  // una carga en curso, no repite el fetch), consumido por los tres.
  // `renderActiveSection` repinta la sección visible en cada momento (o
  // ninguna, si el usuario navegó a otra pantalla mientras la carga
  // estaba en vuelo), y en Backlog también recalcula la preselección del
  // formulario de Job manual por si el catálogo llegó DESPUÉS de que el
  // detalle de la US ya estuviera abierto (orden de llegada no
  // garantizado entre ambos fetches).
  function renderActiveSection() {
    if (state.section === "plan") {
      renderPlansBody();
    } else if (state.section === "jobs") {
      renderJobsBody();
    } else if (state.section === "backlog") {
      recalculateManualJobStoryPreselection();
      renderBacklogBody();
    }
  }

  function recalculateManualJobStoryPreselection() {
    var detail = backlogSection.itemDetail;
    if (
      backlogSection.manualJobStorySelectIndex === 0 &&
      detail &&
      detail.id === backlogSection.selectedItemId &&
      detail.kind === "US" &&
      detail.state === "READY" &&
      plansSection.todoStories
    ) {
      var storyIdx = plansSection.todoStories.findIndex(function (s) { return s.id === detail.id; });
      if (storyIdx >= 0) backlogSection.manualJobStorySelectIndex = storyIdx + 1;
    }
  }

  function loadTodoStories() {
    if (plansSection.todoStories !== null && !plansSection.todoStoriesError) return;
    plansSection.todoStoriesLoading = true;
    BackendClient.getBacklog()
      .then(function (report) {
        var epicsWithTodo = (report.by_epic || []).filter(function (epic) {
          return epic.user_stories && epic.user_stories.READY > 0;
        });
        if (epicsWithTodo.length === 0) {
          plansSection.todoStories = [];
          plansSection.todoStoriesLoading = false;
          renderActiveSection();
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
                if (us.state === "READY") {
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
          renderActiveSection();
        }
      })
      .catch(function (error) {
        plansSection.todoStoriesLoading = false;
        plansSection.todoStoriesError = buildErrorMessage(error);
        renderActiveSection();
      });
  }

  // Punto 1: formulario para pedir un plan (`POST /plans`, campo `goal`
  // con el identificador de la User Story). Single-flight en el envío
  // (mismo criterio que enviar Job/lanzar agente).
  // T-AF024-US04-02: `goal` es un selector poblado con las Stories TO_DO
  // del backlog (no texto libre sin validar).
  function renderPlansForm(wrap) {
    var form = h("div", "plans-form");
    form.appendChild(h("div", "field-label", "Pedir un plan al Arquitecto"));

    // T-AF024-US04-02: selector de User Stories TO_DO en vez de texto libre.
    if (plansSection.todoStories === null || plansSection.todoStoriesLoading) {
      form.appendChild(h("p", "section-note", "Cargando User Stories del backlog…"));
    } else if (plansSection.todoStoriesError) {
      form.appendChild(h("p", "agent-error", "No se pudo cargar el catálogo de User Stories."));
      // Fallback: entrada de texto libre si la carga falló.
      var fallbackInput = document.createElement("input");
      fallbackInput.type = "text";
      fallbackInput.className = "clickable";
      fallbackInput.placeholder = "Identificador de User Story (p. ej. US-AF008-04)";
      fallbackInput.value = plansSection.goalInput;
      fallbackInput.addEventListener("input", function () {
        plansSection.goalInput = fallbackInput.value;
      });
      form.appendChild(fallbackInput);
    } else if (plansSection.todoStories.length === 0) {
      form.appendChild(h("p", "section-note", "No hay User Stories en READY en el backlog."));
    } else {
      var select = document.createElement("select");
      select.className = "clickable launch-select";
      if (plansSection.goalSelectIndex >= plansSection.todoStories.length) plansSection.goalSelectIndex = 0;
      plansSection.todoStories.forEach(function (story, idx) {
        var o = document.createElement("option");
        o.setAttribute("value", String(idx));
        o.textContent = story.id + " (" + (story.epic || "") + ") — READY";
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
      // T-AF008-US04-08: si el paso falló, mostrar el motivo real bajo
      // el paso concreto (`step.result`, el mensaje textual de
      // `JobCreationError`/`ScribeUnavailableError` que ya rellena
      // `dispatch_plan` antes de bloquear el plan) — antes de esta Task
      // el usuario solo veía "BLOQUEADO" a nivel de plan, sin saber cuál
      // de los pasos falló ni por qué. Mismo criterio de "mensaje real
      // del backend, nunca genérico" ya usado en el resto de esta
      // pantalla (`plansSection.actionError`, etc.).
      if (step.status === "failed" && step.result) {
        stepCard.appendChild(h("div", "plan-step-error", String(step.result)));
      }
      cardEl.appendChild(stepCard);
    });

    if (plansSection.actionError) {
      cardEl.appendChild(h("p", "agent-error", plansSection.actionError));
    }

    // T-AF021-US05-02: "Cancelar plan" SOLO mientras el plan está en curso
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
    var approveBtn = button(
      approveLabel,
      "plan-approve" + (plansSection.approvePending ? " plan-approve-pending" : "")
    );
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
    // T-AF024-US04-02: el goal se toma del selector de TO_DO stories (si
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
  // (T-AF021-US05-02, punto 1). Confirmación de SEGUNDA pulsación en la
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
  // (T-AF021-US05-02, punto 2). Lista completa desde `GET /plans` —
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
  // (T-AF021-US06-01). Catálogo combinado (`GET /scripts`) con origen,
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
    renderCatalogResult(wrap);
  }

  // Catálogo combinado (T-AF034-US01-02): una SOLA sección que dibuja
  // Scripts genéricos, Scripts particulares y Acciones transversales, sin
  // pestañas separadas por tipo. Los grupos visibles separan por origen pero
  // conviven en la misma pantalla (mismo criterio que Android `ScriptsScreen`).
  function renderScriptsCatalog(wrap) {
    wrap.appendChild(h("div", "scripts-title", "Catálogo de scripts y acciones"));
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

    var entries = scriptsSection.list || [];
    // Discriminador del catálogo combinado (mismo contrato que el backend,
    // T-AF034-US01-01/-02, ya verificado en `test_api_routes_scripts.py`):
    // las entradas de scripts llevan el campo `command` (las genéricas con
    // null), las Acciones NO llevan `command` en absoluto.
    var scripts = entries.filter(function (entry) {
      return entry.command !== undefined;
    });
    var actions = entries.filter(function (entry) {
      return entry.command === undefined;
    });
    var generic = scripts.filter(function (script) {
      return script.origin === "generic";
    });
    var particular = scripts.filter(function (script) {
      return script.origin === "particular";
    });

    if (entries.length === 0) {
      wrap.appendChild(
        h("p", "section-note", "No hay scripts ni acciones catalogados en la sesión.")
      );
      return;
    }

    if (generic.length > 0) {
      wrap.appendChild(h("div", "scripts-group-title", "Genéricos (Atlas Forge)"));
      wrap.appendChild(h("p", "section-note", "Scripts disponibles en cualquier proyecto del workspace."));
      generic.forEach(function (script) {
        wrap.appendChild(renderScriptCard(script));
      });
    }
    // Un proyecto sin scripts particulares (sin manifiesto) simplemente no
    // dibuja este grupo: no rompe ni muestra errores (criterio 4 de la US).
    if (particular.length > 0) {
      wrap.appendChild(h("div", "scripts-group-title", "Proyecto"));
      wrap.appendChild(h("p", "section-note", "Scripts específicos de este proyecto."));
      particular.forEach(function (script) {
        wrap.appendChild(renderScriptCard(script));
      });
    }
    if (actions.length > 0) {
      wrap.appendChild(h("div", "scripts-group-title", "Acciones transversales"));
      wrap.appendChild(h("p", "section-note", "Acciones que despachan un agente o ejecutan un proceso determinista, disponibles en cualquier proyecto."));
      actions.forEach(function (action) {
        wrap.appendChild(renderActionCard(action));
      });
    }
  }

  // Etiqueta visible del TIPO de ejecución de una entrada del catálogo
  // (T-AF034-US01-03), derivada de `execution_type` (metadato del catálogo
  // combinado, T-AF034-US01-01): 'Script · segundos', 'Acción · agente,
  // minutos', 'Acción · proceso externo'. Retrocompat: sin `execution_type`
  // (o valor no reconocido) se muestra 'no clasificado' — la etiqueta nunca
  // rompe el render (criterio de la Task).
  function executionTypeMeta(executionType) {
    var map = {
      script: "Script · segundos",
      agent_job: "Acción · agente, minutos",
      external_process: "Acción · proceso externo",
    };
    var label = map[executionType] || "no clasificado";
    var cls = map[executionType]
      ? "script-type-" + String(executionType).toLowerCase()
      : "script-type-unknown";
    return { label: label, cls: cls };
  }

  // Etiqueta visible del ORIGEN de una entrada (T-AF034-US01-03): 'Genérico'
  // para Atlas Forge, 'De este proyecto' para los particulares del proyecto
  // activo (mismo vocabulario que la US-AF034-01).
  function originLabel(origin) {
    return origin === "generic" ? "Genérico" : "De este proyecto";
  }

  // Tarjeta de un script: nombre + chips visibles de origen y tipo
  // (T-AF034-US01-03, sin pulsar) + descripción (particulares) + campo de
  // mensaje SOLO para `commit` + botón "Ejecutar" (punto 2): deshabilitado
  // hasta tener mensaje no vacío para commit, y siempre que haya una
  // ejecución en vuelo (single-flight global, punto 5).
  function renderScriptCard(script) {
    var needsMessage = script.id === SCRIPT_WITH_MESSAGE_PARAM;
    var isRunning = scriptsSection.runningEntryId === script.id;
    var busy = scriptsSection.runningEntryId !== null;

    var card = h("div", "script-card");
    var header = h("div", "script-card-header");
    header.appendChild(h("span", "script-name", script.name || script.id));
    var chips = h("div", "script-card-chips");
    chips.appendChild(
      h(
        "span",
        "script-origin script-origin-" + (script.origin === "generic" ? "generic" : "particular"),
        originLabel(script.origin)
      )
    );
    var type = executionTypeMeta(script.execution_type);
    chips.appendChild(h("span", "script-type " + type.cls, type.label));
    header.appendChild(chips);
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
        if (btn) btn.disabled = !commitInput.value.trim() || scriptsSection.runningEntryId !== null;
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

  // Tarjeta de una Acción transversal dentro del catálogo combinado
  // (T-AF034-US01-02): nombre + chips visibles de origen y tipo
  // (T-AF034-US01-03, sin pulsar) + descripción + botón "Ejecutar",
  // deshabilitado mientras haya cualquier ejecución en vuelo (single-flight
  // global, punto 5). El origen de una Acción siempre es 'Genérico' (no
  // existe acción particular en esta versión, ver US-AF034-02).
  function renderActionCard(action) {
    var isRunning = scriptsSection.runningEntryId === action.id;
    var busy = scriptsSection.runningEntryId !== null;

    var card = h("div", "script-card");
    var header = h("div", "script-card-header");
    header.appendChild(h("span", "script-name", action.name || action.id));
    var chips = h("div", "script-card-chips");
    chips.appendChild(h("span", "script-origin script-origin-generic", "Genérico"));
    var type = executionTypeMeta(action.execution_type);
    chips.appendChild(h("span", "script-type " + type.cls, type.label));
    header.appendChild(chips);
    card.appendChild(header);

    if (action.description) {
      card.appendChild(h("div", "script-description", String(action.description)));
    }

    var runLabel = isRunning ? "Ejecutando…" : "Ejecutar";
    var runBtn = button(runLabel, "script-run");
    if (busy) runBtn.disabled = true;
    runBtn.addEventListener("click", function () {
      runAction(action);
    });
    card.appendChild(runBtn);
    return card;
  }

  // Ejecución de un script (punto 2/3/5). Single-flight GLOBAL:
  // `runningEntryId` descarta una segunda invocación (script o acción)
  // mientras la petición anterior sigue en vuelo; el botón además queda
  // deshabilitado (mismo criterio que `SingleFlightAction` en Android
  // `ScriptsViewModel`).
  function runScript(script) {
    if (scriptsSection.runningEntryId) return; // single-flight
    var message = script.id === SCRIPT_WITH_MESSAGE_PARAM ? scriptsSection.commitMessage.trim() : null;
    if (script.id === SCRIPT_WITH_MESSAGE_PARAM && !message) {
      scriptsSection.runError = "Escribe un mensaje para el commit antes de ejecutar.";
      renderScriptsBody();
      return;
    }
    scriptsSection.runningEntryId = script.id;
    scriptsSection.runError = null;
    scriptsSection.lastResult = null;
    scriptsSection.lastActionResult = null;
    renderScriptsBody();

    BackendClient.runScript(script.id, message)
      .then(function (result) {
        scriptsSection.runningEntryId = null;
        scriptsSection.lastResult = { scriptId: script.id, result: result };
        renderScriptsBody();
        return refreshScripts();
      })
      .catch(function (error) {
        scriptsSection.runningEntryId = null;
        scriptsSection.runError = buildErrorMessage(error);
        renderScriptsBody();
      });
  }

  // Ejecución de una Acción transversal (T-AF034-US01-02): MISMO backend
  // que antes de la fusión (`POST /project/actions/{id}`, criterio 3 de la
  // US), y mismo single-flight global — una ejecución en vuelo deshabilita
  // el resto de tarjetas del catálogo.
  function runAction(action) {
    if (scriptsSection.runningEntryId) return; // single-flight global
    scriptsSection.runningEntryId = action.id;
    scriptsSection.runError = null;
    scriptsSection.lastActionResult = null;
    scriptsSection.lastResult = null;
    renderScriptsBody();

    BackendClient.runProjectAction(action.id)
      .then(function (result) {
        scriptsSection.runningEntryId = null;
        scriptsSection.lastActionResult = result;
        renderScriptsBody();
      })
      .catch(function (error) {
        scriptsSection.runningEntryId = null;
        scriptsSection.runError = buildErrorMessage(error);
        renderScriptsBody();
      });
  }

  // Panel de resultado ÚNICO del catálogo (criterio 5): un único bloque que
  // muestra el resultado de la última entrada ejecutada (script o acción),
  // el estado en vuelo o el error — nunca dos paneles separados por tipo.
  function renderCatalogResult(wrap) {
    if (scriptsSection.runError) {
      var errBox = h("div", "script-result");
      errBox.appendChild(h("p", "agent-error", scriptsSection.runError));
      wrap.appendChild(errBox);
      return;
    }
    if (scriptsSection.runningEntryId) {
      wrap.appendChild(h("p", "section-note", "Ejecutando…"));
      return;
    }
    if (scriptsSection.lastResult) {
      renderScriptResult(wrap);
      return;
    }
    if (scriptsSection.lastActionResult) {
      renderActionResult(wrap, scriptsSection.lastActionResult);
    }
  }

  // Resultado completo del último script ejecutado (punto 3): success +
  // exit_code + stdout/stderr/error_message, sin ocultar el fallo. Para
  // `backlog_status` exitoso, `data` se presenta estructurado (punto 4) y
  // `prose` se añade como síntesis cuando está disponible.
  function renderScriptResult(wrap) {
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

  // Resultado de una Acción transversal ejecutada (T-AF034-US01-02): shape
  // del backend `POST /project/actions/{id}` — determinista (`testear`,
  // success/stdout/exit_code) o Job desplegado (`documentar`/…,
  // job_id/status/result). Se dibuja en el mismo panel único que el
  // resultado de scripts.
  function renderActionResult(wrap, r) {
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

  // Presentación legible del informe estructurado de backlog-status
  // (punto 4, T-AF018-US02-04): conteo por Epic, Tasks LISTA, Tasks
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
  // (T-AF020-US04-01). Consume `GET /backlog`/`GET /backlog/{item_id}`/
  // `POST /backlog/{story_id}/launch-development` (T-AF020-US01-01/
  // US02-01, ambos `DONE`) — SIN cambios de backend. Patrón de
  // expandir-en-el-sitio (mismo criterio que Jobs/Plan: nunca navega a
  // otra pantalla), lista de Epics -> expandir muestra sus User Stories
  // -> expandir una US muestra su detalle completo + "Lanzar desarrollo".
  // Ver `backlogSection` (declarado arriba) para el shape completo del
  // estado.

  // Identificador de Epic (`AF-xxx`) a partir de la etiqueta libre
  // `**Epic:**` de una US/Task (p. ej. "AF-020 · Gestión de Backlog
  // (alcance v1)" -> "AF-020") — mismo criterio que `epicIdFromLabel`
  // (Android)/`_epic_id_from_label` (TUI): el PREFIJO, no el string
  // completo (distintas Tasks/US de la MISMA Epic real traen sufijos
  // distintos, verificado sobre el backlog real de este proyecto:
  // `AF-008` con 8 variantes). `null` si el label no sigue la
  // convención (p. ej. el caso real "(ninguna — infraestructura de
  // proyecto)").
  function epicIdFromLabel(epicLabel) {
    var match = /^(AF-\d{3,})/.exec(String(epicLabel || "").trim());
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
    // T-AF036-US26-07: al entrar (navegar) al Backlog, el listado completo
    // deja de estar expandido — la vista retorna a "Por Versión".
    backlogSection.flatExpanded = false;
    refreshBacklogReport();
    // T-AF042-US01-02: el panel de la cola vive ahora en la sección Pipeline;
    // Backlog conserva el snapshot (`loadDispatchQueue`) para las acciones de
    // fila ("Marcar para desarrollo"/"Quitar de la cola"), pero el POLLING
    // periódico se activa en Pipeline.
    loadDispatchQueue();
    renderBacklogBody();
  }

  // T-AF042-US01-01/-02: render de la sección Pipeline — aloja el panel de la
  // cola de despacho (carga y polling activos solo mientras esta sección está
  // abierta, criterio 2 de T-AF042-US01-02).
  function renderPipelineInto(content) {
    pipelineSection.bodyWrap = h("div", "pipeline-body");
    content.appendChild(pipelineSection.bodyWrap);
    loadDispatchQueue();
    startDispatchQueuePolling();
    renderPipelineBody();
  }

  function renderPipelineBody() {
    var wrap = pipelineSection.bodyWrap;
    if (!wrap || state.section !== "pipeline") return;
    wrap.textContent = "";
    renderDispatchQueuePanel(wrap);
  }

  // Recomposición del listado raíz desde `GET /backlog`. A diferencia de
  // Jobs/Agentes (donde un 404 es "sin sesión" -> lista vacía), aquí un
  // 404 real (sin proyecto activo) SÍ es un error a mostrar — mismo
  // criterio ya fijado en Android/TUI y en el propio backend
  // (T-AF020-US01-01). Un fallo puntual con lista previa ya vista
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
    // T-AF036-US16-05 (US-AF036-16): el panel "Próximo foco" se retiró de la
    // pantalla Backlog por decisión de producto (2026-08-19) — no aporta el
    // valor esperado. El dato backend `max_leverage_chain` se conserva (lo
    // usan el CLI y otras vistas).
    // T-AF042-US01-02: el panel de la cola de despacho ya NO se renderiza en
    // Backlog — se trasladó a la sección Pipeline.
    // T-AF036-US26-07: el listado completo es una acción temporal
    // (`flatExpanded`), no una vista persistente — la vista por defecto y al
    // volver es "Por Versión".
    // T-AF022-US17-02/-03 (US-AF022-17, requisitos deprecados 2026-08-24):
    // los paneles deterministas "Bloqueadas" y "En curso" ya NO se renderizan
    // en la pantalla Backlog — no aportan el valor esperado y se estimó que
    // retrasan la carga del listado. El indicador de en-vuelo/huérfana del
    // backend (T-AF022-US17-01) se conserva en `report.py` para otras vistas.
    // El panel "Peticiones para el Arquitecto" (T-AF036-US20-04) se retiró
    // de la pantalla Backlog por decisión de producto (2026-08-25): mostraba
    // el histórico de respuestas de creación como trazas en la cabecera. Se
    // está evaluando llevarlo a la pantalla Arquitecto (ver informe
    // 07-informes/AF-048 o backlog) — el backend de peticiones sigue activo.
    // El panel "Reconciliaciones" (T-AF022-US18-04) se retiró igualmente por
    // la misma decisión: parecía trazas de log y no aportaba valor.
    if (backlogSection.flatExpanded) {
      renderBacklogEpicList(wrap);
    } else {
      renderBacklogByFase(wrap);
    }
  }

  // T-AF022-US17-02 (US-AF022-17, criterio 2): panel determinista
  // "Bloqueadas" en la pantalla Backlog, reintroducido sobre el mismo
  // patrón del deprecated `renderBacklogFocusPanel`. Alimentado por
  // `report.items_bloqueada` (ya parte de `GET /backlog`, report.py): por
  // cada item bloqueado muestra `id + título` y debajo cada elemento de
  // `blocking_dependencies` como `← espera a <dep_id> [<estado>]`
  // (p. ej. `← espera a T-AF023-US03-01 [IN_PROGRESS]`); `[no existe]`
  // cuando el dep no está en el grafo (state null). Sin items bloqueadas
  // muestra "(ninguna bloqueada)" — no rompe la pantalla. Colapsable sin
  // afectar al resto de la vista.
  function renderBacklogBloqueadasPanel(wrap) {
    var report = backlogSection.report;
    if (!report || report.empty) return;
    var blocked = report.items_bloqueada || [];
    if (blocked.length === 0 && backlogSection.bloqueadasCollapsed) return;

    var panel = h("div", "backlog-bloqueadas-panel");
    var header = h("div", "backlog-bloqueadas-header");
    var titleText = blocked.length > 0 ? "Bloqueadas (" + blocked.length + ")" : "Bloqueadas";
    header.appendChild(h("span", "backlog-bloqueadas-title", titleText));
    var toggleBtn = button(
      backlogSection.bloqueadasCollapsed ? "Mostrar" : "Ocultar",
      "backlog-bloqueadas-toggle"
    );
    toggleBtn.addEventListener("click", function () {
      backlogSection.bloqueadasCollapsed = !backlogSection.bloqueadasCollapsed;
      renderBacklogBody();
    });
    header.appendChild(toggleBtn);
    panel.appendChild(header);

    if (!backlogSection.bloqueadasCollapsed) {
      if (blocked.length === 0) {
        panel.appendChild(h("p", "backlog-bloqueadas-empty", "(ninguna bloqueada)"));
      } else {
        var list = h("div", "backlog-bloqueadas-list");
        blocked.forEach(function (entry) {
          var item = h("div", "backlog-bloqueadas-item");
          var label = h("span", "backlog-bloqueadas-label", String(entry.id));
          item.appendChild(label);
          if (entry.title) {
            item.appendChild(h("span", "backlog-bloqueadas-title-text", String(entry.title)));
          }
          (entry.blocking_dependencies || []).forEach(function (dep) {
            var estado = dep && dep.state ? "[" + String(dep.state) + "]" : "[no existe]";
            item.appendChild(
              h(
                "div",
                "backlog-bloqueadas-dep",
                "← espera a " + (dep ? String(dep.id) : "?") + " " + estado
              )
            );
          });
          list.appendChild(item);
        });
        panel.appendChild(list);
      }
      // T-AF022-US17-04: cadena de mayor apalancamiento dentro del panel
      // "Bloqueadas" (solo si hay cadena; vacía -> sin ruido).
      renderLeverageChain(panel);
    }

    wrap.appendChild(panel);
  }

  // T-AF022-US17-04 (US-AF022-17, criterio 4): cadena de mayor
  // apalancamiento (`report.max_leverage_chain`) como sugerencia de por
  // dónde desbloquear el pipeline primero. Muestra la fila de ids encadenados
  // `A → B → C` (con el título de cada item cuando el reporte lo trae), en
  // orden. Si la cadena está vacía no se pinta nada (sin ruido); nunca rompe.
  function renderLeverageChain(wrap) {
    var report = backlogSection.report;
    var chain = (report && report.max_leverage_chain) || [];
    if (chain.length === 0) return;

    var section = h("div", "backlog-leverage-chain");
    section.appendChild(
      h("div", "backlog-leverage-title", "Cadena de mayor apalancamiento")
    );
    var row = h("div", "backlog-leverage-row");
    chain.forEach(function (entry, index) {
      if (index > 0) {
        row.appendChild(h("span", "backlog-leverage-arrow", " → "));
      }
      var chip = h("span", "backlog-leverage-item");
      chip.appendChild(h("span", "backlog-leverage-id", String(entry.id)));
      if (entry.title) {
        chip.appendChild(
          h("span", "backlog-leverage-title-text", " · " + String(entry.title))
        );
      }
      row.appendChild(chip);
    });
    section.appendChild(row);
    section.appendChild(
      h(
        "p",
        "backlog-leverage-note",
        "Completar el primero desbloquea los siguientes en cascada."
      )
    );
    wrap.appendChild(section);
  }

  // T-AF022-US17-03 (US-AF022-17, criterio 3): panel determinista "En curso"
  // con el indicador de **en vuelo / huérfana** por item `IN_PROGRESS`.
  // Alimentado por `report.items_in_progress` (T-AF022-US17-01): cada item
  // lleva un badge determinista —
  //   - "en vuelo" (verde) si `in_flight: true` (tiene entrada `dispatched`
  //     en `dispatch_queue.json`, Job legítimo en curso);
  //   - "huérfana" (rojo/naranja) si `in_flight: false` (IN_PROGRESS sin
  //     entrada — atascada, nunca se resolverá sola), con `title` explicativo.
  // Se muestra por defecto y al filtrar por estado IN_PROGRESS (así, al
  // filtrar por ese estado "se ven SOLO los items en curso, cada uno con su
  // badge"); con otro filtro de estado se oculta. Colapsable sin afectar al
  // resto de la vista, mismo patrón que el panel "Bloqueadas".
  function renderBacklogEnCursoPanel(wrap) {
    var report = backlogSection.report;
    if (!report || report.empty) return;
    if (backlogSection.filterState !== "all" && backlogSection.filterState !== "IN_PROGRESS") return;
    var items = report.items_in_progress || [];
    if (items.length === 0 && backlogSection.enCursoCollapsed) return;

    var panel = h("div", "backlog-en-curso-panel");
    var header = h("div", "backlog-en-curso-header");
    var titleText = items.length > 0 ? "En curso (" + items.length + ")" : "En curso";
    header.appendChild(h("span", "backlog-en-curso-title", titleText));
    var toggleBtn = button(
      backlogSection.enCursoCollapsed ? "Mostrar" : "Ocultar",
      "backlog-en-curso-toggle"
    );
    toggleBtn.addEventListener("click", function () {
      backlogSection.enCursoCollapsed = !backlogSection.enCursoCollapsed;
      renderBacklogBody();
    });
    header.appendChild(toggleBtn);
    panel.appendChild(header);

    if (!backlogSection.enCursoCollapsed) {
      if (items.length === 0) {
        panel.appendChild(h("p", "backlog-en-curso-empty", "(ningún item en curso)"));
      } else {
        var list = h("div", "backlog-en-curso-list");
        items.forEach(function (entry) {
          var item = h("div", "backlog-en-curso-item");
          item.appendChild(h("span", "backlog-en-curso-label", String(entry.id)));
          if (entry.title) {
            item.appendChild(h("span", "backlog-en-curso-title-text", String(entry.title)));
          }
          var inFlight = entry.in_flight === true;
          var badge = h(
            "span",
            "backlog-inflight-badge " + (inFlight ? "backlog-inflight-ok" : "backlog-inflight-orphan"),
            inFlight ? "en vuelo" : "huérfana"
          );
          badge.title = inFlight
            ? "Job en vuelo en la cola de despacho"
            : "sin Job en vuelo en la cola de despacho";
          item.appendChild(badge);
          list.appendChild(item);
        });
        panel.appendChild(list);
      }
    }

    wrap.appendChild(panel);
  }

  function renderBacklogViewToggle(wrap) {
    var header = h("div", "context-bar backlog-controls-left");
    // T-AF036-US02-04: botón "+ Nueva Epic" SIEMPRE visible en la barra de
    // controles — también con backlog vacío (es precisamente el caso donde
    // más falta, criterio de aceptación 1 de US-AF036-02) y mientras el
    // report sigue cargando. Abre el formulario inline (T6) sin llamada a
    // backend.
    var newEpicBtn = button("+ Nueva Epic", "backlog-new-epic-btn");
    newEpicBtn.addEventListener("click", function () {
      backlogSection.newEpicForm = {
        id: "",
        title: "",
        objetivo: "",
        submitting: false,
        error: null,
      };
      renderBacklogBody();
    });
    header.appendChild(newEpicBtn);

    if (backlogSection.report === null || backlogSection.report.empty) {
      // T-AF036-US21-01: la barra de búsqueda y filtros se renderiza SIEMPRE
      // en la vista Backlog — también con backlog vacío/cargando — sin ocultar
      // los controles (criterio de aceptación 1). Solo se omiten los toggles
      // Lista/Por Fase (no hay nada que listar ni agrupar); el formulario
      // inline, si está abierto, queda debajo.
      wrap.appendChild(header);
      renderBacklogFilterBar(wrap);
      if (backlogSection.newEpicForm !== null) {
        wrap.appendChild(renderNewEpicForm());
      }
      return;
    }
    var flatBtn = button("Lista", "backlog-view-toggle");
    // T-AF036-US26-07: "Lista" es una acción puntual — al pulsarlo muestra el
    // listado completo mientras esté abierto; no permanece como vista activa.
    if (backlogSection.flatExpanded) flatBtn.className += " active";
    flatBtn.addEventListener("click", function () {
      backlogSection.viewMode = "by_fase";
      backlogSection.flatExpanded = true;
      renderBacklogBody();
    });
    header.appendChild(flatBtn);
    var faseBtn = button("Por Versión", "backlog-view-toggle");
    if (!backlogSection.flatExpanded) faseBtn.className += " active";
    faseBtn.addEventListener("click", function () {
      backlogSection.flatExpanded = false;
      renderBacklogBody();
    });
    header.appendChild(faseBtn);
    wrap.appendChild(header);
    renderBacklogFilterBar(wrap);
    if (backlogSection.newEpicForm !== null) {
      wrap.appendChild(renderNewEpicForm());
    }
  }

  // T-AF036-US20-04: formulario de creación con ÚNICA entrada de lenguaje
  // natural (sustituye los formularios multi-campo de Nueva Epic/US/Task).
  // El texto se encola como petición de creación hacia el Arquitecto
  // (T-AF036-US20-01/02/03) y el item se materializa cuando el Arquitecto lo
  // procesa (T-AF036-US20-07/08); aquí NO se aportan campos estructurales.
  // `form.kind` ∈ {epic, us, task} y `form.contextId` (epicId/usId padre,
  // null para Epic) fijan a qué endpoint se encola.
  var NEW_EPIC_ID_PATTERN = /^AF-\d{3,}$/;
  var NEW_US_ID_PATTERN = /^US-AF\d{3,}-\d{2}[A-Z]?$/;
  var NEW_TASK_ID_PATTERN = /^T-AF\d{3,}-US\d{2}[A-Z]?-\d{2}[A-Z]?$/;

  function renderNewEpicForm() {
    return renderCreationForm(backlogSection.newEpicForm, "Nueva Epic", "epic", null);
  }

  function renderNewUserStoryForm() {
    return renderCreationForm(backlogSection.newUserStoryForm, "Nueva User Story", "us", backlogSection.newUserStoryForm ? backlogSection.newUserStoryForm.epicId : null);
  }

  function renderNewTaskForm() {
    return renderCreationForm(backlogSection.newTaskForm, "Nueva Task", "task", backlogSection.newTaskForm ? backlogSection.newTaskForm.usId : null);
  }

  // Render genérico del textarea único de creación + botón "Crear" (y
  // "Cancelar"). El botón se habilita solo con descripción no vacía y el
  // envío no en vuelo. En error muestra el `detail` verbatim y deja la
  // descripción editable para reintentar.
  function renderCreationForm(form, title, kind, contextId) {
    if (!form) return h("div");
    var container = h("div", "jobs-form");
    container.appendChild(h("div", "jobs-form-title", title));

    var note = h(
      "p",
      "section-note",
      kind === "epic"
        ? "Describe qué Epic quieres construir."
        : (kind === "us" ? "Describe qué User Story quieres construir dentro de la Epic «" + (contextId || "?") + "»." : "Describe qué Task quieres construir dentro de la US «" + (contextId || "?") + "».")
    );
    container.appendChild(note);

    var textarea = document.createElement("textarea");
    textarea.className = "clickable backlog-new-epic-input";
    textarea.rows = 3;
    textarea.placeholder = "Escribe qué quieres construir o conseguir...";
    textarea.value = form.description || "";
    textarea.addEventListener("input", function () {
      form.description = textarea.value;
      updateBtnState(createBtn, form);
    });
    container.appendChild(textarea);

    var createBtn = button(form.submitting ? "Creando…" : "Crear", "backlog-launch");
    updateBtnState(createBtn, form);
    createBtn.addEventListener("click", function () {
      submitCreationForm(form, kind, contextId);
    });
    container.appendChild(createBtn);

    var cancelBtn = button("Cancelar", "backlog-launch");
    if (form.submitting) cancelBtn.disabled = true;
    cancelBtn.addEventListener("click", function () {
      closeCreationForm(kind);
      renderBacklogBody();
    });
    container.appendChild(cancelBtn);

    if (form.error) {
      container.appendChild(h("p", "agent-error", form.error));
    }
    if (form.requestId) {
      // Tras encolar, mostramos el request_id; el item aparecerá cuando el
      // Arquitecto lo procese.
      container.appendChild(
        h("p", "section-note", "Petición de creación encolada (request: " + form.requestId + "). La entidad aparecerá en el backlog cuando el Arquitecto la procese.")
      );
    }
    return container;
  }

  function updateBtnState(btn, form) {
    btn.disabled = !(form.description || "").trim() || form.submitting;
  }

  function closeCreationForm(kind) {
    if (kind === "epic") backlogSection.newEpicForm = null;
    else if (kind === "us") backlogSection.newUserStoryForm = null;
    else backlogSection.newTaskForm = null;
  }

  // Encolado de una petición de creación (single-flight). Devuelve el
  // request_id; se muestra y la descripción queda editable hasta que se
  // procese (que es lo que exige el criterio de "deja la descripción
  // editable para reintentar").
  function submitCreationForm(form, kind, contextId) {
    if (!form || form.submitting) return;
    var description = (form.description || "").trim();
    if (!description) return;

    form.submitting = true;
    form.error = null;
    renderBacklogBody();

    var promise;
    if (kind === "epic") {
      promise = BackendClient.createFromDescriptionEpic(description);
    } else if (kind === "us") {
      promise = BackendClient.createFromDescriptionUserStory(contextId, description);
    } else {
      promise = BackendClient.createFromDescriptionTask(contextId, description);
    }

    promise
      .then(function (result) {
        var current = kind === "epic" ? backlogSection.newEpicForm
          : (kind === "us" ? backlogSection.newUserStoryForm : backlogSection.newTaskForm);
        if (!current) return;
        current.submitting = false;
        current.requestId = result.request_id;
        renderBacklogBody();
      })
      .catch(function (error) {
        var current = kind === "epic" ? backlogSection.newEpicForm
          : (kind === "us" ? backlogSection.newUserStoryForm : backlogSection.newTaskForm);
        if (!current) return;
        current.submitting = false;
        current.error = buildErrorMessage(error);
        renderBacklogBody();
      });
  }


  // T-AF036-US01-01: barra de controles con buscador + filtro de
  // estado + filtro de prioridad, sobre el listado raíz de Epics.
  // Sigue `07-informes/AF-036/especificacion-ux-backlog.md` (estados 3-4,
  // transiciones T1-T3, "Casos borde" sobre la limitación real del
  // filtro de prioridad).
  var BACKLOG_STATE_OPTIONS = [
    { value: "all", label: "Todos" },
    { value: "READY", label: "READY" },
    { value: "TO_DEVELOP", label: "TO_DEVELOP" },
    { value: "IN_PROGRESS", label: "IN_PROGRESS" },
    { value: "IN_REVIEW", label: "IN_REVIEW" },
    { value: "DONE", label: "DONE" },
    // T-AF036-US21-02: vocabulario completo del modelo AF-040 (estados que
    // aplican a User Stories) — `NO_TASKS`/`TO_PLAN` son estados de US sin
    // Tasks o pendiente de aterrizaje, y `OUT_OF_SCOPE` es el estado "fuera
    // de roadmap" (exclusivo de US). El filtro por estado ya lee estos
    // conteos de `epic.user_stories[state]`, así que añadirlos al selector
    // los hace filtrables sin tocar la lógica de match.
    { value: "NO_TASKS", label: "NO_TASKS" },
    { value: "TO_PLAN", label: "TO_PLAN" },
    { value: "OUT_OF_SCOPE", label: "OUT_OF_SCOPE" },
    { value: "blocked", label: "Bloqueadas" },
  ];
  var BACKLOG_PRIORITY_OPTIONS = [
    { value: "all", label: "Todas" },
    { value: "Crítica", label: "Crítica" },
    { value: "Alta", label: "Alta" },
    { value: "Media", label: "Media" },
    { value: "Baja", label: "Baja" },
    { value: "none", label: "Sin prioridad" },
  ];

  // T-AF036-US11-01: opciones del selector de fase — construidas
  // dinámicamente a partir del informe ya cargado (las fases del roadmap
  // no son un conjunto fijo ni hardcodeable). La primera opción es
  // "Todas" (`value: "all"`); le siguen las fases presentes en
  // `epic.fase` de `by_epic` y en `fase` de los items de
  // `items_lista`/`items_bloqueada`, deduplicadas y ordenadas; se añade
  // "SIN_ASIGNAR" al final si hay alguna Epic/item sin fase.
  function backlogVersionOptions() {
    var report = backlogSection.report;
    var byEpic = (report && report.by_epic) || [];
    var items = ((report && report.items_lista) || []).concat(
      (report && report.items_bloqueada) || []
    );
    var versions = {};
    var hasUnassigned = false;
    byEpic.forEach(function (epic) {
      if (epic.version) {
        versions[epic.version] = true;
      } else {
        hasUnassigned = true;
      }
    });
    items.forEach(function (item) {
      if (item.version) {
        versions[item.version] = true;
      } else {
        hasUnassigned = true;
      }
    });
    var opts = [{ value: "all", label: "Todas" }];
    Object.keys(versions).sort().forEach(function (version) {
      opts.push({ value: version, label: version });
    });
    if (hasUnassigned) {
      opts.push({ value: "SIN_VERSION", label: "SIN VERSIÓN" });
    }
    return opts;
  }

  function backlogFiltersActive() {
    return (
      backlogSection.filterText !== "" ||
      backlogSection.filterState !== "all" ||
      backlogSection.filterPriority !== "all" ||
      backlogSection.filterVersion !== "all"
    );
  }

  function resetBacklogFilters() {
    backlogSection.filterText = "";
    backlogSection.filterTextInput = "";
    backlogSection.filterState = "all";
    backlogSection.filterPriority = "all";
    backlogSection.filterVersion = "all";
    if (backlogSection.filterTextDebounceTimer) {
      clearTimeout(backlogSection.filterTextDebounceTimer);
      backlogSection.filterTextDebounceTimer = null;
    }
  }

  function renderBacklogFilterBar(wrap) {
    var bar = h("div", "backlog-filter-bar");

    var searchInput = document.createElement("input");
    searchInput.type = "text";
    searchInput.className = "clickable backlog-filter-search";
    searchInput.placeholder = "Buscar…";
    searchInput.value = backlogSection.filterTextInput;
    searchInput.addEventListener("input", function () {
      // T1: cada `input` recalcula el filtro en cliente con debounce de
      // 200ms (no se re-renderiza en cada tecla) — el valor tecleado en
      // crudo se guarda aparte (`filterTextInput`) para que el propio
      // `<input>` no pierda lo tecleado durante la espera del debounce.
      backlogSection.filterTextInput = searchInput.value;
      if (backlogSection.filterTextDebounceTimer) {
        clearTimeout(backlogSection.filterTextDebounceTimer);
      }
      backlogSection.filterTextDebounceTimer = setTimeout(function () {
        backlogSection.filterText = backlogSection.filterTextInput;
        backlogSection.filterTextDebounceTimer = null;
        renderBacklogBody();
      }, 200);
    });
    bar.appendChild(searchInput);

    var stateSelect = document.createElement("select");
    stateSelect.className = "clickable backlog-filter-select";
    BACKLOG_STATE_OPTIONS.forEach(function (opt) {
      var o = document.createElement("option");
      o.setAttribute("value", opt.value);
      o.textContent = opt.label;
      stateSelect.appendChild(o);
    });
    stateSelect.value = backlogSection.filterState;
    stateSelect.addEventListener("change", function () {
      // T2: análogo a T1, sin debounce (es un <select>, no hay tecleo).
      backlogSection.filterState = stateSelect.value;
      renderBacklogBody();
    });
    bar.appendChild(stateSelect);

    var priorityWrap = h("div", "backlog-filter-priority-wrap");
    var prioritySelect = document.createElement("select");
    prioritySelect.className = "clickable backlog-filter-select";
    BACKLOG_PRIORITY_OPTIONS.forEach(function (opt) {
      var o = document.createElement("option");
      o.setAttribute("value", opt.value);
      o.textContent = opt.label;
      prioritySelect.appendChild(o);
    });
    prioritySelect.value = backlogSection.filterPriority;
    prioritySelect.addEventListener("change", function () {
      backlogSection.filterPriority = prioritySelect.value;
      renderBacklogBody();
    });
    priorityWrap.appendChild(prioritySelect);
    priorityWrap.appendChild(
      h("p", "backlog-filter-priority-note", "El filtro de prioridad solo considera items pendientes (READY).")
    );
    bar.appendChild(priorityWrap);

    // T-AF036-US26-02: selector de VERSIÓN, después del de prioridad — mismo
    // patrón (change -> actualiza estado -> re-render). Las opciones son
    // dinámicas (`backlogVersionOptions`), así que el <select> se
    // reconstruye en cada render de la barra.
    var versionFilterSelect = document.createElement("select");
    versionFilterSelect.className = "clickable backlog-filter-select";
    backlogVersionOptions().forEach(function (opt) {
      var o = document.createElement("option");
      o.setAttribute("value", opt.value);
      o.textContent = opt.label;
      versionFilterSelect.appendChild(o);
    });
    versionFilterSelect.value = backlogSection.filterVersion;
    versionFilterSelect.addEventListener("change", function () {
      backlogSection.filterVersion = versionFilterSelect.value;
      renderBacklogBody();
    });
    bar.appendChild(versionFilterSelect);

    if (backlogFiltersActive()) {
      var clearBtn = button("Limpiar filtros", "backlog-filter-clear");
      clearBtn.addEventListener("click", function () {
        // T3: resetea filterText/filterState/filterPriority a sus valores
        // por defecto y renderiza.
        resetBacklogFilters();
        renderBacklogBody();
      });
      bar.appendChild(clearBtn);
    }

    wrap.appendChild(bar);
  }

  // Items TO_DO (de `items_lista`/`items_bloqueada`) que pertenecen a la
  // Epic `epicLabel` — mismo cruce por prefijo que usa `epicIdFromLabel`
  // para el resto de la pantalla. Único subconjunto de items con
  // `priority` presente en el informe raíz (ver "Casos borde" de la
  // especificación UX: el filtro de prioridad no cubre IN_PROGRESS/
  // REVIEW/DONE por esa misma razón).
  function backlogTodoItemsForEpic(epicLabel, report) {
    var epicId = epicIdFromLabel(epicLabel);
    var lista = (report.items_lista || []).concat(report.items_bloqueada || []);
    return lista.filter(function (item) {
      return epicIdFromLabel(item.epic) === epicId;
    });
  }

  // T-AF036-US01-04: items de `report.items_bloqueada` que pertenecen a
  // la Epic `epicLabel` — mismo cruce por prefijo ya validado arriba.
  // `items_bloqueada` no trae el campo `user_story` de cada Task (solo
  // `id`/`kind`/`epic`, ver `report.py:_summary`), así que el conteo a
  // nivel de Epic es 100% fiable (no depende de saber a qué US
  // pertenece cada Task), pero no permite derivar de forma fiable la US
  // padre de una Task bloqueada en frontend — decisión explícita
  // (2026-08-16): no se deriva por regex sobre el id (`T-FBxxx-USnn-mm`
  // -> `US-FBxxx-nn`), verificado que esa convención NO es universal en
  // el backlog real (p. ej. `T-AF016-US01-15` pertenece realmente a
  // `US-AF008-05`, no a `US-AF016-01`) — un cruce no fiable sería peor
  // que no cruzar. Ver `expandEpicAndScrollToBlocked` para cómo se
  // resuelve el scroll cuando el bloqueo es solo de Tasks.
  function blockedItemsForEpic(epicLabel, report, version) {
    var epicId = epicIdFromLabel(epicLabel);
    return (report.items_bloqueada || []).filter(function (item) {
      if (epicIdFromLabel(item.epic) !== epicId) return false;
      // En la vista "Por Versión" el badge de una Epic en el grupo `version`
      // solo debe reflejar los bloqueos de las US DE ESA VERSIÓN, no los de
      // todas las US de la Epic (T-AF004-US04-XX). Las US bloqueadas traen
      // su `version` propia (`report.py:_summary`); las Tasks bloqueadas no
      // la traen (las Tasks no declaran version) y no se atribuyen a una US
      // de forma fiable en frontend (decisión documentada en `_summary`/
      // `blockedItemsForEpic` original) — quedan fuera del conteo por
      // versión, igual que en el resto de esta pantalla.
      if (version !== undefined && version !== null && version !== "") {
        return String(item.version || "") === String(version);
      }
      return true;
    });
  }

  // Criterio de aceptación 1/2: una Epic se muestra si cumple LOS TRES
  // filtros a la vez (texto Y estado Y prioridad), cada uno por defecto
  // "sin restricción" si está en su valor por defecto.
  function epicMatchesBacklogFilters(epic, report, version) {
    // Con `version` (vista "Por Versión") el filtro se evalúa SOLO sobre
    // las US/items DE ESA versión — doble filtrado: primero el grupo de
    // versión, luego el criterio del filtro. Sin `version` (vista plana)
    // se evalúa sobre todos los items de la Epic, como siempre.
    var scoped = function (items) {
      if (version === undefined || version === null || version === "") return items;
      if (version === "SIN_VERSION") {
        return items.filter(function (item) { return !item.version; });
      }
      return items.filter(function (item) {
        return String(item.version || "") === String(version);
      });
    };
    // US de la versión del grupo (para filtro de estado/texto en la vista
    // "Por Versión" — `epic.user_stories` mezcla todas las versiones).
    var usInVersion = function () {
      var detail = (epic.user_stories_detail || []).filter(function (us) {
        if (version === "SIN_VERSION") return !us.version;
        return String(us.version || "") === String(version);
      });
      return detail;
    };
    var vs = (version === undefined || version === null || version === "") ? null : version;

    if (backlogSection.filterText !== "") {
      var needle = backlogSection.filterText.toLowerCase();
      // T-AF036-US21-02: el texto coincide con el ID Y el título. Para la
      // Epic se matchea `epic.epic` (id) y `epic.epic_label` (título de la
      // Epic, `report.py:_epic_label_from_file`); para US/Task se matchea
      // `item.id`, `item.title` (expuesto en el informe raíz, T-AF036-US21-02)
      // y `item.objetivo` cuando el dato esté disponible.
      function _matches(value) {
        return value != null && String(value).toLowerCase().indexOf(needle) !== -1;
      }
      var scopedTextItems = vs === null
        ? backlogTodoItemsForEpic(epic.epic, report)
        : scoped(backlogTodoItemsForEpic(epic.epic, report));
      var textMatches =
        _matches(epic.epic) ||
        _matches(epic.epic_label) ||
        scopedTextItems.some(function (item) {
          return _matches(item.id) || _matches(item.title) || _matches(item.objetivo);
        });
      if (!textMatches) return false;
    }

    if (backlogSection.filterState !== "all") {
      if (backlogSection.filterState === "blocked") {
        var epicId = epicIdFromLabel(epic.epic);
        var hasBlocked = scoped(report.items_bloqueada || []).some(function (item) {
          return epicIdFromLabel(item.epic) === epicId;
        });
        if (!hasBlocked) return false;
      } else {
    // Filtro por estado sobre los conteos agregados de `by_epic`
    // (única fuente disponible para TO_DO/IN_PROGRESS/REVIEW/DONE en
    // el informe raíz, ver "Casos borde" de la especificación UX): la
    // Epic se muestra si tiene al menos 1 item en ese estado. En la
    // vista "Por Versión" los conteos se filtran por versión del grupo.
        var usCount;
        var taskCount;
        if (vs !== null) {
          usCount = usInVersion().filter(function (us) {
            return us.state === backlogSection.filterState;
          }).length;
          taskCount = 0; // los conteos `epic.tasks` mezclan versiones; sin
                         // cruce Task→US fiable no se atribuyen por versión
        } else {
          usCount = (epic.user_stories && epic.user_stories[backlogSection.filterState]) || 0;
          taskCount = (epic.tasks && epic.tasks[backlogSection.filterState]) || 0;
        }
        if (usCount + taskCount === 0) return false;
      }
    }

    if (backlogSection.filterPriority !== "all") {
      var todoItems = scoped(backlogTodoItemsForEpic(epic.epic, report));
      var priorityMatches = todoItems.some(function (item) {
        if (backlogSection.filterPriority === "none") {
          return !item.priority;
        }
        return item.priority === backlogSection.filterPriority;
      });
      if (!priorityMatches) return false;
    }

    // T-AF036-US11-01: filtro por fase del roadmap. La fase de la Epic es
    // `epic.fase` (campo presente solo si la Epic la tiene, ver
    // `report.py`); `SIN_ASIGNAR` cubre `fase` ausente/vacía — mismo
    // criterio de agrupación que la vista `by_fase` (que agrupa por
    // `epic.fase || "SIN_ASIGNAR"`). Las vistas que filtran por item (p.
    // T-AF036-US26-02: filtro por VERSIÓN. La versión de la Epic es
    // `epic.version`; `SIN_VERSION` cubre `version` ausente/vacía — mismo
    // criterio de agrupación que la vista "Por Versión". La Epic coincide
    // si su versión es la seleccionada O la de alguna de sus User Stories
    // (`user_stories_detail[].version`), coherente con el filtro de la vista.
    if (backlogSection.filterVersion !== "all") {
      var epicVersion = epic.version || "";
      var usVersions = (epic.user_stories_detail || []).map(function (us) {
        return us.version || "";
      });
      var versionMatches;
      if (backlogSection.filterVersion === "SIN_VERSION") {
        versionMatches = !epicVersion && usVersions.every(function (v) { return !v; });
      } else {
        versionMatches = epicVersion === backlogSection.filterVersion ||
          usVersions.indexOf(backlogSection.filterVersion) !== -1;
      }
      if (!versionMatches) return false;
    }

    return true;
  }

  function filterBacklogEpics(epics, report, version) {
    if (!backlogFiltersActive()) return epics;
    return epics.filter(function (epic) {
      return epicMatchesBacklogFilters(epic, report, version);
    });
  }

  // Contador "Mostrando N de M Epics" (estado 4) + mensaje "Sin
  // resultados para este filtro" con "Limpiar filtros" cuando el filtro
  // no deja ninguna Epic — común a ambas vistas (Lista/Por Fase).
  function renderBacklogFilterSummary(wrap, filteredCount, totalCount) {
    if (!backlogFiltersActive()) return;
    wrap.appendChild(
      h("p", "section-note", "Mostrando " + filteredCount + " de " + totalCount + " Epics")
    );
    if (filteredCount === 0) {
      var emptyWrap = h("div", "backlog-filter-empty");
      emptyWrap.appendChild(h("p", "section-note", "Sin resultados para este filtro"));
      var clearBtn = button("Limpiar filtros", "backlog-filter-clear");
      clearBtn.addEventListener("click", function () {
        resetBacklogFilters();
        renderBacklogBody();
      });
      emptyWrap.appendChild(clearBtn);
      wrap.appendChild(emptyWrap);
    }
  }

  // T-AF036-US15-02: clave de orden natural de una fase — "Fase 0.9" ->
  // [0, 9], "Fase 0.9.1" -> [0, 9, 1], ...; cualquier otra fase (incluida
  // "SIN_ASIGNAR") recibe Infinity para quedar al final.
  function _faseOrderKey(fase) {
    var m = /^Fase\s+(\d+(?:\.\d+)*)$/i.exec(String(fase || "").trim());
    if (!m) return [Infinity, String(fase || "")];
    return m[1].split(".").map(Number);
  }

  // Comparador de fases por orden natural (numérico por componentes), con
  // "SIN_ASIGNAR"/otras fases no numeradas al final.
  function _compareFases(a, b) {
    var ka = _faseOrderKey(a);
    var kb = _faseOrderKey(b);
    var len = Math.max(ka.length, kb.length);
    for (var i = 0; i < len; i++) {
      var va = i < ka.length ? ka[i] : 0;
      var vb = i < kb.length ? kb[i] : 0;
      if (va < vb) return -1;
      if (va > vb) return 1;
    }
    return 0;
  }

  // T-AF036-US15-06 (US-AF036-15 criterio 5): clave de orden natural de una
  // VERSION de Epic — "0.9" -> [0, 9], "0.9.1" -> [0, 9, 1], "1.2" -> [1, 2];
  // cualquier versión no numérica (incluida "SIN_VERSION") recibe Infinity
  // para quedar al final.
  function _versionOrderKey(version) {
    var m = /^(\d+(?:\.\d+)*)$/.exec(String(version || "").trim());
    if (!m) return [Infinity, String(version || "")];
    return m[1].split(".").map(Number);
  }

  // Comparador de versiones por orden natural (numérico por componentes),
  // con "SIN_VERSION"/versiones no numéricas al final.
  function _compareVersions(a, b) {
    var ka = _versionOrderKey(a);
    var kb = _versionOrderKey(b);
    var len = Math.max(ka.length, kb.length);
    for (var i = 0; i < len; i++) {
      var va = i < ka.length ? ka[i] : 0;
      var vb = i < kb.length ? kb[i] : 0;
      if (va < vb) return -1;
      if (va > vb) return 1;
    }
    return 0;
  }

  // T-AF036-US15-02: ¿todas las User Stories de la Epic están fuera del
  // roadmap (OUT_OF_SCOPE/FUERA_ROADMAP)? Usa `user_stories_detail` (US15-01)
  // cuando está disponible; si no, cae a los conteos `user_stories`.
  // Con `version` se evalúa solo sobre las US de esa versión (T-AF018-US03-01):
  // en la vista "Por Versión" cada grupo clasifica la Epic según su situación
  // en ESA versión, no la global — una Epic puede estar "fuera de roadmap" en
  // 0.9 y activa en 0.9.2.
  function epicAllOutOfRoadmap(epic, version) {
    var list = epic.user_stories_detail || [];
    if (version !== undefined && version !== null && version !== "") {
      list = list.filter(function (us) { return String(us.version || "") === String(version); });
    }
    if (list.length > 0) {
      return list.every(function (us) { return isFueraRoadmapState(us.state); });
    }
    var us = epic.user_stories || {};
    var keys = Object.keys(us);
    if (keys.length === 0) return false;
    return keys.every(function (k) { return isFueraRoadmapState(k); });
  }

  // Renderiza un bloque colapsable de Epics al final de un grupo de fase
  // (patrón de "Terminadas (N)" de la vista plana), colapsado por defecto.
  function _renderByFaseCollapsedGroup(wrap, fase, kind, label, epics, faseGroup) {
    if (epics.length === 0) return;
    if (!backlogSection.byFaseOpen[fase]) backlogSection.byFaseOpen[fase] = {};
    var open = !!backlogSection.byFaseOpen[fase][kind];
    var header = button(
      (open ? "▼ " : "▶ ") + label + " (" + epics.length + ")",
      "backlog-done-header"
    );
    header.addEventListener("click", function () {
      backlogSection.byFaseOpen[fase][kind] = !backlogSection.byFaseOpen[fase][kind];
      renderBacklogBody();
    });
    wrap.appendChild(header);
    if (open) {
      epics.forEach(function (epic) { renderBacklogEpicCard(wrap, epic, faseGroup); });
    }
  }

  // (retirado 2026-08-25: panel "Peticiones para el Arquitecto"
  // T-AF036-US20-04 — see `renderBacklogBody` para la decisión de producto;
  // el backend de peticiones y su endpoint siguen activos para la pantalla
  // Arquitecto, que se está evaluando.)

  // (retirado en 2026-08-25: el panel "Reconciliaciones" de
  // T-AF022-US18-04 se quitó de la pantalla Backlog por decisión de
  // producto — ver el punto de render en `renderBacklogBody`.)

  function renderBacklogByFase(wrap) {
    // T-AF036-US26-06: con la vista "Por Versión" por defecto, hay que
    // manejar el report aún no cargado (mismo guard que el listado plano) —
    // sin esto, acceder a `report.by_epic` con `report === null` lanza y
    // rompe el render de toda la pestaña.
    if (backlogSection.report === null) {
      if (backlogSection.reportError) {
        wrap.appendChild(h("p", "agent-error", backlogSection.reportError));
      } else {
        wrap.appendChild(h("p", "section-note", "Cargando backlog…"));
      }
      return;
    }
    var allEpics = backlogSection.report.by_epic || [];
    // Sin filtro global aquí: en la vista "Por Versión" cada Epic se agrupa
    // bajo cada versión donde tenga al menos una US, y el filtro (texto/
    // estado/prioridad) se aplica POR GRUPO de versión abajo — doble
    // filtrado: primero la versión del grupo, luego el criterio del filtro.
    // Un filtro de criticidad solo debe mostrar una Epic en un grupo si
    // alguna US DE ESA VERSIÓN cumple el criterio (no si lo cumple una US
    // de otra versión, que se muestra en su propio grupo).
    var byEpic = allEpics;
    renderBacklogFilterSummary(wrap, byEpic.length, allEpics.length);
    var groups = {};
    byEpic.forEach(function (epic) {
      // T-AF036-US26-05 (AD-AF036-008): la versión es de las USER STORIES,
      // no de la Epic (el campo `epic.version` se retiró). Cada Epic se
      // agrupa bajo CADA versión donde tenga al menos una US; si no tiene
      // ninguna US con versión, va a "SIN_VERSION" (no versionada) al final.
      var usVersions = [];
      (epic.user_stories_detail || []).forEach(function (us) {
        var v = us.version ? String(us.version) : "";
        if (v && usVersions.indexOf(v) === -1) usVersions.push(v);
      });
      if (usVersions.length === 0) usVersions = ["SIN_VERSION"];
      usVersions.forEach(function (version) {
        if (!groups[version]) groups[version] = [];
        groups[version].push(epic);
      });
    });
    var ordered = Object.keys(groups).sort(_compareVersions);
    ordered.forEach(function (version) {
      // Doble filtrado por grupo: con el filtro activo, solo se muestran
      // en este grupo las Epics que cumplen el criterio sobre las US de
      // ESTA versión.
      groups[version] = groups[version].filter(function (epic) {
        return epicMatchesBacklogFilters(epic, backlogSection.report, version);
      });
      if (groups[version].length === 0) return;
      var groupWrap = h("div", "backlog-fase-group");
      groupWrap.appendChild(h("div", "backlog-fase-title", version));
      // T-AF036-US15-02: dentro de cada grupo, Epics abiertas primero; al
      // final (colapsadas) las terminadas y las con todas sus US fuera del
      // roadmap.
      var open = [];
      var done = [];
      var deferred = [];
      groups[version].forEach(function (epic) {
        // Clasificación POR VERSIÓN (T-AF018-US03-01): cada grupo decide
        // si la Epic está activa/terminada/fuera de roadmap según su
        // situación en ESA versión, no la global — una Epic con US DONE
        // en 0.9 y pendientes en 0.9.2 va a "Terminadas" del grupo 0.9 y
        // activa en el 0.9.2 (caso real AF-008).
        if (epicAllOutOfRoadmap(epic, version)) {
          deferred.push(epic);
        } else if (epicIsDone(epic, version)) {
          done.push(epic);
        } else {
          open.push(epic);
        }
      });
      open.forEach(function (epic) { renderBacklogEpicCard(groupWrap, epic, version); });
      _renderByFaseCollapsedGroup(groupWrap, version, "deferred", "Todas fuera de roadmap", deferred, version);
      _renderByFaseCollapsedGroup(groupWrap, version, "done", "Terminadas", done, version);
      wrap.appendChild(groupWrap);
    });
  }

  // Listado raíz de Epics (criterio de aceptación 1/2): conteo por
  // estado, igual que Android/TUI (T-AF020-US01-02). Cada fila expande/
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
    var allByEpic = backlogSection.report.by_epic || [];
    if (backlogSection.report.empty || allByEpic.length === 0) {
      // T-AF036-US02-04, caso borde de la especificación UX: en backlog
      // vacío el botón "+ Nueva Epic" sí se muestra (ya está en la barra de
      // controles, renderBacklogViewToggle) con el mensaje adaptado.
      wrap.appendChild(
        h("p", "section-note", "El backlog está vacío. Crea la primera Epic para empezar.")
      );
      return;
    }
    var byEpic = filterBacklogEpics(allByEpic, backlogSection.report);
    renderBacklogFilterSummary(wrap, byEpic.length, allByEpic.length);
    var realEpics = byEpic.filter(function (e) { return epicIdFromLabel(e.epic) !== null; });
    var orphanItems = byEpic.filter(function (e) { return epicIdFromLabel(e.epic) === null; });

    // T-AF036-US01-04, criterio 3: Epics con `todoCount === 0` (mismo
    // cálculo ya usado para `doneClass` en `renderBacklogEpicCard`)
    // quedan agrupadas bajo un separador "Terminadas (N)", plegado por
    // defecto — el foco por defecto es siempre el trabajo pendiente.
    var pendingEpics = realEpics.filter(function (e) { return !epicIsDone(e); });
    var doneEpics = realEpics.filter(function (e) { return epicIsDone(e); });
    pendingEpics.forEach(function (epic) {
      renderBacklogEpicCard(wrap, epic);
    });
    if (doneEpics.length > 0) {
      var doneHeader = button(
        (backlogSection.showDoneEpics ? "▼ " : "▶ ") + "Terminadas (" + doneEpics.length + ")",
        "backlog-done-header"
      );
      doneHeader.addEventListener("click", function () {
        backlogSection.showDoneEpics = !backlogSection.showDoneEpics;
        renderBacklogBody();
      });
      wrap.appendChild(doneHeader);
      if (backlogSection.showDoneEpics) {
        doneEpics.forEach(function (epic) {
          renderBacklogEpicCard(wrap, epic);
        });
      }
    }

    if (orphanItems.length > 0) {
      var orphanHeader = h("div", "job-detail-label", "(sin epic)");
      orphanHeader.style.opacity = "0.55";
      wrap.appendChild(orphanHeader);
      orphanItems.forEach(function (epic) {
        renderBacklogEpicCard(wrap, epic);
      });
    }
  }

  // `todoCount === 0` — extraída para reutilizar tanto en `doneClass`
  // como en la agrupación "Terminadas" sin duplicar la fórmula.
  // T-AF036-US02-04: una Epic SIN items (recién creada, sin US/Tasks aún)
  // no cuenta como "terminada" — no hay nada DONE que celebrar, es una
  // Epic pendiente vacía: debe renderizarse como tarjeta activa (y no
  // quedar oculta bajo el grupo "Terminadas (N)" plegado por defecto,
  // que rompía el criterio "la Epic aparece expandida tras crearla").
  function epicIsDone(epic, version) {
    var totalCount = sumCounts(epic.user_stories) + sumCounts(epic.tasks);
    // Bug corregido (2026-08-17, encontrado end-to-end vía el formulario
    // real de "+ Nueva User Story"): antes solo contaba `TO_DO` como
    // "pendiente" — una US recién creada nace en `NO_TASKS`
    // (T-AF008-US15-01), no `TO_DO`, así que la Epic con una única US
    // nueva se consideraba erróneamente "Terminada" (`todoCount === 0`)
    // y quedaba oculta bajo el grupo plegado "Terminadas (N)", pese a no
    // tener NADA completado — la Epic recién creada literalmente
    // desaparecía del listado visible. `NO_TASKS`/`TO_PLAN` cuentan
    // igual que `READY`: cualquier estado que no sea `DONE` es trabajo
    // pendiente (AF-040; OUT_OF_SCOPE no es pendiente).
    //
    // Con `version` se evalúa SOLO sobre las US de esa versión
    // (`user_stories_detail`): en la vista "Por Versión" cada grupo
    // clasifica la Epic según su situación en ESA versión, no la global.
    // Así una Epic con US DONE en 0.9 pero US pendientes en 0.9.2 queda
    // en "Terminadas" dentro del grupo 0.9 (donde no le queda trabajo) y
    // activa en el grupo 0.9.2 (donde sí le queda) — caso real AF-008.
    if (version !== undefined && version !== null && version !== "") {
      var list = (epic.user_stories_detail || []).filter(function (us) {
        return String(us.version || "") === String(version);
      });
      if (list.length > 0) {
        // OUT_OF_SCOPE/FUERA_ROADMAP no es trabajo pendiente (mismo
        // criterio que la vista plana, `pendingCount`): una US fuera de
        // roadmap no debe mantener la Epic activa en esa versión — caso
        // real AF-003 en 0.9 (US-AF003-01/-02 DONE, -03 OUT_OF_SCOPE).
        var pendingInVersion = list.some(function (us) {
          return us.state !== "DONE" && !isFueraRoadmapState(us.state);
        });
        return !pendingInVersion;
      }
      // Sin US de esta versión en el detalle, se evitan los conteos
      // globales (`epic.user_stories` mezcla todas las versiones): la
      // Epic no tiene trabajo en ESA versión, no cuenta como pendiente ahí.
      return true;
    }
    var pendingCount =
      (epic.user_stories && (epic.user_stories.READY || 0) + (epic.user_stories.NO_TASKS || 0) + (epic.user_stories.TO_PLAN || 0) + (epic.user_stories.TO_DEVELOP || 0) + (epic.user_stories.IN_PROGRESS || 0) + (epic.user_stories.IN_REVIEW || 0) || 0) +
      (epic.tasks && (epic.tasks.READY || 0) + (epic.tasks.TO_DEVELOP || 0) + (epic.tasks.IN_PROGRESS || 0) + (epic.tasks.IN_REVIEW || 0) || 0);
    return totalCount > 0 && pendingCount === 0;
  }

  function renderBacklogEpicCard(wrap, epic, faseGroup) {
      var epicId = epicIdFromLabel(epic.epic);
      var selected = epicId !== null && isEpicExpanded(epicId);
      var doneClass = epicIsDone(epic, faseGroup) ? " backlog-epic-done" : " backlog-epic-active";
      var card = h("div", "job-card" + doneClass + (selected ? " job-card-selected" : ""));
      // T-AF036-US01-08: regresión de T-AF018-US02-06 — al corregir
      // epic_label (pasó de devolver el id a devolver el título real),
      // esta línea sustituyó por completo el id visible por el título,
      // en vez de mostrar ambos. `epicTitleText` junta id+título con
      // " · " SOLO cuando difieren — una Epic huérfana sin fichero
      // propio ya devuelve epic_id como fallback de epic_label desde el
      // backend (mismo caso documentado más abajo en `epicIdFromLabel`
      // -> `null`), así que id === epic_label ahí y no debe duplicarse
      // ("AF-999 · AF-999"). `epicIdFromLabel` más abajo sigue usando
      // `epic.epic` (el id crudo), no este texto compuesto, para el
      // cruce de prefijos.
      var epicLabel = epic.epic_label || epic.epic;
      var epicTitleText = epicLabel === epic.epic ? epic.epic : epic.epic + " · " + epicLabel;
      var usSummary = stateCountsSummary(epic.user_stories);
      var taskSummary = stateCountsSummary(epic.tasks);
      var countsParts = [];
      if (usSummary) countsParts.push("US: " + usSummary);
      if (taskSummary) countsParts.push("Task: " + taskSummary);

      // Layout: id+título a la izquierda, conteos alineados a la
      // derecha en la misma línea (`justify-content: space-between`) —
      // antes era una única cadena de texto concatenada con " · ", sin
      // distinción visual entre ambos bloques de información.
      var line = h("div", "job-line backlog-epic-line" + (selected ? " job-line-selected" : ""));
      line.appendChild(h("span", "backlog-epic-line-title", epicTitleText));
      if (countsParts.length > 0) {
        line.appendChild(h("span", "backlog-epic-line-counts", countsParts.join(" · ")));
      }
      line.tabIndex = 0;
      line.setAttribute("role", "button");
      if (epicId === null) {
        // T-AF036-US01-05: el label libre "(sin epic)" no sigue la
        // convención `AF-xxx` (`epicIdFromLabel` -> `null`) — no hay
        // ningún `item_id` de Epic real que pedir a
        // `GET /backlog/{item_id}`, así que en vez de `toggleEpicDetail`
        // se alterna `backlogSection.orphanExpanded` (booleano local,
        // sin fetch) y se pinta el detalle agregado directamente con los
        // conteos que el propio `epic` de `by_epic` ya trae en memoria
        // (criterio de aceptación 2: cero llamadas de red adicionales).
        line.setAttribute("aria-expanded", backlogSection.orphanExpanded ? "true" : "false");
        line.addEventListener("click", function () {
          backlogSection.orphanExpanded = !backlogSection.orphanExpanded;
          renderBacklogBody();
        });
        card.appendChild(line);
        card.appendChild(h("div", "job-hint", backlogSection.orphanExpanded ? "▲ Plegar detalle" : "▼ Ver detalle"));
        if (backlogSection.orphanExpanded) {
          card.appendChild(renderOrphanDetail(epic));
        }
        wrap.appendChild(card);
        return;
      }
      line.setAttribute("aria-expanded", selected ? "true" : "false");
      line.addEventListener("click", function () {
        toggleEpicDetail(epicId);
      });
      card.appendChild(line);

      // T-AF036-US01-04, criterio 1: badge "N bloqueadas" si la Epic
      // tiene al menos un item en `items_bloqueada` — conteo 100%
      // fiable (cuenta total de la Epic, sin necesitar saber a qué US
      // pertenece cada Task, ver `blockedItemsForEpic`).
      var blockedItems = blockedItemsForEpic(epic.epic, backlogSection.report, faseGroup);
      if (blockedItems.length > 0) {
        var blockedBadge = button("", "backlog-blocked-badge");
        blockedBadge.appendChild(h("span", "backlog-blocked-badge-chip", blockedItems.length + " bloqueadas"));
        blockedBadge.title = blockedItems
          .map(function (item) {
            var deps = (item.blocking_dependencies || [])
              .map(function (dep) {
                return dep.id + (dep.state ? " [" + dep.state + "]" : " (no existe)");
              })
              .join(", ") || "dependencia pendiente";
            return item.id + " bloqueada por: " + deps;
          })
          .join("\n");
        blockedBadge.addEventListener("click", function (event) {
          event.stopPropagation();
          expandEpicAndScrollToBlocked(epicId, blockedItems);
        });
        card.appendChild(blockedBadge);
      }

      renderProgressBar(card, epic);
      card.appendChild(h("div", "job-hint", selected ? "▲ Plegar detalle" : "▼ Ver detalle"));
      if (selected) {
        card.appendChild(renderEpicDetail(faseGroup, epicId));
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
  // T-AF036-US27-03: en modo `multi` se gestionan N Epics/US con mapas
  // paralelos; en `single` se conservan los slots únicos (backward-compat).
  function isMultiMode() {
    return backlogSection.expansionMode === "multi";
  }
  function isEpicExpanded(epicId) {
    return isMultiMode()
      ? !!backlogSection.expandedEpicIds[epicId]
      : backlogSection.selectedEpicId === epicId;
  }
  function isItemExpanded(itemId) {
    return isMultiMode()
      ? !!backlogSection.expandedItemIds[itemId]
      : backlogSection.selectedItemId === itemId;
  }
  function toggleEpicDetail(epicId) {
    // T-AF036-US27-03: modo multi — mapas paralelos por Epic.
    if (isMultiMode()) {
      if (backlogSection.expandedEpicIds[epicId]) {
        // Plegar esta Epic: cierra las US abiertas (decisión documentada
        // en T-AF036-US27-03: "o todas" — sin rastrear el epicId padre por
        // item, al plegar una Epic se cierran las US abiertas). No colapsa
        // otras Epics.
        delete backlogSection.expandedEpicIds[epicId];
        delete backlogSection.epicDetails[epicId];
        backlogSection.proposeStoriesError = null;
        backlogSection.proposeStoriesResult = null;
        backlogSection.coverageError = null;
        backlogSection.coverageResult = null;
        backlogSection.itemDetails = {};
        backlogSection.expandedItemIds = {};
        renderBacklogBody();
        return;
      }
      backlogSection.expandedEpicIds[epicId] = true;
      backlogSection.epicDetails[epicId] = { detail: null, error: null };
      backlogSection.proposeStoriesError = null;
      backlogSection.proposeStoriesResult = null;
      backlogSection.coverageError = null;
      backlogSection.coverageResult = null;
      renderBacklogBody();

      BackendClient.getBacklogItem(epicId)
        .then(function (detail) {
          if (!isEpicExpanded(epicId)) return;
          backlogSection.epicDetails[epicId].detail = detail;
          renderBacklogBody();
          if (backlogSection.pendingBlockedScrollEpicId === epicId) {
            scrollToFirstBlockedUS(backlogSection.pendingBlockedScrollItems || []);
            backlogSection.pendingBlockedScrollEpicId = null;
            backlogSection.pendingBlockedScrollItems = null;
          }
        })
        .catch(function (error) {
          if (!isEpicExpanded(epicId)) return;
          backlogSection.epicDetails[epicId].error = buildErrorMessage(error);
          renderBacklogBody();
          if (backlogSection.pendingBlockedScrollEpicId === epicId) {
            backlogSection.pendingBlockedScrollEpicId = null;
            backlogSection.pendingBlockedScrollItems = null;
          }
        });
      return;
    }
    // Modo single: comportamiento actual intacto.
    if (backlogSection.selectedEpicId === epicId) {
      backlogSection.selectedEpicId = null;
      backlogSection.epicDetail = null;
      backlogSection.epicDetailError = null;
      // T-AF036-US10-01: al plegar la Epic se limpia el estado de
      // "Proponer User Stories" — un error/resultado previo no debe
      // reaparecer al reexpandir la misma Epic.
      backlogSection.proposeStoriesError = null;
      backlogSection.proposeStoriesResult = null;
      // T-AF036-US05-01: mismo criterio para "Revisar cobertura".
      backlogSection.coverageError = null;
      backlogSection.coverageResult = null;
      closeItemDetail();
      renderBacklogBody();
      return;
    }
    backlogSection.selectedEpicId = epicId;
    backlogSection.epicDetail = null;
    backlogSection.epicDetailError = null;
    // T-AF036-US10-01: el error/resultado de "Proponer User Stories"
    // solo tiene sentido asociado al detalle de la Epic que lo generó —
    // se limpia al abrir una Epic distinta.
    backlogSection.proposeStoriesError = null;
    backlogSection.proposeStoriesResult = null;
    // T-AF036-US05-01: mismo criterio para "Revisar cobertura".
    backlogSection.coverageError = null;
    backlogSection.coverageResult = null;
    closeItemDetail();
    renderBacklogBody();

    BackendClient.getBacklogItem(epicId)
      .then(function (detail) {
        if (backlogSection.selectedEpicId !== epicId) return;
        backlogSection.epicDetail = detail;
        renderBacklogBody();
        if (backlogSection.pendingBlockedScrollEpicId === epicId) {
          scrollToFirstBlockedUS(backlogSection.pendingBlockedScrollItems || []);
          backlogSection.pendingBlockedScrollEpicId = null;
          backlogSection.pendingBlockedScrollItems = null;
        }
      })
      .catch(function (error) {
        if (backlogSection.selectedEpicId !== epicId) return;
        backlogSection.epicDetailError = buildErrorMessage(error);
        if (backlogSection.pendingBlockedScrollEpicId === epicId) {
          backlogSection.pendingBlockedScrollEpicId = null;
          backlogSection.pendingBlockedScrollItems = null;
        }
        renderBacklogBody();
      });
  }

  // T-AF036-US01-04, criterio 2 / transición T7: pulsar el badge "N
  // bloqueadas" expande la Epic (si no lo estaba ya) y hace scroll a la
  // primera User Story bloqueada dentro de su detalle. Si ya estaba
  // expandida, solo hace scroll (sin repetir el fetch de
  // `toggleEpicDetail`) — mismo criterio explícito de la Task.
  function expandEpicAndScrollToBlocked(epicId, blockedItems) {
    var alreadyExpanded = isEpicExpanded(epicId) &&
      (isMultiMode() ? !!backlogSection.epicDetails[epicId].detail : backlogSection.epicDetail !== null);
    if (alreadyExpanded) {
      scrollToFirstBlockedUS(blockedItems);
      return;
    }
    backlogSection.pendingBlockedScrollEpicId = epicId;
    backlogSection.pendingBlockedScrollItems = blockedItems;
    toggleEpicDetail(epicId);
  }

  // Localiza el DOM del detalle ya renderizado y hace scroll: si algún
  // item bloqueado es directamente una US (`kind === "US"`), va a la
  // primera con ese id; si el bloqueo es solo de Tasks (US padre no
  // derivable de forma fiable, ver `blockedItemsForEpic`), va al inicio
  // del listado de User Stories de la Epic — nunca falla silenciosamente
  // ni adivina una US incorrecta.
  function scrollToFirstBlockedUS(blockedItems) {
    var blockedUS = blockedItems.filter(function (item) {
      return item.kind === "US";
    });
    var target = null;
    if (blockedUS.length > 0) {
      var firstId = blockedUS
        .map(function (item) { return item.id; })
        .sort()[0];
      target = document.getElementById("backlog-us-" + firstId);
    }
    if (!target) {
      target = document.querySelector(".backlog-us-list-label");
    }
    if (target) {
      target.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }

  // Resuelve la User Story padre de `taskId` SIN ampliar el backend
  // (`GET /backlog/{task_id}` nunca expone `user_story` para una Task,
  // confirmado leyendo `build_item_detail` antes de implementar — la
  // relación solo se expone al revés, desde la US) — expande la Epic
  // primero (si hace falta), luego consulta `GET /backlog/{us_id}` de
  // cada User Story de `epicDetail.user_stories` hasta encontrar la que
  // lista `taskId` entre sus `tasks[]`, expande esa US concreta
  // (`toggleItemDetail`) y hace scroll a la Task ya visible dentro de su
  // detalle. Nunca adivina la US por convención de nombre de fichero
  // (`T-<epic>-US<nn>-<mm>`) — ya verificado en `T-AF036-US01-04` que
  // esa convención no es universal en el backlog real.
  function expandEpicAndScrollToChainTask(epicId, taskId) {
    var epicAlreadyExpanded = isEpicExpanded(epicId) &&
      (isMultiMode() ? !!backlogSection.epicDetails[epicId].detail : backlogSection.epicDetail !== null);
    if (epicAlreadyExpanded) {
      findParentUserStoryAndScrollToTask(
        isMultiMode() ? backlogSection.epicDetails[epicId].detail : backlogSection.epicDetail,
        taskId
      );
      return;
    }
    // T-AF036-US27-03: en modo multi, expandir la Epic pedida NO colapsa las
    // otras — `toggleEpicDetail` gestiona el mapa. El scroll a la Task se
    // resuelve en el camino "ya expandida" de llamadas posteriores.
    if (isMultiMode()) {
      toggleEpicDetail(epicId);
      return;
    }
    backlogSection.selectedEpicId = epicId;
    backlogSection.epicDetail = null;
    backlogSection.epicDetailError = null;
    backlogSection.proposeStoriesError = null;
    backlogSection.proposeStoriesResult = null;
    closeItemDetail();
    renderBacklogBody();

    BackendClient.getBacklogItem(epicId)
      .then(function (detail) {
        if (backlogSection.selectedEpicId !== epicId) return;
        backlogSection.epicDetail = detail;
        renderBacklogBody();
        findParentUserStoryAndScrollToTask(detail, taskId);
      })
      .catch(function (error) {
        if (backlogSection.selectedEpicId !== epicId) return;
        backlogSection.epicDetailError = buildErrorMessage(error);
        renderBacklogBody();
      });
  }

  function findParentUserStoryAndScrollToTask(epicDetail, taskId) {
    var userStories = (epicDetail && epicDetail.user_stories) || [];
    if (userStories.length === 0) return;

    var found = false;
    userStories.forEach(function (userStory) {
      if (found) return;
      BackendClient.getBacklogItem(userStory.id)
        .then(function (usDetail) {
          if (found) return;
          var tasks = usDetail.tasks || [];
          var hasTask = tasks.some(function (t) { return t.id === taskId; });
          if (hasTask) {
            found = true;
            // Expande esa User Story concreta (si no lo estaba ya) y, en
            // cuanto su detalle esté en el DOM, hace scroll a la Task.
            if (!isItemExpanded(userStory.id)) {
              toggleItemDetail(userStory.id);
            }
            // `toggleItemDetail` reconstruye el DOM de forma asíncrona
            // (fetch propio) — esperar a que `itemDetail` refleje esta US
            // antes de intentar el scroll, mismo criterio que el resto de
            // este fichero (nunca asumir que el DOM ya tiene la fila).
            waitForTaskInDomAndScroll(taskId);
          }
        })
        .catch(function () {
          // Fallo puntual al consultar una US concreta: se ignora y se
          // sigue probando con el resto — un error de red en una US no
          // debe impedir localizar la Task en otra.
        });
    });
  }

  // Sondeo simple y acotado del DOM: `toggleItemDetail` es asíncrono
  // (fetch + render), así que el elemento `backlog-task-<id>` puede no
  // existir todavía en el instante en que se pide el scroll. Reintenta
  // cada 100ms hasta 3s (30 intentos) — mismo orden de magnitud que el
  // resto de esperas de UI de esta pantalla, sin bloquear el hilo
  // principal (usa `setTimeout`, no un bucle síncrono).
  function waitForTaskInDomAndScroll(taskId) {
    var elementId = "backlog-task-" + taskId;
    var attempts = 0;
    function tryScroll() {
      var target = document.getElementById(elementId);
      if (target) {
        target.scrollIntoView({ behavior: "smooth", block: "center" });
        return;
      }
      attempts += 1;
      if (attempts < 30) {
        setTimeout(tryScroll, 100);
      }
    }
    tryScroll();
  }

  function closeItemDetail(itemId) {
    // T-AF036-US27-03: en modo multi, cierra solo la US pedida (o todas si
    // no se indica); en single, cierra la única US.
    if (isMultiMode()) {
      if (itemId === undefined) {
        backlogSection.itemDetails = {};
        backlogSection.expandedItemIds = {};
      } else {
        delete backlogSection.itemDetails[itemId];
        delete backlogSection.expandedItemIds[itemId];
      }
      backlogSection.launchError = null;
      backlogSection.launchResult = null;
      return;
    }
    backlogSection.selectedItemId = null;
    backlogSection.itemDetail = null;
    backlogSection.itemDetailError = null;
    backlogSection.launchError = null;
    backlogSection.launchResult = null;
    backlogSection.manualJobAgents = null;
    backlogSection.manualJobError = null;
    backlogSection.manualJobResult = null;
    // T-AF008-US10-03: no se limpia `enqueueTaskInFlight` (single-flight
    // real, sigue en curso aunque el usuario cierre el detalle) — sí se
    // limpia el error de encolar una Task concreta, que solo tiene sentido
    // asociado al detalle que se está cerrando.
    backlogSection.enqueueTaskError = null;
    // T-AF036-US10-01: el error/resultado de "Aterrizar en Tasks" solo
    // tiene sentido asociado al detalle de la US que lo generó — se
    // limpia al cerrarlo, igual que `launchResult`.
    backlogSection.proposeTasksError = null;
    backlogSection.proposeTasksResult = null;
    // Cerrar la US padre también cierra cualquier Task anidada expandida
    // dentro de ella (deja de ser visible en el DOM de todos modos).
    backlogSection.selectedNestedTaskId = null;
    backlogSection.nestedTaskDetail = null;
    backlogSection.nestedTaskDetailError = null;
    // T-AF036-US06-01: el informe de cierre solo tiene sentido asociado al
    // detalle de la US que lo cargó — se limpia al cerrarlo, mismo criterio
    // que `proposeTasksError`/`launchResult` de arriba.
    backlogSection.closingReportUsId = null;
    backlogSection.closingReportLoading = false;
    backlogSection.closingReportError = null;
    backlogSection.closingReport = null;
    backlogSection.closingReportScrollTaskId = null;
  }

  // Aviso explícito de sección mal formada (criterio de aceptación 5,
  // mismo patrón que `ParseWarningBanner`/Android y las líneas `⚠ ...`
  // de la TUI): el resto del detalle disponible se muestra igual, esto
  // solo añade el aviso visible encima.
  function renderParseWarning(wrap, detail) {
    if (!detail || !detail.parse_warning) return;
    wrap.appendChild(h("p", "stale-note", "⚠ " + detail.parse_warning));
  }

  // T-AF036-US01-05: detalle agregado en línea de la tarjeta "(sin
  // epic)" — sin `epicId` real no hay `GET /backlog/{item_id}` posible
  // (no existe ningún `item_id` de Epic que pedir), así que el detalle
  // es directamente el desglose por estado que el propio `epic` de
  // `by_epic` ya trae en memoria (`epic.user_stories`/`epic.tasks`,
  // mismos conteos que ya resume la fila con `stateCountsSummary`) — no
  // se listan los `id` individuales de cada item huérfano porque el
  // informe raíz (`GET /backlog`) no los expone agregados de esa forma
  // sin backend nuevo (fuera de alcance de esta Task, ver
  // `items_lista`/`items_bloqueada`, que solo cubren items `TO_DO`/
  // bloqueados, no todos los estados).
  function renderOrphanDetail(epic) {
    var box = h("div", "job-detail");
    box.appendChild(
      h(
        "p",
        "section-note",
        "Items de infraestructura de proyecto sin Epic asociada — solo se muestra el desglose por estado, sin listado individual (el informe raíz no expone los identificadores de estos items)."
      )
    );
    var usSummary = stateCountsSummary(epic.user_stories);
    box.appendChild(h("div", "job-detail-field", "User Stories: " + (usSummary || "(ninguna)")));
    var taskSummary = stateCountsSummary(epic.tasks);
    box.appendChild(h("div", "job-detail-field", "Tasks: " + (taskSummary || "(ninguna)")));
    return box;
  }

  // Detalle de la Epic expandida (criterio de aceptación 2): objetivo +
  // desglose de sus User Stories con estado — tocar una US expande su
  // detalle completo (criterio de aceptación 3), sin navegar.
  function renderEpicDetail(faseGroup, epicId) {
    var box = h("div", "job-detail");
    // T-AF036-US27-03: en modo multi el detalle se lee del mapa por Epic.
    var st = isMultiMode() && epicId ? backlogSection.epicDetails[epicId] : null;
    var error = isMultiMode() && epicId ? (st && st.error) : backlogSection.epicDetailError;
    var detail = isMultiMode() && epicId ? (st && st.detail) : backlogSection.epicDetail;
    if (error) {
      box.appendChild(h("p", "agent-error", error));
      return box;
    }
    if (detail === null || detail === undefined) {
      box.appendChild(h("p", "section-note", "Cargando…"));
      return box;
    }
    renderParseWarning(box, detail);
    box.appendChild(h("div", "job-detail-field", "Objetivo: " + (detail.objetivo || "(sin objetivo declarado)")));

    var userStories = detail.user_stories || [];
    var usListLabel = h("div", "job-detail-label backlog-us-list-label", "User Stories:");
    box.appendChild(usListLabel);

    // T-AF036-US01-07: aplicar filtro de estado a las User Stories en el
    // detalle expandido, igual que en el listado raíz (epicMatchesBacklogFilters).
    var filteredUserStories = userStories.filter(function (userStory) {
      if (backlogSection.filterState === "all") {
        return true;
      }
      if (backlogSection.filterState === "blocked") {
        // "Bloqueadas" se refiere al estado explícito "BLOQUEADA", que es un
        // valor de state en detail.user_stories (igual que en Task).
        return userStory.state === "BLOQUEADA";
      }
      // Filtro por estado: TO_DO, IN_PROGRESS, REVIEW, DONE.
      return userStory.state === backlogSection.filterState;
    });

    // T-AF036-US26-02: filtro por VERSIÓN aplicado sobre la versión de cada
    // User Story (la versión es de la US/Epic, ya no hay fase). `SIN_VERSION`
    // cubre `version` ausente/vacía.
    if (backlogSection.filterVersion !== "all") {
      filteredUserStories = filteredUserStories.filter(function (userStory) {
        var usVersion = userStory.version || "";
        if (backlogSection.filterVersion === "SIN_VERSION") {
          return !usVersion;
        }
        return usVersion === backlogSection.filterVersion;
      });
    }

    // Filtro por versión del grupo en la vista "Por Versión": cuando
    // `faseGroup` es una cadena de versión (no null/vacía), solo se
    // muestran US cuya versión coincide con la del grupo. Sin esto,
    // un Epic con US 0.9 + 0.9.1 + 0.9.2 se despliega en el bloque 0.9
    // mostrando TODAS las US, incluidas las de otras versiones.
    if (faseGroup) {
      filteredUserStories = filteredUserStories.filter(function (userStory) {
        var usVersion = userStory.version || "";
        return usVersion === faseGroup;
      });
    }

    // Filtro por PRIORIDAD sobre las US del detalle expandido, igual que a
    // nivel de Epic (T-AF036-US01-07): con el filtro de criticidad activo,
    // las US que no cumplen el criterio no deben aparecer dentro de la Epic
    // aunque la Epic en su conjunto matchee por otra US/task.
    if (backlogSection.filterPriority !== "all") {
      filteredUserStories = filteredUserStories.filter(function (userStory) {
        if (backlogSection.filterPriority === "none") {
          return !userStory.priority;
        }
        return userStory.priority === backlogSection.filterPriority;
      });
    }

if (filteredUserStories.length === 0) {
      // T-AF036-US01-07: mensaje explícito cuando no hay User Stories que
      // coincidan con el filtro activo.
      if (backlogFiltersActive()) {
        box.appendChild(h("div", "job-detail-field", "(ninguna que coincida con el filtro activo)"));
      } else {
        box.appendChild(h("div", "job-detail-field", "(ninguna)"));
      }
    }

    // Tres bloques dentro del detalle de la Epic, en este orden: US
    // pendientes, US fuera de roadmap y US terminadas. Solo aparece la US
    // en el bloque que le corresponde — una US OUT_OF_SCOPE/FUERA_ROADMAP
    // no se muestra en el apartado de pendientes como si fuera trabajo
    // activo (decisión del usuario, 2026-08-25). "Fuera de roadmap" y
    // "Terminadas" son bloques colapsables, mismo criterio visual que el
    // grupo "Terminadas" de Epics en la vista "Por Versión".
    var openUserStories = [];
    var fueraRoadmapUserStories = [];
    var doneUserStories = [];
    filteredUserStories.forEach(function (userStory) {
      if (userStory.state === "DONE") {
        doneUserStories.push(userStory);
      } else if (isFueraRoadmapState(userStory.state)) {
        fueraRoadmapUserStories.push(userStory);
      } else {
        openUserStories.push(userStory);
      }
    });

    openUserStories.forEach(function (userStory) {
      renderUserStoryCard(box, userStory);
    });

    var byFaseOpen = backlogSection.byFaseOpen[faseGroup || "all"];
    if (!byFaseOpen) backlogSection.byFaseOpen[faseGroup || "all"] = byFaseOpen = {};

    if (fueraRoadmapUserStories.length > 0) {
      var fueraKey = "us-fuera-roadmap-" + (faseGroup || "all");
      var fueraOpen = !!backlogSection.byFaseOpen[faseGroup || "all"][fueraKey];
      var fueraHeader = button(
        (fueraOpen ? "▼ " : "▶ ") + "Fuera de roadmap (" + fueraRoadmapUserStories.length + ")",
        "backlog-done-header"
      );
      fueraHeader.addEventListener("click", function () {
        backlogSection.byFaseOpen[faseGroup || "all"][fueraKey] = !backlogSection.byFaseOpen[faseGroup || "all"][fueraKey];
        renderBacklogBody();
      });
      box.appendChild(fueraHeader);
      if (fueraOpen) {
        fueraRoadmapUserStories.forEach(function (userStory) {
          renderUserStoryCard(box, userStory);
        });
      }
    }

    if (doneUserStories.length > 0) {
      var doneKey = "us-done-" + (faseGroup || "all");
      var doneOpen = !!backlogSection.byFaseOpen[faseGroup || "all"][doneKey];
      var doneHeader = button(
        (doneOpen ? "▼ " : "▶ ") + "Terminadas (" + doneUserStories.length + ")",
        "backlog-done-header"
      );
      doneHeader.addEventListener("click", function () {
        backlogSection.byFaseOpen[faseGroup || "all"][doneKey] = !backlogSection.byFaseOpen[faseGroup || "all"][doneKey];
        renderBacklogBody();
      });
      box.appendChild(doneHeader);
      if (doneOpen) {
        doneUserStories.forEach(function (userStory) {
          renderUserStoryCard(box, userStory);
        });
      }
    }

    // T-AF036-US16-06: los tres botones de acción del detalle de Epic —
    // "+ Nueva User Story", "Proponer User Stories" y "Revisar cobertura" —
    // se agrupan en UN solo `.accion-controls` (flex row + wrap + gap) para
    // que queden alineados en una fila horizontal, no apilados. Cada botón
    // conserva su acción y single-flight; los mensajes de error/resultado se
    // pintan debajo de la fila (sin romper el layout).

    // T-AF036-US02-05: "+ Nueva User Story" — abre el formulario inline
    // (T8) con `epic_id` heredado del contexto (`detail.id`).
    var newUsBtn = button("+ Nueva User Story", "backlog-new-epic-btn");
    newUsBtn.addEventListener("click", function () {
      backlogSection.newUserStoryForm = {
        epicId: detail.id,
        id: "",
        title: "",
        objetivo: "",
        criterios: "",
        priority: "",
        submitting: false,
        error: null,
      };
      renderBacklogBody();
    });

    // T-AF036-US10-01: "Proponer User Stories" — vía automática/alternativa
    // a los formularios manuales, con single-flight por epic_id.
    var proposeStoriesBtn = button(
      backlogSection.proposeStoriesInFlight === detail.id ? "Proponiendo User Stories…" : "Proponer User Stories",
      "accion-run"
    );
    if (backlogSection.proposeStoriesInFlight === detail.id) proposeStoriesBtn.disabled = true;
    proposeStoriesBtn.addEventListener("click", function () {
      proposeStoriesAction(detail.id);
    });

    // T-AF036-US05-01: "Revisar cobertura" — single-flight por epic_id.
    var coverageBtn = button(
      backlogSection.coverageInFlight === detail.id ? "Revisando cobertura…" : "Revisar cobertura",
      "accion-run"
    );
    if (backlogSection.coverageInFlight === detail.id) coverageBtn.disabled = true;
    coverageBtn.addEventListener("click", function () {
      reviewCoverageAction(detail.id);
    });

    var actionRow = h("div", "accion-controls");
    actionRow.appendChild(newUsBtn);
    actionRow.appendChild(proposeStoriesBtn);
    actionRow.appendChild(coverageBtn);
    box.appendChild(actionRow);

    // Formulario inline de nueva User Story (aparece tras la fila de
    // acciones).
    if (backlogSection.newUserStoryForm !== null && backlogSection.newUserStoryForm.epicId === detail.id) {
      box.appendChild(renderNewUserStoryForm());
    }

    // Mensajes de "Proponer User Stories" (error/resultado verbatim).
    if (backlogSection.proposeStoriesError) {
      box.appendChild(h("p", "agent-error", backlogSection.proposeStoriesError));
    }
    if (backlogSection.proposeStoriesResult) {
      var storiesResult = backlogSection.proposeStoriesResult;
      var storyIds = (storiesResult.stories || []).map(function (s) { return s.id; }).join(", ");
      var storyWord = storiesResult.num_stories === 1 ? "User Story" : "User Stories";
      box.appendChild(
        h(
          "p",
          "job-hint",
          storiesResult.num_stories + " " + storyWord +
          " propuesta" + (storiesResult.num_stories === 1 ? "" : "s") +
          (storyIds ? ": " + storyIds : "") +
          " — el listado se ha refrescado."
        )
      );
    }

    // Mensajes de "Revisar cobertura" (error/resultado verbatim).
    if (backlogSection.coverageError) {
      box.appendChild(h("p", "agent-error", backlogSection.coverageError));
    }
    if (backlogSection.coverageResult) {
      box.appendChild(renderCoverageResult(backlogSection.coverageResult));
    }

    return box;
  }

  // Render de una tarjeta de User Story dentro del detalle expandido de
  // una Epic (T-AF018-US03-01 refactor de `renderEpicDetail`): extraído a
  // función propia para poder reutilizarlo tanto en el listado de US
  // pendientes como en el grupo colapsable "Terminadas" del final.
  function renderUserStoryCard(box, userStory) {
    var selected = isItemExpanded(userStory.id);
    var todoClass = userStory.state === "DONE" ? " backlog-epic-done" : " backlog-epic-active";
    // T-AF036-US09-01: User Story postergada (OUT_OF_SCOPE/FUERA_ROADMAP)
    // -> clase de tarjeta propia con color/atenuación distintivos, no
    // confundible con el resto de estados.
    var fueraRoadmapClass = isFueraRoadmapState(userStory.state) ? " backlog-fuera-roadmap" : "";
    var itemCard = h("div", "job-card" + todoClass + fueraRoadmapClass + (selected ? " job-card-selected" : ""));
    // T-AF036-US01-04, T7: id de anclaje para el scroll del badge "N
    // bloqueadas" (ver `scrollToFirstBlockedUS`).
    itemCard.id = "backlog-us-" + userStory.id;
    // T-AF036-US01-09: indicador de número de Tasks visible antes de
    // expandir la US — mismo criterio de layout que T-AF036-US01-08
    // (id/estado a la izquierda, indicador a la derecha, misma
    // línea). `task_count` viene ya calculado por el backend
    // (`build_epic_detail`), sin fetch adicional.
    var taskCount = typeof userStory.task_count === "number" ? userStory.task_count : 0;
    var taskCountText = taskCount === 0 ? "Sin Tasks" : taskCount + " Tasks";
    var taskCountClass = taskCount === 0 ? "backlog-us-task-count-zero" : "backlog-us-task-count-some";
    var itemLine = h("div", "job-line backlog-us-line" + (selected ? " job-line-selected" : ""));
    itemLine.appendChild(
      h(
        "span",
        "backlog-us-line-title" + (isFueraRoadmapState(userStory.state) ? " backlog-us-line-title--fuera-roadmap" : ""),
        // T-AF036-US19-02: ID + nombre (título); el estado genérico ya NO
        // va en el texto de la línea (queda solo en el `<select>`). Excepción:
        // el estado especial "fuera de roadmap" (OUT_OF_SCOPE) conserva su
        // etiqueta visible, tal como exige US-AF036-09. Si el `title` es
        // null/vacío, se muestra solo el ID. T-AF036-US19-03: el backend
        // rellena `title` con el `id` cuando el frontmatter no declara
        // `title` (fallback T-AF036-US19-01); por eso además del null/vacío
        // se compara `title !== userStory.id` para no duplicar el ID.
        (userStory.title && userStory.title !== userStory.id
          ? userStory.id + " · " + userStory.title
          : userStory.id)
          + (isFueraRoadmapState(userStory.state) ? " — Fuera de roadmap" : "")
      )
    );
    // La cabecera de la US solo muestra código + título (arriba) y los
    // controles de prioridad/estado/versión (debajo, `renderPriorityStateControls`).
    // La fecha de última actualización vive en el detalle expandido
    // (`renderItemDetail`), no en la línea.
    var stateSelect = renderPriorityStateControls(userStory.id, userStory.priority, userStory.state, "US", userStory.version);
    if (stateSelect) itemLine.appendChild(stateSelect);
    // T-AF036-US08-01: la línea de la US es clicable para desplegar/plegar
    // el detalle (`toggleItemDetail`); los `<select>` de prioridad/estado/
    // versión usan `stopPropagation` para no disparar el toggle al tocarlos.
    itemLine.tabIndex = 0;
    itemLine.setAttribute("role", "button");
    itemLine.setAttribute("aria-expanded", selected ? "true" : "false");
    itemLine.addEventListener("click", function () {
      toggleItemDetail(userStory.id);
    });
    itemCard.appendChild(itemLine);
    if (backlogSection.editItemError && backlogSection.editItemErrorFor === userStory.id) {
      itemCard.appendChild(h("p", "agent-error", backlogSection.editItemError));
    }
    itemCard.appendChild(h("div", "job-hint", selected ? "▲ Plegar detalle" : "▼ Ver detalle"));
    if (selected) {
      itemCard.appendChild(renderItemDetail(userStory.id));
    }
    box.appendChild(itemCard);
  }

  // T-AF036-US05-01: pinta el resultado del detector de cobertura de una
  // Epic. Cuando la Epic no declara alcance (`declared_alcance: null`) se
  // muestra el mensaje explícito del backend — nunca un resultado vacío
  // ambiguo. Con alcance, se muestra el texto crudo, los huecos detectados
  // (si los hay) y el aviso de aproximación.
  function renderCoverageResult(result) {
    var box = h("div", "accion-result");
    if (result.declared_alcance === null || result.declared_alcance === undefined) {
      box.appendChild(h("p", "section-note", result.message || "No se puede calcular cobertura."));
      return box;
    }
    box.appendChild(h("div", "accion-result-title", "Alcance v1 declarado"));
    box.appendChild(h("pre", "accion-result-code", result.declared_alcance));
    var gaps = result.gaps || [];
    if (gaps.length === 0) {
      box.appendChild(h("p", "job-hint", "Sin huecos detectados: cada punto del alcance tiene cobertura clara en las User Stories/Tasks reales."));
    } else {
      box.appendChild(h("div", "accion-result-title", "Huecos detectados (sin cobertura clara)"));
      var gapList = h("ul", "accion-result-gaps");
      gaps.forEach(function (gap) {
        gapList.appendChild(h("li", null, gap));
      });
      box.appendChild(gapList);
    }
    if (result.message) {
      box.appendChild(h("p", "section-note", result.message));
    }
    return box;
  }

  // T-AF008-US10-03: carga (o recarga) el snapshot de GET /backlog/queue
  // — se dispara al entrar a la sección Backlog, y de nuevo tras cada
  // acción de encolar/desencolar con éxito (mismo criterio de refresco
  // que el resto de esta pantalla: éxito refresca el listado/detalle
  // real, nunca se asume el estado nuevo sin confirmarlo contra el
  // backend). Sin single-flight propio: una recarga solapada con otra
  // en curso simplemente sobreescribe con el resultado que llegue
  // último, mismo criterio ya usado por `refreshBacklogReport`.
  function loadDispatchQueue() {
    BackendClient.getDispatchQueue()
      .then(function (queue) {
        backlogSection.dispatchQueue = queue;
        backlogSection.dispatchQueueError = null;
        pipelineSection.dispatchQueue = queue;
        pipelineSection.dispatchQueueError = null;
        if (state.section === "backlog") renderBacklogBody();
        else if (state.section === "pipeline") renderPipelineBody();
      })
      .catch(function (error) {
        backlogSection.dispatchQueueError = buildErrorMessage(error);
        pipelineSection.dispatchQueueError = buildErrorMessage(error);
        if (state.section === "backlog") renderBacklogBody();
        else if (state.section === "pipeline") renderPipelineBody();
      });
  }

  // T-AF036-US12-01: ciclo de polling del panel de la cola de despacho —
  // re-renderiza SOLO si el contenido cambió (comparación del nuevo
  // GET /backlog/queue con el estado actual), para no perturbar el scroll ni
  // hacer parpadear la interfaz en cada ciclo. T-AF042-US01-02: mantiene al
  // día el snapshot de AMBAS secciones (Backlog usa el dato para las acciones
  // de fila; Pipeline muestra el panel) y re-renderiza la sección activa.
  function pollDispatchQueue() {
    BackendClient.getDispatchQueue()
      .then(function (queue) {
        backlogSection.dispatchQueueError = null;
        pipelineSection.dispatchQueueError = null;
        var backlogChanged = JSON.stringify(queue) !== JSON.stringify(backlogSection.dispatchQueue);
        var pipelineChanged = JSON.stringify(queue) !== JSON.stringify(pipelineSection.dispatchQueue);
        backlogSection.dispatchQueue = queue;
        pipelineSection.dispatchQueue = queue;
        if (state.section === "pipeline" && pipelineChanged) renderPipelineBody();
        else if (state.section === "backlog" && backlogChanged) renderBacklogBody();
      })
      .catch(function (error) {
        backlogSection.dispatchQueueError = buildErrorMessage(error);
        pipelineSection.dispatchQueueError = buildErrorMessage(error);
        if (state.section === "backlog") renderBacklogBody();
        else if (state.section === "pipeline") renderPipelineBody();
      });
  }

  // T-AF036-US12-01: timer de polling mientras la sección del panel de la cola
  // (Pipeline, T-AF042-US01-02) está abierta — mismo patrón de
  // `startRolesPolling`/`stopRolesPolling`.
  function startDispatchQueuePolling() {
    if (pipelineSection.dispatchQueuePollTimer) return;
    pipelineSection.dispatchQueuePollTimer = setInterval(function () {
      if (state.section !== "pipeline") { stopDispatchQueuePolling(); return; }
      pollDispatchQueue();
    }, POLL_INTERVAL_MILLIS);
  }

  function stopDispatchQueuePolling() {
    if (pipelineSection.dispatchQueuePollTimer) {
      clearInterval(pipelineSection.dispatchQueuePollTimer);
      pipelineSection.dispatchQueuePollTimer = null;
    }
  }

  // `null` si `taskId` no aparece en ningún grupo de la cola cargada —
  // usado tanto para decidir el texto del botón ("Marcar para
  // desarrollo" vs. "Quitar de la cola") como para el propio panel de
  // cola. Cruce en frontend sobre datos ya cargados, sin fetch
  // adicional — mismo criterio ya usado en el resto de esta pantalla
  // (`items_bloqueada`, `blockedItemsForEpic`).
  function dispatchQueueEntryForTask(taskId) {
    var queue = backlogSection.dispatchQueue;
    if (!queue) return null;
    var groups = [queue.queued || [], queue.dispatched || [], queue.failed || []];
    for (var i = 0; i < groups.length; i++) {
      for (var j = 0; j < groups[i].length; j++) {
        if (groups[i][j].task_id === taskId) return groups[i][j];
      }
    }
    return null;
  }

  // T-AF036-US08-01: recarga cualquier detalle expandido que pueda estar
  // mostrando `itemId` en este momento — una User Story vive tanto en
  // `epicDetail.user_stories[]` (fila dentro de la Epic) como, si está
  // ella misma expandida, en `itemDetail`; una Task vive en
  // `itemDetail.tasks[]` (fila dentro de su US) y, si está expandida
  // dentro de esa US, en `nestedTaskDetail`. Tras un PUT con éxito se
  // refrescan TODOS los que apliquen (fetch real contra el backend, no
  // parcheado en memoria) — mismo criterio de "único origen de verdad"
  // que el resto de esta pantalla (`toggleEpicDetail`/`toggleItemDetail`).
  function refreshOpenDetailsFor(itemId) {
    // T-AF036-US27-03: en modo multi, refresca TODAS las Epics y US abiertas
    // (mapas), sin dejar ninguna obsoleta.
    if (isMultiMode()) {
      Object.keys(backlogSection.expandedEpicIds).forEach(function (epicId) {
        BackendClient.getBacklogItem(epicId).then(function (detail) {
          if (!isEpicExpanded(epicId)) return;
          backlogSection.epicDetails[epicId].detail = detail;
          renderBacklogBody();
        });
      });
      Object.keys(backlogSection.expandedItemIds).forEach(function (openId) {
        BackendClient.getBacklogItem(openId).then(function (detail) {
          if (!isItemExpanded(openId)) return;
          backlogSection.itemDetails[openId].detail = detail;
          renderBacklogBody();
        });
      });
      if (backlogSection.selectedNestedTaskId !== null) {
        var nestedId = backlogSection.selectedNestedTaskId;
        BackendClient.getBacklogItem(nestedId).then(function (detail) {
          if (backlogSection.selectedNestedTaskId !== nestedId) return;
          backlogSection.nestedTaskDetail = detail;
          renderBacklogBody();
        });
      }
      return;
    }
    if (backlogSection.selectedEpicId !== null) {
      var epicId = backlogSection.selectedEpicId;
      BackendClient.getBacklogItem(epicId).then(function (detail) {
        if (backlogSection.selectedEpicId !== epicId) return;
        backlogSection.epicDetail = detail;
        renderBacklogBody();
      });
    }
    if (backlogSection.selectedItemId !== null) {
      var selectedId = backlogSection.selectedItemId;
      BackendClient.getBacklogItem(selectedId).then(function (detail) {
        if (backlogSection.selectedItemId !== selectedId) return;
        backlogSection.itemDetail = detail;
        renderBacklogBody();
      });
    }
    if (backlogSection.selectedNestedTaskId !== null) {
      var nestedId = backlogSection.selectedNestedTaskId;
      BackendClient.getBacklogItem(nestedId).then(function (detail) {
        if (backlogSection.selectedNestedTaskId !== nestedId) return;
        backlogSection.nestedTaskDetail = detail;
        renderBacklogBody();
      });
    }
  }

  // T-AF036-US08-01, criterio de aceptación 1: cambia la prioridad de una
  // User Story/Task desde el `<select>` de su línea de título, sin
  // desplegar el detalle. Single-flight por `itemId` (mismo criterio que
  // `enqueueTaskAction`). Éxito: refresca el listado raíz completo
  // (`refreshBacklogReport`, barra de progreso/badges/filtros) y
  // cualquier detalle expandido que muestre este item — nunca recarga la
  // página. Error: se muestra verbatim, la selección hecha por el
  // usuario en el `<select>` no se toca (el propio DOM del control ya
  // quedó con el valor elegido; solo se revierte si el caller vuelve a
  // pintar desde el estado real tras el refresco).
  function setItemPriorityAction(itemId, newPriority) {
    if (backlogSection.editItemInFlight) return;
    backlogSection.editItemInFlight = itemId;
    backlogSection.editItemError = null;
    backlogSection.editItemErrorFor = null;
    renderBacklogBody();

    BackendClient.setBacklogItemPriority(itemId, newPriority)
      .then(function () {
        backlogSection.editItemInFlight = null;
        refreshBacklogReport();
        refreshOpenDetailsFor(itemId);
        renderBacklogBody();
      })
      .catch(function (error) {
        backlogSection.editItemInFlight = null;
        backlogSection.editItemError = buildErrorMessage(error);
        backlogSection.editItemErrorFor = itemId;
        renderBacklogBody();
      });
  }

  // T-AF036-US14-02: cambia la fase de una Epic/User Story desde el editor
  // inline del detalle, sin recargar la página. Single-flight por `itemId`
  // (mismo criterio que `setItemPriorityAction`). Éxito: refresca el
  // informe (`refreshBacklogReport`, la vista "Por Fase" reagrupa el item
  // en su nueva fase) y cualquier detalle expandido. Error: se muestra
  // verbatim sin romper la fila.
  function setItemFaseAction(itemId, newFase) {
    if (backlogSection.editItemInFlight) return;
    backlogSection.editItemInFlight = itemId;
    backlogSection.editItemError = null;
    backlogSection.editItemErrorFor = null;
    renderBacklogBody();

    BackendClient.setBacklogItemFase(itemId, newFase)
      .then(function () {
        backlogSection.editItemInFlight = null;
        refreshBacklogReport();
        refreshOpenDetailsFor(itemId);
        renderBacklogBody();
      })
      .catch(function (error) {
        backlogSection.editItemInFlight = null;
        backlogSection.editItemError = buildErrorMessage(error);
        backlogSection.editItemErrorFor = itemId;
        renderBacklogBody();
      });
  }

  // T-AF036-US26-03: cambia la versión de una Epic/User Story vía
  // `PUT /backlog/{item_id}/version` (T-AF036-US25-02), sin recargar.
  // Éxito: refresca el informe y el detalle abierto. Error (valor inválido
  // del backend): se muestra verbatim sin dejar el input con el valor
  // inconsistente (el detalle conserva el `version` persistido en el re-render).
  function setItemVersionAction(itemId, newVersion) {
    if (backlogSection.editItemInFlight) return;
    backlogSection.editItemInFlight = itemId;
    backlogSection.editItemError = null;
    backlogSection.editItemErrorFor = null;
    renderBacklogBody();

    BackendClient.setBacklogItemVersion(itemId, newVersion)
      .then(function () {
        backlogSection.editItemInFlight = null;
        refreshBacklogReport();
        refreshOpenDetailsFor(itemId);
        renderBacklogBody();
      })
      .catch(function (error) {
        backlogSection.editItemInFlight = null;
        backlogSection.editItemError = buildErrorMessage(error);
        backlogSection.editItemErrorFor = itemId;
        renderBacklogBody();
      });
  }

  // T-AF036-US14-02: editor inline de fase (input de texto libre + botón
  // Guardar) para el detalle expandido de una Epic/User Story — muestra el
  // valor actual (placeholder "SIN_ASIGNAR" si ausente/vacío) y persiste vía
  // `PUT /backlog/{item_id}/fase`. `stopPropagation` para no plegar el
  // detalle al interactuar.
  function renderFaseEditor(itemId, currentFase) {
    var wrap = h("div", "job-detail-field backlog-fase-editor");
    wrap.appendChild(h("span", "job-detail-label", "Fase: "));
    var input = document.createElement("input");
    input.type = "text";
    input.className = "backlog-fase-input";
    input.placeholder = "SIN_ASIGNAR";
    input.value = currentFase || "";
    input.addEventListener("click", function (event) { event.stopPropagation(); });
    input.addEventListener("keydown", function (event) {
      event.stopPropagation();
      if (event.key === "Enter") setItemFaseAction(itemId, input.value.trim() || null);
    });
    wrap.appendChild(input);
    var btn = button("Guardar");
    btn.addEventListener("click", function (event) {
      event.stopPropagation();
      setItemFaseAction(itemId, input.value.trim() || null);
    });
    wrap.appendChild(btn);
    return wrap;
  }

  // T-AF036-US26-03: editor inline de VERSIÓN (input de texto + botón
  // Guardar) para el detalle expandido de una Epic/User Story — sustituye a
  // `renderFaseEditor`. Muestra el valor actual (placeholder "SIN VERSIÓN" si
  // ausente/vacío) y persiste vía `PUT /backlog/{item_id}/version` (conjunto
  // cerrado validado en servidor). `stopPropagation` para no plegar el
  // detalle al interactuar.
  function renderVersionEditor(itemId, currentVersion) {
    var wrap = h("div", "job-detail-field backlog-version-editor");
    wrap.appendChild(h("span", "job-detail-label", "Versión: "));
    var input = document.createElement("input");
    input.type = "text";
    input.className = "backlog-version-input";
    input.placeholder = "SIN VERSIÓN";
    input.value = currentVersion || "";
    input.addEventListener("click", function (event) { event.stopPropagation(); });
    input.addEventListener("keydown", function (event) {
      event.stopPropagation();
      if (event.key === "Enter") setItemVersionAction(itemId, input.value.trim() || null);
    });
    wrap.appendChild(input);
    var btn = button("Guardar");
    btn.addEventListener("click", function (event) {
      event.stopPropagation();
      setItemVersionAction(itemId, input.value.trim() || null);
    });
    wrap.appendChild(btn);
    return wrap;
  }

  // T-AF036-US08-01, criterio de aceptación 1/2: cambia el estado de una
  // User Story/Task desde el `<select>` de su línea de título. Si el
  // backend reporta `promoted_epics` no vacío (US marcada DONE dejó a su
  // Epic con todos los hijos DONE), el refresco del listado raíz ya basta
  // para reflejar la Epic promocionada (mismo dato que
  // `refreshBacklogReport` siempre trae) — no hace falta ningún caso
  // especial aparte.
  function setItemStateAction(itemId, newState) {
    if (backlogSection.editItemInFlight) return;
    backlogSection.editItemInFlight = itemId;
    backlogSection.editItemError = null;
    backlogSection.editItemErrorFor = null;
    renderBacklogBody();

    BackendClient.setBacklogItemState(itemId, newState)
      .then(function (result) {
        backlogSection.editItemInFlight = null;
        // T-AF008-US14-04: marcar una User Story como EN_DESARROLLO desde
        // este selector es un atajo del mismo efecto que "Marcar toda la
        // Story para desarrollo" — el backend devuelve `enqueued`/
        // `skipped_already_queued` en ese caso (T-AF036-US16-02: se retiró
        // el botón/acción explícita; el atajo por estado se conserva como
        // único camino). Se refresca la cola de despacho al detectar que se
        // encolaron tasks.
        if (result && result.enqueued) {
          loadDispatchQueue();
        }
        refreshBacklogReport();
        refreshOpenDetailsFor(itemId);
        renderBacklogBody();
      })
      .catch(function (error) {
        backlogSection.editItemInFlight = null;
        backlogSection.editItemError = buildErrorMessage(error);
        backlogSection.editItemErrorFor = itemId;
        renderBacklogBody();
      });
  }

  var EDITABLE_PRIORITIES = ["Crítica", "Alta", "Media", "Baja"];
  // T-AF008-US14-01: EN_DESARROLLO añadido al conjunto editable — alineado con
  // `validator_v2._VALID_STATES`/`backlog/edit.py::VALID_STATES`
  // (backend).
  //
  // T-AF008-US15-01/-02 (2026-08-17): `NO_TASKS`/`TO_PLAN` (AF-040;
  // antes EN_DISEÑO) incluidos como `<option>` — necesario para que el
  // `<select>` HTML muestre correctamente el estado ACTUAL de una User
  // Story recién creada (nace en `NO_TASKS`) o en tránsito (`TO_PLAN`),
  // aunque el flujo normal para entrar/salir de esos estados es el botón
  // único "Progresar" (`renderProgresarUserStoryControls`), no este
  // selector — mismo criterio que ya aplica a `TO_DEVELOP`/`DONE`: el
  // selector permite corrección manual excepcional, no sustituye el flujo
  // guiado.
  //
  // T-AF036-US09-01 (US-AF036-09, criterio 3): `OUT_OF_SCOPE` (AF-040;
  // antes FUERA_ROADMAP) AÑADIDO como `<option>` — el selector de estado
  // genérico de US-AF036-08 es el control reutilizado para marcar/
  // desmarcar "fuera de roadmap" (no se duplica ningún control). El
  // backend lo acepta (`set_item_state` valida contra `VALID_STATES`,
  // que incluye OUT_OF_SCOPE).
  var EDITABLE_STATES = ["NO_TASKS", "TO_PLAN", "READY", "TO_DEVELOP", "IN_PROGRESS", "IN_REVIEW", "DONE", "OUT_OF_SCOPE"];

  // T-AF036-US26-03: versiones de entrega asignables en el selector de la
  // cabecera de una User Story — coherente con `VALID_VERSIONS` del backend
  // (`atlas_forge/backlog/edit.py`) y con `.atlas-forge/version.yml`
  // (`open: 0.9`, `future: [0.9.1, 0.9.2]`).
  var BACKLOG_VERSIONS = ["0.9", "0.9.1", "0.9.2"];

  // T-AF036-US22-02: réplica en cliente de las transiciones legales de la
  // máquina canónica (`atlas_forge/core/state_machines.py`) — usada para
  // DESHABILITAR en el selector de estado las opciones no permitidas desde
  // el estado actual. La fuente de verdad sigue siendo el backend
  // (T-AF036-US22-01 lo rechaza con 400), así que si esta réplica se
  // desincronizara, el backend corta la transición ilegal.
  var STATE_TRANSITIONS = {
    T: {
      "READY": ["TO_DEVELOP"],
      "TO_DEVELOP": ["READY", "IN_PROGRESS"],
      "IN_PROGRESS": ["IN_REVIEW"],
      "IN_REVIEW": ["IN_PROGRESS", "DONE"],
      "DONE": [],
    },
    US: {
      "NO_TASKS": ["TO_PLAN", "OUT_OF_SCOPE"],
      "TO_PLAN": ["READY", "TO_DEVELOP", "IN_PROGRESS", "IN_REVIEW", "OUT_OF_SCOPE"],
      "READY": ["TO_DEVELOP", "IN_PROGRESS", "IN_REVIEW", "OUT_OF_SCOPE"],
      "TO_DEVELOP": ["READY", "IN_PROGRESS", "IN_REVIEW", "OUT_OF_SCOPE"],
      "IN_PROGRESS": ["READY", "TO_DEVELOP", "IN_REVIEW", "OUT_OF_SCOPE"],
      "IN_REVIEW": ["DONE", "OUT_OF_SCOPE"],
      "DONE": ["OUT_OF_SCOPE"],
      "OUT_OF_SCOPE": [],
    },
  };
  function isLegalStateTransition(kind, fromState, toState) {
    var transitions = (STATE_TRANSITIONS[kind] || {})[fromState] || [];
    return transitions.indexOf(toState) !== -1;
  }

  // T-AF036-US09-01: estados "fuera de roadmap" (postergada). El
  // vocabulario canónico de User Story es `OUT_OF_SCOPE` (AF-040; antes
  // FUERA_ROADMAP); las Epics conservan `FUERA_ROADMAP`
  // (`EPIC_STATES`). Ambos se muestran igual: etiqueta "Fuera de
  // roadmap" + color/badge propio no confundible con el resto de estados.
  var FUERA_ROADMAP_STATES = { "OUT_OF_SCOPE": true, "FUERA_ROADMAP": true };
  function isFueraRoadmapState(state) {
    return FUERA_ROADMAP_STATES[state] === true;
  }
  // Etiqueta legible para el estado de un item — los estados "fuera de
  // roadmap" se muestran como "Fuera de roadmap" en vez del valor crudo.
  function stateDisplayLabel(state) {
    return isFueraRoadmapState(state) ? "Fuera de roadmap" : (state || "desconocido");
  }

  // T-AF036-US13-03: fase del roadmap legible para el encabezado — el valor
  // crudo si existe, "SIN_ASIGNAR" si está ausente/vacío (mismo criterio de
  // agrupación que la vista "Por Fase").
  function faseHeaderLabel(fase) {
    return fase ? fase : "SIN_ASIGNAR";
  }

  // T-AF036-US26-02: etiqueta de versión visible en las cabeceras de
  // US/Task — el valor crudo si existe, "SIN VERSIÓN" si está ausente/vacío
  // (mismo criterio de agrupación que la vista "Por Versión").
  function versionHeaderLabel(version) {
    return version ? version : "SIN VERSIÓN";
  }

  // T-AF036-US13-03: convierte el timestamp ISO-8601 UTC de `updated_at` a
  // fecha/hora local legible "YYYY-MM-DD HH:MM" (mismo criterio que el resto
  // de timestamps que la web ya formatea). Devuelve "—" si es `null`/inválido
  // (retrocompatibilidad con items creados antes de la US-AF036-13).
  function formatUpdatedAt(updatedAt) {
    if (!updatedAt) return "—";
    try {
      var when = new Date(updatedAt);
      if (isNaN(when.getTime())) return "—";
      var y = when.getFullYear();
      var m = String(when.getMonth() + 1).padStart(2, "0");
      var d = String(when.getDate()).padStart(2, "0");
      var hh = String(when.getHours()).padStart(2, "0");
      var mm = String(when.getMinutes()).padStart(2, "0");
      return y + "-" + m + "-" + d + " " + hh + ":" + mm;
    } catch (_e) {
      return "—";
    }
  }

  // T-AF036-US08-01, criterio de aceptación 1/5: los dos `<select>` de
  // prioridad/estado en la línea de título — solo para User Story/Task
  // (nunca Epic, que ni siquiera llega a llamar a esta función: su
  // `priority` no existe en el esquema y su `state` solo cambia por
  // promoción automática). `stopPropagation` en ambos: la línea entera
  // es clicable para expandir/plegar el detalle (`toggleEpicDetail`/
  // `toggleItemDetail`/`toggleNestedTaskDetail`), y estos controles viven
  // DENTRO de esa línea — sin cortar la propagación, tocar el `<select>`
  // también desplegaría/plegaría el detalle.
  function renderPriorityStateControls(itemId, currentPriority, currentState, kind, currentVersion) {
    var wrap = h("span", "backlog-edit-controls");
    var inFlight = backlogSection.editItemInFlight === itemId;

    var prioritySelect = document.createElement("select");
    prioritySelect.className = "backlog-edit-priority";
    prioritySelect.disabled = inFlight;
    var noneOption = document.createElement("option");
    noneOption.value = "";
    noneOption.textContent = "Sin prioridad";
    if (!currentPriority) noneOption.selected = true;
    prioritySelect.appendChild(noneOption);
    EDITABLE_PRIORITIES.forEach(function (p) {
      var option = document.createElement("option");
      option.value = p;
      option.textContent = p;
      if (currentPriority === p) option.selected = true;
      prioritySelect.appendChild(option);
    });
    prioritySelect.addEventListener("click", function (event) {
      event.stopPropagation();
    });
    prioritySelect.addEventListener("change", function (event) {
      event.stopPropagation();
      setItemPriorityAction(itemId, prioritySelect.value || null);
    });
    wrap.appendChild(prioritySelect);

    var stateSelect = document.createElement("select");
    // T-AF008-US14-01, criterio "distinguible visualmente": clase
    // modificadora cuando el estado ACTUAL es TO_DEVELOP (AF-040; antes
    // EN_DESARROLLO) — mismo patrón que el resto de la pantalla, un color
    // propio no confundible con READY/IN_PROGRESS/IN_REVIEW/DONE (ver
    // `.backlog-edit-state--to-develop` en style.css). T-AF008-US15-01/-02:
    // mismo criterio para NO_TASKS/TO_PLAN, cada uno con su propia
    // clase/color.
    // T-AF008-US15-01/-02: mismo criterio para NO_TASKS/TO_PLAN, cada
    // uno con su propia clase/color. T-AF036-US09-01: mismo criterio
    // para OUT_OF_SCOPE (US postergada), con su color propio.
    var STATE_CSS_CLASS = {
      "TO_DEVELOP": "backlog-edit-state--to-develop",
      "NO_TASKS": "backlog-edit-state--no-tasks",
      "TO_PLAN": "backlog-edit-state--to-plan",
      "OUT_OF_SCOPE": "backlog-edit-state--out-of-scope",
    };
    stateSelect.className = "backlog-edit-state" + (STATE_CSS_CLASS[currentState] ? " " + STATE_CSS_CLASS[currentState] : "");
    stateSelect.disabled = inFlight;
    // T-AF036-US22-02: deshabilitar las opciones que NO son transiciones
    // legales desde el estado actual (adelante y atrás), según `kind`. El
    // estado actual queda seleccionable (es el valor mostrado).
    EDITABLE_STATES.forEach(function (s) {
      var option = document.createElement("option");
      option.value = s;
      option.textContent = s;
      if (currentState === s) option.selected = true;
      if (s !== currentState && !isLegalStateTransition(kind, currentState, s)) {
        option.disabled = true;
      }
      stateSelect.appendChild(option);
    });
    stateSelect.addEventListener("click", function (event) {
      event.stopPropagation();
    });
    stateSelect.addEventListener("change", function (event) {
      event.stopPropagation();
      setItemStateAction(itemId, stateSelect.value);
    });
    wrap.appendChild(stateSelect);

    // T-AF036-US26-03: selector de VERSIÓN en la cabecera de la User Story
    // (no en el detalle): muestra la versión actual y permite cambiarla vía
    // `PUT /backlog/{id}/version`. Solo para US y solo si el estado lo
    // permite — una US `DONE` o `IN_REVIEW` (cerrada o pendiente del
    // veredicto del Arquitecto) no puede cambiar su versión (backend
    // también lo rechaza; aquí se deshabilita antes para evitar el round-trip).
    // `stopPropagation` igual que los otros `<select>` de la línea.
    if (kind === "US") {
      var versionSelect = document.createElement("select");
      versionSelect.className = "backlog-edit-version";
      versionSelect.disabled = inFlight || (currentState === "DONE" || currentState === "IN_REVIEW");
      var noneOption = document.createElement("option");
      noneOption.value = "";
      noneOption.textContent = "Sin versión";
      if (!currentVersion || currentVersion === "null") noneOption.selected = true;
      versionSelect.appendChild(noneOption);
      BACKLOG_VERSIONS.forEach(function (v) {
        var o = document.createElement("option");
        o.value = v;
        o.textContent = v;
        if (currentVersion === v) o.selected = true;
        versionSelect.appendChild(o);
      });
      versionSelect.addEventListener("click", function (event) { event.stopPropagation(); });
      versionSelect.addEventListener("change", function (event) {
        event.stopPropagation();
        setItemVersionAction(itemId, versionSelect.value || null);
      });
      wrap.appendChild(versionSelect);
    }

    return wrap;
  }

  // T-AF008-US10-03, criterio de aceptación 1: marca/desmarca una Task
  // TO_DO para desarrollo. Single-flight por `task_id` (guarda el id en
  // vuelo, no un booleano — mismo criterio ya usado por
  // `proposeStoriesInFlight`). Éxito: refresca la cola completa (para
  // que el cambio se refleje "de inmediato en la vista de cola", mismo
  // criterio explícito del encargo) — no basta con actualizar el
  // estado local sin confirmar contra el backend real.
  function enqueueTaskAction(taskId) {
    if (backlogSection.enqueueTaskInFlight) return;
    backlogSection.enqueueTaskInFlight = taskId;
    backlogSection.enqueueTaskError = null;
    renderBacklogBody();

    BackendClient.enqueueTask(taskId)
      .then(function () {
        backlogSection.enqueueTaskInFlight = null;
        loadDispatchQueue();
        // T-AF008-US14-01: encolar ahora también escribe `state: EN_DESARROLLO`
        // en el fichero real — se refresca el detalle ya cargado de esta
        // Task para que el selector de estado de la línea de título
        // muestre el valor real de inmediato, sin esperar a un refresco
        // manual (mismo mecanismo que `setItemStateAction`).
        refreshOpenDetailsFor(taskId);
        renderBacklogBody();
      })
      .catch(function (error) {
        backlogSection.enqueueTaskInFlight = null;
        backlogSection.enqueueTaskError = buildErrorMessage(error);
        renderBacklogBody();
      });
  }

  function dequeueTaskAction(taskId) {
    if (backlogSection.enqueueTaskInFlight) return;
    backlogSection.enqueueTaskInFlight = taskId;
    backlogSection.enqueueTaskError = null;
    renderBacklogBody();

    BackendClient.dequeueTask(taskId)
      .then(function () {
        backlogSection.enqueueTaskInFlight = null;
        loadDispatchQueue();
        // T-AF008-US14-01: desencolar revierte `state` a `TO_DO` — mismo
        // motivo que en enqueueTaskAction, refrescar el detalle ya
        // cargado.
        refreshOpenDetailsFor(taskId);
        renderBacklogBody();
      })
      .catch(function (error) {
        backlogSection.enqueueTaskInFlight = null;
        backlogSection.enqueueTaskError = buildErrorMessage(error);
        renderBacklogBody();
      });
  }

  // T-AF036-US10-01: motivo real de un pipeline no aprobado, verbatim del
  // backend (criterio 3 de la Task — "no un mensaje genérico"). Se junta
  // solo lo que el backend trae: `validation_errors` (lista de strings)
  // si la validación falló, y `self_audit.justification`/`suggestions`
  // si la autoauditoría no llegó a APROBADO. Nunca inventa texto propio
  // más allá de las etiquetas de contexto.
  function proposePipelineReason(result) {
    var parts = [];
    if (result.validation_valid === false) {
      var errors = result.validation_errors || [];
      if (errors.length > 0) {
        parts.push("Validación: " + errors.join("; "));
      }
    }
    if (result.self_audit && result.self_audit.status !== "APROBADO") {
      parts.push(
        "Autoevaluación (" + result.self_audit.status + "): " +
        (result.self_audit.justification || "(sin justificación)")
      );
      var suggestions = result.self_audit.suggestions || [];
      if (suggestions.length > 0) {
        parts.push("Sugerencias: " + suggestions.join("; "));
      }
    }
    if (parts.length === 0) {
      parts.push("El pipeline no aprobó la propuesta (respuesta sin motivo detallado).");
    }
    return parts.join("\n");
  }

  // T-AF036-US10-01: refresco del detalle de la Epic abierta tras un
  // pipeline aprobado — mismo patrón lazy-fetch + guard de respuesta
  // obsoleta que `toggleEpicDetail`, para que las User Stories recién
  // escritas a disco aparezcan en el listado SIN recargar la página
  // (criterio de aceptación 1).
  function refreshEpicDetail(epicId) {
    BackendClient.getBacklogItem(epicId)
      .then(function (detail) {
        if (backlogSection.selectedEpicId !== epicId) return;
        backlogSection.epicDetail = detail;
        renderBacklogBody();
      })
      .catch(function () {
        // El detalle se queda con los datos previos; el listado raíz ya
        // se refrescó aparte (`refreshBacklogReport`), no es bloqueante.
      });
  }

  // Mismo criterio para el detalle de la User Story abierta tras
  // "Aterrizar en Tasks" (criterio de aceptación 2).
  function refreshUsDetail(usId) {
    BackendClient.getBacklogItem(usId)
      .then(function (detail) {
        if (backlogSection.selectedItemId !== usId) return;
        backlogSection.itemDetail = detail;
        renderBacklogBody();
        // T-AF036-US06-01: al refrescar el detalle de una US (p. ej. tras
        // aterrizar Tasks) se recarga también su informe de cierre.
        if (detail.kind === "US") {
          loadUsClosingReport(usId);
        }
      })
      .catch(function () {
        // Mismo criterio de robustez que `refreshEpicDetail`.
      });
  }

  // T-AF036-US10-01, "Proponer User Stories": invoca el pipeline
  // Epic→User Story del backend con single-flight por epic_id. Éxito
  // (APROBADO): refresca el detalle de la Epic + el listado raíz.
  // Pipeline no aprobado (o validación fallida): muestra el motivo
  // verbatim y no toca el listado (nada se escribió a disco).
  function proposeStoriesAction(epicId) {
    if (backlogSection.proposeStoriesInFlight) return;
    backlogSection.proposeStoriesInFlight = epicId;
    backlogSection.proposeStoriesError = null;
    backlogSection.proposeStoriesResult = null;
    renderBacklogBody();

    BackendClient.proposeStories(epicId)
      .then(function (result) {
        backlogSection.proposeStoriesInFlight = null;
        if (result.validation_valid !== true || !result.self_audit || result.self_audit.status !== "APROBADO") {
          backlogSection.proposeStoriesError = proposePipelineReason(result);
          renderBacklogBody();
          return;
        }
        backlogSection.proposeStoriesResult = result;
        renderBacklogBody();
        refreshEpicDetail(epicId);
        refreshBacklogReport();
      })
      .catch(function (error) {
        backlogSection.proposeStoriesInFlight = null;
        backlogSection.proposeStoriesError = buildErrorMessage(error);
        renderBacklogBody();
      });
  }

  // T-AF036-US05-01: revisa la cobertura del alcance v1 de una Epic
  // (`GET /backlog/epic/{epic_id}/coverage`, detector determinista-
  // aproximado). Single-flight por epic_id — el botón se deshabilita y
  // muestra "Revisando cobertura…" mientras la petición está en vuelo.
  // El resultado (o el error verbatim del backend, p. ej. el 404 de una
  // Epic sin fichero propio) se guarda en `coverageResult`/`coverageError`
  // y se pinta SOLO en el detalle de la Epic que lo generó.
  function reviewCoverageAction(epicId) {
    if (backlogSection.coverageInFlight) return;
    backlogSection.coverageInFlight = epicId;
    backlogSection.coverageError = null;
    backlogSection.coverageResult = null;
    renderBacklogBody();

    BackendClient.getEpicCoverage(epicId)
      .then(function (result) {
        backlogSection.coverageInFlight = null;
        backlogSection.coverageResult = result;
        renderBacklogBody();
      })
      .catch(function (error) {
        backlogSection.coverageInFlight = null;
        backlogSection.coverageError = buildErrorMessage(error);
        renderBacklogBody();
      });
  }

  // DEPRECATED (T-AF008-US15-02, 2026-08-17): "Aterrizar en Tasks"
  // llamaba SIEMPRE de forma síncrona a `propose-tasks` desde el
  // navegador — sustituido por el botón único "Progresar"
  // (`renderProgresarUserStoryControls`), que marca `EN_DISEÑO` y deja
  // que el Dispatcher reparta el aterrizaje al Arquitecto libre
  // (`run_us_landing_dispatch_cycle`, backend). Esta función ya no tiene
  // ningún botón que la invoque — se conserva sin borrar por si hace
  // falta reactivar el atajo síncrono en el futuro, mismo criterio de
  // "marcar deprecated, no borrar sin más" ya aplicado en esta sesión.
  function proposeTasksAction(usId) {
    if (backlogSection.proposeTasksInFlight) return;
    backlogSection.proposeTasksInFlight = usId;
    backlogSection.proposeTasksError = null;
    backlogSection.proposeTasksResult = null;
    renderBacklogBody();

    BackendClient.proposeTasks(usId)
      .then(function (result) {
        backlogSection.proposeTasksInFlight = null;
        if (result.validation_valid !== true || !result.self_audit || result.self_audit.status !== "APROBADO") {
          backlogSection.proposeTasksError = proposePipelineReason(result);
          renderBacklogBody();
          return;
        }
        backlogSection.proposeTasksResult = result;
        renderBacklogBody();
        refreshUsDetail(usId);
        refreshBacklogReport();
      })
      .catch(function (error) {
        backlogSection.proposeTasksInFlight = null;
        backlogSection.proposeTasksError = buildErrorMessage(error);
        renderBacklogBody();
      });
  }

  // T-AF008-US10-03, criterio 3/6 de US-AF008-10: panel de la cola de
  // despacho dentro de la propia pantalla Backlog — lista las Tasks
  // encoladas (ordenadas por prioridad, ya así en la respuesta del
  // backend, `GET /backlog/queue`), con su estado y agente asignado si
  // aplica, sin necesitar la pantalla Plan ni Agentes por separado.
  // Colapsable (mismo patrón que el panel "Próximo foco",
  // T-AF036-US01-02), expandido por defecto.
  var QUEUE_STATUS_LABEL = {
    queued: "Pendiente",
    dispatched: "En curso",
    awaiting_tester: "Esperando al Tester",
    completed: "Completada",
    failed: "Fallida",
  };

  function renderDispatchQueuePanel(wrap) {
    if (pipelineSection.dispatchQueue === null) return;

    var queue = pipelineSection.dispatchQueue;
    // T-AF008-US10-04: el backend ya deriva `effective_status` por
    // entrada cruzando la cola con el estado real del fichero de la Task
    // (GET /backlog/queue) — la UI solo pinta los grupos derivados y no
    // lista nunca una Task DONE/READY como "En curso". `awaiting_tester`
    // distingue el caso de retención (Developer esperando al Tester).
    var groups = [
      { key: "queued", entries: queue.queued || [] },
      { key: "dispatched", entries: queue.dispatched || [] },
      { key: "awaiting_tester", entries: queue.awaiting_tester || [] },
      { key: "completed", entries: queue.completed || [] },
      { key: "failed", entries: queue.failed || [] },
    ];
    var allEntries = [];
    groups.forEach(function (group) {
      group.entries.forEach(function (e) { allEntries.push({ entry: e, status: e.effective_status || group.key }); });
    });

    // T-AF036-US17-10: cola vacía = estado neutro SIN error. Se limpia
    // cualquier error espurio que pudiera haber quedado de un borrado/
    // requeue/poll (la cola vacía no es un fallo real) y NO se pinta el
    // panel (información neutra). Esta comprobación va ANTES del chequeo de
    // error para que una cola simplemente vacía nunca muestre un error.
    if (allEntries.length === 0) {
      pipelineSection.dispatchQueueError = null;
      return;
    }

    if (pipelineSection.dispatchQueueError) {
      wrap.appendChild(h("p", "agent-error", "Cola de despacho: " + pipelineSection.dispatchQueueError));
      return;
    }

    var panel = h("div", "backlog-focus-panel");
    var header = h("div", "backlog-focus-header");
    header.appendChild(h("span", "backlog-focus-title", "Cola de despacho (" + allEntries.length + ")"));
    // T-AF042-US06-13: sin toggle "Ocultar"/"Mostrar" — el panel se muestra
    // siempre expandido en la ventana Pipeline.
    // T-AF042-US07-01: botón "Borrar completadas" (masivo) — borra TODAS las
    // entradas completadas de la cola (las DONE), conservando failed/queued/
    // dispatched. Compite con el borrado individual (aspa/Aceptar por fila):
    // ambos coexisten. Sin confirmación.
    var hasCompleted = (queue.completed || []).length > 0;
    if (hasCompleted) {
      var clearCompletedBtn = button("Borrar completadas", "backlog-focus-toggle");
      clearCompletedBtn.addEventListener("click", function () {
        BackendClient.clearCompleted()
          .then(function () { loadDispatchQueue(); })
          .catch(function (error) {
            pipelineSection.dispatchQueueError = buildErrorMessage(error);
            renderPipelineBody();
          });
      });
      header.appendChild(clearCompletedBtn);
    }
    panel.appendChild(header);

    // T-AF042-US06-03/-09: tabla de la cola — las columnas (tarea, estado,
    // encolada, despachada, terminada, acciones) se alinean verticalmente
    // entre todas las filas porque comparten la misma `<table>` (a diferencia
    // de filas grid independientes, que no se alinean entre sí).
    var table = document.createElement("table");
    table.className = "backlog-queue-table";
    var thead = document.createElement("thead");
    var headRow = document.createElement("tr");
    ["Tarea", "Estado", "Encolada", "Despachada", "Terminada", ""].forEach(function (label, i) {
      var th = document.createElement("th");
      if (i === 0) th.className = "backlog-queue-th-task";
      th.textContent = label;
      headRow.appendChild(th);
    });
    thead.appendChild(headRow);
    table.appendChild(thead);
    var tbody = document.createElement("tbody");
    table.appendChild(tbody);

    allEntries.forEach(function (item) {
        var entry = item.entry;
        var row = document.createElement("tr");
        row.className = "backlog-queue-row";
        var statusClass =
          item.status === "failed" ? "job-status-ko" :
          item.status === "completed" ? "job-status-ok" : "job-status-run";
        var titleParts = [entry.task_id];
        if (entry.priority) titleParts.push(entry.priority);
        var titleEl = h("span", "backlog-queue-row-title", titleParts.join(" · "));
        var tdTitle = document.createElement("td");
        tdTitle.appendChild(titleEl);
        row.appendChild(tdTitle);
        var statusText = QUEUE_STATUS_LABEL[item.status] || item.status;
        if (entry.agent_name) statusText += " — " + entry.agent_name;
        var tdStatus = document.createElement("td");
        tdStatus.className = "backlog-queue-row-status " + statusClass;
        tdStatus.textContent = statusText;
        row.appendChild(tdStatus);
        // T-AF036-US17-03: fechas de las transiciones — UNA columna por
        // transición (encolada / despachada / terminada), alineadas
        // verticalmente entre filas por la tabla; "—" si no existe.
        [entry.enqueued_at, entry.dispatched_at, entry.finished_at].forEach(function (ts) {
          var td = document.createElement("td");
          td.className = "backlog-queue-row-col";
          td.textContent = ts ? formatUpdatedAt(ts) : "—";
          row.appendChild(td);
        });
        // T-AF036-US17-06/-07/-09: acciones de fila en la ÚLTIMA columna,
        // alineadas a la derecha (patrón estándar de tabla: los datos se
        // leen de izquierda a derecha y el botón vive al final de la fila).
        var tdActions = document.createElement("td");
        tdActions.className = "backlog-queue-row-actions";
        // T-AF036-US17-06: botón "Quitar" solo para filas `queued` — invoca
        // `DELETE /backlog/{task_id}/enqueue` (retira la entrada y revierte la
        // task real a `READY`) y refresca la cola y el listado del Backlog.
        // `stopPropagation` para no disparar la navegación de la fila.
        if (item.status === "queued") {
          var dequeueBtn = button("Quitar", "backlog-focus-toggle");
          dequeueBtn.title = "Quitar de la cola";
          dequeueBtn.addEventListener("click", function (event) {
            event.stopPropagation();
            BackendClient.dequeueTask(entry.task_id)
              .then(function () {
                loadDispatchQueue();
                refreshBacklogReport();
              })
              .catch(function (error) {
                pipelineSection.dispatchQueueError = buildErrorMessage(error);
                renderPipelineBody();
              });
          });
          tdActions.appendChild(dequeueBtn);
        }
        // T-AF036-US17-07/-09: botón "Aceptar" por fila `completed` (borra
        // SOLO esa entrada terminal, conservando el resto de la cola) —
        // sustituye al botón masivo "Borrar histórico". Pide confirmación,
        // llama a `DELETE /backlog/queue/entry/{task_id}` y refresca.
        if (item.status === "completed") {
          // T-AF036-US17-09: botón "Aceptar" por fila `completed` (antes aspa
          // ✕) — borra SOLO esa entrada terminal, conservando el resto de la
          // cola. Sustituye al botón masivo "Borrar histórico". Pide
          // confirmación, llama a `DELETE /backlog/queue/entry/{task_id}` y
          // refresca.
          var removeBtn = button("Aceptar", "backlog-focus-toggle backlog-queue-row-action");
          removeBtn.title = "Borrar esta entrada completada";
          removeBtn.setAttribute("aria-label", "Borrar entrada " + entry.task_id);
          removeBtn.addEventListener("click", function (event) {
            event.stopPropagation();
            BackendClient.deleteQueueEntry(entry.task_id)
              .then(function () {
                loadDispatchQueue();
              })
              .catch(function (error) {
                pipelineSection.dispatchQueueError = buildErrorMessage(error);
                renderPipelineBody();
              });
          });
          tdActions.appendChild(removeBtn);
        }
        // T-AF036-US17-08/-09: botón "Reencolar" por fila `failed` — devuelve
        // la entrada a `queued` para que el Dispatcher la reintente, con
        // confirmación.
        if (item.status === "failed") {
          var requeueBtn = button("Reencolar", "backlog-focus-toggle");
          if (entry.result) requeueBtn.title = "Motivo del fallo: " + entry.result;
          requeueBtn.addEventListener("click", function (event) {
            event.stopPropagation();
            BackendClient.requeueQueueEntry(entry.task_id)
              .then(function () {
                loadDispatchQueue();
                refreshBacklogReport();
              })
              .catch(function (error) {
                pipelineSection.dispatchQueueError = buildErrorMessage(error);
                renderPipelineBody();
              });
          });
          tdActions.appendChild(requeueBtn);
        }
        row.appendChild(tdActions);
        // T-AF036-US12-02: cada fila con `us_id` resoluble (la Task pertenece
        // a una User Story) es clicable y navega directamente a la tarea en
        // el listado del Backlog (expande la Epic, la US padre y hace scroll).
        if (entry.us_id) {
          row.className += " backlog-queue-row-link";
          titleEl.textContent += "  →";
          row.addEventListener("click", function () {
            navigateToQueueTask(entry);
          });
        }
        tbody.appendChild(row);
      });

    panel.appendChild(table);
    wrap.appendChild(panel);
  }

  // T-AF036-US12-02: navega desde una fila de la cola de despacho hasta la
  // tarea concreta en el listado del Backlog, reutilizando
  // `expandEpicAndScrollToChainTask` (expande la Epic, la US padre y hace
  // scroll a la task). Resuelve la Epic de la Task a través de su User Story
  // padre (`us_id` de la entrada de cola). No cambia el estado del panel de
  // la cola. Si la resolución falla (tarea no resoluble), no hace nada — no
  // rompe el render.
  function navigateToQueueTask(entry) {
    if (!entry.us_id) return;
    // T-AF042-US01-02: el panel de la cola vive ahora en la sección Pipeline;
    // la navegación desde una fila expande la Epic en el listado de Backlog,
    // así que antes hay que volver a esa sección para que el render de Backlog
    // sea el activo.
    if (state.section !== "backlog") switchSection("backlog");
    BackendClient.getBacklogItem(entry.us_id)
      .then(function (usDetail) {
        if (!usDetail || !usDetail.epic) return;
        var epicId = epicIdFromLabel(usDetail.epic);
        if (!epicId) return;
        expandEpicAndScrollToChainTask(epicId, entry.task_id);
      })
      .catch(function () {
        // Tarea/Epic no resoluble: sin acción, sin romper el render.
      });
  }

  // Despliegue del detalle completo de una User Story/Task (criterio de
  // aceptación 3): mismo patrón lazy-fetch + guard de respuesta obsoleta
  // que `toggleEpicDetail`. Al abrir el detalle de una User Story, se
  // carga también el catálogo de agentes Developer para el formulario
  // "Lanzar desarrollo" (criterio de aceptación 4).
  function toggleItemDetail(itemId) {
    // T-AF036-US27-03: modo multi — N US expandidas (mapa por itemId).
    if (isMultiMode()) {
      if (backlogSection.expandedItemIds[itemId]) {
        closeItemDetail(itemId);
        renderBacklogBody();
        return;
      }
      backlogSection.expandedItemIds[itemId] = true;
      backlogSection.itemDetails[itemId] = { detail: null, error: null };
      backlogSection.launchError = null;
      backlogSection.launchResult = null;
      backlogSection.advancedOptionsCollapsed = true;
      backlogSection.manualJobStorySelectIndex = 0;
      renderBacklogBody();
      loadTodoStories();

      BackendClient.getBacklogItem(itemId)
        .then(function (detail) {
          if (!isItemExpanded(itemId)) return;
          backlogSection.itemDetails[itemId].detail = detail;
          if (detail.kind === "US" && detail.state === "READY" && plansSection.todoStories) {
            var storyIdx = plansSection.todoStories.findIndex(function (s) { return s.id === itemId; });
            if (storyIdx >= 0) backlogSection.manualJobStorySelectIndex = storyIdx + 1;
          }
          renderBacklogBody();
          if (detail.kind === "US") {
            refreshDeveloperAgents();
            loadUsClosingReport(itemId);
          }
        })
        .catch(function (error) {
          if (!isItemExpanded(itemId)) return;
          backlogSection.itemDetails[itemId].error = buildErrorMessage(error);
          renderBacklogBody();
        });
      return;
    }
    // Modo single: comportamiento actual intacto.
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
    // T-AF036-US07-01: cada detalle nuevo empieza con "Opciones avanzadas"
    // colapsado — no se arrastra el estado abierto/cerrado de la US/Task
    // anterior.
    backlogSection.advancedOptionsCollapsed = true;
    // T-AF024-US15-02: reinicia el selector de Story del formulario de Job
    // manual al abrir cualquier detalle nuevo — se recalcula abajo si la
    // Story recién abierta está en TO_DO.
    backlogSection.manualJobStorySelectIndex = 0;
    renderBacklogBody();
    // T-AF024-US15-02: mismo catálogo de Stories TO_DO que el flujo de
    // Plan/Jobs — necesario aquí para poder preseleccionar la propia US
    // del detalle si aplica (justo debajo).
    loadTodoStories();

    BackendClient.getBacklogItem(itemId)
      .then(function (detail) {
        if (backlogSection.selectedItemId !== itemId) return;
        backlogSection.itemDetail = detail;
        // T-AF024-US15-02: si la US recién abierta está en TO_DO y ya
        // figura en el catálogo cargado, se preselecciona por defecto en
        // el formulario de Job manual — es la Story del propio contexto
        // donde vive ese formulario, desmarcable por el humano si quiere
        // un Job suelto sin veredicto automático.
        if (detail.kind === "US" && detail.state === "READY" && plansSection.todoStories) {
          var storyIdx = plansSection.todoStories.findIndex(function (s) { return s.id === itemId; });
          if (storyIdx >= 0) backlogSection.manualJobStorySelectIndex = storyIdx + 1;
        }
        renderBacklogBody();
        if (detail.kind === "US") {
          refreshDeveloperAgents();
          // T-AF036-US06-01: la carga del informe de cierre es automática
          // al expandir el detalle de una User Story (sin clic explícito),
          // igual que las demás sub-secciones del detalle.
          loadUsClosingReport(itemId);
        }
      })
      .catch(function (error) {
        if (backlogSection.selectedItemId !== itemId) return;
        backlogSection.itemDetailError = buildErrorMessage(error);
        renderBacklogBody();
      });
  }

  // T-AF036-US06-01: carga el informe de cierre real de la User Story
  // `usId` (GET /backlog/us/{us_id}/report) — single-flight por US, con
  // indicador de carga mientras la petición está en vuelo. El caso
  // "informe ausente" (`{exists: false}`) es un resultado VÁLIDO, no un
  // error: solo las respuestas con error real llegan a
  // `closingReportError`.
  function loadUsClosingReport(usId) {
    backlogSection.closingReportUsId = usId;
    backlogSection.closingReportLoading = true;
    backlogSection.closingReportError = null;
    backlogSection.closingReport = null;
    backlogSection.closingReportScrollTaskId = null;
    renderBacklogBody();

    BackendClient.getUsClosingReport(usId)
      .then(function (data) {
        if (backlogSection.closingReportUsId !== usId) return;
        backlogSection.closingReportLoading = false;
        backlogSection.closingReport = data;
        renderBacklogBody();
      })
      .catch(function (error) {
        if (backlogSection.closingReportUsId !== usId) return;
        backlogSection.closingReportLoading = false;
        backlogSection.closingReportError = buildErrorMessage(error);
        renderBacklogBody();
      });
  }

  // T-AF008-US10-03: expande/pliega el detalle de una Task DENTRO del
  // detalle ya expandido de su propia User Story — slot de estado
  // separado de `toggleItemDetail` (ver comentario en
  // `selectedNestedTaskId`, arriba en `backlogSection`).
  function toggleNestedTaskDetail(taskId) {
    if (backlogSection.selectedNestedTaskId === taskId) {
      backlogSection.selectedNestedTaskId = null;
      backlogSection.nestedTaskDetail = null;
      backlogSection.nestedTaskDetailError = null;
      backlogSection.enqueueTaskError = null;
      renderBacklogBody();
      return;
    }
    backlogSection.selectedNestedTaskId = taskId;
    backlogSection.nestedTaskDetail = null;
    backlogSection.nestedTaskDetailError = null;
    backlogSection.enqueueTaskError = null;
    // T-AF036-US07-01: mismo criterio que `toggleItemDetail` — cada detalle
    // nuevo (aquí, una Task anidada) empieza con el desplegable colapsado.
    backlogSection.advancedOptionsCollapsed = true;
    renderBacklogBody();

    BackendClient.getBacklogItem(taskId)
      .then(function (detail) {
        if (backlogSection.selectedNestedTaskId !== taskId) return;
        backlogSection.nestedTaskDetail = detail;
        renderBacklogBody();
      })
      .catch(function (error) {
        if (backlogSection.selectedNestedTaskId !== taskId) return;
        backlogSection.nestedTaskDetailError = buildErrorMessage(error);
        renderBacklogBody();
      });
  }

  // Detalle de una Task individual anidada dentro de su US — mismos
  // campos que `renderItemDetail` para una Task (estado, epic, objetivo,
  // criterios) más el control de encolar; nunca el bloque exclusivo de
  // User Story (dependencias/Tasks/formularios), que no aplica aquí.
  function renderNestedTaskDetail() {
    var box = h("div", "job-detail");
    if (backlogSection.nestedTaskDetailError) {
      box.appendChild(h("p", "agent-error", backlogSection.nestedTaskDetailError));
      return box;
    }
    if (backlogSection.nestedTaskDetail === null) {
      box.appendChild(h("p", "section-note", "Cargando…"));
      return box;
    }
    var detail = backlogSection.nestedTaskDetail;
    renderParseWarning(box, detail);
    if (detail.epic) {
      box.appendChild(h("div", "job-detail-field", "Epic: " + detail.epic));
    }
    // T-AF008-US11-02: mismo criterio que `renderItemDetail` — esta Task
    // anidada es siempre `kind === "T"` (nunca una User Story llega
    // aquí), así que se muestra sin condición extra.
    box.appendChild(h("div", "job-detail-field", "Dificultad: " + (detail.difficulty || "Sin puntuar")));
    box.appendChild(h("div", "job-detail-field", "Objetivo: " + (detail.objetivo || "(sin objetivo declarado)")));
    box.appendChild(
      h(
        "div",
        "job-detail-field",
        "Criterios de aceptación: " + (detail.criterios_aceptacion || "(sin criterios declarados)")
      )
    );
    box.appendChild(renderEnqueueTaskControls(detail));
    return box;
  }

  // Detalle completo de una User Story/Task (criterio de aceptación 3):
  // objetivo, criterios de aceptación, y — solo para una User Story — la
  // lista de sus Tasks con estado + el formulario "Lanzar desarrollo"
  // (criterio de aceptación 4).
  // T-AF036-US07-01: desplegable "Opciones avanzadas" del detalle de una
  // User Story — agrupa "Lanzar desarrollo" (Job directo) y "Crear Job
  // manual" (genérico), que pasan a ser acciones secundarias tras la
  // consolidación que deja "Marcar para desarrollo" como acción principal.
  // Colapsado por defecto (`advancedOptionsCollapsed`), mismo patrón visual
  // que los otros colapsables de esta pantalla (panel "Próximo foco"/"Cola
  // de despacho": `.backlog-focus-panel`/`-header`/`-title`/`-toggle`).
  // El estado abierto/cerrado NO persiste entre distintas Tasks/US: cada
  // detalle nuevo lo reinicia a colapsado (ver `toggleItemDetail`/
  // `toggleNestedTaskDetail`), criterio 4 de la Task.
  function renderAdvancedOptionsCollapsible(storyId) {
    var panel = h("div", "backlog-focus-panel");
    var header = h("div", "backlog-focus-header");
    header.appendChild(h("span", "backlog-focus-title", "Opciones avanzadas"));
    var toggleBtn = button(
      backlogSection.advancedOptionsCollapsed ? "Mostrar" : "Ocultar",
      "backlog-focus-toggle"
    );
    toggleBtn.addEventListener("click", function () {
      backlogSection.advancedOptionsCollapsed = !backlogSection.advancedOptionsCollapsed;
      renderBacklogBody();
    });
    header.appendChild(toggleBtn);
    panel.appendChild(header);

    if (!backlogSection.advancedOptionsCollapsed) {
      panel.appendChild(renderLaunchDevelopmentForm(storyId));
      panel.appendChild(renderManualJobForm(storyId));
    }

    return panel;
  }

  // T-AF036-US06-01: bloque "Informe de cierre" del detalle de una User
  // Story — solo lectura (criterio 7). Estados explícitos, nunca un hueco
  // vacío: cargando -> indicador; error real -> motivo verbatim; informe
  // ausente -> texto explícito; informe presente -> contenido literal con
  // saltos de línea preservados + enlace por Task cerrada a su sección
  // (scroll dentro del bloque ya cargado, sin fetch adicional).
  function renderUsClosingReport(detail) {
    var wrap = h("div", "us-closing-report");
    wrap.appendChild(h("div", "job-detail-label", "Informe de cierre:"));

    if (backlogSection.closingReportUsId !== detail.id) {
      // El informe pertenece a otra US (o aún no se disparó su carga) — no
      // se pinta nada bajo el bloque hasta que llegue.
      return wrap;
    }

    if (backlogSection.closingReportLoading) {
      wrap.appendChild(h("p", "section-note", "Cargando informe de cierre…"));
      return wrap;
    }

    if (backlogSection.closingReportError) {
      wrap.appendChild(h("p", "agent-error", backlogSection.closingReportError));
      return wrap;
    }

    var report = backlogSection.closingReport;
    if (!report || !report.exists) {
      wrap.appendChild(
        h(
          "p",
          "section-note",
          "Sin informe de cierre — ninguna Task de esta User Story se ha cerrado todavía"
        )
      );
      return wrap;
    }

    // Enlace por Task cerrada a su sección dentro del informe ya cargado —
    // scroll puro a un ancla del propio bloque, sin fetch adicional
    // (criterio 3).
    var closedTasks = (detail.tasks || []).filter(function (t) {
      return t.state === "DONE";
    });
    if (closedTasks.length > 0) {
      var links = h("div", "us-closing-report-task-links");
      closedTasks.forEach(function (t) {
        var a = h("a", "us-closing-report-task-link", t.id);
        a.href = "#us-report-task-" + t.id;
        a.addEventListener("click", function (ev) {
          ev.preventDefault();
          scrollToReportTask(t.id);
        });
        links.appendChild(a);
      });
      wrap.appendChild(links);
    }

    var content = h("div", "us-closing-report-content");
    // Texto literal, saltos de línea preservados (sin renderer Markdown
    // completo); cada encabezado `## <task_id> · ...` de una Task cerrada
    // recibe un ancla para el scroll de arriba.
    content.style.whiteSpace = "pre-wrap";
    var lines = report.content.split("\n");
    lines.forEach(function (line) {
      var taskMatch = /^##\s+(T-AF\d+(?:-US\d+)?-\d+)\s*(?:·|\.|:|-|$)/.exec(line);
      var isClosedTaskHeading =
        taskMatch !== null && closedTasks.some(function (t) { return t.id === taskMatch[1]; });
      if (isClosedTaskHeading) {
        var heading = h("div", "us-closing-report-task-heading", line);
        heading.id = "us-report-task-" + taskMatch[1];
        content.appendChild(heading);
      } else {
        content.appendChild(document.createTextNode(line + "\n"));
      }
    });
    wrap.appendChild(content);
    return wrap;
  }

  function scrollToReportTask(taskId) {
    var el = document.getElementById("us-report-task-" + taskId);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  function renderItemDetail(itemId) {
    var box = h("div", "job-detail");
    // T-AF036-US27-03: en modo multi el detalle se lee del mapa por itemId.
    var st = isMultiMode() && itemId ? backlogSection.itemDetails[itemId] : null;
    var error = isMultiMode() && itemId ? (st && st.error) : backlogSection.itemDetailError;
    var detail = isMultiMode() && itemId ? (st && st.detail) : backlogSection.itemDetail;
    if (error) {
      box.appendChild(h("p", "agent-error", error));
      return box;
    }
    if (detail === null || detail === undefined) {
      box.appendChild(h("p", "section-note", "Cargando…"));
      return box;
    }
    renderParseWarning(box, detail);
    if (detail.epic) {
      box.appendChild(h("div", "job-detail-field", "Epic: " + detail.epic));
    }
    // T-AF036-US13-03: fecha de última transición de estado en el detalle
    // (movida aquí desde la cabecera de la US — la línea solo muestra
    // código/título y los controles de prioridad/estado/versión).
    box.appendChild(h("div", "job-detail-field", "Última actualización: " + formatUpdatedAt(detail.updated_at)));
    // T-AF008-US11-02: solo para Task (el campo no existe en el esquema
    // de User Story, `build_item_detail` siempre devuelve `null` ahí) —
    // "Sin puntuar" explícito en vez de omitir el campo en silencio
    // (criterio de aceptación explícito de la Task).
    if (detail.kind === "T") {
      box.appendChild(h("div", "job-detail-field", "Dificultad: " + (detail.difficulty || "Sin puntuar")));
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
    // `atlas_forge/backlog/detail.py`). "Lanzar desarrollo" es también
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
        // T-AF008-US10-03: cada Task listada aquí pasa a ser expandible
        // (antes texto plano, `.job-detail-field` sin listener) — sin
        // esto, no existía ninguna forma de llegar al detalle de una
        // Task individual desde la UI, así que el botón "Marcar para
        // desarrollo"/"Quitar de la cola" de `renderEnqueueTaskControls`
        // no tenía dónde vivir. Usa `toggleNestedTaskDetail`/su propio
        // slot de estado (`selectedNestedTaskId`), NUNCA
        // `toggleItemDetail`/`selectedItemId` (el de la propia US): ese
        // slot ya está ocupado por la US padre mientras esta lista es
        // visible — reutilizarlo colapsaría el detalle de la US en
        // cuanto se expandiera una de sus Tasks.
        tasks.forEach(function (task) {
          var taskSelected = backlogSection.selectedNestedTaskId === task.id;
          // T-AF036-US09-01: Task postergada (OUT_OF_SCOPE/FUERA_ROADMAP)
          // -> clase propia, mismo criterio que la fila de User Story.
          var taskFueraRoadmap = isFueraRoadmapState(task.state) ? " backlog-fuera-roadmap" : "";
          var taskCard = h("div", "job-card" + taskFueraRoadmap + (taskSelected ? " job-card-selected" : ""));
          // T-AF036-US01-10: id de anclaje para el scroll del panel
          // "Próximo foco" a una Task concreta — mismo patrón que
          // `itemCard.id = "backlog-us-" + userStory.id` para User Story.
          taskCard.id = "backlog-task-" + task.id;
          var taskLine = h("div", "job-line" + (taskSelected ? " job-line-selected" : ""));
          taskLine.appendChild(
            h(
              "span",
              "backlog-task-line-title" + (isFueraRoadmapState(task.state) ? " backlog-us-line-title--fuera-roadmap" : ""),
              // T-AF036-US19-02: ID + nombre (título); el estado genérico ya
              // NO va en el texto de la línea (queda solo en el `<select>`).
              // Excepción: "fuera de roadmap" conserva su etiqueta visible
              // (US-AF036-09). Si el `title` es null/vacío, solo el ID.
              // T-AF036-US19-03: el backend rellena `title` con el `id`
              // cuando falta `title:` (fallback T-AF036-US19-01); se compara
              // `title !== task.id` para no duplicar el ID.
              (task.title && task.title !== task.id
                ? task.id + " · " + task.title
                : task.id)
                + (isFueraRoadmapState(task.state) ? " — Fuera de roadmap" : "")
            )
          );
          // T-AF036-US08-01: mismos controles en línea que la fila de
          // User Story, aquí para la Task anidada — closure captura `task`
          // del `forEach`, no `userStory` del scope exterior.
          taskLine.appendChild(renderPriorityStateControls(task.id, task.priority, task.state, "T"));
          taskLine.tabIndex = 0;
          taskLine.setAttribute("role", "button");
          taskLine.setAttribute("aria-expanded", taskSelected ? "true" : "false");
          taskLine.addEventListener("click", function () {
            toggleNestedTaskDetail(task.id);
          });
          taskCard.appendChild(taskLine);
          if (backlogSection.editItemError && backlogSection.editItemErrorFor === task.id) {
            taskCard.appendChild(h("p", "agent-error", backlogSection.editItemError));
          }
          taskCard.appendChild(h("div", "job-hint", taskSelected ? "▲ Plegar detalle" : "▼ Ver detalle"));
          if (taskSelected) {
            taskCard.appendChild(renderNestedTaskDetail());
          }
          box.appendChild(taskCard);
        });
      }
      // T-AF036-US02-06: botón "+ Nueva Task" al final de la lista de
      // Tasks — siempre visible (incluso con lista vacía), nunca dentro del
      // bucle de arriba. Abre el formulario inline (T9) con `us_id`/`epic_id`
      // heredados del contexto (`detail.id` es la US, `detail.epic` es la
      // Epic), mostrados pero no editables — no hay ningún `<input>` de US/Epic
      // en este formulario.
      var newTaskBtn = button("+ Nueva Task", "backlog-new-epic-btn");
      newTaskBtn.addEventListener("click", function () {
        backlogSection.newTaskForm = {
          usId: detail.id,
          epicId: detail.epic || null,
          id: "",
          title: "",
          objetivo: "",
          criterios: "",
          priority: "",
          submitting: false,
          error: null,
        };
        renderBacklogBody();
      });

      // T-AF036-US07-02 (bug 2026-08-17): los controles de acción
      // principal del detalle ("+ Nueva Task"; "Progresar" se eliminó en
      // T-AF036-US16-01 y "Marcar toda la Story" en T-AF036-US16-02) se
      // unen en un ÚNICO contenedor `.accion-controls` flex para que se
      // alineen en
      // una sola fila, con el mismo alto y espaciado consistente. Los
      // mensajes de error/resultado de cada acción se añaden DESPUÉS de la
      // fila de botones, no dentro de ella.
      var actionControls = h("div", "accion-controls");
      actionControls.appendChild(newTaskBtn);
      box.appendChild(actionControls);
      if (backlogSection.newTaskForm !== null && backlogSection.newTaskForm.usId === detail.id) {
        box.appendChild(renderNewTaskForm());
      }

      box.appendChild(renderAdvancedOptionsCollapsible(detail.id));

      // T-AF036-US06-01: bloque "Informe de cierre" — bajo el bloque de
      // Tasks, con indicador de carga automático (sin clic explícito).
      box.appendChild(renderUsClosingReport(detail));
    } else {
      // Task individual: botón "Marcar para desarrollo" (si TO_DO y no
      // encolada) / "Quitar de la cola" (si ya encolada) — criterio de
      // aceptación 1. `dispatchQueueEntryForTask` cruza sobre
      // `backlogSection.dispatchQueue` ya cargado, sin fetch adicional.
      box.appendChild(renderEnqueueTaskControls(detail));
    }
    return box;
  }

  function renderEnqueueTaskControls(detail) {
    var wrap = h("div", "accion-controls");
    var queueEntry = dispatchQueueEntryForTask(detail.id);
    var inFlight = backlogSection.enqueueTaskInFlight === detail.id;

    if (queueEntry === null) {
      if (detail.state !== "READY") {
        // Fuera de READY no tiene sentido encolar (mismo criterio 400
        // que ya aplica el backend) — no se muestra ningún botón en vez
        // de mostrar uno que siempre fallaría al pulsarlo.
        return wrap;
      }
      var enqueueBtn = button(inFlight ? "Encolando…" : "Marcar para desarrollo", "accion-run");
      if (inFlight) enqueueBtn.disabled = true;
      enqueueBtn.addEventListener("click", function () {
        enqueueTaskAction(detail.id);
      });
      wrap.appendChild(enqueueBtn);
    } else if (queueEntry.status === "queued") {
      var dequeueBtn = button(inFlight ? "Quitando…" : "Quitar de la cola", "accion-run");
      if (inFlight) dequeueBtn.disabled = true;
      dequeueBtn.addEventListener("click", function () {
        dequeueTaskAction(detail.id);
      });
      wrap.appendChild(dequeueBtn);
    } else {
      // `dispatched`/`failed`: ya no es mutable desde aquí (mismo
      // criterio 409 del backend) — se informa el estado real en vez de
      // ofrecer un botón que fallaría.
      var statusLabel = QUEUE_STATUS_LABEL[queueEntry.status] || queueEntry.status;
      wrap.appendChild(h("p", "section-note", "En la cola de despacho: " + statusLabel));
    }

    if (backlogSection.enqueueTaskError) {
      wrap.appendChild(h("p", "agent-error", backlogSection.enqueueTaskError));
    }
    return wrap;
  }

  // T-AF036-US07-02: los controles de acción principal del detalle de la
  // User Story ("+ Nueva Task", y el atajo por estado) se unen en una única
  // fila `.accion-controls`. El botón "Marcar toda la Story para desarrollo"
  // se retiró en T-AF036-US16-02: el encolado de las Tasks de la US se hace
  // vía el selector de estado (mover la US a TO_DEVELOP).
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

  // T-AF036-US01-03: % DONE real de la Epic = (US done + Task done) /
  // (US total + Task total), calculado en frontend a partir de los
  // conteos ya presentes en `by_epic` (sin backend nuevo) — sustituye a
  // `unblock_degree` (T-AF024-US07-01, grado de desbloqueo por
  // dependencias) como barra PRINCIPAL de cada tarjeta de Epic, porque
  // `unblock_degree` no mide progreso: una Epic con Tasks TO_DO sin
  // dependencias entre sí marca 100% sin nada hecho (diagnóstico de
  // `07-informes/AF-036/especificacion-ux-backlog.md`, estado 3 punto 3).
  function sumCounts(counts) {
    if (!counts) return 0;
    return Object.keys(counts).reduce(function (total, state) {
      return total + counts[state];
    }, 0);
  }

  function epicDonePercent(epic) {
    var doneCount = ((epic.user_stories && epic.user_stories.DONE) || 0) +
      ((epic.tasks && epic.tasks.DONE) || 0);
    var totalCount = sumCounts(epic.user_stories) + sumCounts(epic.tasks);
    if (totalCount === 0) return 0;
    return Math.round((doneCount / totalCount) * 100);
  }

  function renderProgressBar(card, epic) {
    var pct = epicDonePercent(epic);
    var color;
    if (pct === 0) color = "#9e9e9e";
    else if (pct >= 100) color = "#2e7d32";
    else color = "#ef6c00";
    var bar = h("div", "backlog-progress-bar");
    var fill = h("div", "backlog-progress-fill");
    fill.style.width = pct + "%";
    fill.style.background = color;
    bar.appendChild(fill);
    card.appendChild(bar);
  }

  // Degradada a barra SECUNDARIA (T-AF036-US01-03): `unblock_degree`
  // sigue siendo una señal real y útil ("¿cuánto de esta Epic puedo
  // empezar a trabajar ya mismo?"), pero nunca se muestra sin la
  // etiqueta explícita "Desbloqueo: N%" — para que no se confunda con
  // progreso (ver "Alternativas descartadas" del documento de UX).
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
    card.appendChild(h("div", "backlog-heat-label", "Desbloqueo: " + pct + "%"));
  }

  function findBlockingDependencies() {
    var detail = backlogSection.itemDetail;
    if (!detail || !detail.dependencies) return [];
    return detail.dependencies.filter(function (dep) {
      return dep.state !== "DONE";
    });
  }
  // T-AF024-US09-03: carga los agentes activos (sin stopped) de la sesion
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
  // `POST /backlog/{story_id}/launch-development`, T-AF020-US02-01): el
  // backend resuelve el contexto completo (objetivo + Tasks TO_DO), aquí
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
      // (400 sin Tasks TO_DO, 404 agente inválido) — `buildErrorMessage`
      // ya surge del `detail` verbatim de `BackendRequestError`, nunca
      // un mensaje genérico (mismo patrón que T-AF021-US04-01).
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
  // T-AF024-US09-03: formulario manual de creacion de Job como accion
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

    // T-AF024-US15-02: Story TO_DO opcional a asociar al Job — mismo
    // selector/catálogo (`plansSection.todoStories`) que ya usa el flujo
    // de Plan, no un campo de texto libre nuevo. Preseleccionada a la
    // propia US de este detalle si está en TO_DO (`toggleItemDetail`/
    // `recalculateManualJobStoryPreselection`); desmarcable por el
    // humano si quiere un Job suelto sin veredicto automático.
    form.appendChild(h("div", "field-label", "Asociar a una Story (opcional — dispara veredicto del Arquitecto al cerrar)"));
    if (plansSection.todoStoriesLoading) {
      form.appendChild(h("p", "section-note", "Cargando User Stories del backlog…"));
    } else if (plansSection.todoStoriesError) {
      form.appendChild(h("p", "agent-error", "No se pudo cargar el catálogo de User Stories — el Job se puede enviar igualmente, sin Story asociada."));
    } else {
      var storySelect = document.createElement("select");
      storySelect.className = "clickable launch-select";
      var noStoryOpt = document.createElement("option");
      noStoryOpt.setAttribute("value", "");
      noStoryOpt.textContent = "Sin Story asociada";
      storySelect.appendChild(noStoryOpt);
      var todoStoriesForManual = plansSection.todoStories || [];
      todoStoriesForManual.forEach(function (story, idx) {
        var o = document.createElement("option");
        o.setAttribute("value", String(idx + 1));
        o.textContent = story.id + " (" + (story.epic || "") + ") — READY";
        storySelect.appendChild(o);
      });
      if (todoStoriesForManual.length === 0) {
        storySelect.disabled = true;
        noStoryOpt.textContent = "No hay User Stories en READY en el backlog";
      }
      storySelect.selectedIndex = 0;
      if (
        backlogSection.manualJobStorySelectIndex > 0 &&
        backlogSection.manualJobStorySelectIndex <= todoStoriesForManual.length
      ) {
        storySelect.selectedIndex = backlogSection.manualJobStorySelectIndex;
      }
      storySelect.addEventListener("change", function () {
        backlogSection.manualJobStorySelectIndex = parseInt(storySelect.value, 10) || 0;
      });
      form.appendChild(storySelect);
    }

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

    var payload = { agent_id: agent.id, description: description };
    // T-AF024-US15-02: 0 es "Sin Story asociada" — solo se envía
    // `story_id` si el humano eligió (o dejó preseleccionada) una Story
    // real del catálogo TO_DO.
    var todoStoriesForManual = plansSection.todoStories || [];
    if (
      backlogSection.manualJobStorySelectIndex > 0 &&
      backlogSection.manualJobStorySelectIndex <= todoStoriesForManual.length
    ) {
      var chosenManualStory = todoStoriesForManual[backlogSection.manualJobStorySelectIndex - 1];
      if (chosenManualStory) payload.story_id = chosenManualStory.id;
    }

    BackendClient.createAndDispatchJob(payload)
      .then(function (job) {
        backlogSection.creatingManualJob = false;
        backlogSection.manualJobResult = job;
        backlogSection.manualJobDescription = "";
        renderBacklogBody();
      })
      .catch(function (error) {
        backlogSection.creatingManualJob = false;
        backlogSection.manualJobError = buildErrorMessage(error);
        renderBacklogBody();
      });
  }

  // Despacho single-flight (criterio de aceptación explícito de
  // T-AF020-US02-02, reutilizado aquí: "un segundo clic mientras la
  // petición anterior sigue en vuelo no despacha un segundo Job") —
  // mismo guard hand-rolled que el resto de acciones de esta web
  // (`launching`/`createInFlight`/`runningEntryId`): primera línea
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
  // US-AF024-11 (reescritura completa): pantalla unificada — una fila por
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
    // Límite de Developer simultáneos (US-AF024-12 criterio 6): carga
    // independiente de la de arriba — un fallo aquí no debe bloquear el
    // resto de la pantalla, buildUnifiedRows ya tiene su propio fallback
    // al default mientras esto no haya respondido.
    BackendClient.getSystemPreferences()
      .then(function (result) {
        rolesSection.maxSimultaneousDevelopers = result.max_simultaneous_developers;
        if (state.section === "roles") renderRolesBody();
      })
      .catch(function () {
        // Sin preferencia disponible: buildUnifiedRows sigue usando el
        // default local, no hay nada más que hacer aquí.
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
    if (rolesSection.awakenError) {
      wrap.appendChild(h("p", "agent-error", rolesSection.awakenError));
    }
    if (rolesSection.stale) {
      wrap.appendChild(h("p", "stale-note", "Puede que esta lista esté desactualizada (sin conexión con el backend)."));
    }
    if (rolesSection.listError && rolesSection.agentsList === null) {
      wrap.appendChild(h("p", "agent-error", rolesSection.listError));
    }

    var rows = buildUnifiedRows();
    rows.forEach(function (row) { renderUnifiedRow(wrap, row); });
  }

  // ── construcción de filas unificadas ────────────────────────────────────

  // Default local (US-AF024-12): solo se usa mientras `GET
  // /system/preferences` no ha respondido todavía (ver
  // `loadRolesPreferences`) — coincide con
  // `system_preferences.DEFAULT_MAX_SIMULTANEOUS_DEVELOPERS` en backend,
  // pero el valor real y editable vive ahí, no aquí.
  var DEFAULT_MAX_SIMULTANEOUS_DEVELOPERS = 3;

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

    // Developer: filas FIJAS e independientes — una por número
    // (Developer-1, Developer-2, ..., Developer-N con N = límite
    // configurado, `rolesSection.maxSimultaneousDevelopers`,
    // US-AF024-12). Cada fila es un "slot" estable: si existe una
    // instancia real con ESE nombre se muestra; si no, fila sintética
    // "stopped" con el MISMO nombre, lanzable por su cuenta — mismo
    // patrón que Auditor-OSS/UX (agentes no relacionados que comparten
    // rol). T-AF005-US01-08 (2026-08-18): matar un Developer NO renumera
    // las filas ni hace aparecer "Developer-4" — la fila de la instancia
    // muerta vuelve a su estado lanzable con su nombre original, y
    // lanzar desde ella crea la instancia con ese número (el backend lo
    // fija vía `developer_number` en el payload, no por conteo).
    var devAgents = agents.filter(function (a) { return a.role === "developer"; });
    var maxDevelopers = rolesSection.maxSimultaneousDevelopers !== null
      ? rolesSection.maxSimultaneousDevelopers
      : DEFAULT_MAX_SIMULTANEOUS_DEVELOPERS;
    for (var devNum = 1; devNum <= maxDevelopers; devNum++) {
      var devName = "Developer-" + devNum;
      var realDev = null;
      for (var di = 0; di < devAgents.length; di++) {
        if (devAgents[di].name === devName) {
          realDev = devAgents[di];
          break;
        }
      }
      if (realDev) {
        rows.push(realDev);
      } else {
        rows.push(syntheticRow("developer", "stopped", devName));
      }
    }

    // UX y Auditor-OSS (T-AF024-US13-01/-02/-03): igual que Arquitecto,
    // instancia única — se reutiliza la instancia real si ya está
    // lanzada, o una fila sintética "stopped" (Lanzar habilitado, el rol
    // sí está registrado en el backend) si no. A diferencia de
    // Arquitecto, no tienen estado propio en la barra superior: la fuente
    // de verdad es `rolesSection.agentsList`, igual que Developer.
    ["auditor_oss", "ux"].forEach(function (role) {
      var existing = agents.filter(function (a) { return a.role === role; })[0];
      rows.push(existing || syntheticRow(role, "stopped"));
    });

    // Tester: rol SÍ registrado en el backend (`atlas_forge/agents/tester.py`,
    // T-AF022-US15-01) — instancia única, mismo patrón que Auditor-OSS/UX:
    // se reutiliza la instancia real si ya está lanzada, o una fila
    // sintética "stopped" (Lanzar habilitado al elegir runtime) si no.
    // Bug corregido 2026-08-18 (segundo): se pintaba SIEMPRE como fila
    // sintética, ignorando la instancia real — tras reiniciar atlas_forge el
    // Tester vivo aparecía como "detenido".
    var realTester = agents.filter(function (a) { return a.role === "tester"; })[0];
    rows.push(realTester || syntheticRow("tester", "stopped"));

    return rows;
  }

  function syntheticRow(role, status, nameOverride) {
    var nameMap = { arquitecto: "Arquitecto", developer: "Developer", auditor_oss: "Auditor-OSS", ux: "UX", tester: "Tester" };
    return {
      _synthetic: true,
      id: null,
      name: nameOverride || nameMap[role] || role,
      role: role,
      status: status || "unregistered",
      runtime_id: null,
      // T-AF024-US11-03: la fila sintética refleja el default del rol
      // (compartido por todas sus instancias) en vez de hardcodear null,
      // para que "Guardar modelo" sea visible de inmediato.
      model: defaultModelLabelFor(role),
      last_command_at: null,
    };
  }

  // Clave única y estable por fila. Para instancias reales, el id del
  // agente; para filas sintéticas (id null), la posición
  // "synthetic:<role>:<name>" — de modo que Developer-1/2/3 sean filas
  // distintas aunque compartan id null (T-AF024-US11-03).
  function rowKeyFor(agent) {
    if (agent && agent.id) return "agent:" + agent.id;
    return "synthetic:" + agent.role + ":" + agent.name;
  }

  // Nombre visible del modelo por defecto del rol (a partir del model_id
  // guardado en default_model_by_role), o null si no hay default o el id
  // ya no está en el catálogo. Bug corregido 2026-08-18: si el default
  // persistido no es un id válido del catálogo (p. ej. "claude-code", un
  // runtime, guardado por un camino legacy), se devuelve null en vez de
  // mostrar el id corrupto como nombre — una fila no lanzada sin runtime
  // elegido muestra "Modelo: se define al lanzar", nunca "Modelo:
  // claude-code".
  function defaultModelLabelFor(role) {
    var modelId = rolesSection.defaults && rolesSection.defaults[role];
    if (!modelId) return null;
    var match = (rolesSection.models || []).filter(function (m) { return m.id === modelId; })[0];
    return match ? match.name : null;
  }

  // Nombre amigable de un id de modelo del catálogo (para mostrar el
  // modelo concreto de un agente vivo como "DeepSeek V4 Flash" en vez de
  // "opencode-go/deepseek-v4-flash"). Busca en el catálogo de la pestaña
  // Agentes y, si no está cargado (el usuario está en otra pestaña), en el
  // catálogo propio de la barra del Arquitecto. Si el id no está en
  // ninguno, devuelve el id tal cual — nunca null para no ocultar el dato.
  function catalogModelName(modelId) {
    if (!modelId) return modelId;
    var source = rolesSection.models && rolesSection.models.length
      ? rolesSection.models
      : (arquitectoState.catalog || []);
    var match = source.filter(function (m) { return m.id === modelId; })[0];
    return match ? match.name : modelId;
  }

  // T-AF005-US07-03: runtime elegido para la fila ANTES de lanzar. Si el
  // usuario ya eligió uno en el selector, ese gana; si no, se usa como
  // fallback VISIBLE (no silencioso) el runtime implícito del default de
  // modelo del rol; si tampoco hay, devuelve "" (lanzamiento bloqueado
  // hasta que se elija). El runtime elegido se conserva por fila.
  function chosenRuntimeForRow(agent) {
    var rowKey = rowKeyFor(agent);
    var stored = rolesSection.chosenRuntimeByRow[rowKey];
    if (stored) return stored;
    var defaultId = rolesSection.defaults && rolesSection.defaults[agent.role];
    return launchRuntimeForModel(defaultId) || "";
  }

  function setChosenRuntimeForRow(agent, runtime) {
    rolesSection.chosenRuntimeByRow[rowKeyFor(agent)] = runtime;
    // Un cambio de runtime invalida el modelo elegido para la fila (el
    // catálogo de modelos depende del runtime) — se limpia para que el
    // selector de modelo vuelva a "sin elegir" con el nuevo runtime.
    delete rolesSection.chosenModelByRow[rowKeyFor(agent)];
  }

  // T-AF024-US11-13 (2026-08-17, tercera revisión): modelo elegido para
  // la fila ANTES de lanzar, para OpenCode Y Claude Code (el cambio en
  // caliente queda bloqueado). Sin fallback al default del rol aquí —
  // a diferencia del runtime, el modelo simplemente queda "sin elegir"
  // si el usuario no lo toca (el catálogo puede no tener default, y
  // lanzar sin modelo elegido es válido para el runtime que lo permita).
  function chosenModelForRow(agent) {
    return rolesSection.chosenModelByRow[rowKeyFor(agent)] || "";
  }

  function setChosenModelForRow(agent, modelId) {
    rolesSection.chosenModelByRow[rowKeyFor(agent)] = modelId;
  }

  // Catálogo de modelos filtrado al runtime elegido para la fila —
  // `models.yml` usa snake_case (`claude_code`), el runtime real
  // registrado usa kebab-case (`claude-code`), mismo criterio de mapeo
  // ya usado en el backend (`_CATALOG_RUNTIME_BY_REAL_TYPE`, routes.py).
  var _MODEL_CATALOG_RUNTIME_BY_REAL_TYPE = { opencode: "opencode", "claude-code": "claude_code", codex: "codex" };
  function modelCatalogForRuntime(runtimeId) {
    var catalogRuntime = _MODEL_CATALOG_RUNTIME_BY_REAL_TYPE[runtimeId];
    if (!catalogRuntime) return [];
    return (rolesSection.models || []).filter(function (m) {
      return m.runtime === catalogRuntime && m.enabled !== false;
    });
  }

  // Selector de modelo para una fila NO lanzada — solo aplica si ya hay
  // un runtime elegido que admite modelo (OpenCode/Claude Code); Codex
  // devuelve null (sin catálogo todavía). No es obligatorio: si el
  // usuario no elige nada, `launch_agent` lanza sin `--model` (el
  // runtime arranca con su propio default).
  function renderModelSelectorForLaunch(agent) {
    var runtimeId = chosenRuntimeForRow(agent);
    var catalog = modelCatalogForRuntime(runtimeId);
    if (catalog.length === 0) return null;

    var wrap = h("div", "agent-model");
    wrap.appendChild(h("span", "agent-runtime-label", "Modelo: "));
    var sel = document.createElement("select");
    sel.className = "clickable runtime-select";
    var noneOpt = document.createElement("option");
    noneOpt.value = "";
    noneOpt.textContent = "— por defecto del runtime —";
    sel.appendChild(noneOpt);
    catalog.forEach(function (m) {
      var option = document.createElement("option");
      option.setAttribute("value", m.id);
      option.textContent = m.name;
      sel.appendChild(option);
    });
    sel.value = chosenModelForRow(agent);
    sel.addEventListener("change", function () {
      setChosenModelForRow(agent, sel.value);
      renderRolesBody();
    });
    wrap.appendChild(sel);
    return wrap;
  }

  // Selector de runtime para una fila NO lanzada — el runtime es una
  // elección obligatoria y explícita (criterio 1 de US-AF005-07): nunca se
  // lanza con un runtime asumido en silencio, y nunca se infiere del modelo.
  function renderRuntimeSelector(agent) {
    var wrap = h("div", "agent-runtime");
    wrap.appendChild(h("span", "agent-runtime-label", "Runtime: "));
    var sel = document.createElement("select");
    sel.className = "clickable runtime-select";
    var opts = [
      { value: "", label: "— elige runtime —" },
      { value: "opencode", label: "OpenCode" },
      { value: "claude-code", label: "Claude Code" },
      { value: "codex", label: "Codex" },
    ];
    opts.forEach(function (o) {
      var option = document.createElement("option");
      option.setAttribute("value", o.value);
      option.textContent = o.label;
      sel.appendChild(option);
    });
    sel.value = chosenRuntimeForRow(agent);
    sel.addEventListener("change", function () {
      setChosenRuntimeForRow(agent, sel.value);
      renderRolesBody();
    });
    wrap.appendChild(sel);
    return wrap;
  }

  // ── renderizado de UNA fila unificada ───────────────────────────────────

  function renderUnifiedRow(wrap, agent) {
    var isWorking = agent.status === "working";
    var isStopped = agent.status === "stopped";
    var isUnregistered = agent.status === "unregistered";
    var isUnavailable = agent.status === "unavailable";
    var isFailed = agent.status === "failed";

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
    } else if (agent.status === "limited") {
      statusLabel = "sin límite de sesión";
    } else if (isUnavailable) {
      // T-AF024-US11-16: un Developer `unavailable` (proceso caído fuera de
      // atlas_forge) muestra un aviso de conexión perdida, no el valor crudo.
      statusLabel = "caído · conexión perdida";
    } else if (isFailed) {
      // T-AF008-US18-04: fallo operativo de auto-liberación ("working sin
      // Job en vuelo") — motivo consultable debajo de la fila.
      statusLabel = "fallo · working sin Job";
    } else {
      statusLabel = agent.status;
    }
    var statusRow = h("div", "agent-status-row");
    var dot = h("span", "status-dot");
    dot.style.backgroundColor = agentStatusColor(agent.status);
    statusRow.appendChild(dot);
    statusRow.appendChild(h("span", "status-text", "Estado: " + statusLabel));
    info.appendChild(statusRow);

    // T-AF024-US21-01: hora de recuperación visible (no solo tooltip)
    // mientras el agente está `limited`.
    if (agent.status === "limited" && agent.limited_until) {
      info.appendChild(h("div", "agent-limited-until", formatLimitedUntil(agent.limited_until)));
    }

    // T-AF008-US18-04: motivo del fallo de auto-liberación consultable en la
    // propia fila mientras `status === "failed"`.
    if (isFailed && agent.failure_reason) {
      info.appendChild(h("div", "agent-failed-reason", String(agent.failure_reason)));
    }

    // T-AF024-US11-16: aviso en el detalle de un agente caído (`unavailable`)
    // — el operador debe saber que la conexión se perdió y cómo liberar la
    // plaza para reutilizarla.
    if (isUnavailable) {
      info.appendChild(
        h("div", "agent-unavailable-note",
          "El proceso del agente se detuvo fuera de atlas_forge — se ha perdido la conexión. " +
          "Usa 'Liberar' para reutilizar su plaza.")
      );
    }

    // 3. Tiempo desde la última orden
    info.appendChild(h("div", "agent-model", formatLastCommand(agent.last_command_at)));

    // 4. Runtime (T-AF005-US07-03, T-AF024-US11-01): dos campos separados.
    // - Agente NO lanzado: el runtime es una elección OBLIGATORIA y
    //   explícita (selector) — nunca se infiere en silencio del modelo, y
    //   el lanzamiento se bloquea hasta elegirlo (criterio 1 de US-AF005-07).
    // - Agente VIVO: el runtime queda FIJO, se muestra como texto sin
    //   ningún control de cambio en caliente (criterio 2).
    var isLiveRow = !!(agent.id && agent.status !== "stopped" && agent.status !== "unregistered" && agent.status !== "unavailable");
    if (isLiveRow) {
      info.appendChild(
        h("div", "agent-runtime", "Runtime: " + runtimeDisplayName(agent.runtime_id))
      );
    } else {
      info.appendChild(renderRuntimeSelector(agent));
    }

    // Modelo (decisión de producto 2026-08-17, T-AF024-US11-13 —
    // segundo cambio de criterio en la misma Task): el cambio de modelo
    // EN CALIENTE queda BLOQUEADO por ahora para todos los runtimes (el
    // mecanismo real resultó frágil en ambos — atajos de OpenCode
    // rotos/reparados a medias, diálogo de confirmación de Claude Code —
    // se deja para investigar en una Task aparte). El modelo se elige
    // AL LANZAR, para OpenCode Y Claude Code (antes solo OpenCode) — ver
    // `renderRuntimeSelector`/`chosenModelForRow`. Un agente vivo
    // siempre muestra el modelo como texto plano, nunca un selector.
    if (isLiveRow && agent.runtime_id === "claude-code") {
      // Claude Code no tiene lectura pasiva (agent.model siempre null) —
      // se usa el texto real leído por `/status` (`statusModelByAgentId`,
      // consulta puntual al montar la fila), igual que antes servía
      // para preseleccionar el selector inline ahora retirado.
      var isPending = rolesSection.statusModelByAgentId[agent.id] === "__pending__";
      var isUndef = rolesSection.statusModelByAgentId[agent.id] === undefined;
      if (isUndef && agent.status === "idle") {
        rolesSection.statusModelByAgentId[agent.id] = "__pending__";
        BackendClient.getAgentStatusModel(agent.id)
          .then(function (result) {
            rolesSection.statusModelByAgentId[agent.id] = result.model || null;
            renderRolesBody();
          })
          .catch(function () {
            rolesSection.statusModelByAgentId[agent.id] = null;
            renderRolesBody();
          });
      }
      var claudeModelText = isPending || isUndef ? "cargando…" : (rolesSection.statusModelByAgentId[agent.id] || "sin modelo");
      info.appendChild(h("div", "agent-model", "Modelo: " + claudeModelText));
    } else if (isLiveRow) {
      var modelLabel = catalogModelName(agent.model) || "sin modelo";
      info.appendChild(h("div", "agent-model", "Modelo: " + modelLabel));
    } else {
      // No lanzado: selector de modelo por fila (T-AF024-US11-13,
      // 2026-08-17, tercera revisión — el modelo se elige AL LANZAR
      // para OpenCode y Claude Code, no en caliente). Solo aparece si el
      // runtime elegido tiene catálogo; si no hay ninguno elegido
      // todavía o es Codex, se muestra el texto informativo de siempre.
      var modelSelector = renderModelSelectorForLaunch(agent);
      if (modelSelector) {
        info.appendChild(modelSelector);
      } else {
        var defaultForLaunch = defaultModelLabelFor(agent.role);
        var preModelLabel = defaultForLaunch
          ? "Modelo: " + defaultForLaunch
          : "Modelo: se define al lanzar";
        info.appendChild(h("div", "agent-model agent-model-prelaunch", preModelLabel));
      }
    }

    // --- Comando de conexión como texto de detalle (no botón) ---
    if (isLiveRow && agent.session_name) {
      var comandoDetalle = renderCommandoConexionDetalle(agent);
      info.appendChild(comandoDetalle);
    }

    card.appendChild(info);

    // --- ACCIONES (bloque derecho, en la misma fila que agent-info) ---
    var actions = h("div", "agent-actions");

    // (a) Detener/Eliminar (renombrado de Lanzar/Detener)
    actions.appendChild(renderLanzarDetenerBtn(agent));

    // (b) Cambiar modelo — SOLO cuando la capacidad del runtime + estado lo
    // permite (criterio 3 de US-AF005-07 / T-AF005-US07-03): OpenCode vivo
    // en idle (cambio en caliente real), o no lanzado con runtime OpenCode
    // elegido (default de modelo para el lanzamiento). Nunca para Claude
    // Code (no admite cambio de modelo) ni para un runtime no elegido.
    var changeModelBtn = renderCambiarModeloBtn(agent);
    if (changeModelBtn) actions.appendChild(changeModelBtn);

    // (c) Ver log en vivo (T-AF032-US02-01)
    actions.appendChild(renderVerLogEnVivoBtn(agent));

    // (d) Despertar — siempre visible, deshabilitado salvo cuando el
    // agente está trabajando (envía empujón al pane).
    actions.appendChild(renderDespertarBtn(agent));

    card.appendChild(actions);

    // Editor inline de modelo por defecto (fila completa debajo)
    if (rolesSection.editingRole === agent.role && rolesSection.editingRowKey === rowKeyFor(agent)) {
      var editorWrap = h("div", "agent-editor-row");
      card.appendChild(editorWrap);
      renderDefaultModelEditorInline(editorWrap, agent.role);
    }

    // Error de lanzar/detener del Arquitecto (T-AF024-US11-09 criterio 2):
    // antes solo se veía en la barra superior — invisible si el usuario
    // está en la pantalla Agentes, que es desde donde se pulsa "Lanzar".
    // Se traduce el 400 crudo del backend a un mensaje accionable.
    if (agent.role === "arquitecto" && arquitectoState.error) {
      card.appendChild(h("div", "agent-error", translateArquitectoError(arquitectoState.error)));
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

  // Hora legible de recuperación de un agente `limited` (T-AF024-US21-01,
  // criterio de aceptación: "la pantalla Agentes muestra la hora de
  // recuperación de forma visible... no solo en un tooltip") — formato
  // corto de hora local del navegador, mismo criterio de legibilidad que
  // `formatLastCommand`.
  function formatLimitedUntil(limitedUntil) {
    if (!limitedUntil) return "";
    try {
      var when = new Date(limitedUntil);
      if (isNaN(when.getTime())) return "";
      return "Recupera a las " + when.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    } catch (_e) {
      return "";
    }
  }

  // ── botón Cambiar modelo ────────────────────────────────────────────────
  // Cambio de criterio (T-AF024-US11-13, 2026-08-17, tercera revisión):
  // el cambio de modelo EN CALIENTE queda BLOQUEADO para todos los
  // runtimes — el mecanismo real resultó frágil tanto en OpenCode
  // (atajos de teclado rotos con la CLI actual, navegación por índice de
  // línea mezclaba cabeceras de proveedor con opciones reales) como en
  // Claude Code (diálogo de confirmación "Switch model?" no siempre
  // predecible) — se deja para investigar en una Task aparte. El modelo
  // se elige AL LANZAR, para OpenCode Y Claude Code (antes solo
  // OpenCode) — ver `renderRuntimeSelector`. Esta función ya no ofrece
  // ningún control: el modelo de un agente vivo se muestra solo como
  // texto plano (ver el bloque de "Modelo:" en `renderUnifiedRow`).
  function renderCambiarModeloBtn(agent) {
    return null;
  }

  // Cambia el modelo de un agente VIVO (idle), con single-flight y
  // feedback del resultado real. `model` viene ya resuelto del `<select>`
  // inline (`renderLiveModelSelectorInline`), no de un `prompt()` —
  // T-AF024-US11-12, ajuste de diseño del usuario.
  //
  // Un único endpoint para ambos runtimes (T-AF024-US11-13, decisión de
  // producto 2026-08-17): `PUT /agents/{id}/model` — el backend resuelve
  // internamente el mecanismo real según el runtime (atajos de teclado
  // para OpenCode, comando interno '/model <id>' + confirmación de
  // diálogo para Claude Code, `set_active_model`/
  // `set_active_model_claude_code` en `atlas_forge/agent_model.py`).
  function changeLiveAgentModel(agent, model) {
    if (rolesSection.changeModelInFlight === agent.id) return;
    if (!model) return;
    rolesSection.changeModelInFlight = agent.id;
    rolesSection.changeModelError = null;
    renderRolesBody();

    BackendClient.setAgentModel(agent.id, model)
      .then(function (result) {
        rolesSection.changeModelInFlight = null;
        // Mensaje arriba de la lista (mismo canal que "Despertar"), no
        // pegado a la fila — decisión de producto 2026-08-17.
        rolesSection.actionMessage = result.changed
          ? "Modelo de " + agent.name + " cambiado a " + result.model + "."
          : "Modelo solicitado (" + result.model + ") para " + agent.name + ", pendiente de confirmar.";
        // Limpia la selección en curso: el siguiente render debe
        // preseleccionar contra el `agent.model` real ya actualizado
        // (próximo tick de polling), no arrastrar el índice de la
        // elección que se acaba de aplicar.
        delete rolesSection.liveModelIndexByAgentId[agent.id];
        renderRolesBody();
      })
      .catch(function (error) {
        rolesSection.changeModelInFlight = null;
        rolesSection.changeModelError = buildErrorMessage(error);
        renderRolesBody();
      });
  }

  // Selector de modelo INLINE para un agente OpenCode vivo en idle
  // (T-AF024-US11-12, ajuste de diseño del usuario, 2026-08-17): mismo
  // patrón visual que `renderRuntimeSelector` (dropdown directo en la
  // fila, sin botón previo que abrir) — un `<select>` con el catálogo
  // real de modelos disponibles para ese agente
  // (`GET /agents/{id}/available-models`, mismo endpoint que ya usaba el
  // flujo con `prompt()` que sustituye) más un botón "Confirmar" para
  // aplicar el cambio (`PUT /agents/{id}/model`, vía `changeLiveAgentModel`)
  // — a diferencia del runtime (elección diferida hasta "Lanzar"), cambiar
  // el modelo de un agente YA vivo tiene efecto inmediato en el backend,
  // así que no basta con un `change` silencioso: hace falta una
  // confirmación explícita para no aplicar el cambio con cada tecleo/click
  // accidental sobre el `<select>`.
  function renderLiveModelSelectorInline(agent) {
    var wrap = h("div", "agent-model");

    var cached = rolesSection.liveModelOptionsByAgentId[agent.id];
    if (cached === undefined) {
      // Catálogo no cargado todavía para este agente: dispara la carga
      // (una sola vez, `null` marca "ya en curso" para no repetir la
      // petición en cada re-render mientras responde) y muestra un
      // estado de carga inline.
      rolesSection.liveModelOptionsByAgentId[agent.id] = null;
      BackendClient.getAgentAvailableModels(agent.id)
        .then(function (result) {
          rolesSection.liveModelOptionsByAgentId[agent.id] = result.supports_model
            ? (result.models || [])
            : [];
          renderRolesBody();
        })
        .catch(function (error) {
          rolesSection.liveModelOptionsByAgentId[agent.id] = [];
          rolesSection.changeModelError = buildErrorMessage(error);
          renderRolesBody();
        });
    }

    // Claude Code no tiene lectura pasiva de modelo (agent.model siempre
    // null) — sin esto, el <select> siempre preseleccionaría el primer
    // elemento del catálogo en vez del modelo real con el que arrancó
    // (bug real reportado por el usuario en vivo, 2026-08-17: agente
    // lanzado con Haiku, la UI mostraba "Sonnet"). Consulta puntual, UNA
    // sola vez por agente (decisión de producto: nunca en cada polling,
    // mismo criterio ya fijado para GET /agents/{id}/status-model — solo
    // bajo demanda explícita, nunca automático en bucle). Guarda
    // INDEPENDIENTE de la carga del catálogo de arriba (bug real: antes
    // vivía anidada dentro de `if (cached === undefined)`, así que si el
    // catálogo ya estaba cacheado de un render previo, esta consulta
    // nunca se disparaba).
    var isClaudeCode = agent.runtime_id === "claude-code";
    var statusModelPending = isClaudeCode && rolesSection.statusModelByAgentId[agent.id] === undefined;
    if (statusModelPending) {
      rolesSection.statusModelByAgentId[agent.id] = "__pending__";
      BackendClient.getAgentStatusModel(agent.id)
        .then(function (result) {
          rolesSection.statusModelByAgentId[agent.id] = result.model || null;
          renderRolesBody();
        })
        .catch(function () {
          rolesSection.statusModelByAgentId[agent.id] = null;
          renderRolesBody();
        });
    }

    if (cached === undefined || cached === null) {
      wrap.appendChild(h("span", "agent-runtime-label", "Modelo: "));
      wrap.appendChild(document.createTextNode("cargando…"));
      return wrap;
    }

    // Claude Code: mientras la consulta real a /status está en curso, no
    // se construye el <select> con una preselección todavía desconocida
    // (bug real reportado por el usuario en vivo, 2026-08-17: se veía un
    // parpadeo "Sonnet" → "Opus" al cargar, porque el <select> se pintaba
    // antes de tener el dato real y luego se reconstruía al llegar la
    // respuesta) — se muestra "cargando…" hasta saber el valor real,
    // igual que ya hace el catálogo de arriba.
    if (isClaudeCode && rolesSection.statusModelByAgentId[agent.id] === "__pending__") {
      wrap.appendChild(h("span", "agent-runtime-label", "Modelo: "));
      wrap.appendChild(document.createTextNode("cargando…"));
      return wrap;
    }

    if (cached.length === 0) {
      // Catálogo vacío (o el agente no admite cambio pese a ser OpenCode,
      // caso borde defensivo) — se muestra el modelo actual como texto,
      // igual que antes de esta Task, sin selector inútil.
      wrap.appendChild(h("span", "agent-runtime-label", "Modelo: " + (agent.model || "sin modelo")));
      return wrap;
    }

    wrap.appendChild(h("span", "agent-runtime-label", "Modelo: "));
    var sel = document.createElement("select");
    // Mismo estilo visual que `.runtime-select` (compartido, no
    // duplicado en CSS), pero con una clase propia `.live-model-select`
    // — necesaria para distinguir este <select> de MODELO del de RUNTIME
    // por selector DOM (bug real detectado por
    // `agents_runtime_model_lifecycle.test.js` durante el desarrollo de
    // esta Task: con la misma clase, un test que comprobaba "un agente
    // vivo no debe tener selector de runtime" encontraba este <select> de
    // modelo y daba un falso positivo).
    sel.className = "clickable runtime-select live-model-select";
    // `cached` es `[{id, name, runtime}]` (contrato real de
    // `GET /agents/{id}/available-models`, verificado contra
    // `routes.py::get_agent_available_models`) — NUNCA un array de
    // strings. Bug real detectado en la propia verificación manual en
    // navegador de esta Task (el <select> mostraba literalmente
    // "[object Object]"): el valor que viaja a `PUT /agents/{id}/model`
    // es `m.id`, el texto visible es `m.name`.
    cached.forEach(function (m) {
      var option = document.createElement("option");
      option.setAttribute("value", m.id);
      option.textContent = m.name;
      sel.appendChild(option);
    });
    // Preselección: `liveModelIndexByAgentId` SOLO se rellena cuando el
    // usuario elige algo a mano en el <select> (evento "change" más
    // abajo) — nunca aquí. Bug real corregido (2026-08-17): antes esta
    // rama calculaba el índice inicial Y lo guardaba en
    // `liveModelIndexByAgentId`, así que si `statusModelByAgentId`
    // todavía no había respondido en el PRIMER render (la consulta a
    // `/status` es async), la preselección caía en el índice 0
    // ("Sonnet") y quedaba FIJADA para siempre — la respuesta real de
    // `/status` llegaba después, pero el índice ya cacheado nunca se
    // recalculaba (agente lanzado con Opus, la UI seguía mostrando
    // Sonnet indefinidamente). Ahora el cálculo se repite en CADA render
    // mientras el usuario no haya tocado el <select>.
    var userChosenIndex = rolesSection.liveModelIndexByAgentId[agent.id];
    var currentIndex;
    if (userChosenIndex !== undefined) {
      currentIndex = userChosenIndex;
    } else {
      // El modelo actual del agente si está en el catálogo, si no el
      // primero — nunca deja el <select> en un índice fuera de rango.
      // Para Claude Code, `agent.model` es siempre null (sin lectura
      // pasiva) — se usa en su lugar el texto real leído por `/status`
      // (`statusModelByAgentId`), con matching por inclusión de nombre:
      // el texto real trae formato libre (p. ej. "Default (Sonnet 5 ·
      // Efficient for routine tasks)"), nunca coincide exacto con el id
      // del catálogo ("sonnet") — sí contiene el nombre visible
      // ("Sonnet").
      var realModelText = agent.runtime_id === "claude-code"
        ? rolesSection.statusModelByAgentId[agent.id]
        : agent.model;
      var idxOfCurrent = realModelText
        ? cached.findIndex(function (m) {
            return m.id === realModelText || realModelText.toLowerCase().indexOf(m.name.toLowerCase()) !== -1;
          })
        : -1;
      currentIndex = idxOfCurrent >= 0 ? idxOfCurrent : 0;
    }
    sel.selectedIndex = Math.min(currentIndex, cached.length - 1);
    var isChanging = rolesSection.changeModelInFlight === agent.id;
    sel.disabled = isChanging;
    sel.addEventListener("change", function () {
      rolesSection.liveModelIndexByAgentId[agent.id] = sel.selectedIndex;
    });
    wrap.appendChild(sel);

    var confirmBtn = button(isChanging ? "Cambiando…" : "Confirmar", "agent-model-change");
    confirmBtn.disabled = isChanging;
    confirmBtn.addEventListener("click", function () {
      changeLiveAgentModel(agent, cached[sel.selectedIndex].id);
    });
    wrap.appendChild(confirmBtn);

    return wrap;
  }

  // ── botón Lanzar / Detener ──────────────────────────────────────────────

  // T-AF021-US03-04 (US-AF021-03, criterio 3): aviso best-effort de "Job en
  // curso" en el flujo de detener. Consulta `GET /jobs`, filtra los Jobs
  // `running` del agente objetivo y guarda el texto del aviso (o "") en
  // `rolesSection.runningJobNotice`. NO cambia el mecanismo de detención (el
  // humano decide); si el fetch falla, no hay aviso y la detención sigue.
  function refreshRunningJobNotice(agentId) {
    BackendClient.getJobs()
      .then(function (jobs) {
        var text = "";
        if (jobs && jobs.length) {
          var running = jobs.filter(function (job) {
            return (
              String(job.agent_id) === String(agentId) &&
              String(job.status) === "running"
            );
          });
          if (running.length) {
            var ids = running.map(function (job) { return String(job.id); }).join(", ");
            text = "⚠ Este agente tiene un Job en curso (" + ids + ", estado running) — detenerlo puede interrumpirlo.";
          }
        }
        rolesSection.runningJobNotice[agentId] = text;
        // Re-render solo si el agente sigue esperando confirmación (el flujo
        // no vuelve a disparar este refresh desde el render, así que no hay
        // bucle).
        var stillPending =
          rolesSection.devStopPendingFor === agentId ||
          (arquitectoState.stopPending &&
            arquitectoState.agent &&
            arquitectoState.agent.id === agentId);
        if (state.section === "roles" && stillPending) renderRolesBody();
      })
      .catch(function () {
        rolesSection.runningJobNotice[agentId] = "";
      });
  }

  function renderLanzarDetenerBtn(agent) {
    var isUnavailable = agent.status === "unavailable";
    var isLive = agent.id && agent.status !== "stopped" && agent.status !== "unregistered" && !isUnavailable;
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
          // T-AF021-US03-04: junto a la confirmación, aviso si el agente
          // tiene un Job en curso (best-effort, no bloquea la detención).
          var arqWrap = h("div", "agent-stop-confirm-wrap");
          var arqNotice = rolesSection.runningJobNotice[agent.id];
          if (arqNotice) {
            arqWrap.appendChild(h("span", "agent-stop-notice", arqNotice));
          }
          var stopConfirm = button("Confirmar detener", "arq-btn-stop-confirm");
          stopConfirm.addEventListener("click", stopArquitecto);
          arqWrap.appendChild(stopConfirm);
          return arqWrap;
        }
        var stopBtn = button("Detener", "agent-stop");
        stopBtn.addEventListener("click", stopArquitecto);
        return stopBtn;
      }
      if (arquitectoState.launchPending) {
        var lp = button("Lanzando…"); lp.disabled = true; return lp;
      }
      // ¿es sintético (no está lanzado) o stopped?
      var launchBtn = button(isUnregistered ? "Lanzar" : "Lanzar");
      // T-AF005-US07-03: el lanzamiento exige un runtime elegido — si no
      // hay ninguno, se bloquea con un aviso explícito (criterio 1 de
      // US-AF005-07: nunca se lanza con un runtime asumido en silencio).
      if (isUnregistered) {
        launchBtn.disabled = true;
        launchBtn.title = "rol no disponible todavía: pendiente de registrar en el backend";
      } else if (!chosenRuntimeForRow(agent)) {
        launchBtn.disabled = true;
        launchBtn.title = "Elige un runtime antes de lanzar";
      } else {
        launchBtn.addEventListener("click", function () { launchArquitecto(agent); });
      }
      return launchBtn;
    }

    // Developer: "Detener" elimina la instancia por completo (no pausa),
    // y exige confirmación de doble pulsación.
    if (showDetener) {
      if (rolesSection.devStopPendingFor === agent.id) {
        // T-AF021-US03-04: junto a la confirmación, aviso si el agente
        // tiene un Job en curso (best-effort, no bloquea la detención).
        var devWrap = h("div", "agent-stop-confirm-wrap");
        var devNotice = rolesSection.runningJobNotice[agent.id];
        if (devNotice) {
          devWrap.appendChild(h("span", "agent-stop-notice", devNotice));
        }
        var devStopConfirm = button("¿Seguro? Confirmar detener", "agent-stop");
        devStopConfirm.addEventListener("click", function () { stopDevAgent(agent); });
        devWrap.appendChild(devStopConfirm);
        return devWrap;
      }
      var devStop = button("Detener", "agent-stop");
      devStop.addEventListener("click", function () {
        rolesSection.devStopPendingFor = agent.id;
        rolesSection.runningJobNotice[agent.id] = "";
        refreshRunningJobNotice(agent.id);
        renderRolesBody();
      });
      return devStop;
    }

    // T-AF024-US11-16: un agente caído (`unavailable`, proceso muerto fuera
    // de atlas_forge) se LIBERA, no se lanza — retira su plaza del límite vía
    // `POST /agents/{id}/release` (backend T-AF005-US01-09). A diferencia de
    // "Lanzar" (que el backend rechazaría por plaza ocupada), liberar deja
    // la fila en estado lanzable de nuevo.
    if (isUnavailable) {
      var releaseBtn = button("Liberar", "agent-release");
      releaseBtn.addEventListener("click", function () { releaseCrashedAgent(agent); });
      return releaseBtn;
    }

    // Stopped, unavailable o unregistered
    var devLaunch = button("Lanzar");
    if (isUnregistered) {
      devLaunch.disabled = true;
      devLaunch.title = "rol no disponible todavía: pendiente de registrar en el backend";
    } else if (!chosenRuntimeForRow(agent)) {
      // T-AF005-US07-03: el lanzamiento exige un runtime elegido — se
      // bloquea con aviso explícito si no hay ninguno (criterio 1 de
      // US-AF005-07). Cada fila de Developer/Tester/UX/Auditor-OSS es un
      // slot independiente lanzable por su cuenta cuando se elige runtime
      // (T-AF005-US01-08, 2026-08-18).
      devLaunch.disabled = true;
      devLaunch.title = "Elige un runtime antes de lanzar";
    } else if (isStopped || isUnavailable) {
      devLaunch.addEventListener("click", function () { launchStoppedDev(agent); });
    }
    return devLaunch;
  }

  function stopDevAgent(agent) {
    if (!agent.id) return;
    BackendClient.stopAgent(agent.id)
      .then(function () {
        rolesSection.devStopPendingFor = null;
        rolesSection.actionMessage = agent.name + " eliminado.";
        return pollRolesAgents();
      })
      .catch(function (error) {
        rolesSection.devStopPendingFor = null;
        rolesSection.actionMessage = buildErrorMessage(error);
        renderRolesBody();
      });
  }

  // T-AF024-US11-16: libera un Developer caído (`unavailable`). Retira su
  // plaza del límite vía `POST /agents/{id}/release` (backend
  // T-AF005-US01-09). Tras el éxito se refresca la lista: el agente ya no
  // está en la sesión, la fila vuelve a ser sintética "stopped" lanzable
  // con su nombre original y reaparece el botón "Lanzar" con su selector de
  // runtime/modelo intactos. Si el backend falla (p. ej. endpoint aún no
  // disponible), se muestra el error del 400/404 sin romper la fila.
  function releaseCrashedAgent(agent) {
    if (!agent.id) return;
    if (rolesSection.releaseInFlight) return;
    rolesSection.releaseInFlight = true;
    BackendClient.releaseAgent(agent.id)
      .then(function () {
        rolesSection.releaseInFlight = false;
        rolesSection.actionMessage = agent.name + " liberado — plaza reutilizable.";
        return pollRolesAgents();
      })
      .catch(function (error) {
        rolesSection.releaseInFlight = false;
        rolesSection.actionMessage = buildErrorMessage(error);
        renderRolesBody();
      });
  }

  // T-AF005-US07-02: resuelve el runtime REAL de un id de modelo del
  // catálogo (`rolesSection.models`, `{id, name, runtime}` — el campo
  // `runtime` del catálogo usa snake_case: `claude_code` → `claude-code`).
  // Devuelve `null` si el modelo no está en el catálogo (p. ej. un modelo
  // libre de OpenCode), para que el llamador use su fallback.
  function launchRuntimeForModel(modelId) {
    var match = (rolesSection.models || []).find(function (m) { return m.id === modelId; });
    if (!match) return null;
    return match.runtime === "claude_code" ? "claude-code" : match.runtime;
  }

function launchStoppedDev(agent) {
    var payload = { role: agent.role };
    // T-AF005-US01-08 (2026-08-18): para Developer se envía el número de
    // slot de la fila pulsada (`developer_number`), de modo que el agente
    // nace con el nombre de ESA fila ("Developer-N"), no con el que el
    // conteo del backend decida en ese instante. Cada slot es
    // independiente (Developer-1/2/3), igual que Auditor-OSS/UX.
    if (agent.role === "developer") {
      var devMatch = /^Developer-(\d+)$/.exec(agent.name || "");
      if (devMatch) {
        payload.developer_number = parseInt(devMatch[1], 10);
      }
    }
    // T-AF005-US07-02/-03: el runtime se manda SIEMPRE explícito en
    // `POST /agents` (contrato: runtime separado del modelo), y es la
    // elección OBLIGATORIA de esta pantalla — se toma del selector de la
    // fila (`chosenRuntimeForRow`), nunca se infiere del modelo. Sin
    // runtime elegido el lanzamiento está bloqueado (el botón ya viene
    // deshabilitado); defensa aquí por si se llegara a invocar.
    var chosenRuntime = chosenRuntimeForRow(agent);
    if (!chosenRuntime) {
      rolesSection.actionMessage = "Elige un runtime antes de lanzar a " + agent.name + ".";
      renderRolesBody();
      return;
    }
    payload.runtime_type = chosenRuntime;

    // El modelo elegido POR FILA en el selector (T-AF024-US11-13,
    // 2026-08-17, tercera revisión: ahora tanto OpenCode como Claude
    // Code admiten elegir modelo al lanzar — antes solo OpenCode, y
    // tomado del default del rol en vez de una elección explícita por
    // instancia). Nunca el modelo recordado de una instancia anterior
    // (criterio 3 de US-AF005-07: tras detener un agente, no se reutiliza
    // el modelo recordado como si siguiera siendo válido) — el
    // `chosenModelByRow` se limpia al detener/cambiar runtime. Opcional:
    // si no se elige nada, se lanza sin `model_id` (el runtime arranca
    // con su propio default).
    var chosenModel = chosenModelForRow(agent);
    if (chosenModel) {
      payload.model_id = chosenModel;
    }
    // Se refresca la lista justo antes de lanzar para reducir la ventana
    // de desincronización con el polling de 3s; el nombre real de la
    // instancia se confirma después con `launchFeedbackMessageFor(result)`.
    pollRolesAgents().then(function () {
      return BackendClient.launchAgent(payload);
    }).then(function (result) {
        rolesSection.actionMessage = launchFeedbackMessageFor(result);
        return pollRolesAgents();
      })
      .catch(function (error) {
        rolesSection.actionMessage = buildErrorMessage(error);
        renderRolesBody();
      });
  }

  // ── botón Copiar comando de conexión ────────────────────────────────────

  function renderCommandoConexionDetalle(agent) {
    // Híbrido (T-AF023-US04, decisión del usuario): el `opencode run` del
    // agente OpenCode vive en una sesión tmux determinista
    // (`developer-1-<proyecto>`), así que el comando de conexión es SIEMPRE
    // el tmux clásico — el `session_name` del agente es un nombre de sesión
    // tmux real que conecta.
    var comando = "tmux -L atlas-forge attach -t " + agent.session_name;
    var wrap = h("div", "agent-comando-conexion");
    wrap.appendChild(h("span", null, "Comando conexión: "));

    var codeBlock = document.createElement("code");
    codeBlock.textContent = comando;
    codeBlock.style.cursor = "pointer";
    codeBlock.title = "Click para copiar";
    codeBlock.addEventListener("click", function () {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(comando).then(function () {
          var prevText = codeBlock.textContent;
          codeBlock.textContent = "Copiado ✓";
          setTimeout(function () {
            codeBlock.textContent = prevText;
          }, 2500);
        });
      } else {
        codeBlock.select();
      }
    });
    wrap.appendChild(codeBlock);
    return wrap;
  }

  // ── botón Ver log en vivo (T-AF032-US02-01) ─────────────────────────────

  function renderVerLogEnVivoBtn(agent) {
    var isLive = agent.id && agent.status !== "stopped" && agent.status !== "unregistered" && agent.status !== "unavailable";
    var canOpen = isLive && agent.session_name;

    var btn = button("Ver log en vivo", "agent-model-change");
    btn.disabled = !canOpen;
    if (!canOpen) {
      btn.title = "no disponible: el agente no tiene sesión activa";
      return btn;
    }
    btn.addEventListener("click", function () {
      window.open(
        "/ui/agent-pane.html?agent_id=" + encodeURIComponent(agent.id),
        "_blank"
      );
    });
    return btn;
  }


  // ── botón Despertar (envía un empujón al pane) ──────────────────────────
  // Siempre visible; deshabilitado solo cuando no hay sesión tmux viva a
  // la que enviar nada (stopped/unregistered/unavailable) — decisión de
  // producto 2026-08-17: el estado `working` del backend es una
  // transición manual que solo dispara el Dispatcher al despachar un Job
  // formal (`mark_working`, `atlas_forge/agents/lifecycle.py`), no una
  // detección real de actividad en el pane; un agente puede estar
  // realmente ocupado (conversación directa por tmux, fuera del
  // mecanismo de Jobs) mientras el backend lo sigue reportando `idle`.
  // Limitar el botón a `working` lo dejaba inutilizable en ese caso real
  // — se habilita en cualquier estado "vivo" (idle/working/limited).

  function renderDespertarBtn(agent) {
    var isAlive = agent.status === "idle" || agent.status === "working" || agent.status === "limited";
    var isAwakening = rolesSection.awakeningAgentId === agent.id;
    var label = isAwakening ? "Despertando…" : "Despertar";
    var btn = button(label, "agent-model-change");

    if (!isAlive) {
      btn.disabled = true;
      btn.title = "no disponible: el agente no tiene una sesión activa";
      return btn;
    }
    btn.disabled = isAwakening;

    btn.addEventListener("click", function () {
      if (isAwakening) return;
      requestAwaken(agent);
    });
    return btn;
  }

  function requestAwaken(agent) {
    if (rolesSection.awakeningAgentId) return;

    rolesSection.awakeningAgentId = agent.id;
    rolesSection.awakenError = null;
    renderRolesBody();

    BackendClient.sendAgentKeys(agent.id, "continua")
      .then(function () {
        rolesSection.awakeningAgentId = null;
        rolesSection.actionMessage =
          "Empujón enviado a " + agent.name + ".";
        renderRolesBody();
        return pollRolesAgents();
      })
      .catch(function (error) {
        rolesSection.awakeningAgentId = null;
        rolesSection.awakenError = buildErrorMessage(error);
        renderRolesBody();
      });
  }

  // ── editor inline de modelo por defecto ──────────────────────────────────

  function renderDefaultModelEditorInline(wrap, role) {
    var enabledModels = rolesSection.models.filter(function (m) { return m.enabled; });
    var defaultModel = rolesSection.defaults[role];

    wrap.appendChild(h("p", "section-note",
      "Modelo por defecto del rol " + role + " (compartido por todas sus instancias al lanzarlas)."));

    // T-AF024-US11-09 criterio 3: Arquitecto es un rol de instancia única
    // sin fila sintética alternativa — dejarlo sin default bloquea "Lanzar"
    // sin que el usuario entienda por qué. A diferencia de Developer (varias
    // filas, tiene sentido dejar alguna sin default entre lanzamientos), aquí
    // se bloquea la opción en el propio <select> con el motivo visible.
    var isArquitecto = role === "arquitecto";
    if (isArquitecto) {
      wrap.appendChild(h("p", "section-note",
        "Arquitecto necesita siempre un modelo asignado: sin él, \"Lanzar\" queda deshabilitado."));
    }

    var sel = document.createElement("select");
    sel.className = "clickable launch-select";
    sel.style.margin = "6px 0";
    var noneOpt = document.createElement("option");
    noneOpt.value = "";
    noneOpt.textContent = "— sin default —";
    if (isArquitecto) {
      noneOpt.disabled = true;
      noneOpt.title = "Arquitecto no puede quedar sin modelo por defecto";
    }
    sel.appendChild(noneOpt);
    // T-AF024-US11-07: mientras el usuario no haya interactuado con el
    // <select> (`modelIndexDirty` false), cada reconstrucción refleja el
    // default real del backend, igual que antes. En cuanto interactúa,
    // cualquier reconstrucción posterior (incluido un tick de polling con
    // el editor todavía abierto) debe reflejar `modelIndex` — su elección
    // en curso — y no volver a saltar al default aunque no haya pulsado
    // "Guardar modelo" todavía.
    enabledModels.forEach(function (model, idx) {
      var o = document.createElement("option");
      o.value = String(idx);
      o.textContent = model.name + " (" + model.runtime + ")";
      if (rolesSection.modelIndexDirty) {
        if (rolesSection.modelIndex === idx) o.selected = true;
      } else if (defaultModel === model.id) {
        o.selected = true;
      }
      sel.appendChild(o);
    });
    sel.addEventListener("change", function () {
      rolesSection.modelIndex = parseInt(sel.value, 10) || 0;
      rolesSection.modelIndexDirty = true;
    });
    // T-AF024-US11-08: comportamiento nativo del <select> HTML — con el
    // elemento enfocado, el scroll-wheel del navegador cambia la opción
    // resaltada (y dispara "change") sin que el usuario haya abierto el
    // desplegable ni confirmado nada. Bloquear el evento "wheel" mientras
    // el select tiene foco impide ese cambio accidental; el usuario sigue
    // pudiendo elegir con clic/teclado (Enter/flechas tras abrir con clic
    // o Space), que sí son acciones explícitas.
    sel.addEventListener("wheel", function (event) {
      event.preventDefault();
    }, { passive: false });
    wrap.appendChild(sel);

    var actionsRow = h("div", "agent-actions");

    var saveBtn = button(rolesSection.saving ? "Guardando…" : "Guardar modelo");
    if (rolesSection.saving) saveBtn.disabled = true;
    saveBtn.addEventListener("click", function () { saveRoleModel(role); });
    actionsRow.appendChild(saveBtn);

    var cancelBtn = button("Cancelar", "agent-model-change");
    cancelBtn.addEventListener("click", function () {
      rolesSection.editingRole = null;
      rolesSection.editingRowKey = null;
      rolesSection.modelIndex = 0;
      rolesSection.modelIndexDirty = false;
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

    // T-AF024-US11-09 criterio 3 (defensa en profundidad): el <select> ya
    // deshabilita "— sin default —" para Arquitecto, pero si de todos modos
    // no hay ningún modelo real seleccionable (p. ej. catálogo sin modelos
    // habilitados), no se guarda un default vacío en silencio.
    if (role === "arquitecto" && !modelId) {
      rolesSection.saveError = "Arquitecto no puede quedar sin modelo por defecto: elige un modelo del catálogo.";
      renderRolesBody();
      return;
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
        rolesSection.editingRowKey = null;
        rolesSection.modelIndex = 0;
        rolesSection.modelIndexDirty = false;
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

  // ------------------------------------------------------- Configuración
  // (US-AF024-12): catálogo abierto de preferencias de sistema. Hoy solo
  // el límite de Developer simultáneos; el siguiente valor configurable
  // que aparezca se añade como otra fila del mismo formulario.

  function renderConfiguracionInto(content) {
    configuracionSection.bodyWrap = content;
    if (configuracionSection.state === null) {
      loadSystemPreferences();
      content.appendChild(h("p", "section-note", "Cargando configuración…"));
      return;
    }
    if (configuracionSection.state === "loading") {
      content.appendChild(h("p", "section-note", "Cargando configuración…"));
      return;
    }
    if (configuracionSection.state === "unavailable") {
      content.appendChild(h("p", "agent-error", configuracionSection.error));
      return;
    }
    renderConfiguracionBody();
  }

  function loadSystemPreferences() {
    configuracionSection.state = "loading";
    BackendClient.getSystemPreferences()
      .then(function (result) {
        configuracionSection.state = "ready";
        configuracionSection.maxSimultaneousDevelopers = result.max_simultaneous_developers;
        configuracionSection.maxSimultaneousDevelopersInput = String(result.max_simultaneous_developers);
configuracionSection.developerWaitsForTesterReview = result.developer_waits_for_tester_review;
        // T-AF036-US27-02: modo de expansión del backlog desde el backend.
        configuracionSection.backlogMultipleExpansion = result.backlog_multiple_expansion || "single";
        // T-AF022-US18-04: reencolado automático de huérfanas (default false).
        configuracionSection.autoReenqueueOrphaned = !!result.auto_reenqueue_orphaned;
        configuracionSection.backlogMultipleExpansionDirty = false;
        configuracionSection.dirty = false;
        // T-AF036-US27-03: el modo de expansión se aplica al Backlog.
        backlogSection.expansionMode = result.backlog_multiple_expansion === "multi" ? "multi" : "single";
        configuracionSection.saveError = null;
        renderConfiguracionBody();
      })
      .catch(function (error) {
        configuracionSection.state = "unavailable";
        configuracionSection.error = buildErrorMessage(error);
        renderConfiguracionBody();
      });
  }

  function renderConfiguracionBody() {
    var wrap = configuracionSection.bodyWrap;
    if (!wrap) return;
    wrap.textContent = "";

    if (configuracionSection.state !== "ready") return;

    var form = h("div", "jobs-form");

    form.appendChild(h("div", "jobs-form-title", "Preferencias de sistema"));

    var row = h("div", "model-row");
    row.appendChild(h("span", "model-role-label", "Máximo de Developer simultáneos: "));
    var input = document.createElement("input");
    input.type = "number";
    input.min = "1";
    input.step = "1";
    input.className = "clickable";
    input.value = configuracionSection.maxSimultaneousDevelopersInput;
    input.addEventListener("input", function () {
      configuracionSection.maxSimultaneousDevelopersInput = input.value;
      configuracionSection.dirty =
        String(configuracionSection.maxSimultaneousDevelopers) !== input.value ||
        configuracionSection.backlogMultipleExpansionDirty;
      renderConfiguracionBody();
    });
    row.appendChild(input);
    form.appendChild(row);
    form.appendChild(h(
      "p",
      "section-note",
      "Número de instancias de Developer que puedes tener lanzadas a la vez. Cambiarlo no afecta a las instancias ya lanzadas, solo al límite para lanzar nuevas."
    ));

    // T-AF036-US27-02: modo de expansión del backlog — `single` (una Epic/US
    // desplegada a la vez) o `multi` (varias a la vez).
    var expansionRow = h("div", "model-row");
    expansionRow.appendChild(h("span", "model-role-label", "Despliegue del Backlog: "));
    var expansionSelect = document.createElement("select");
    expansionSelect.className = "clickable";
    var expansionOptions = [
      { value: "single", label: "Una Epic/US desplegada a la vez" },
      { value: "multi", label: "Varias Epics y US desplegadas a la vez" },
    ];
    expansionOptions.forEach(function (opt) {
      var o = document.createElement("option");
      o.setAttribute("value", opt.value);
      o.textContent = opt.label;
      expansionSelect.appendChild(o);
    });
    expansionSelect.value = configuracionSection.backlogMultipleExpansion;
    expansionSelect.addEventListener("change", function () {
      configuracionSection.backlogMultipleExpansion = expansionSelect.value;
      configuracionSection.backlogMultipleExpansionDirty = true;
      configuracionSection.dirty =
        String(configuracionSection.maxSimultaneousDevelopers) !== configuracionSection.maxSimultaneousDevelopersInput ||
        true;
      renderConfiguracionBody();
    });
    expansionRow.appendChild(expansionSelect);
    form.appendChild(expansionRow);

    var saveBtn = button("Guardar preferencias");
    var maxDirty = String(configuracionSection.maxSimultaneousDevelopers) !== configuracionSection.maxSimultaneousDevelopersInput;
    var parsedValue = parseInt(configuracionSection.maxSimultaneousDevelopersInput, 10);
    // El máximo solo se valida si está modificado; si cambió solo la expansión,
    // el valor de max developers (sin tocar) es válido.
    var isValidMax = !maxDirty || (
      configuracionSection.maxSimultaneousDevelopersInput.trim() !== ""
      && !isNaN(parsedValue)
      && String(parsedValue) === configuracionSection.maxSimultaneousDevelopersInput.trim()
      && parsedValue >= 1
    );
    var isValidValue = isValidMax;
    if (configuracionSection.saving || !configuracionSection.dirty || !isValidValue) {
      saveBtn.disabled = true;
    }
    if (configuracionSection.saving) {
      saveBtn.textContent = "Guardando…";
    }
    saveBtn.addEventListener("click", saveSystemPreferences);
    form.appendChild(saveBtn);

    if (configuracionSection.dirty && !isValidValue) {
      form.appendChild(h("p", "agent-error", "Introduce un número entero mayor que 0."));
    }
    if (configuracionSection.saveError) {
      form.appendChild(h("p", "agent-error", configuracionSection.saveError));
    }
    if (!configuracionSection.dirty && !configuracionSection.saving) {
      form.appendChild(h("p", "section-note", "Sin cambios pendientes."));
    }

    form.appendChild(h("div", "jobs-form-title", "Dispatcher"));

    var reviewRow = h("div", "model-row");
    var reviewLabel = document.createElement("label");
    var reviewCheckbox = document.createElement("input");
    reviewCheckbox.type = "checkbox";
    reviewCheckbox.checked = !!configuracionSection.developerWaitsForTesterReview;
    reviewCheckbox.disabled = !!configuracionSection.savingReviewPreference;
    reviewCheckbox.addEventListener("change", function () {
      saveDeveloperWaitsForTesterReview(reviewCheckbox.checked);
    });
    reviewLabel.appendChild(reviewCheckbox);
    reviewLabel.appendChild(document.createTextNode(" El Developer espera al veredicto del Tester antes de coger una Task nueva"));
    reviewRow.appendChild(reviewLabel);
    form.appendChild(reviewRow);
    form.appendChild(h(
      "p",
      "section-note",
      "Si está activo, un Developer con una Task suya todavía en IN_REVIEW no recibe una Task TO_DEVELOP nueva hasta que el Tester la resuelva."
    ));
    if (configuracionSection.reviewPreferenceSaveError) {
      form.appendChild(h("p", "agent-error", configuracionSection.reviewPreferenceSaveError));
    }

    // T-AF022-US18-04: toggle "reencolar automáticamente las huérfanas tras
    // reinicio/pérdida de Job" — persiste `auto_reenqueue_orphaned`. Con él
    // activo, una Task `dispatched` huérfana (Job perdido) vuelve a
    // `TO_DEVELOP` en vez de a `READY`, re-encolada sola.
    var orphanRow = h("div", "model-row");
    var orphanLabel = document.createElement("label");
    var orphanCheckbox = document.createElement("input");
    orphanCheckbox.type = "checkbox";
    orphanCheckbox.checked = !!configuracionSection.autoReenqueueOrphaned;
    orphanCheckbox.disabled = !!configuracionSection.savingOrphanPreference;
    orphanCheckbox.addEventListener("change", function () {
      saveAutoReenqueueOrphaned(orphanCheckbox.checked);
    });
    orphanLabel.appendChild(orphanCheckbox);
    orphanLabel.appendChild(document.createTextNode(" Reencolar automáticamente las huérfanas tras reinicio/pérdida de Job"));
    orphanRow.appendChild(orphanLabel);
    form.appendChild(orphanRow);
    form.appendChild(h(
      "p",
      "section-note",
      "Si está activo, la reconciliación revierte una Task huérfana (IN_PROGRESS/dispatched sin Job en vuelo) a TO_DEVELOP para que el Dispatcher la re-despache sola; si no, vuelve a READY para decisión humana."
    ));
    if (configuracionSection.orphanPreferenceSaveError) {
      form.appendChild(h("p", "agent-error", configuracionSection.orphanPreferenceSaveError));
    }

    form.appendChild(h("div", "jobs-form-title", "Reiniciar Atlas Forge"));

    form.appendChild(h(
      "p",
      "section-note",
      "Reinicia el servicio atlas-forge-api. Durante unos segundos la web no podrá contactar con el backend y los agentes quedarán momentáneamente inaccesibles desde la web (sus sesiones tmux sobreviven al reinicio)."
    ));

    if (configuracionSection.restarting) {
      form.appendChild(h("p", "section-note", "Reiniciando… esperando a que el backend vuelva a responder."));
    } else if (configuracionSection.restartPendingFor) {
      var restartConfirm = button("¿Seguro? Confirmar reinicio", "agent-stop");
      restartConfirm.addEventListener("click", requestSystemRestart);
      form.appendChild(restartConfirm);
    } else {
      var restartBtn = button("Reiniciar Atlas Forge", "agent-stop");
      restartBtn.addEventListener("click", function () {
        configuracionSection.restartPendingFor = true;
        renderConfiguracionBody();
      });
      form.appendChild(restartBtn);
    }

    if (configuracionSection.restartMessage) {
      form.appendChild(h("p", "section-note", configuracionSection.restartMessage));
    }
    if (configuracionSection.restartError) {
      form.appendChild(h("p", "agent-error", configuracionSection.restartError));
    }

    wrap.appendChild(form);
  }

  function saveDeveloperWaitsForTesterReview(nextValue) {
    configuracionSection.savingReviewPreference = true;
    configuracionSection.reviewPreferenceSaveError = null;
    renderConfiguracionBody();

    BackendClient.updateSystemPreferences({ developer_waits_for_tester_review: nextValue })
      .then(function (result) {
        configuracionSection.savingReviewPreference = false;
        configuracionSection.developerWaitsForTesterReview = result.developer_waits_for_tester_review;
        renderConfiguracionBody();
      })
      .catch(function (error) {
        configuracionSection.savingReviewPreference = false;
        configuracionSection.reviewPreferenceSaveError = buildErrorMessage(error);
        renderConfiguracionBody();
      });
  }

  // T-AF022-US18-04: toggle "reencolar automáticamente las huérfanas tras
  // reinicio/pérdida de Job" — persiste `auto_reenqueue_orphaned`. Mismo
  // patrón que `saveDeveloperWaitsForTesterReview` (guardada independiente
  // del resto de preferencias, con su propio single-flight y error).
  function saveAutoReenqueueOrphaned(nextValue) {
    configuracionSection.savingOrphanPreference = true;
    configuracionSection.orphanPreferenceSaveError = null;
    renderConfiguracionBody();

    BackendClient.updateSystemPreferences({ auto_reenqueue_orphaned: nextValue })
      .then(function (result) {
        configuracionSection.savingOrphanPreference = false;
        configuracionSection.autoReenqueueOrphaned = !!result.auto_reenqueue_orphaned;
        renderConfiguracionBody();
      })
      .catch(function (error) {
        configuracionSection.savingOrphanPreference = false;
        configuracionSection.orphanPreferenceSaveError = buildErrorMessage(error);
        renderConfiguracionBody();
      });
  }

  function saveSystemPreferences() {
    if (configuracionSection.saving) return;
    var maxDirty = String(configuracionSection.maxSimultaneousDevelopers) !== configuracionSection.maxSimultaneousDevelopersInput;
    var parsedValue = parseInt(configuracionSection.maxSimultaneousDevelopersInput, 10);
    var isValidValue = configuracionSection.maxSimultaneousDevelopersInput.trim() !== ""
      && !isNaN(parsedValue)
      && String(parsedValue) === configuracionSection.maxSimultaneousDevelopersInput.trim()
      && parsedValue >= 1;
    if (maxDirty && !isValidValue) return;

    configuracionSection.saving = true;
    configuracionSection.saveError = null;
    renderConfiguracionBody();

    // T-AF036-US27-02: payload con los campos modificados — el máximo (si
    // cambió) y/o el modo de expansión del backlog (si cambió).
    var payload = {};
    if (maxDirty) {
      payload.max_simultaneous_developers = parsedValue;
    }
    if (configuracionSection.backlogMultipleExpansionDirty) {
      payload.backlog_multiple_expansion = configuracionSection.backlogMultipleExpansion;
    }

    BackendClient.updateSystemPreferences(payload)
      .then(function (result) {
        configuracionSection.saving = false;
        configuracionSection.dirty = false;
        configuracionSection.backlogMultipleExpansionDirty = false;
        configuracionSection.maxSimultaneousDevelopers = result.max_simultaneous_developers;
        configuracionSection.maxSimultaneousDevelopersInput = String(result.max_simultaneous_developers);
        configuracionSection.backlogMultipleExpansion = result.backlog_multiple_expansion || "single";
        // T-AF036-US27-04: cambio de modo en caliente — el modo guardado se
        // aplica al Backlog en el acto, sin recargar la página (criterio 2 de
        // la US). No se migra el estado de expansión en curso entre modos:
        // la selección abierta del modo anterior colapsa y se reabre en el
        // nuevo (comportamiento documentado en T-AF036-US27-04).
        backlogSection.expansionMode = result.backlog_multiple_expansion === "multi" ? "multi" : "single";
        renderConfiguracionBody();
      })
      .catch(function (error) {
        configuracionSection.saving = false;
        configuracionSection.saveError = buildErrorMessage(error);
        renderConfiguracionBody();
      });
  }

  // Reinicio del servicio (T-AF037-US05-02): captura el nº de agentes
  // antes, lanza `POST /system/restart` (fire-and-forget, 202) y hace
  // polling a `GET /agents` hasta que el backend vuelve a responder. Los
  // errores de conexión durante la caída son esperados, no un fallo.
  var RESTART_POLL_MILLIS = 3000;
  var RESTART_POLL_TIMEOUT_MILLIS = 90000;

  function requestSystemRestart() {
    if (configuracionSection.restarting) return;
    configuracionSection.restartPendingFor = false;
    configuracionSection.restarting = true;
    configuracionSection.restartMessage = null;
    configuracionSection.restartError = null;
    renderConfiguracionBody();

    BackendClient.getAgents()
      .then(function (agents) {
        var beforeCount = Array.isArray(agents) ? agents.length : 0;
        return BackendClient.restartSystem().then(function () {
          startRestartPolling(beforeCount);
        });
      })
      .catch(function (error) {
        configuracionSection.restarting = false;
        configuracionSection.restartError = buildErrorMessage(error);
        renderConfiguracionBody();
      });
  }

  function startRestartPolling(beforeAgentCount) {
    var startedAt = Date.now();
    var attempts = 0;

    function poll() {
      attempts += 1;
      BackendClient.getAgents()
        .then(function (agents) {
          var afterCount = Array.isArray(agents) ? agents.length : 0;
          configuracionSection.restarting = false;
          configuracionSection.restartPollTimer = null;
          if (afterCount === beforeAgentCount) {
            configuracionSection.restartMessage =
              "Reinicio completado. El backend responde de nuevo con " + afterCount + " agente(s), los mismos que antes del reinicio.";
          } else {
            configuracionSection.restartMessage =
              "Reinicio completado, pero el número de agentes ha cambiado (antes: " + beforeAgentCount + ", ahora: " + afterCount + "). Revisa el log de reconciliación en .claude/state/<proyecto>/reconciliation_log.jsonl.";
          }
          renderConfiguracionBody();
        })
        .catch(function () {
          // Backend caído todavía: esperado durante el reinicio. Se sigue
          // sondeando hasta el timeout.
          if (Date.now() - startedAt >= RESTART_POLL_TIMEOUT_MILLIS) {
            configuracionSection.restarting = false;
            configuracionSection.restartPollTimer = null;
            configuracionSection.restartError =
              "El backend no ha vuelto a responder tras " + Math.round(RESTART_POLL_TIMEOUT_MILLIS / 1000) + "s. Comprueba el estado del servicio (systemctl status atlas-forge-api).";
            renderConfiguracionBody();
            return;
          }
          configuracionSection.restartPollTimer = setTimeout(poll, RESTART_POLL_MILLIS);
        });
    }

    configuracionSection.restartPollTimer = setTimeout(poll, RESTART_POLL_MILLIS);
  }

  // ------------------------------------------------------------- AF-025
  // Acciones transversales de proyecto (US-AF025-01 a US-AF025-07): desde
  // T-AF034-US01-02 se dibujan dentro del catálogo combinado de la sección
  // SCRIPTS (`renderActionCard`/`runAction`/`renderActionResult`, que viven
  // en el bloque SCRIPTS), consumiendo los metadatos del backend
  // (`GET /scripts` via `list_actions()`), no esta constante hardcodeada.
  // El backend de ejecución es el mismo (`POST /project/actions/{id}`).
  // Eliminada aquí la antigua pestaña independiente y su estado propio.

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
        // T-AF008-US15-01/-02 (2026-08-17): NO_TASKS/TO_PLAN (AF-040;
        // antes EN_DISEÑO) también son trabajo pendiente real (una US
        // recién creada, o esperando al Arquitecto) — antes solo contaba
        // TO_DO, dejando el badge en 0 pese a haber Epics/US con trabajo
        // real por hacer.
        (report.by_epic || []).forEach(function (epic) {
          count += (epic.user_stories && epic.user_stories.READY || 0)
                 + (epic.user_stories && epic.user_stories.NO_TASKS || 0)
                 + (epic.user_stories && epic.user_stories.TO_PLAN || 0)
                 + (epic.user_stories && epic.user_stories.TO_DEVELOP || 0)
                 + (epic.tasks && epic.tasks.READY || 0)
                 + (epic.tasks && epic.tasks.TO_DEVELOP || 0);
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

  // T-AF024-US11-09 criterio 2: traduce el 400 crudo de
  // LaunchAgentRequest.resolved_runtime_type ("Se requiere 'runtime_type' o
  // 'model_id'/'model' para lanzar un agente.") a un mensaje accionable que
  // le dice al usuario exactamente qué hacer, en vez de mostrar el texto
  // literal del backend. Defensa en profundidad: el guard síncrono de
  // `launchArquitecto` ya debería impedir que esta llamada llegue a
  // dispararse, pero si de todos modos llega, no se muestra en crudo.
  function translateArquitectoError(message) {
    if (typeof message === "string" && message.indexOf("runtime_type") !== -1 && message.indexOf("model_id") !== -1) {
      return "El Arquitecto no tiene modelo asignado — ve a \"Cambiar modelo\" y elige uno antes de lanzar.";
    }
    return message;
  }

  // -------------------------------------------------- abrir selector (US02-02)
  function openProjectPicker(reason) {
    state.pickerReason = reason || "initial";
    state.showPicker = true;
    render();
  }

  // -------------------------------------------------- seleccionar proyecto
  function requestSelectProject(project) {
    selectProject(project);
  }

  function selectProject(project) {
    stopArquitectoPolling();
    clearRoot();
    ROOT.textContent = "Seleccionando proyecto…";
    BackendClient.selectProject(project.id)
      .then(function () {
        state.showPicker = false;
        // Al cambiar de proyecto se resetea el contexto; las secciones
        // operativas se vuelven a cargar para la nueva sesión (sus datos
        // dependen del proyecto activo).
        state.sections = { jobs: null, plan: null, scripts: null, backlog: null, roles: null };
        return loadContext();
      })
      .catch(function (error) {
        state.showPicker = false;
        showError(buildErrorMessage(error), loadContext);
      });
  }

  // ------------------------------------------------- AF-028 Pestaña Arquitecto
  // (US-AF028-02): 5 órdenes deterministas, prompt libre e historial de
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

  // T-AF021-US02-04: enlace "Atlas Forge" de la cabecera hacia la
  // sección de inicio (backlog). Listener registrado una sola vez aquí
  // (fuera de renderOperational, que se re-ejecuta en cada cambio de
  // sección) porque el elemento vive en index.html, no en el árbol
  // gestionado por app.js.
  var atlasForgeHomeLink = document.getElementById("atlas-forge-home-link");
  if (atlasForgeHomeLink) {
    atlasForgeHomeLink.addEventListener("click", function (event) {
      event.preventDefault();
      switchSection("backlog");
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    checkConnectivity();
  });
})();