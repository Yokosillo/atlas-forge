/* T-AF042-US01-01 (US-AF042-01): la nueva sección "Pipeline" en la barra de
 * secciones. Verifica que la pestaña existe y que navegar a ella renderiza su
 * contenedor (la cola de despacho se añadió en T-AF042-US01-02) sin romper el
 * resto de secciones. */

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

async function test_pipeline_tab_exists_and_renders_content() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await _clickTab(page, "Pipeline");

    // La sección renderiza su contenedor (`pipeline-body`, que aloja la cola
    // de despacho desde T-AF042-US01-02).
    await page.waitForFunction(
      () => {
        const content = document.querySelector(".section-content");
        return content && content.querySelector(".pipeline-body");
      },
      { timeout: 10000 }
    );
    const info = await page.evaluate(() => {
      const content = document.querySelector(".section-content");
      return {
        title: (content && content.querySelector("h3") || {}).textContent || "",
        hasPipelineBody: !!content.querySelector(".pipeline-body"),
      };
    });
    assert.ok(info.title.includes("Pipeline"), "El encabezado debe ser 'Pipeline': " + info.title);
    assert.ok(
      info.hasPipelineBody,
      "La sección Pipeline debe renderizar su contenedor `.pipeline-body`"
    );
  });
}

async function test_pipeline_tab_does_not_break_other_sections() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await _clickTab(page, "Pipeline");
    await page.waitForFunction(() => {
      const content = document.querySelector(".section-content");
      return content && content.querySelector(".pipeline-body");
    }, { timeout: 10000 });

    // Volver a Backlog: la sección sigue funcionando.
    await _clickTab(page, "Backlog");
    await page.waitForFunction(() => {
      const content = document.querySelector(".section-content");
      return content && content.querySelector("h3") && content.querySelector("h3").textContent.includes("Backlog");
    }, { timeout: 10000 });
    const backlogOk = await page.evaluate(() => {
      const content = document.querySelector(".section-content");
      return content !== null && content.textContent.length > 0;
    });
    assert.ok(backlogOk, "Volver a Backlog no debe romper la sección");
  });
}

module.exports = [
  {
    name: "T-AF042-US01-01: la pestaña 'Pipeline' existe y renderiza su contenido",
    fn: test_pipeline_tab_exists_and_renders_content,
  },
  {
    name: "T-AF042-US01-01: navegar a Pipeline y volver a Backlog no rompe las secciones",
    fn: test_pipeline_tab_does_not_break_other_sections,
  },
];