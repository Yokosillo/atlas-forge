/* T-AF036-US12-03 (US-AF036-12): tests web deterministas del panel de la
 * cola de despacho — renderizado de grupos/estados, auto-refresh periódico
 * (T-AF036-US12-01) y navegación a la tarea desde la fila (T-AF036-US12-02).
 *
 * El backend aislado tiene la cola vacía y el panel solo se pinta con
 * entradas, así que se INTERCEPTA `GET /backlog/queue` (mecanismo explícito
 * de `00-gobierno/DEVELOPER.md`) para sembrar una cola controlada; para el
 * auto-refresh se cambia la respuesta interceptada y se espera el intervalo
 * real de polling (3s, `POLL_INTERVAL_MILLIS`). */

"use strict";

const assert = require("assert");
const { withBackend, waitVisible } = require("./harness");

const QUEUE = {
  queued: [
    { task_id: "T-AF900-US01-01", us_id: "US-AF900-01", priority: "Alta", agent_name: null },
  ],
  dispatched: [
    { task_id: "T-AF900-US01-02", us_id: "US-AF900-01", priority: "Media", agent_name: "Developer-1" },
  ],
  awaiting_tester: [
    { task_id: "T-AF900-US01-03", us_id: "US-AF900-01", priority: "Baja", agent_name: "Developer-1" },
  ],
  completed: [
    { task_id: "T-AF900-US01-04", us_id: "US-AF900-01", priority: "Alta", agent_name: null },
  ],
  failed: [
    { task_id: "T-AF900-US01-05", us_id: "US-AF900-01", priority: "Crítica", agent_name: null, result: "Timeout: el agente no respondió." },
  ],
};

const QUEUE_UPDATED = {
  queued: [{ task_id: "T-AF900-US01-06", us_id: "US-AF900-01", priority: "Alta", agent_name: null }],
  dispatched: [],
  awaiting_tester: [],
  completed: [],
  failed: [],
};

async function _goToTab(page, labelPrefix) {
  await waitVisible(page, ".section-tab");
  const tabs = await page.$$(".section-tab");
  for (const tab of tabs) {
    const text = await page.evaluate((el) => el.textContent, tab);
    if (text.trim().startsWith(labelPrefix)) { await tab.click(); return; }
  }
  throw new Error("No se encontró la pestaña '" + labelPrefix + "'.");
}

// ── criterio 1: el panel renderiza grupos/estados con etiquetas legibles ──

async function test_t_af036_us12_03_panel_renders_groups_and_states() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.setRequestInterception(true);
    page.on("request", (req) => {
      if (req.method() === "GET" && /\/backlog\/queue$/.test(req.url())) {
        req.respond({ status: 200, contentType: "application/json", body: JSON.stringify(QUEUE) });
        return;
      }
      req.continue();
    });
    await page.goto(baseUrl + "/ui/");
    await _goToTab(page, "Backlog");
    await page.waitForFunction(() => document.querySelectorAll(".backlog-queue-row").length >= 5, { timeout: 10000 });

    const info = await page.evaluate(() => {
      const title = (document.querySelector(".backlog-focus-title") || {}).textContent || "";
      const rows = Array.from(document.querySelectorAll(".backlog-queue-row"));
      return {
        title,
        count: rows.length,
        texts: rows.map((r) => r.textContent),
      };
    });
    assert.ok(info.title.includes("Cola de despacho (5)"), "título con conteo: " + info.title);
    assert.ok(info.texts.some((t) => t.includes("Pendiente")), "grupo queued legible");
    assert.ok(info.texts.some((t) => t.includes("En curso")), "grupo dispatched legible");
    assert.ok(info.texts.some((t) => t.includes("Esperando al Tester")), "grupo awaiting_tester legible");
    assert.ok(info.texts.some((t) => t.includes("Completada")), "grupo completed legible");
    assert.ok(info.texts.some((t) => t.includes("Fallida")), "grupo failed legible");
  });
}

// ── criterio 2: una entrada failed muestra el motivo (entry.result) ──

async function test_t_af036_us12_03_failed_entry_shows_reason() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.setRequestInterception(true);
    page.on("request", (req) => {
      if (req.method() === "GET" && /\/backlog\/queue$/.test(req.url())) {
        req.respond({ status: 200, contentType: "application/json", body: JSON.stringify(QUEUE) });
        return;
      }
      req.continue();
    });
    await page.goto(baseUrl + "/ui/");
    await _goToTab(page, "Backlog");
    await page.waitForFunction(() => document.querySelectorAll(".backlog-queue-row").length >= 5, { timeout: 10000 });

    const hasReason = await page.evaluate(() =>
      Array.from(document.querySelectorAll(".plan-step-error")).some(
        (el) => el.textContent.includes("Timeout: el agente no respondió.")
      )
    );
    assert.strictEqual(hasReason, true, "la entrada failed debe mostrar su motivo");
  });
}

