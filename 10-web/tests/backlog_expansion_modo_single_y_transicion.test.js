/* T-AF036-US27-04 (US-AF036-27): cobertura determinista de la transición de
 * modo y del modo `single` en el despliegue del Backlog.
 *
 * 1. Modo `single` (default): abrir una segunda Epic COLAPSA la primera
 *    (backward-compat, criterio 4 de la US).
 * 2. Transición en caliente `single` -> `multi` (cambiar desde Configuración
 *    y volver al Backlog SIN recargar la página): el modo se aplica en el
 *    acto (criterio 2 de la US), la Epic abierta en modo single colapsa
 *    (no se migra el estado en curso — comportamiento documentado en
 *    T-AF036-US27-04) y en modo multi abrir una segunda Epic NO colapsa la
 *    primera.
 *
 * Navegador real (Chromium) contra el backend aislado; SOLO se intercambia
 * el estado de datos de `GET/PUT /system/preferences` (datos, no lógica). */

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
  for (const [epic, us] of [["AF-971", "US-AF971-01"], ["AF-972", "US-AF972-01"]]) {
    _write(path.join(b, "epics"), epic + ".md",
      `---\nid: ${epic}\ntype: epic\ntitle: ${epic}\nstate: READY\ndependencies: []\n---\n\n## Objetivo\n\nO.\n`);
    _write(path.join(b, "user-stories"), us + ".md",
      `---\nid: ${us}\ntype: user_story\ntitle: ${us}\nstate: READY\ndependencies: []\nepic: ${epic}\nversion: 0.9.2\n---\n\n## Historia\n\nH.\n\n## Criterios de aceptación\n\n- C.\n`);
  }
}

function _interceptPrefs(page, prefs) {
  return page.setRequestInterception(true).then(() => {
    page.on("request", (req) => {
      if (req.method() === "GET" && /\/system\/preferences$/.test(req.url())) {
        req.respond({ status: 200, contentType: "application/json", body: JSON.stringify(prefs) });
        return;
      }
      if (req.method() === "PUT" && /\/system\/preferences$/.test(req.url())) {
        let body = {};
        try { body = JSON.parse(req.postData() || "{}"); } catch (_e) {}
        Object.assign(prefs, body); // muta el objeto capturado (visible para el test).
        req.respond({ status: 200, contentType: "application/json", body: JSON.stringify(prefs) });
        return;
      }
      req.continue();
    });
  });
}

async function _openEpic(page, epicId) {
  await page.evaluate((id) => {
    const line = Array.from(document.querySelectorAll(".backlog-epic-line")).find((l) => l.textContent.includes(id));
    if (line) line.click();
  }, epicId);
}

function _epicHasDetail(page, epicId) {
  return page.evaluate((id) => {
    const card = Array.from(document.querySelectorAll(".backlog-epic-line")).find((l) => l.textContent.includes(id));
    return card ? !!card.closest(".job-card").querySelector(".backlog-us-line") : false;
  }, epicId);
}

async function _setExpansionMode(page, mode) {
  await _goToTab(page, "Configuración");
  await page.waitForFunction(() => {
    const labels = Array.from(document.querySelectorAll(".model-role-label"));
    return labels.some((l) => l.textContent.includes("Despliegue del Backlog"));
  }, { timeout: 10000 });
  await page.evaluate((m) => {
    const row = Array.from(document.querySelectorAll(".model-row")).find((r) =>
      r.textContent.includes("Despliegue del Backlog")
    );
    const sel = row.querySelector("select");
    sel.value = m;
    sel.dispatchEvent(new Event("change", { bubbles: true }));
  }, mode);
  await page.waitForFunction(() => {
    const btn = Array.from(document.querySelectorAll("button")).find((b) => b.textContent.trim() === "Guardar preferencias");
    return btn && !btn.disabled;
  }, { timeout: 10000 });
  await page.evaluate(() => {
    const btn = Array.from(document.querySelectorAll("button")).find((b) => b.textContent.trim() === "Guardar preferencias");
    if (btn) btn.click();
  });
  // Esperar a que el PUT resuelva y el modo se aplique al Backlog.
  await new Promise((r) => setTimeout(r, 900));
}

