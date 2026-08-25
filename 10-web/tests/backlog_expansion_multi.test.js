/* T-AF036-US27-03 (US-AF036-27): en modo `multi` abrir una segunda Epic NO
 * colapsa la primera, y abrir la US de una Epic NO colapsa la US de otra.
 * Verificado en navegador real. */

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
  for (const [epic, us] of [["AF-981", "US-AF981-01"], ["AF-982", "US-AF982-01"]]) {
    _write(path.join(b, "epics"), epic + ".md",
      `---\nid: ${epic}\ntype: epic\ntitle: ${epic}\nstate: READY\ndependencies: []\n---\n\n## Objetivo\n\nO.\n`);
    _write(path.join(b, "user-stories"), us + ".md",
      `---\nid: ${us}\ntype: user_story\ntitle: ${us}\nstate: READY\ndependencies: []\nepic: ${epic}\nversion: 0.9.2\n---\n\n## Historia\n\nH.\n\n## Criterios de aceptación\n\n- C.\n`);
  }
}

async function _openEpic(page, epicId) {
  await page.evaluate((id) => {
    const line = Array.from(document.querySelectorAll(".backlog-epic-line")).find((l) => l.textContent.includes(id));
    if (line) line.click();
  }, epicId);
}

async function _epicHasDetail(page, epicId) {
  return page.evaluate((id) => {
    const card = Array.from(document.querySelectorAll(".backlog-epic-line")).find((l) => l.textContent.includes(id));
    return card ? !!card.closest(".job-card").querySelector(".backlog-us-line") : false;
  });
}

async function test_multi_dos_epics_abiertas_simultaneamente() {
  await withBackend(async ({ page, baseUrl, projectPath }) => {
    await _seed(projectPath);
    await page.setRequestInterception(true);
    page.on("request", (req) => {
      if (req.method() === "GET" && /\/system\/preferences$/.test(req.url())) {
        req.respond({ status: 200, contentType: "application/json", body: JSON.stringify({ backlog_multiple_expansion: "multi", max_simultaneous_developers: 3 }) });
        return;
      }
      req.continue();
    });

    await page.goto(baseUrl + "/ui/");
    await _goToTab(page, "Configuración");
    // Cargar la preferencia (expone el modo multi al Backlog).
    await page.waitForFunction(() => {
      const labels = Array.from(document.querySelectorAll(".model-role-label"));
      return labels.some((l) => l.textContent.includes("Despliegue del Backlog"));
    }, { timeout: 10000 });
    await _goToTab(page, "Backlog");
    await waitVisible(page, ".backlog-epic-line");

    // Abrir AF-981 y luego AF-982: ambas deben quedar con su detalle (listado de US).
    await _openEpic(page, "AF-981");
    await page.waitForFunction(() => document.querySelectorAll(".backlog-us-line").length >= 1, { timeout: 10000 });
    await _openEpic(page, "AF-982");
    await page.waitForFunction(() => document.querySelectorAll(".backlog-us-line").length >= 2, { timeout: 10000 });
    // Ambos listados de US presentes -> ambas Epics expandidas a la vez.
    const texts = await page.evaluate(() =>
      Array.from(document.querySelectorAll(".backlog-us-line")).map((l) => l.textContent)
    );
    assert.ok(texts.some((t) => t.includes("US-AF981-01")), "el listado de US de AF-981 debe seguir visible");
    assert.ok(texts.some((t) => t.includes("US-AF982-01")), "el listado de US de AF-982 debe estar visible");
  });
}

async function test_multi_us_de_distintas_epics_no_se_colapsan() {
  await withBackend(async ({ page, baseUrl, projectPath }) => {
    await _seed(projectPath);
    await page.setRequestInterception(true);
    page.on("request", (req) => {
      if (req.method() === "GET" && /\/system\/preferences$/.test(req.url())) {
        req.respond({ status: 200, contentType: "application/json", body: JSON.stringify({ backlog_multiple_expansion: "multi", max_simultaneous_developers: 3 }) });
        return;
      }
      req.continue();
    });

    await page.goto(baseUrl + "/ui/");
    await _goToTab(page, "Configuración");
    await page.waitForFunction(() => {
      const labels = Array.from(document.querySelectorAll(".model-role-label"));
      return labels.some((l) => l.textContent.includes("Despliegue del Backlog"));
    }, { timeout: 10000 });
    await _goToTab(page, "Backlog");
    await waitVisible(page, ".backlog-epic-line");

    await _openEpic(page, "AF-981");
    await _openEpic(page, "AF-982");
    await page.waitForFunction(() => document.querySelectorAll(".backlog-us-line").length >= 2, { timeout: 10000 });

    // Abrir la US de AF-981 y luego la de AF-982: ambas detalle abierto.
    await page.evaluate(() => {
      const lines = Array.from(document.querySelectorAll(".backlog-us-line"));
      const target = lines.find((l) => l.textContent.includes("US-AF981-01"));
      if (target) target.click();
    });
    await page.waitForFunction(() => document.querySelectorAll(".job-detail-field").length >= 1, { timeout: 10000 });
    await page.evaluate(() => {
      const lines = Array.from(document.querySelectorAll(".backlog-us-line"));
      const target = lines.find((l) => l.textContent.includes("US-AF982-01"));
      if (target) target.click();
    });
    await new Promise((r) => setTimeout(r, 800));

    // Ambas US quedan expandidas (dos job-card-selected de US o dos detalle visible).
    const expanded = await page.evaluate(() =>
      Array.from(document.querySelectorAll(".backlog-us-line")).filter((l) => l.classList.contains("job-line-selected")).length
    );
    assert.ok(expanded >= 2, "deben quedar al menos 2 US expandidas a la vez, got: " + expanded);
  });
}

module.exports = [
  {
    name: "T-AF036-US27-03: en modo multi, dos Epics abiertas muestran a la vez sus listados de US",
    fn: test_multi_dos_epics_abiertas_simultaneamente,
  },
  {
    name: "T-AF036-US27-03: en modo multi, abrir la US de una Epic no colapsa la US de otra",
    fn: test_multi_us_de_distintas_epics_no_se_colapsan,
  },
];