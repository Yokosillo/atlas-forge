/* T-AF042-US01-02 (US-AF042-01): la cola de despacho se trasladó de la pestaña
 * Backlog a la sección Pipeline — se renderiza ahí (carga + polling) y ya NO
 * en Backlog, conservando el estado colapsado y sin cambios funcionales.
 * Verificado en navegador real (Chromium + backend aislado vía harness). */

"use strict";

const assert = require("assert");
const { withBackend, waitVisible, sleep } = require("./harness");

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

async function _seedEpicUsTask(page, epicId, usId, taskId) {
  await page.evaluate(
    async ({ epicId, usId, taskId }) => {
      const post = async (p, b) => {
        const r = await fetch(p, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(b),
        });
        if (!r.ok) throw new Error("POST " + p + " falló: " + r.status);
      };
      await post("/backlog/epic", { id: epicId, title: "Epic " + epicId, objetivo: "O." });
      await post("/backlog/epic/" + epicId + "/us", { id: usId, title: "US " + usId, objetivo: "H.", criterios_aceptacion: "C." });
      await post("/backlog/us/" + usId + "/task", { id: taskId, title: "Task " + taskId, objetivo: "O.", descripcion: "D.", criterios_aceptacion: "C.", priority: "Alta" });
    },
    { epicId, usId, taskId }
  );
}

async function _enqueue(page, taskId) {
  const ok = await page.evaluate(async (taskId) => {
    const r = await fetch("/backlog/" + taskId + "/enqueue", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    return r.ok;
  }, taskId);
  assert.ok(ok, "No se pudo encolar la Task " + taskId);
}

async function _queueRows(page) {
  return page.evaluate(() => document.querySelectorAll(".backlog-queue-row").length);
}

// Criterio 1 + relocalización: al entrar en Pipeline se renderiza el panel de
// la cola (igual que se veía en Backlog) y el panel ya NO aparece en Backlog.
async function test_pipeline_muestra_panel_y_no_en_backlog() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await _seedEpicUsTask(page, "AF-961", "US-AF961-01", "T-AF961-US01-01");
    await _enqueue(page, "T-AF961-US01-01");
    await page.reload();

    await _clickTab(page, "Pipeline");
    await waitVisible(page, ".backlog-focus-panel");
    assert.ok(
      (await page.evaluate(() => document.body.textContent)).includes("Cola de despacho"),
      "El panel 'Cola de despacho' debe renderizarse en la sección Pipeline"
    );
    assert.ok((await _queueRows(page)) >= 1, "Pipeline debe mostrar las filas de la cola");

    // Relocalización: el panel ya no está en la pestaña Backlog.
    await _clickTab(page, "Backlog");
    await waitVisible(page, ".section-content");
    const inBacklog = await page.evaluate(() => !!document.querySelector(".backlog-focus-panel"));
    assert.ok(!inBacklog, "El panel de la cola NO debe renderizarse en Backlog tras la relocalización");
  });
}

// Criterio 2 (corrección): la carga y el polling se activan al entrar en
// Pipeline y el panel se actualiza por polling sin recarga manual.
async function test_pipeline_polling_actualiza_panel() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await _seedEpicUsTask(page, "AF-962", "US-AF962-01", "T-AF962-US01-01");
    await _enqueue(page, "T-AF962-US01-01");
    await page.reload();

    await _clickTab(page, "Pipeline");
    await waitVisible(page, ".backlog-focus-panel");
    let rows = await _queueRows(page);
    assert.strictEqual(rows, 1, "El panel debe mostrar 1 fila inicialmente, got: " + rows);

    // Encolar una segunda Task mientras la sección Pipeline está abierta.
    await _seedEpicUsTask(page, "AF-963", "US-AF963-01", "T-AF963-US01-01");
    await _enqueue(page, "T-AF963-US01-01");

    // Esperar un ciclo de polling (POLL_INTERVAL_MILLIS = 3000ms) + margen.
    await sleep(3800);

    rows = await _queueRows(page);
    assert.strictEqual(rows, 2, "El panel de Pipeline debe reflejar la nueva Task por polling, got: " + rows);
  });
}

module.exports = [
  {
    name: "T-AF042-US01-02: el panel de la cola se renderiza en Pipeline y ya no en Backlog",
    fn: test_pipeline_muestra_panel_y_no_en_backlog,
  },
  {
    name: "T-AF042-US01-02: el panel de Pipeline se actualiza por polling sin recarga manual",
    fn: test_pipeline_polling_actualiza_panel,
  },
];