/* T-AF036-US18-02 (US-AF036-18): el detalle de una Epic muestra su VERSION
 * (no su fase) y NO ofrece editor de fase; el editor de fase se conserva
 * para la User Story (US-AF036-14).
 *
 * Se verifica sobre la web real (`withBackend`): una Epic recién creada
 * (via POST /backlog/epic -> `version: 0.9`) expandida muestra
 * "Versión: 0.9" y ningún `.backlog-fase-editor`; una User Story bajo ella,
 * expandida, SÍ muestra su editor de fase. */

"use strict";

const assert = require("assert");
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
  throw new Error("No se encontró la pestaña 'Backlog' en la navegación.");
}

async function _seedEpicAndUs(page, epicId, usId) {
  await page.evaluate(
    async ({ epicId, usId }) => {
      const post = async (p, b) => {
        const r = await fetch(p, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(b),
        });
        if (!r.ok) throw new Error("POST " + p + " falló: " + r.status);
      };
      await post("/backlog/epic", { id: epicId, title: "Epic " + epicId, objetivo: "O." });
      await post("/backlog/epic/" + epicId + "/us", {
        id: usId, title: "US " + usId, objetivo: "H.", criterios_aceptacion: "C.",
      });
    },
    { epicId, usId }
  );
}

async function _openEpicDetail(page, epicId) {
  await waitVisible(page, ".backlog-epic-line");
  const ok = await page.evaluate((id) => {
    const line = Array.from(document.querySelectorAll(".backlog-epic-line")).find((l) =>
      l.textContent.includes(id)
    );
    if (!line) return false;
    line.click();
    return true;
  }, epicId);
  assert.ok(ok, "No se encontró la línea de la Epic '" + epicId + "'.");
}

async function _openUsDetail(page, usId) {
  await waitVisible(page, ".backlog-us-line");
  const ok = await page.evaluate((id) => {
    const line = Array.from(document.querySelectorAll(".backlog-us-line")).find((l) =>
      l.textContent.includes(id)
    );
    if (!line) return false;
    line.click();
    return true;
  }, usId);
  assert.ok(ok, "No se encontró la línea de la US '" + usId + "'.");
}

async function test_epic_detail_shows_version_and_no_fase_editor() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await _seedEpicAndUs(page, "AF-980", "US-AF980-01");
    await _goToBacklogTab(page);
    await _openEpicDetail(page, "AF-980");

    // La Epic expandida muestra su VERSION y NO ningún editor de fase.
    await page.waitForFunction(
      () =>
        Array.from(document.querySelectorAll(".job-detail-field")).some((el) =>
          /Versión:/.test(el.textContent)
        ),
      { timeout: 10000 }
    );
    const detail = await page.evaluate(() => {
      const fields = Array.from(document.querySelectorAll(".job-detail-field")).map((el) => el.textContent.trim());
      return {
        versionLine: fields.find((f) => /Versión:/.test(f)),
        hasFaseEditor: document.querySelector(".backlog-fase-editor") !== null,
      };
    });
    assert.ok(
      /Versión:\s*0\.9/.test(detail.versionLine || ""),
      "El detalle de la Epic debe mostrar 'Versión: 0.9', got: " + JSON.stringify(detail.versionLine)
    );
    assert.strictEqual(detail.hasFaseEditor, false, "La Epic no debe mostrar ningún editor de fase.");
  });
}

async function test_us_detail_still_shows_fase_editor() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await _seedEpicAndUs(page, "AF-981", "US-AF981-01");
    await _goToBacklogTab(page);
    await _openEpicDetail(page, "AF-981");
    await _openUsDetail(page, "US-AF981-01");

    await page.waitForFunction(
      () => document.querySelector(".backlog-fase-editor") !== null,
      { timeout: 10000 }
    );
    assert.ok(
      await page.evaluate(() => document.querySelector(".backlog-fase-input") !== null),
      "La User Story debe seguir mostrando su editor de fase."
    );
  });
}

module.exports = [
  {
    name: "T-AF036-US18-02: el detalle de la Epic muestra 'Versión: 0.9' y no ofrece editor de fase",
    fn: test_epic_detail_shows_version_and_no_fase_editor,
  },
  {
    name: "T-AF036-US18-02: el detalle de la User Story sigue mostrando su editor de fase",
    fn: test_us_detail_still_shows_fase_editor,
  },
];