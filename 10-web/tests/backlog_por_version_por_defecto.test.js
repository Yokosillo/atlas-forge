/* T-AF036-US26-06 (US-AF036-26): la vista "Por Versión" es la pantalla por
 * defecto del Backlog. Al entrar en la pestaña Backlog se ve la vista
 * agrupada por version (de US), no el listado completo; el listado queda
 * accesible vía el toggle "Lista". Verificado en navegador real (Chromium +
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

function _write(dir, filename, content) {
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, filename), content);
}

async function _seed(page, projectPath) {
  const b = path.join(projectPath, "02-backlog");
  _write(path.join(b, "epics"), "AF-990.md",
    "---\nid: AF-990\ntype: epic\ntitle: AF-990\nstate: READY\ndependencies: []\n---\n\n## Objetivo\n\nO.\n");
  _write(path.join(b, "user-stories"), "US-AF990-01.md",
    "---\nid: US-AF990-01\ntype: user_story\ntitle: US\nstate: READY\ndependencies: []\nepic: AF-990\nversion: 0.9.2\n---\n\n## Historia\n\nH.\n\n## Criterios de aceptación\n\n- C.\n");
}

async function test_por_version_es_vista_por_defecto() {
  await withBackend(async ({ page, baseUrl, projectPath }) => {
    await _seed(page, projectPath);
    await page.goto(baseUrl + "/ui/");
    await _goToBacklogTab(page);

    // La vista agrupada por version se muestra por defecto (sin tocar el toggle).
    await page.waitForFunction(() => document.querySelectorAll(".backlog-fase-group").length >= 1, { timeout: 10000 });
    const grouped = await page.evaluate(() => ({
      groups: document.querySelectorAll(".backlog-fase-group").length,
      hasVersionTitle: Array.from(document.querySelectorAll(".backlog-fase-title")).some((t) => t.textContent.trim() === "0.9.2"),
      toggleActive: (() => {
        const btn = Array.from(document.querySelectorAll(".backlog-view-toggle")).find((b) => b.textContent.trim() === "Por Versión");
        return btn ? btn.className.includes("active") : false;
      })(),
    }));
    assert.ok(grouped.groups >= 1, "La vista por defecto debe ser la agrupada por version");
    assert.ok(grouped.hasVersionTitle, "Debe mostrarse la cabecera de grupo '0.9.2'");
    assert.ok(grouped.toggleActive, "El toggle 'Por Versión' debe estar activo por defecto");
  });
}

async function test_listado_completo_accesible_via_toggle() {
  await withBackend(async ({ page, baseUrl, projectPath }) => {
    await _seed(page, projectPath);
    await page.goto(baseUrl + "/ui/");
    await _goToBacklogTab(page);
    await page.waitForFunction(() => document.querySelectorAll(".backlog-fase-group").length >= 1, { timeout: 10000 });

    // Cambiar a "Lista": la vista plana queda accesible.
    await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll(".backlog-view-toggle")).find((b) => b.textContent.trim() === "Lista");
      if (btn) btn.click();
    });
    await page.waitForFunction(() => document.querySelectorAll(".backlog-fase-group").length === 0, { timeout: 10000 });
    const flatVisible = await page.evaluate(() => document.querySelectorAll(".backlog-epic-line").length >= 1);
    assert.ok(flatVisible, "El listado completo (flat) debe ser accesible vía el toggle 'Lista'");
  });
}

module.exports = [
  {
    name: "T-AF036-US26-06: al entrar en el Backlog la vista mostrada es la 'Por Versión'",
    fn: test_por_version_es_vista_por_defecto,
  },
  {
    name: "T-AF036-US26-06: el listado completo queda accesible vía el toggle 'Lista'",
    fn: test_listado_completo_accesible_via_toggle,
  },
];