// ── criterio 3 + 4: auto-refresh y preservación del estado colapsado ──

async function test_t_af036_us12_03_auto_refresh_updates_and_preserves_collapsed() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.setRequestInterception(true);
    let current = QUEUE;
    page.on("request", (req) => {
      if (req.method() === "GET" && /\/backlog\/queue$/.test(req.url())) {
        req.respond({ status: 200, contentType: "application/json", body: JSON.stringify(current) });
        return;
      }
      req.continue();
    });
    await page.goto(baseUrl + "/ui/");
    await _goToTab(page, "Backlog");
    await page.waitForFunction(() => document.querySelectorAll(".backlog-queue-row").length >= 5, { timeout: 10000 });

    // Colapsar el panel.
    await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll(".backlog-focus-toggle")).find((b) => b.textContent.trim() === "Ocultar");
      if (btn) btn.click();
    });
    await page.waitForFunction(() => {
      const btn = Array.from(document.querySelectorAll(".backlog-focus-toggle"))[0];
      return btn && btn.textContent.trim() === "Mostrar";
    }, { timeout: 10000 });

    // Cambiar la cola y esperar el intervalo real de polling (3s).
    current = QUEUE_UPDATED;
    await new Promise((r) => setTimeout(r, 4000));

    // Auto-refresh: la cola nueva (1 queued) se refleja en el título tras el
    // polling, SIN acción manual.
    const collapsedState = await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll(".backlog-focus-toggle"))[0];
      return { label: btn ? btn.textContent.trim() : null, rows: document.querySelectorAll(".backlog-queue-row").length };
    });
    // El panel sigue colapsado (etiqueta "Mostrar") pese al auto-refresh.
    assert.strictEqual(collapsedState.label, "Mostrar", "el estado colapsado debe preservarse tras el auto-refresh");

    // Expandir y verificar que el título refleja el conteo nuevo (1).
    await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll(".backlog-focus-toggle"))[0];
      if (btn) btn.click();
    });
    await page.waitForFunction(() => {
      const t = (document.querySelector(".backlog-focus-title") || {}).textContent || "";
      return t.includes("Cola de despacho (1)");
    }, { timeout: 10000 });
  });
}

// ── criterio 5: navegación a la tarea (resoluble) y no-ruptura (no resoluble) ──

async function test_t_af036_us12_03_row_navigation() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.setRequestInterception(true);
    let navigatedUs = null;
    page.on("request", (req) => {
      if (req.method() === "GET" && /\/backlog\/queue$/.test(req.url())) {
        req.respond({ status: 200, contentType: "application/json", body: JSON.stringify(QUEUE) });
        return;
      }
      // Navegación a la tarea: la fila resoluble pide el detalle de su US.
      const usMatch = /\/backlog\/(US-AF900-01)$/.exec(req.url());
      if (req.method() === "GET" && usMatch) {
        navigatedUs = usMatch[1];
        req.respond({ status: 200, contentType: "application/json", body: JSON.stringify({
          id: "US-AF900-01", epic: "AF-900", user_stories: [],
        }) });
        return;
      }
      req.continue();
    });
    await page.goto(baseUrl + "/ui/");
    await _goToTab(page, "Backlog");
    await page.waitForFunction(() => document.querySelectorAll(".backlog-queue-row").length >= 5, { timeout: 10000 });

    // Todas las filas de QUEUE tienen us_id -> clicables (clase link).
    const linkRows = await page.evaluate(() =>
      Array.from(document.querySelectorAll(".backlog-queue-row-link")).length
    );
    assert.strictEqual(linkRows, 5, "las 5 filas con us_id deben ser clicables");

    // Hacer clic en una fila resoluble: dispara GET /backlog/US-AF900-01.
    await page.evaluate(() => {
      const row = Array.from(document.querySelectorAll(".backlog-queue-row-link"))[0];
      if (row) row.click();
    });
    await new Promise((r) => setTimeout(r, 500));
    assert.strictEqual(navigatedUs, "US-AF900-01", "una fila resoluble debe intentar navegar a su US");

    // Una fila SIN us_id no debe ser clicable ni romper el render.
    const queueNoUs = { queued: [{ task_id: "T-AF900-US01-07", priority: "Alta" }], dispatched: [], awaiting_tester: [], completed: [], failed: [] };
    // Volver a sembrar con una entrada sin us_id.
    await page.setRequestInterception(false);
    await page.setRequestInterception(true);
    page.removeAllListeners("request");
    page.on("request", (req) => {
      if (req.method() === "GET" && /\/backlog\/queue$/.test(req.url())) {
        req.respond({ status: 200, contentType: "application/json", body: JSON.stringify(queueNoUs) });
        return;
      }
      req.continue();
    });
    // Forzar una recarga del panel vía navegación.
    await page.reload();
    await _goToTab(page, "Backlog");
    await page.waitForFunction(() => document.querySelectorAll(".backlog-queue-row").length >= 1, { timeout: 10000 });
    const noLink = await page.evaluate(() =>
      document.querySelectorAll(".backlog-queue-row-link").length
    );
    assert.strictEqual(noLink, 0, "una fila sin us_id no debe tener enlace");
  });
}


