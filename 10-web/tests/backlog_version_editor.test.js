/* T-AF036-US26-03 (US-AF036-26): editor de versión para Epics y User Stories.
 * Verificado en navegador real (Chromium) contra el backend aislado. */

"use strict";

const assert = require("assert");
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

async function _seed(page) {
  await page.evaluate(async () => {
    const post = async (p, b) => {
      const r = await fetch(p, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(b),
      });
      if (!r.ok) throw new Error("POST " + p + " falló: " + r.status);
    };
    await post("/backlog/epic", { id: "AF-994", title: "Editor de versión", objetivo: "O." });
    await post("/backlog/epic/AF-994/us", { id: "US-AF994-01", title: "Editar versión", objetivo: "H.", criterios_aceptacion: "C." });
  });
}

async function _openEpic(page, epicId) {
  await page.evaluate((id) => {
    const line = Array.from(document.querySelectorAll(".backlog-epic-line")).find((l) => l.textContent.includes(id));
    if (line) line.click();
  }, epicId);
}

async function _versionEditorCount(page) {
  return page.evaluate(() => document.querySelectorAll(".backlog-version-editor").length);
}

async function test_editor_presente_para_epic_y_us() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await _seed(page);
    await _goToBacklogTab(page);
    await waitVisible(page, ".backlog-epic-line");

    // Detalle de la Epic: debe haber un editor de versión (antes era texto estático).
    await _openEpic(page, "AF-994");
    await page.waitForFunction(() => document.querySelector(".backlog-us-line") !== null, { timeout: 10000 });
    assert.ok((await _versionEditorCount(page)) >= 1, "La Epic debe tener editor de versión");

    // Detalle de la US: también debe tener editor de versión.
    await page.evaluate(() => {
      const line = Array.from(document.querySelectorAll(".backlog-us-line")).find((l) => l.textContent.includes("US-AF994-01"));
      if (line) line.click();
    });
    await page.waitForFunction(() => document.querySelector(".backlog-version-input") !== null, { timeout: 10000 });
    assert.ok((await _versionEditorCount(page)) >= 1, "La US debe tener editor de versión");
  });
}

async function _editEpicVersion(page, value, onPut) {
  await page.evaluate((v) => {
    const editor = document.querySelector(".backlog-version-editor");
    const input = editor.querySelector(".backlog-version-input");
    input.value = v;
    const btn = Array.from(editor.querySelectorAll("button")).find((b) => b.textContent.trim() === "Guardar");
    if (btn) btn.click();
  }, value);
  if (onPut) await onPut();
}

async function test_edicion_persiste_via_endpoint() {
  let putResolve = null;
  const putPromise = new Promise((r) => { putResolve = r; });

  await withBackend(async ({ page, baseUrl }) => {
    await page.setRequestInterception(true);
    page.on("request", (req) => {
      const m = /\/backlog\/(AF-994)\/version$/.exec(req.url());
      if (req.method() === "PUT" && m) {
        if (putResolve) { putResolve(); putResolve = null; }
        req.respond({ status: 200, contentType: "application/json", body: JSON.stringify({ item_id: "AF-994", version: "0.9.1" }) });
        return;
      }
      req.continue();
    });

    await page.goto(baseUrl + "/ui/");
    await _seed(page);
    await _goToBacklogTab(page);
    await _openEpic(page, "AF-994");
    await page.waitForFunction(() => {
      const eds = document.querySelectorAll(".backlog-version-editor");
      return eds.length === 1;
    }, { timeout: 10000 });

    await _editEpicVersion(page, "0.9.1", () => Promise.race([putPromise, new Promise((_, rej) => setTimeout(() => rej(new Error("timeout esperando PUT")), 10000))]));
    // Sin error: el editor persiste la versión válida vía el endpoint.
    await new Promise((r) => setTimeout(r, 500));
    const hasError = await page.evaluate(() => !!document.querySelector(".agent-error"));
    assert.strictEqual(hasError, false, "Una versión válida no debe mostrar error");
  });
}

async function test_error_no_deja_valor_inconsistente() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.setRequestInterception(true);
    page.on("request", (req) => {
      const m = /\/backlog\/(AF-994)\/version$/.exec(req.url());
      if (req.method() === "PUT" && m) {
        req.respond({ status: 400, contentType: "application/json", body: JSON.stringify({ detail: "Versión inválida: '9.9.9'. Válidas: 0.9, 0.9.1, 0.9.2 o null." }) });
        return;
      }
      req.continue();
    });

    await page.goto(baseUrl + "/ui/");
    await _seed(page);
    await _goToBacklogTab(page);
    await _openEpic(page, "AF-994");
    await page.waitForFunction(() => {
      const eds = document.querySelectorAll(".backlog-version-editor");
      return eds.length === 1;
    }, { timeout: 10000 });

    await _editEpicVersion(page, "9.9.9");
    await page.waitForFunction(() => {
      const err = document.querySelector(".agent-error");
      return err && err.textContent.includes("Versión inválida");
    }, { timeout: 10000 });
    const inputVal = await page.evaluate(() => {
      const editor = document.querySelector(".backlog-version-editor");
      return editor.querySelector(".backlog-version-input").value;
    });
    assert.notStrictEqual(inputVal, "9.9.9", "El input no debe quedar con el valor inválido tras el error");
  });
}

module.exports = [
  {
    name: "T-AF036-US26-03: el editor de versión está presente para Epics y User Stories",
    fn: test_editor_presente_para_epic_y_us,
  },
  {
    name: "T-AF036-US26-03: editar versión de la Epic persiste vía endpoint sin error",
    fn: test_edicion_persiste_via_endpoint,
  },
  {
    name: "T-AF036-US26-03: un error de validación se muestra y no deja el input con el valor inválido",
    fn: test_error_no_deja_valor_inconsistente,
  },
];