/* T-AF036-US26-07 (US-AF036-26): el listado completo (flat) es un botón de
 * acción temporal, no una vista persistente. Al entrar en Backlog se ve
 * "Por Versión"; pulsar "Lista" muestra el listado completo; al navegar/
 * volver, la vista retorna a "Por Versión". Verificado en navegador real. */

"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const { withBackend, waitVisible } = require("./harness");

async function _goToTab(page, labelPrefix) {
  await waitVisible(page, ".section-tab");
  const clicked = await page.evaluate((prefix) => {
    const tab = Array.from(document.querySelectorAll(".section-tab")).find((el) =>
      (el.textContent || "").trim().startsWith(prefix)
    );
    if (tab) { tab.click(); return true; }
    return false;
  }, labelPrefix);
  if (!clicked) throw new Error("No se encontró la pestaña '" + labelPrefix + "'.");
}

function _write(dir, filename, content) {
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, filename), content);
}

async function _seed(projectPath) {
  const b = path.join(projectPath, "02-backlog");
  _write(path.join(b, "epics"), "AF-990.md",
    "---\nid: AF-990\ntype: epic\ntitle: AF-990\nstate: READY\ndependencies: []\n---\n\n## Objetivo\n\nO.\n");
  _write(path.join(b, "user-stories"), "US-AF990-01.md",
    "---\nid: US-AF990-01\ntype: user_story\ntitle: US\nstate: READY\ndependencies: []\nepic: AF-990\nversion: 0.9.2\n---\n\n## Historia\n\nH.\n\n## Criterios de aceptación\n\n- C.\n");
}

async function _groupCount(page) {
  return page.evaluate(() => document.querySelectorAll(".backlog-fase-group").length);
}

async function test_por_defecto_por_version_y_lista_temporal() {
  await withBackend(async ({ page, baseUrl, projectPath }) => {
    await _seed(projectPath);
    await page.goto(baseUrl + "/ui/");
    await _goToTab(page, "Backlog");

    // Por defecto: vista "Por Versión" (agrupada), no el listado plano.
    await page.waitForFunction(() => document.querySelectorAll(".backlog-fase-group").length >= 1, { timeout: 10000 });
    assert.strictEqual(await _groupCount(page), 1, "Por defecto se muestra la vista agrupada por version");

    // Pulsar "Lista": se muestra el listado completo (sin grupos).
    await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll(".backlog-view-toggle")).find((b) => b.textContent.trim() === "Lista");
      if (btn) btn.click();
    });
    await page.waitForFunction(() => document.querySelectorAll(".backlog-fase-group").length === 0, { timeout: 10000 });
    assert.strictEqual(await _groupCount(page), 0, "Al pulsar 'Lista' se muestra el listado completo (sin grupos)");
    assert.ok((await page.evaluate(() => document.querySelectorAll(".backlog-epic-line").length)) >= 1, "El listado completo muestra las Epics");

    // Al volver a "Por Versión" (botón) retorna la vista agrupada.
    await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll(".backlog-view-toggle")).find((b) => b.textContent.trim() === "Por Versión");
      if (btn) btn.click();
    });
    await page.waitForFunction(() => document.querySelectorAll(".backlog-fase-group").length >= 1, { timeout: 10000 });
    assert.strictEqual(await _groupCount(page), 1, "Volver a 'Por Versión' muestra la vista agrupada");
  });
}

async function test_navegar_devuelve_a_por_version() {
  await withBackend(async ({ page, baseUrl, projectPath }) => {
    await _seed(projectPath);
    await page.goto(baseUrl + "/ui/");
    await _goToTab(page, "Backlog");
    await page.waitForFunction(() => document.querySelectorAll(".backlog-fase-group").length >= 1, { timeout: 10000 });

    // Abrir el listado completo.
    await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll(".backlog-view-toggle")).find((b) => b.textContent.trim() === "Lista");
      if (btn) btn.click();
    });
    await page.waitForFunction(() => document.querySelectorAll(".backlog-fase-group").length === 0, { timeout: 10000 });
    assert.strictEqual(await _groupCount(page), 0, "El listado completo está abierto");

    // Navegar a otra sección y volver: la vista retorna a "Por Versión".
    await _goToTab(page, "Agentes");
    await waitVisible(page, ".section-tab");
    await _goToTab(page, "Backlog");
    await page.waitForFunction(() => document.querySelectorAll(".backlog-fase-group").length >= 1, { timeout: 10000 });
    assert.strictEqual(await _groupCount(page), 1, "Al volver al Backlog se muestra 'Por Versión' (no el listado completo)");
  });
}

module.exports = [
  {
    name: "T-AF036-US26-07: por defecto se ve 'Por Versión' y 'Lista' despliega el listado completo temporalmente",
    fn: test_por_defecto_por_version_y_lista_temporal,
  },
  {
    name: "T-AF036-US26-07: al navegar/volver al Backlog la vista retorna a 'Por Versión'",
    fn: test_navegar_devuelve_a_por_version,
  },
];