/* T-AF036-US15-03 / T-AF036-US15-06 (US-AF036-15): al expandir una Epic en la
 * vista "Por Fase" se muestran sus User Stories con su fase; el filtrado por
 * fase se aplica vía el filtro global de fase (la vista agrupa las Epics por
 * VERSION, no por fase — no hay "fase de grupo"). La vista plana (flat)
 * muestra todas. Verificado en navegador real (Chromium + backend aislado). */

"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const { withBackend, waitVisible } = require("./harness");

async function _goToBacklogTab(page) {
  await waitVisible(page, ".section-tab");
  const tabs = await page.$$(".section-tab");
  for (const tab of tabs) {
    const text = await page.evaluate((el) => el.textContent, tab);
    if (text.trim().startsWith("Backlog")) {
      await tab.click();
      return;
    }
  }
  throw new Error("No se encontró la pestaña 'Backlog'.");
}

async function _seed(page, epicId, usIds) {
  await page.evaluate(
    async ({ epicId, usIds }) => {
      const post = async (p, b) => {
        const r = await fetch(p, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(b),
        });
        if (!r.ok) throw new Error("POST " + p + " falló: " + r.status);
      };
      await post("/backlog/epic", { id: epicId, title: "Epic " + epicId, objetivo: "O." });
      for (const usId of usIds) {
        await post("/backlog/epic/" + epicId + "/us", { id: usId, title: "US " + usId, objetivo: "H.", criterios_aceptacion: "C." });
      }
    },
    { epicId, usIds }
  );
}

function _findFile(projectPath, subdir, idPrefix) {
  const dir = path.join(projectPath, "02-backlog", subdir);
  const name = fs.readdirSync(dir).find((n) => n.startsWith(idPrefix));
  assert.ok(name, "No se encontró " + idPrefix + " en " + dir);
  return path.join(dir, name);
}

function _setUsFase(projectPath, usId, fase) {
  const p = _findFile(projectPath, "user-stories", usId);
  const original = fs.readFileSync(p, "utf-8");
  const idx = original.indexOf("\n---");
  fs.writeFileSync(p, original.slice(0, idx) + "\nfase: " + fase + original.slice(idx));
}

// T-AF036-US18-01: `POST /backlog/epic` crea la Epic con `version: 0.9`. La
// vista "Por Fase" agrupa por VERSION (T-AF036-US15-06), así que no hace
// falta tocar la Epic aquí — solo se fija la fase de las US.

async function _clickButtonByText(page, text) {
  const clicked = await page.evaluate((label) => {
    const btn = Array.from(document.querySelectorAll("button")).find((b) => b.textContent.includes(label));
    if (!btn || btn.disabled) return false;
    btn.click();
    return true;
  }, text);
  assert.ok(clicked, "No se encontró el botón con texto que contenga '" + text + "'.");
}

async function _openEpicInGroup(page, epicId) {
  const ok = await page.evaluate((id) => {
    const line = Array.from(document.querySelectorAll(".backlog-epic-line")).find((l) => l.textContent.includes(id));
    if (!line) return false;
    line.click();
    return true;
  }, epicId);
  assert.ok(ok, "No se encontró la línea de la Epic '" + epicId + "'.");
}

async function _visibleUsIds(page) {
  return page.evaluate(() =>
    Array.from(document.querySelectorAll(".backlog-us-line")).map((l) => l.textContent.trim())
  );
}

async function test_por_fase_expand_epic_shows_us_with_fase() {
  await withBackend(async ({ page, baseUrl, projectPath }) => {
    assert.ok(projectPath, "El backend aislado debe exponer la ruta real del proyecto activo.");

    await page.goto(baseUrl + "/ui/");
    // Epic AF-961 (agrupada por VERSION 0.9) con dos US de distintas fases:
    // al expandirla se ven TODAS sus US, cada una con su fase — la vista ya
    // no filtra por "fase del grupo" (el grupo es VERSION, T-AF036-US15-06).
    await _seed(page, "AF-961", ["US-AF961-01", "US-AF961-02"]);
    _setUsFase(projectPath, "US-AF961-01", "Fase 1.1");
    _setUsFase(projectPath, "US-AF961-02", "Fase 2.0");

    await page.reload();
    await _goToBacklogTab(page);
    await _clickButtonByText(page, "Por Fase");
    await waitVisible(page, ".backlog-fase-title");

    await _openEpicInGroup(page, "AF-961");
    await waitVisible(page, ".backlog-us-line");

    const visible = await _visibleUsIds(page);
    assert.ok(
      visible.some((t) => t.includes("US-AF961-01")),
      "Debe verse US-AF961-01 (fase 1.1), got: " + JSON.stringify(visible)
    );
    assert.ok(
      visible.some((t) => t.includes("US-AF961-02")),
      "Debe verse US-AF961-02 (fase 2.0) — el grupo es VERSION, no fase, got: " + JSON.stringify(visible)
    );
  });
}

async function test_flat_muestra_todas_las_us() {
  await withBackend(async ({ page, baseUrl, projectPath }) => {
    assert.ok(projectPath, "El backend aislado debe exponer la ruta real del proyecto activo.");

    await page.goto(baseUrl + "/ui/");
    await _seed(page, "AF-962", ["US-AF962-01", "US-AF962-02"]);
    _setUsFase(projectPath, "US-AF962-01", "Fase 1.1");
    _setUsFase(projectPath, "US-AF962-02", "Fase 2.0");

    await page.reload();
    await _goToBacklogTab(page);
    // Vista plana por defecto: expandir la Epic muestra TODAS las US.
    await _openEpicInGroup(page, "AF-962");
    await waitVisible(page, ".backlog-us-line");

    const visible = await _visibleUsIds(page);
    assert.ok(
      visible.some((t) => t.includes("US-AF962-01")) && visible.some((t) => t.includes("US-AF962-02")),
      "La vista plana debe mostrar todas las US de la Epic, got: " + JSON.stringify(visible)
    );
  });
}

module.exports = [
  {
    name: "T-AF036-US15-06: al expandir una Epic en 'Por Fase' se ven sus US con su fase",
    fn: test_por_fase_expand_epic_shows_us_with_fase,
  },
  {
    name: "T-AF036-US15-03: la vista plana (flat) no se ve afectada y muestra todas las US",
    fn: test_flat_muestra_todas_las_us,
  },
];