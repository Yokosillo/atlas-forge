/* T-AF008-US17-01 (US-AF008-17): toda Task en TO_DEVELOP tiene su entrada en
 * la cola de despacho, con independencia del camino que la llevó ahí — y por
 * tanto se muestra en la ventana Pipeline. Verificado en navegador real
 * (Chromium + backend aislado vía harness). */

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

// Criterio 5 (camino Task individual -> TO_DEVELOP): una Task puesta en
// TO_DEVELOP desde su estado (sin pasar por el botón de encolar) crea su
// entrada en la cola y aparece en la ventana Pipeline como `queued`.
async function test_task_to_develop_visible_en_cola() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    // Sembrar Epic + US + Task, y poner la Task en TO_DEVELOP vía PUT state.
    await page.evaluate(async () => {
      const post = async (p, b) => {
        const r = await fetch(p, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(b),
        });
        if (!r.ok) throw new Error("POST " + p + " falló: " + r.status);
      };
      await post("/backlog/epic", { id: "AF-998", title: "Epic TO_DEVELOP", objetivo: "O." });
      await post("/backlog/epic/AF-998/us", { id: "US-AF998-01", title: "US", objetivo: "H.", criterios_aceptacion: "C." });
      await post("/backlog/us/US-AF998-01/task", {
        id: "T-AF998-US01-01", title: "Task", objetivo: "O.", descripcion: "D.",
        criterios_aceptacion: "C.", priority: "Alta",
      });
      const r = await fetch("/backlog/T-AF998-US01-01/state", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ state: "TO_DEVELOP" }),
      });
      if (!r.ok) throw new Error("PUT state TO_DEVELOP falló: " + r.status);
    });

    await page.reload();
    await _clickTab(page, "Pipeline");
    await waitVisible(page, ".backlog-focus-panel");

    // La Task TO_DEVELOP debe aparecer como fila `queued` en el panel.
    const rows = await page.evaluate(() =>
      Array.from(document.querySelectorAll(".backlog-queue-row")).map((r) => r.textContent)
    );
    assert.ok(
      rows.some((r) => r.includes("T-AF998-US01-01")),
      "La Task en TO_DEVELOP debe aparecer en la cola Pipeline: " + JSON.stringify(rows)
    );
  });
}

module.exports = [
  {
    name: "T-AF008-US17-01: una Task puesta en TO_DEVELOP aparece en la cola Pipeline",
    fn: test_task_to_develop_visible_en_cola,
  },
];