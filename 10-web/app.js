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

  // --------------------------------------------------------------- state
  var state = {
    connected: false, // getHealth respondió OK
    projects: [], // candidatos descubiertos (GET /projects)
    active: null, // proyecto activo (GET /project) o null si no hay
    contextError: null,
    // Navegación entre secciones operativas (solo visible con contexto
    // resuelto). `sections` guarda el estado ya cargado de cada sección
    // para NO perderlo al navegar entre ellas sin recargar (punto 5).
    section: "agents",
    sections: { agents: null, jobs: null, plan: null, scripts: null },
    showPicker: false,
    pickerReason: "initial", // "initial" (onboarding) | "change" (voluntario)
    pendingSelection: null,
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

    // Menú/pestañas simples entre las 4 secciones operativas (punto 1):
    // enlaces/botones que cambian qué sección del DOM se muestra, sin
    // recargar la página.
    var nav = h("nav", "section-nav");
    ["agents", "jobs", "plan", "scripts"].forEach(function (key) {
      var tab = button(SECTION_LABEL(key), "section-tab");
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
    return { agents: "Agentes", jobs: "Jobs", plan: "Plan", scripts: "Scripts" }[key];
  }

  function switchSection(key) {
    if (key !== state.section && state.section === "agents") {
      // Al salir de la pestaña Agentes se para el polling (no se hacen
      // llamadas de fondo sin pantalla visible); al volver se reanuda.
      stopAgentsPolling();
    }
    if (key !== state.section && state.section === "jobs") {
      // Al salir de la pestaña Jobs se cierra el WebSocket (no se mantiene
      // una conexión de fondo sin pantalla visible); al volver se reabre.
      // El estado propio de la sección no se pierde: vive en `jobsSection`.
      stopJobsWebSocket();
    }
    if (key !== state.section && state.section === "plan") {
      // Mismo criterio que Jobs: al salir de la pestaña Plan se cierra el
      // canal `WS /ws/plans`; el estado vive en `plansSection`.
      stopPlansWebSocket();
    }
    state.section = key;
    renderOperational();
  }

  // ----------------------------------------------------- contenido sección
  function renderSectionContent() {
    var content = h("div", "section-content");
    content.appendChild(h("h3", null, SECTION_LABEL(state.section)));

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
  // agente (T-FB021-US03-02): "Ver actividad" (pane) y "Detener"
  // (confirmación de segunda pulsación). La fila de acciones está alineada
  // a la derecha y el botón "Detener" es el ÚLTIMO elemento: al crecer su
  // etiqueta con el aviso combinado se expande hacia la izquierda, sin
  // desplazar su borde derecho ni mover el botón entre el primer y el
  // segundo clic (bug real corregido en la TUI, ver `agents.py`).
  function renderAgentActions(agent) {
    var actions = h("div", "agent-actions");

    var paneBtn = button("Ver actividad");
    paneBtn.addEventListener("click", function () {
      viewAgentPane(agent);
    });
    actions.appendChild(paneBtn);

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

    var select = document.createElement("select");
    select.className = "clickable launch-select";
    catalog.forEach(function (opt, idx) {
      var o = document.createElement("option");
      o.setAttribute("value", String(idx));
      o.textContent =
        roleLabel(opt.agent_role) +
        " sobre " +
        opt.runtime_name +
        (opt.supports_model ? " (admite modelo)" : " (no admite modelo)");
      select.appendChild(o);
    });
    select.selectedIndex = agentsSection.optionIndex;
    select.addEventListener("change", function () {
      agentsSection.optionIndex = parseInt(select.value, 10) || 0;
      renderAgentsBody();
    });
    form.appendChild(select);

    var modelInput = document.createElement("input");
    modelInput.type = "text";
    modelInput.className = "clickable";
    if (option.supports_model) {
      modelInput.value = agentsSection.modelInput;
      modelInput.placeholder = "Modelo (opcional, solo si el runtime lo admite)";
      modelInput.addEventListener("input", function () {
        agentsSection.modelInput = modelInput.value;
      });
    } else {
      modelInput.disabled = true;
      modelInput.value = "";
      modelInput.placeholder = "Este runtime no admite modelo";
    }
    form.appendChild(modelInput);

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
    var launchBtn = button("Lanzar");
    if (agentsSection.launching) {
      launchBtn.disabled = true;
      launchBtn.textContent = "Lanzando…";
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

  // Lanzar (`POST /agents`). Single-flight: si ya hay una petición en
  // vuelo, la segunda invocación se descarta de inmediato (no se encola,
  // no se despacha un segundo agente).
  function launchAgents() {
    if (agentsSection.launching) return;
    var option = agentsSection.catalog[agentsSection.optionIndex];
    if (!option) return;

    agentsSection.launching = true;
    agentsSection.actionMessage = null;
    // Re-render inmediato: el botón queda deshabilitado ("Lanzando…")
    // mientras la petición está en vuelo, además del descarte del segundo
    // clic por el single-flight.
    renderAgentsBody();

    var payload = { role: option.agent_role, runtime_type: option.runtime_type };
    if (option.supports_model && agentsSection.modelInput.trim()) {
      payload.model = agentsSection.modelInput.trim();
    }
    if (agentsSection.taskInput.trim()) {
      payload.initial_job_description = agentsSection.taskInput.trim();
    }

    BackendClient.launchAgent(payload)
      .then(function (result) {
        agentsSection.launching = false;
        agentsSection.actionMessage = launchFeedbackMessageFor(result);
        renderAgentsBody();
        // Refleja el nuevo agente sin esperar al siguiente ciclo de polling.
        return pollAgents();
      })
      .catch(function (error) {
        agentsSection.launching = false;
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

  // Punto 1: formulario para pedir un plan (`POST /plans`, campo `goal`
  // con el identificador de la User Story). Single-flight en el envío
  // (mismo criterio que enviar Job/lanzar agente).
  function renderPlansForm(wrap) {
    var form = h("div", "plans-form");
    form.appendChild(h("div", "field-label", "Pedir un plan al Critic"));
    var goalInput = document.createElement("input");
    goalInput.type = "text";
    goalInput.className = "clickable";
    goalInput.placeholder = "Identificador de la User Story (p. ej. US-FB008-04)";
    goalInput.value = plansSection.goalInput;
    goalInput.addEventListener("input", function () {
      plansSection.goalInput = goalInput.value;
    });
    form.appendChild(goalInput);

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
    var goal = plansSection.goalInput.trim();
    if (!goal) {
      plansSection.requestError = "Escribe un identificador de User Story antes de pedir el plan.";
      renderPlansBody();
      return;
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

  // Catálogo en DOS grupos con cabecera (punto 1): "Genéricos (Factory
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
      generic.forEach(function (script) {
        wrap.appendChild(renderScriptCard(script));
      });
    }
    if (particular.length > 0) {
      wrap.appendChild(h("div", "scripts-group-title", "Proyecto"));
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
    if (script.command) {
      card.appendChild(h("div", "script-command", String(script.command)));
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
        if (state.section === "scripts") renderScriptsBody();
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
      render();
    } catch (error) {
      state.contextError = buildErrorMessage(error);
      render();
    }
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
    clearRoot();
    ROOT.textContent = "Seleccionando proyecto…";
    BackendClient.selectProject(project.id)
      .then(function () {
        state.showPicker = false;
        state.pendingSelection = null;
        // Al cambiar de proyecto se resetea el contexto; las secciones
        // operativas se vuelven a cargar para la nueva sesión (sus datos
        // dependen del proyecto activo).
        state.sections = { agents: null, jobs: null, plan: null, scripts: null };
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

  document.addEventListener("DOMContentLoaded", function () {
    checkConnectivity();
  });
})();