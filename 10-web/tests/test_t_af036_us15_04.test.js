/* T-AF036-US15-04 (US-AF036-15): tests web deterministas de la vista "Por
 * Fase" — orden natural de VERSIONES (las Epics se agrupan por `version`,
 * US-AF036-18/T-AF036-US15-06), agrupación dentro de cada grupo (Epics
 * abiertas antes; terminadas y todas-fuera-de-roadmap al final colapsadas)
 * y, al expandir una Epic, sus US con su fase. Se siembra un backlog
 * sintético escribiendo los ficheros reales en `projectPath` (frontmatter
 * con version/estados mixtos) y se navega la web real con `withBackend`. */

"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const { withBackend, waitVisible } = require("./harness");

function _write(dir, filename, content) {
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, filename), content);
}

function _epic(b, id, version) {
  const versionLine = version ? `version: ${version}\n` : "";
  _write(path.join(b, "epics"), id + ".md",
    `---\nid: ${id}\ntype: epic\ntitle: ${id}\nstate: READY\ndependencies: []\n${versionLine}---\n\n## Objetivo\n\nO.\n`);
}
function _us(b, id, epic, state, fase) {
  const faseLine = fase ? `fase: ${fase}\n` : "";
  _write(path.join(b, "user-stories"), id + ".md",
    `---\nid: ${id}\ntype: user_story\ntitle: ${id}\nstate: ${state}\ndependencies: []\nepic: ${epic}\n${faseLine}---\n\n## Historia\n\nH.\n\n## Criterios de aceptación\n\n- C.\n`);
}
function _task(b, id, epic, us, state) {
  _write(path.join(b, "tasks"), id + ".md",
    `---\nid: ${id}\ntype: task\ntitle: ${id}\nstate: ${state}\ndependencies: []\nepic: ${epic}\nuser_story: ${us}\n---\n\n## Objetivo\n\nO.\n\n## Criterios de aceptación\n\n- C.\n`);
}

function _seed(projectPath) {
  const b = path.join(projectPath, "02-backlog");
  // VERSION 1.2: epic abierta (US con task READY)
  _epic(b, "AF-962", "1.2");
  _us(b, "US-AF962-01", "AF-962", "READY", "Fase 1.2");
  _task(b, "T-AF962-US01-01", "AF-962", "US-AF962-01", "READY");
  // VERSION 1.1: epic terminada (US DONE con task DONE)
  _epic(b, "AF-961", "1.1");
  _us(b, "US-AF961-01", "AF-961", "DONE", "Fase 1.1");
  _task(b, "T-AF961-US01-01", "AF-961", "US-AF961-01", "DONE");
  // VERSION 1.0: epic con todas las US fuera de roadmap
  _epic(b, "AF-960", "1.0");
  _us(b, "US-AF960-01", "AF-960", "OUT_OF_SCOPE", "Fase 1.0");
  // SIN_VERSION: epic sin version, abierta
  _epic(b, "AF-963", null);
  _us(b, "US-AF963-01", "AF-963", "READY", null);
  _task(b, "T-AF963-US01-01", "AF-963", "US-AF963-01", "READY");
}

async function _goToTab(page, labelPrefix) {
  await waitVisible(page, ".section-tab");
  const tabs = await page.$$(".section-tab");
  for (const tab of tabs) {
    const text = await page.evaluate((el) => el.textContent, tab);
    if (text.trim().startsWith(labelPrefix)) { await tab.click(); return; }
  }
  throw new Error("No se encontró la pestaña '" + labelPrefix + "'.");
}

async function _clickByText(page, text) {
  return page.evaluate((t) => {
    const btn = Array.from(document.querySelectorAll("button")).find((b) => b.textContent.trim() === t);
    if (!btn) return false; btn.click(); return true;
  }, text);
}

// ── criterio: orden natural de fases (1.0 < 1.1 < 1.2; SIN_ASIGNAR al final) ──

async function test_t_af036_us15_04_fases_ordered_naturally() {
  await withBackend(async ({ page, baseUrl, projectPath }) => {
    _seed(projectPath);
    await page.goto(baseUrl + "/ui/");
    await _goToTab(page, "Backlog");
    await waitVisible(page, ".backlog-epic-line");
    await _clickByText(page, "Por Fase");
    await page.waitForFunction(
      () => document.querySelectorAll(".backlog-fase-title").length >= 4, { timeout: 10000 }
    );
    const titles = await page.evaluate(() =>
      Array.from(document.querySelectorAll(".backlog-fase-title")).map((t) => t.textContent.trim())
    );
    assert.deepStrictEqual(titles, ["1.0", "1.1", "1.2", "SIN_VERSION"],
      "las versiones deben ordenarse naturalmente con SIN_VERSION al final");
  });
}

// ── criterio: dentro de una version, terminadas colapsadas; abiertas visibles ──

