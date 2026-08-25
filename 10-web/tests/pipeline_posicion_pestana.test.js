/* T-AF042-US01-05 (US-AF042-01): la pestaña "Pipeline" aparece a la derecha
 * de "Backlog" y a la izquierda de "Agentes" (roles) en la barra de
 * secciones. Verificado en navegador real. */

"use strict";

const assert = require("assert");
const { withBackend, waitVisible } = require("./harness");

async function test_pipeline_posicionada_entre_backlog_y_agentes() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await waitVisible(page, ".section-tab");

    const labels = await page.evaluate(() =>
      Array.from(document.querySelectorAll(".section-tab")).map((el) => el.textContent.trim())
    );

    const idxBacklog = labels.findIndex((l) => l === "Backlog");
    const idxPipeline = labels.findIndex((l) => l === "Pipeline");
    const idxAgentes = labels.findIndex((l) => l === "Agentes" || l === "Roles" || l === "Agentes (roles)" || l.startsWith("Agentes"));

    assert.ok(idxBacklog !== -1, "debe existir la pestaña Backlog");
    assert.ok(idxPipeline !== -1, "debe existir la pestaña Pipeline");
    assert.ok(idxAgentes !== -1, "debe existir la pestaña Agentes/roles: " + JSON.stringify(labels));
    assert.ok(idxBacklog < idxPipeline, "Pipeline debe estar a la derecha de Backlog");
    assert.ok(idxPipeline < idxAgentes, "Pipeline debe estar a la izquierda de Agentes (roles)");
  });
}

module.exports = [
  {
    name: "T-AF042-US01-05: la pestaña Pipeline está a la derecha de Backlog y a la izquierda de Agentes",
    fn: test_pipeline_posicionada_entre_backlog_y_agentes,
  },
];