const QUEUE_WITH_DATES = {
  queued: [{ task_id: "T-AF900-US01-10", us_id: "US-AF900-01", priority: "Alta", enqueued_at: "2026-08-20T10:00:00+00:00" }],
  dispatched: [{ task_id: "T-AF900-US01-11", us_id: "US-AF900-01", priority: "Media", agent_name: "Developer-1", enqueued_at: "2026-08-20T10:05:00+00:00", dispatched_at: "2026-08-20T10:10:00+00:00" }],
  awaiting_tester: [],
  completed: [{ task_id: "T-AF900-US01-12", us_id: "US-AF900-01", priority: "Alta", enqueued_at: "2026-08-20T10:00:00+00:00", dispatched_at: "2026-08-20T10:05:00+00:00", finished_at: "2026-08-20T11:00:00+00:00" }],
  failed: [],
};

async function test_t_af036_us17_03_rows_show_transition_dates() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.setRequestInterception(true);
    page.on("request", (req) => {
      if (req.method() === "GET" && /\/backlog\/queue$/.test(req.url())) {
        req.respond({ status: 200, contentType: "application/json", body: JSON.stringify(QUEUE_WITH_DATES) });
        return;
      }
      req.continue();
    });
    await page.goto(baseUrl + "/ui/");
    await _goToTab(page, "Backlog");
    await page.waitForFunction(() => document.querySelectorAll(".backlog-queue-row-dates").length >= 3, { timeout: 10000 });

    const rows = await page.evaluate(() =>
      Array.from(document.querySelectorAll(".backlog-queue-row-dates")).map((el) => el.textContent)
    );
    // queued: solo "encolada" (sin despachada ni terminada)
    assert.ok(
      rows.some((t) => t.includes("encolada") && !t.includes("despachada") && !t.includes("terminada")),
      "fila queued debe mostrar solo 'encolada': " + JSON.stringify(rows)
    );
    // dispatched: encolada + despachada, sin terminada
    assert.ok(
      rows.some((t) => t.includes("encolada") && t.includes("despachada") && !t.includes("terminada")),
      "fila dispatched debe omitir 'terminada': " + JSON.stringify(rows)
    );
    // completed: las tres
    assert.ok(
      rows.some((t) => t.includes("encolada") && t.includes("despachada") && t.includes("terminada")),
      "fila completed debe mostrar las tres fechas: " + JSON.stringify(rows)
    );
    // formato legible (YYYY-MM-DD HH:MM)
    assert.ok(
      rows.some((t) => /\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test(t)),
      "las fechas deben tener formato legible: " + JSON.stringify(rows)
    );
  });
}


async function test_t_af036_us17_04_clear_history_button() {
  const QUEUE_BEFORE = {
    queued: [{ task_id: "T-AF900-US01-20", us_id: "US-AF900-01", priority: "Alta" }],
    dispatched: [{ task_id: "T-AF900-US01-21", us_id: "US-AF900-01", priority: "Media", agent_name: "Developer-1" }],
    awaiting_tester: [],
    completed: [{ task_id: "T-AF900-US01-22", us_id: "US-AF900-01", priority: "Alta" }],
    failed: [{ task_id: "T-AF900-US01-23", us_id: "US-AF900-01", priority: "Crítica", result: "falló" }],
  };
  const QUEUE_AFTER = {
    queued: QUEUE_BEFORE.queued,
    dispatched: QUEUE_BEFORE.dispatched,
    awaiting_tester: [],
    completed: [],
    failed: [],
  };
  let cleared = false;

  await withBackend(async ({ page, baseUrl }) => {
    await page.evaluateOnNewDocument(() => { window.confirm = function () { return true; }; });
    await page.setRequestInterception(true);
    page.on("request", (req) => {
      if (req.method() === "GET" && /\/backlog\/queue$/.test(req.url())) {
        req.respond({ status: 200, contentType: "application/json", body: JSON.stringify(cleared ? QUEUE_AFTER : QUEUE_BEFORE) });
        return;
      }
      if (req.method() === "DELETE" && /\/backlog\/queue\/history$/.test(req.url())) {
        cleared = true;
        req.respond({ status: 200, contentType: "application/json", body: JSON.stringify({ removed: 2 }) });
        return;
      }
      req.continue();
    });
    await page.goto(baseUrl + "/ui/");
    await _goToTab(page, "Backlog");

    // El botón "Borrar histórico" aparece (hay entradas terminales).
    await page.waitForFunction(
      () => Array.from(document.querySelectorAll("button")).some((b) => b.textContent.trim() === "Borrar histórico"),
      { timeout: 10000 }
    );

    // Tras borrar: se refresca la cola y desaparecen completed/failed, quedan las en curso.
    await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll("button")).find((b) => b.textContent.trim() === "Borrar histórico");
      btn.click();
    });
    await page.waitForFunction(
      () => {
        const texts = Array.from(document.querySelectorAll(".backlog-queue-row")).map((r) => r.textContent);
        return texts.some((t) => t.includes("T-AF900-US01-20"))
          && !texts.some((t) => t.includes("T-AF900-US01-22"))
          && !texts.some((t) => t.includes("T-AF900-US01-23"));
      },
      { timeout: 10000 }
    );
  });
}


