/* T-AF042-US01-04 (US-AF042-01): tests web deterministas de la ventana
 * Pipeline — el panel de la cola de despacho se muestra en la sección
 * Pipeline y ya NO en la pestaña Backlog, sin regresión en el resto del
 * Backlog (Epics/US/Tasks) y con el comportamiento del panel intacto.
 * Verificado en navegador real (Chromium + backend aislado vía harness). */

"use strict";

const assert = require("assert");
const { withBackend, waitVisible } = require("./harness");

async function _clickTab(page, labelPrefix) {
  await waitVisible(page, ".section-tab");
  const tabs = await page.$$(".section-tab");
  for (const tab of tabs) {
    const text = await page.evaluate((el) => el.textContent, tab);
    if (text.trim().startsWith(labelPrefix)) {
      await tab.click();
      return;
    }
  }
  throw new Error("No se encontró la pestaña '" + labelPrefix + "'.");
}

async function _seed(page) {
  await page.evaluate(async () => {
    const post = async (p, b) => {
      const r = await fetch(p, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(b),
      });
      if (!r.ok) throw new Error("POST " + p + " falló: " + r.status);
    };
    await post("/backlog/epic", { id: "AF-971", title: "Epic Pipeline", objetivo: "O." });
    await post("/backlog/epic/AF-971/us", { id: "US-AF971-01", title: "US", objetivo: "H.", criterios_aceptacion: "C." });
    await post("/backlog/us/US-AF971-01/task", {
      id: "T-AF971-US01-01", title: "Task", objetivo: "O.", descripcion: "D.",
      criterios_aceptacion: "C.", priority: "Alta",
    });
    const r = await fetch("/backlog/T-AF971-US01-01/enqueue", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}),
    });
    if (!r.ok) throw new Error("enqueue falló: " + r.status);
  });
}

// Criterio 1 + US-AF042-01#1: el panel de la cola se muestra en Pipeline.
async function test_panel_presente_en_pipeline() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await _seed(page);
    await page.reload();
    await _clickTab(page, "Pipeline");

    await waitVisible(page, ".backlog-focus-panel");
    const rows = await page.evaluate(() =>
      Array.from(document.querySelectorAll(".backlog-queue-row")).map((r) => r.textContent)
    );
    assert.ok(
      rows.some((r) => r.includes("T-AF971-US01-01")),
      "El panel de Pipeline debe mostrar la Task encolada: " + JSON.stringify(rows)
    );
  });
}

// Criterio 2 + US-AF042-01#2: el panel NO se muestra en Backlog.
async function test_panel_ausente_en_backlog() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await _seed(page);
    await page.reload();
    await _clickTab(page, "Backlog");

    await waitVisible(page, ".section-content");
    const panelPresent = await page.evaluate(() => !!document.querySelector(".backlog-focus-panel"));
    assert.strictEqual(panelPresent, false, "El panel de la cola NO debe aparecer en la pestaña Backlog");
  });
}

// Criterio 3 + US-AF042-01#3: el resto de Backlog (Epic/US) sigue visible.
async function test_backlog_content_intacto() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await _seed(page);
    await page.reload();
    await _clickTab(page, "Backlog");

    // La Epic del backlog sigue visible y expandible.
    await page.evaluate(() => {
      const line = Array.from(document.querySelectorAll(".backlog-epic-line")).find((l) => l.textContent.includes("AF-971"));
      if (line) line.click();
    });
    await page.waitForFunction(
      () => Array.from(document.querySelectorAll(".backlog-us-line-title")).some((t) => t.textContent.includes("US-AF971-01")),
      { timeout: 10000 }
    );
    const usVisible = await page.evaluate(() =>
      Array.from(document.querySelectorAll(".backlog-us-line-title")).some((t) => t.textContent.includes("US-AF971-01"))
    );
    assert.ok(usVisible, "La User Story debe seguir visible en el Backlog tras quitar el panel");
  });
}

// US-AF042-01#4: el comportamiento del panel (acción de fila queued) se
// conserva en la sección Pipeline.
async function test_panel_accion_fila_en_pipeline() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await _seed(page);
    await page.reload();
    await _clickTab(page, "Pipeline");
    await waitVisible(page, ".backlog-focus-panel");

    // La fila `queued` conserva su acción ("Quitar").
    const hasQuitar = await page.evaluate(() => {
      const row = Array.from(document.querySelectorAll(".backlog-queue-row")).find((r) => r.textContent.includes("T-AF971-US01-01"));
      return row ? /Quitar/.test(row.textContent) : false;
    });
    assert.ok(hasQuitar, "La fila queued de la cola en Pipeline debe conservar su acción 'Quitar'");
  });
}

module.exports = [
  {
    name: "T-AF042-US01-04: el panel de la cola se muestra en la sección Pipeline",
    fn: test_panel_presente_en_pipeline,
  },
  {
    name: "T-AF042-US01-04: el panel de la cola NO se muestra en la pestaña Backlog",
    fn: test_panel_ausente_en_backlog,
  },
  {
    name: "T-AF042-US01-04: el resto del Backlog (Epic/US) sigue visible tras quitar el panel",
    fn: test_backlog_content_intacto,
  },
  {
    name: "T-AF042-US01-04: el panel conserva su acción de fila (Quitar) en la sección Pipeline",
    fn: test_panel_accion_fila_en_pipeline,
  },
];