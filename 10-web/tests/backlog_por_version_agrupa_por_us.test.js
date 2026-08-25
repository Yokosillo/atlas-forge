/* T-AF036-US26-05 (AD-AF036-008): la vista "Por Versión" agrupa por la
 * VERSION de las USER STORIES de cada Epic (no por `epic.version`, que se
 * retiró). Una Epic con US en varias versiones aparece bajo cada una; una
 * Epic sin US con version cae en "no versionada" (SIN_VERSION). Verificado
 * en navegador real (Chromium + backend aislado). */

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

function _epic(b, id) {
  _write(path.join(b, "epics"), id + ".md",
    `---\nid: ${id}\ntype: epic\ntitle: ${id}\nstate: READY\ndependencies: []\n---\n\n## Objetivo\n\nO.\n`);
}
function _us(b, id, epic, state, version) {
  const versionLine = version ? `version: ${version}\n` : "";
  _write(path.join(b, "user-stories"), id + ".md",
    `---\nid: ${id}\ntype: user_story\ntitle: ${id}\nstate: ${state}\ndependencies: []\nepic: ${epic}\n${versionLine}---\n\n## Historia\n\nH.\n\n## Criterios de aceptación\n\n- C.\n`);
}

async function _clickByText(page, text) {
  return page.evaluate((t) => {
    const btn = Array.from(document.querySelectorAll("button")).find((b) => b.textContent.trim() === t);
    if (!btn) return false; btn.click(); return true;
  }, text);
}

async function _groupVersions(page) {
  return page.evaluate(() =>
    Array.from(document.querySelectorAll(".backlog-fase-group")).map((g) => ({
      version: (g.querySelector(".backlog-fase-title") || {}).textContent.trim(),
      epics: Array.from(g.querySelectorAll(".backlog-epic-line")).map((l) => l.textContent),
    }))
  );
}

// ── criterio 1: una Epic con US en varias versiones aparece bajo cada una ──

async function test_epic_multi_version_aparece_en_cada_version() {
  await withBackend(async ({ page, baseUrl, projectPath }) => {
    const b = path.join(projectPath, "02-backlog");
    // Epic AF-981 con una US en 0.9 y otra en 0.9.2.
    _epic(b, "AF-981");
    _us(b, "US-AF981-01", "AF-981", "READY", "0.9");
    _us(b, "US-AF981-02", "AF-981", "READY", "0.9.2");
    // Epic AF-982 con una sola US en 0.9.1.
    _epic(b, "AF-982");
    _us(b, "US-AF982-01", "AF-982", "READY", "0.9.1");

    await page.goto(baseUrl + "/ui/");
    await _goToBacklogTab(page);
    await waitVisible(page, ".backlog-epic-line");
    await _clickByText(page, "Por Versión");
    await page.waitForFunction(() => document.querySelectorAll(".backlog-fase-title").length >= 3, { timeout: 10000 });

    const groups = await _groupVersions(page);
    const g09 = groups.find((g) => g.version === "0.9");
    const g092 = groups.find((g) => g.version === "0.9.2");
    const g091 = groups.find((g) => g.version === "0.9.1");
    assert.ok(g09 && g09.epics.some((e) => e.includes("AF-981")), "AF-981 debe estar en el grupo 0.9");
    assert.ok(g092 && g092.epics.some((e) => e.includes("AF-981")), "AF-981 debe estar también en el grupo 0.9.2");
    assert.ok(g091 && g091.epics.some((e) => e.includes("AF-982")), "AF-982 debe estar en el grupo 0.9.1");
    assert.ok(!g09 || !g09.epics.some((e) => e.includes("AF-982")), "AF-982 no debe estar en 0.9");
  });
}

// ── criterio 2: una Epic sin US con version cae en "no versionada" ──

async function test_epic_sin_us_versionada_cae_en_no_versionada() {
  await withBackend(async ({ page, baseUrl, projectPath }) => {
    const b = path.join(projectPath, "02-backlog");
    // Epic AF-983 con una US SIN version (null) -> no versionada.
    _epic(b, "AF-983");
    _us(b, "US-AF983-01", "AF-983", "READY", null);
    // Epic AF-984 SIN ninguna US (no se crea ninguna) -> no versionada.
    _epic(b, "AF-984");
    // Epic AF-985 con una US versionada en 0.9.
    _epic(b, "AF-985");
    _us(b, "US-AF985-01", "AF-985", "READY", "0.9");

    await page.goto(baseUrl + "/ui/");
    await _goToBacklogTab(page);
    await waitVisible(page, ".backlog-epic-line");
    await _clickByText(page, "Por Versión");
    await page.waitForFunction(() => {
      const groups = Array.from(document.querySelectorAll(".backlog-fase-group"));
      return groups.some((g) => (g.querySelector(".backlog-fase-title") || {}).textContent.trim() === "SIN_VERSION");
    }, { timeout: 10000 });

    const groups = await _groupVersions(page);
    const sin = groups.find((g) => g.version === "SIN_VERSION");
    assert.ok(sin, "Debe existir el grupo 'no versionada' (SIN_VERSION) al final");
    assert.ok(sin.epics.some((e) => e.includes("AF-983")), "AF-983 (US sin version) debe estar en no versionada");
    assert.ok(sin.epics.some((e) => e.includes("AF-984")), "AF-984 (sin US) debe estar en no versionada");
    assert.ok(!sin.epics.some((e) => e.includes("AF-985")), "AF-985 (US en 0.9) no debe estar en no versionada");
    // SIN_VERSION al final (después de 0.9).
    const g09 = groups.find((g) => g.version === "0.9");
    assert.ok(groups.indexOf(sin) > groups.indexOf(g09), "no versionada debe quedar al final (después de 0.9)");
  });
}

module.exports = [
  {
    name: "T-AF036-US26-05: una Epic con US en varias versiones aparece bajo cada una",
    fn: test_epic_multi_version_aparece_en_cada_version,
  },
  {
    name: "T-AF036-US26-05: una Epic sin US (o sin version) cae en el apartado 'no versionada' al final",
    fn: test_epic_sin_us_versionada_cae_en_no_versionada,
  },
];