async function _enterBacklog(page) {
  await _goToTab(page, "Backlog");
  await waitVisible(page, ".backlog-epic-line");
}

// -------------------------------------------------------------------------
// Criterio 4 de la US: modo `single` (default) — abrir una segunda Epic
// colapsa la primera.
// -------------------------------------------------------------------------

async function test_single_colapsa_la_epic_anterior() {
  await withBackend(async ({ page, baseUrl, projectPath }) => {
    await _seed(projectPath);
    const prefs = { backlog_multiple_expansion: "single", max_simultaneous_developers: 3 };
    await _interceptPrefs(page, prefs);
    await page.goto(baseUrl + "/ui/");
    await _setExpansionMode(page, "single");
    await _enterBacklog(page);

    await _openEpic(page, "AF-971");
    await page.waitForFunction(() => document.querySelectorAll(".backlog-us-line").length >= 1, { timeout: 10000 });
    await _openEpic(page, "AF-972");
    await new Promise((r) => setTimeout(r, 700));

    // Single: solo la última Epic queda expandida.
    assert.strictEqual(await _epicHasDetail(page, "AF-971"), false, "AF-971 debe colapsarse al abrir AF-972 en single");
    assert.strictEqual(await _epicHasDetail(page, "AF-972"), true, "AF-972 debe estar expandida");
  });
}

// -------------------------------------------------------------------------
// Transición en caliente single -> multi y modo multi sin colapso cruzado
// (comportamiento documentado en T-AF036-US27-04).
// -------------------------------------------------------------------------

async function test_transicion_caliente_single_a_multi() {
  await withBackend(async ({ page, baseUrl, projectPath }) => {
    await _seed(projectPath);
    const prefs = { backlog_multiple_expansion: "single", max_simultaneous_developers: 3 };
    await _interceptPrefs(page, prefs);
    await page.goto(baseUrl + "/ui/");
    await _setExpansionMode(page, "single");
    await _enterBacklog(page);

    // Abrir AF-971 en modo single (solo ella).
    await _openEpic(page, "AF-971");
    await page.waitForFunction(() => document.querySelectorAll(".backlog-us-line").length >= 1, { timeout: 10000 });

    // Cambiar a "multi" desde Configuración SIN recargar la página.
    await _setExpansionMode(page, "multi");
    assert.strictEqual(prefs.backlog_multiple_expansion, "multi", "el PUT debe haber persistido 'multi'");

    // Volver al Backlog: la Epic abierta en single colapsa (no se migra el
    // estado en curso entre modos — comportamiento documentado).
    await _enterBacklog(page);
    assert.strictEqual(await _epicHasDetail(page, "AF-971"), false, "el estado abierto en single no se migra a multi");

    // En multi, abrir dos Epics: la primera NO colapsa.
    await _openEpic(page, "AF-971");
    await page.waitForFunction(() => document.querySelectorAll(".backlog-us-line").length >= 1, { timeout: 10000 });
    await _openEpic(page, "AF-972");
    await page.waitForFunction(() => document.querySelectorAll(".backlog-us-line").length >= 2, { timeout: 10000 });

    assert.strictEqual(await _epicHasDetail(page, "AF-971"), true, "AF-971 debe seguir expandida en multi");
    assert.strictEqual(await _epicHasDetail(page, "AF-972"), true, "AF-972 debe estar expandida en multi");
  });
}

module.exports = [
  {
    name: "T-AF036-US27-04: en modo single, abrir una segunda Epic colapsa la anterior (backward-compat)",
    fn: test_single_colapsa_la_epic_anterior,
  },
  {
    name: "T-AF036-US27-04: transición caliente single->multi sin recargar; lo abierto en single colapsa y luego multi no colapsa entre Epics",
    fn: test_transicion_caliente_single_a_multi,
  },
];