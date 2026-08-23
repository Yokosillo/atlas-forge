/* T-AF036-US12-01 (US-AF036-12): el panel de la cola de despacho se
 * actualiza automáticamente por polling mientras la pestaña de Backlog está
 * abierta, sin recarga manual, y no pierde el estado colapsado/expandido.
 * Verificado en navegador real (Chromium + backend aislado). */

"use strict";

const assert = require("assert");
const { withBackend, waitVisible, sleep } = require("./harness");

async function _goToBacklogTab(page) {
  await waitVisible(page, ".section-tab");
  const tabs = await page.$$(".section-tab");
  for (const tab of tabs) {
    const text = await page.evaluate((el) => el.textContent, tab);
    if (text.trim().startsWith("Backlog")) {
      await tab.click();
      return;
    }
  }
  throw new Error("No se encontró la pestaña 'Backlog'.");
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

async function _queueText(page) {
  return page.evaluate(() =>
    Array.from(document.querySelectorAll(".backlog-queue-row")).map((r) => r.textContent).join(" ")
  );
}

async function test_cola_se_actualiza_por_polling_sin_recarga() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await _seedEpicUsTask(page, "AF-951", "US-AF951-01", "T-AF951-US01-01");
    await _enqueue(page, "T-AF951-US01-01");
    await page.reload();
    await _goToBacklogTab(page);

    await waitVisible(page, ".backlog-queue-row");
    let text = await _queueText(page);
    assert.ok(text.includes("T-AF951-US01-01"), "El panel debe mostrar la Task encolada, got: " + text);

    // Encolar una segunda Task mientras la pestaña está abierta (sin recargar).
    await _seedEpicUsTask(page, "AF-952", "US-AF952-01", "T-AF952-US01-01");
    await _enqueue(page, "T-AF952-US01-01");

    // Esperar un ciclo de polling (POLL_INTERVAL_MILLIS = 3000ms) + margen.
    await sleep(3800);

    text = await _queueText(page);
    assert.ok(
      text.includes("T-AF952-US01-01"),
      "El panel debe reflejar la nueva Task por polling sin recarga manual, got: " + text
    );
  });
}

async function test_cola_polling_preserva_estado_colapsado() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await _seedEpicUsTask(page, "AF-953", "US-AF953-01", "T-AF953-US01-01");
    await _enqueue(page, "T-AF953-US01-01");
    await page.reload();
    await _goToBacklogTab(page);
    await waitVisible(page, ".backlog-queue-row");

    // Colapsar el panel.
    const collapsed = await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll("button")).find((b) => b.textContent.trim() === "Ocultar");
      if (!btn) return false;
      btn.click();
      return true;
    });
    assert.ok(collapsed, "No se pudo colapsar el panel.");

    // Encolar otra Task mientras está colapsado y esperar un ciclo de polling.
    await _seedEpicUsTask(page, "AF-954", "US-AF954-01", "T-AF954-US01-01");
    await _enqueue(page, "T-AF954-US01-01");
    await sleep(3800);

    // El panel sigue colapsado (botón "Mostrar" visible, sin filas) — el
    // auto-refresh no lo expande ni fuerza scroll.
    const state = await page.evaluate(() => {
      const showBtn = Array.from(document.querySelectorAll("button")).some((b) => b.textContent.trim() === "Mostrar");
      const rows = document.querySelectorAll(".backlog-queue-row").length;
      return { showBtn, rows };
    });
    assert.ok(state.showBtn, "El panel debe seguir colapsado (botón 'Mostrar' presente) tras el polling.");
    assert.strictEqual(state.rows, 0, "Colapsado: no deben renderizarse filas tras el polling.");
  });
}

module.exports = [
  {
    name: "T-AF036-US12-01: el panel de la cola se actualiza por polling sin recarga manual",
    fn: test_cola_se_actualiza_por_polling_sin_recarga,
  },
  {
    name: "T-AF036-US12-01: el auto-refresh preserva el estado colapsado del panel",
    fn: test_cola_polling_preserva_estado_colapsado,
  },
];