async function test_t_af036_us15_04_done_epics_collapsed_and_open_visible() {
  await withBackend(async ({ page, baseUrl, projectPath }) => {
    _seed(projectPath);
    await page.goto(baseUrl + "/ui/");
    await _goToTab(page, "Backlog");
    await waitVisible(page, ".backlog-epic-line");
    await _clickByText(page, "Por Fase");
    await page.waitForFunction(
      () => document.querySelectorAll(".backlog-fase-title").length >= 4, { timeout: 10000 }
    );
    const state = await page.evaluate(() => {
      const groups = Array.from(document.querySelectorAll(".backlog-fase-group"));
      const g11 = groups.find((g) => (g.querySelector(".backlog-fase-title") || {}).textContent.trim() === "1.1");
      const g12 = groups.find((g) => (g.querySelector(".backlog-fase-title") || {}).textContent.trim() === "1.2");
      const hasTerminadas = !!g11 && Array.from(g11.querySelectorAll("button")).some((b) => b.textContent.includes("Terminadas (1)"));
      const doneVisible = !!g11 && Array.from(g11.querySelectorAll(".backlog-epic-line")).some((l) => l.textContent.includes("AF-961"));
      const openVisible = !!g12 && Array.from(g12.querySelectorAll(".backlog-epic-line")).some((l) => l.textContent.includes("AF-962"));
      return { hasTerminadas, doneVisible, openVisible };
    });
    assert.strictEqual(state.hasTerminadas, true, "debe haber separador 'Terminadas (1)' colapsado");
    assert.strictEqual(state.doneVisible, false, "la epic terminada debe estar colapsada (no visible)");
    assert.strictEqual(state.openVisible, true, "la epic abierta debe verse directamente");
  });
}

// ── criterio: epic con todas las US fuera de roadmap al final colapsada ──

async function test_t_af036_us15_04_all_out_of_roadmap_collapsed() {
  await withBackend(async ({ page, baseUrl, projectPath }) => {
    _seed(projectPath);
    await page.goto(baseUrl + "/ui/");
    await _goToTab(page, "Backlog");
    await waitVisible(page, ".backlog-epic-line");
    await _clickByText(page, "Por Fase");
    await page.waitForFunction(
      () => document.querySelectorAll(".backlog-fase-title").length >= 4, { timeout: 10000 }
    );
    const deferred = await page.evaluate(() => {
      const groups = Array.from(document.querySelectorAll(".backlog-fase-group"));
      const g10 = groups.find((g) => (g.querySelector(".backlog-fase-title") || {}).textContent.trim() === "1.0");
      return !!g10 && Array.from(g10.querySelectorAll("button")).some((b) => b.textContent.includes("Todas fuera de roadmap (1)"));
    });
    assert.strictEqual(deferred, true, "debe haber separador 'Todas fuera de roadmap (1)' colapsado");
  });
}

// ── criterio: al expandir una Epic se ven sus US con su fase ──

async function test_t_af036_us15_04_expand_epic_shows_us_with_fase() {
  await withBackend(async ({ page, baseUrl, projectPath }) => {
    const b = path.join(projectPath, "02-backlog");
    // Epic en VERSION 1.0 con US de varias fases: al expandirla se ven TODAS
    // sus US, cada una con su fase (US-AF036-13); el filtrado por fase se
    // aplica vía el filtro global, no por el grupo (que ahora es VERSION).
    _epic(b, "AF-990", "1.0");
    _us(b, "US-AF990-01", "AF-990", "READY", "Fase 1.0");
    _us(b, "US-AF990-02", "AF-990", "READY", "Fase 1.1");
    _us(b, "US-AF990-03", "AF-990", "READY", null);

    await page.goto(baseUrl + "/ui/");
    await _goToTab(page, "Backlog");
    await waitVisible(page, ".backlog-epic-line");
    await _clickByText(page, "Por Fase");
    await page.waitForFunction(() => document.querySelector(".backlog-fase-title"), { timeout: 10000 });

    await page.evaluate(() => {
      const g = Array.from(document.querySelectorAll(".backlog-fase-group"))
        .find((gr) => (gr.querySelector(".backlog-fase-title") || {}).textContent.trim() === "1.0");
      const l = g ? Array.from(g.querySelectorAll(".backlog-epic-line")).find((e) => e.textContent.includes("AF-990")) : null;
      if (l) l.click();
    });
    await page.waitForFunction(() => document.querySelector(".backlog-us-line"), { timeout: 10000 });

    const visibleUS = await page.evaluate(() =>
      Array.from(document.querySelectorAll(".backlog-us-line-title"))
        .map((l) => l.textContent).filter((t) => t.includes("US-AF990"))
    );
    assert.ok(visibleUS.some((t) => t.includes("US-AF990-01")), "debe verse US-AF990-01 (fase 1.0)");
    assert.ok(visibleUS.some((t) => t.includes("US-AF990-02")), "debe verse US-AF990-02 (fase 1.1)");
    assert.ok(visibleUS.some((t) => t.includes("US-AF990-03")), "debe verse US-AF990-03 (SIN_ASIGNAR)");
  });
}

module.exports = [
  {
    name: "La vista 'Por Fase' ordena las versiones naturalmente (1.0 < 1.1 < 1.2; SIN_VERSION al final)",
    fn: test_t_af036_us15_04_fases_ordered_naturally,
  },
  {
    name: "Dentro de una fase, las Epics terminadas quedan colapsadas y las abiertas visibles",
    fn: test_t_af036_us15_04_done_epics_collapsed_and_open_visible,
  },
  {
    name: "Una Epic con todas sus US fuera del roadmap queda colapsada al final de su fase",
    fn: test_t_af036_us15_04_all_out_of_roadmap_collapsed,
  },
  {
    name: "Al expandir una Epic en 'Por Fase' se ven sus US con su fase",
    fn: test_t_af036_us15_04_expand_epic_shows_us_with_fase,
  },
];
