/* T-AF036-US26-08 (US-AF036-26): los botones de vista y filtros del Backlog
 * se alinean a la izquierda. Verificado en navegador real (Chromium +
 * backend aislado). */

"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const { withBackend, waitVisible } = require("./harness");

async function _goToBacklogTab(page) {
  await waitVisible(page, ".section-tab");
  const clicked = await page.evaluate(() => {
    const tab = Array.from(document.querySelectorAll(".section-tab")).find((el) =>
      (el.textContent || "").trim().startsWith("Backlog")
    );
    if (tab) { tab.click(); return true; }
    return false;
  });
  if (!clicked) throw new Error("No se encontró la pestaña 'Backlog'.");
}

async function _seed(projectPath) {
  const b = path.join(projectPath, "02-backlog");
  fs.mkdirSync(path.join(b, "epics"), { recursive: true });
  fs.writeFileSync(path.join(b, "epics", "AF-990.md"),
    "---\nid: AF-990\ntype: epic\ntitle: AF-990\nstate: READY\ndependencies: []\n---\n\n## Objetivo\n\nO.\n");
  fs.mkdirSync(path.join(b, "user-stories"), { recursive: true });
  fs.writeFileSync(path.join(b, "user-stories", "US-AF990-01.md"),
    "---\nid: US-AF990-01\ntype: user_story\ntitle: US\nstate: READY\ndependencies: []\nepic: AF-990\nversion: 0.9.2\n---\n\n## Historia\n\nH.\n\n## Criterios de aceptación\n\n- C.\n");
}

async function test_controles_y_filtros_alineados_a_la_izquierda() {
  await withBackend(async ({ page, baseUrl, projectPath }) => {
    await _seed(projectPath);
    await page.goto(baseUrl + "/ui/");
    await _goToBacklogTab(page);
    await waitVisible(page, ".backlog-filter-bar");

    // La cabecera de controles fuerza justificación izquierda.
    const header = await page.evaluate(() => {
      const bar = document.querySelector(".backlog-controls-left");
      if (!bar) return null;
      return {
        hasClass: bar.classList.contains("backlog-controls-left"),
        justify: getComputedStyle(bar).justifyContent,
      };
    });
    assert.ok(header && header.hasClass, "la cabecera debe llevar la clase backlog-controls-left");
    assert.strictEqual(header.justify, "flex-start", "los controles deben justificarse a la izquierda");

    // La barra de filtros también justifica a la izquierda.
    const filter = await page.evaluate(() => {
      const bar = document.querySelector(".backlog-filter-bar");
      return bar ? getComputedStyle(bar).justifyContent : null;
    });
    assert.strictEqual(filter, "flex-start", "la barra de filtros debe alinearse a la izquierda");
  });
}

module.exports = [
  {
    name: "T-AF036-US26-08: los botones de vista y la barra de filtros del Backlog quedan alineados a la izquierda",
    fn: test_controles_y_filtros_alineados_a_la_izquierda,
  },
];