/* T-AF036-US12-02 (US-AF036-12): cada fila de la cola de despacho con
 * `us_id` resoluble es un enlace que navega directamente a la tarea en el
 * listado del Backlog (expande la Epic, la US padre y hace scroll), sin
 * búsqueda manual. Las filas conservan su información (task_id, estado,
 * agente, motivo de error). Verificado en navegador real (Chromium + backend
 * aislado). */

"use strict";

const assert = require("assert");
const { withBackend, waitVisible } = require("./harness");

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

async function _seedAndEnqueue(page, epicId, usId, taskId) {
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
      await post("/backlog/epic/" + epicId + "/us", {
        id: usId, title: "US " + usId, objetivo: "H.", criterios_aceptacion: "C.",
      });
      await post("/backlog/us/" + usId + "/task", {
        id: taskId, title: "Task " + taskId, objetivo: "O.", descripcion: "D.",
        criterios_aceptacion: "C.", priority: "Alta",
      });
      // Encolar la Task en la cola de despacho.
      const r = await fetch("/backlog/" + taskId + "/enqueue", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (!r.ok) throw new Error("POST enqueue falló: " + r.status);
    },
    { epicId, usId, taskId }
  );
}

async function test_queue_row_is_link_and_navigates_to_task() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await _seedAndEnqueue(page, "AF-951", "US-AF951-01", "T-AF951-US01-01");
    await page.reload();
    await _goToBacklogTab(page);

    // La cola de despacho aparece (el panel se pinta si hay entradas).
    await waitVisible(page, ".backlog-queue-row");
    await waitVisible(page, ".backlog-queue-row-link");

    // La fila de la Task es un enlace y conserva la información (task_id).
    const rowInfo = await page.evaluate(() => {
      const row = Array.from(document.querySelectorAll(".backlog-queue-row-link")).find((r) =>
        r.textContent.includes("T-AF951-US01-01")
      );
      if (!row) return null;
      return {
        text: row.textContent,
        title: (row.querySelector(".backlog-queue-row-title") || {}).textContent || "",
        status: (row.querySelector(".backlog-queue-row-status") || {}).textContent || "",
      };
    });
    assert.ok(rowInfo, "Debe existir una fila de la cola con enlace para T-AF951-US01-01.");
    assert.ok(
      rowInfo.title.includes("T-AF951-US01-01") && rowInfo.title.includes("→"),
      "La fila debe mostrar el task_id y el indicador '→', got: " + JSON.stringify(rowInfo)
    );
    assert.ok(rowInfo.status, "La fila debe conservar el estado/agente, got: " + JSON.stringify(rowInfo));

    // Hacer clic en la fila: navega a la tarea (expande la Epic + scroll).
    const clicked = await page.evaluate(() => {
      const row = Array.from(document.querySelectorAll(".backlog-queue-row-link")).find((r) =>
        r.textContent.includes("T-AF951-US01-01")
      );
      if (!row) return false;
      row.click();
      return true;
    });
    assert.ok(clicked, "No se pudo hacer clic en la fila de la cola.");

    // La Epic se expande (aria-expanded=true) y aparece la línea de la Task.
    await page.waitForFunction(
      () => {
        const epicLine = Array.from(document.querySelectorAll(".backlog-epic-line")).find((l) =>
          l.textContent.includes("AF-951")
        );
        return epicLine && epicLine.getAttribute("aria-expanded") === "true";
      },
      { timeout: 10000 }
    );
    await waitVisible(page, ".backlog-task-line-title");
    const taskVisible = await page.evaluate(() =>
      Array.from(document.querySelectorAll(".backlog-task-line-title")).some((t) =>
        t.textContent.includes("T-AF951-US01-01")
      )
    );
    assert.ok(taskVisible, "Tras navegar desde la cola debe verse la Task en el detalle expandido.");
  });
}

module.exports = [
  {
    name: "T-AF036-US12-02: cada fila de la cola con task_id resoluble es un enlace que navega a la tarea",
    fn: test_queue_row_is_link_and_navigates_to_task,
  },
];