async function test_t_af036_us17_06_dequeue_queued_button() {
  const BASE = {
    queued: [{ task_id: "T-AF900-US01-30", us_id: "US-AF900-01", priority: "Alta" }],
    dispatched: [{ task_id: "T-AF900-US01-31", us_id: "US-AF900-01", priority: "Media", agent_name: "Developer-1" }],
    awaiting_tester: [], completed: [], failed: [],
  };
  let dequeued = false;

  await withBackend(async ({ page, baseUrl }) => {
    await page.evaluateOnNewDocument(() => { window.confirm = function () { return true; }; });
    await page.setRequestInterception(true);
    page.on("request", (req) => {
      if (req.method() === "GET" && /\/backlog\/queue$/.test(req.url())) {
        const body = dequeued ? { ...BASE, queued: [] } : BASE;
        req.respond({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
        return;
      }
      if (req.method() === "DELETE" && /\/backlog\/T-AF900-US01-30\/enqueue$/.test(req.url())) {
        dequeued = true;
        req.respond({ status: 200, contentType: "application/json", body: JSON.stringify({ dequeued: true }) });
        return;
      }
      req.continue();
    });
    await page.goto(baseUrl + "/ui/");
    await _goToTab(page, "Backlog");

    // El botón "Quitar de la cola" aparece SOLO en la fila queued.
    await page.waitForFunction(
      () => Array.from(document.querySelectorAll("button")).some((b) => b.textContent.trim() === "Quitar de la cola"),
      { timeout: 10000 }
    );
    const queuedRowTexts = await page.evaluate(() =>
      Array.from(document.querySelectorAll(".backlog-queue-row"))
        .filter((r) => r.querySelector("button") && r.querySelector("button").textContent.trim() === "Quitar de la cola")
        .map((r) => r.textContent)
    );
    assert.strictEqual(
      queuedRowTexts.length, 1,
      "solo la fila queued debe tener el botón 'Quitar de la cola': " + JSON.stringify(queuedRowTexts)
    );

    // Al pulsarlo, la fila queued desaparece tras el refresco.
    await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll("button")).find((b) => b.textContent.trim() === "Quitar de la cola");
      btn.click();
    });
    await page.waitForFunction(
      () => !Array.from(document.querySelectorAll(".backlog-queue-row")).some((r) => r.textContent.includes("T-AF900-US01-30")),
      { timeout: 10000 }
    );
  });
}

module.exports = [
  {
    name: "El panel de la cola de despacho renderiza los grupos con etiquetas/estados legibles",
    fn: test_t_af036_us12_03_panel_renders_groups_and_states,
  },
  {
    name: "Una entrada failed del panel muestra el motivo de error",
    fn: test_t_af036_us12_03_failed_entry_shows_reason,
  },
  {
    name: "El panel se auto-refresca periódicamente y preserva el estado colapsado",
    fn: test_t_af036_us12_03_auto_refresh_updates_and_preserves_collapsed,
  },
  {
    name: "Las filas con us_id son clicables y navegan; las sin us_id no rompen el render",
    fn: test_t_af036_us12_03_row_navigation,
  },
  {
    name: "T-AF036-US17-03: las filas de la cola muestran las fechas de encolada/despachada/terminada",
    fn: test_t_af036_us17_03_rows_show_transition_dates,
  },
  {
    name: "T-AF036-US17-04: el botón 'Borrar histórico' borra las terminales y conserva las en curso tras confirmar",
    fn: test_t_af036_us17_04_clear_history_button,
  },
  {
    name: "T-AF036-US17-06: el botón 'Quitar de la cola' aparece solo en filas queued y las retira tras confirmar",
    fn: test_t_af036_us17_06_dequeue_queued_button,
  },
];
