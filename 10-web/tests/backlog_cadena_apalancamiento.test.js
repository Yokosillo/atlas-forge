/* Tests web deterministas de la cadena de mayor apalancamiento en la
 * pantalla Backlog (T-AF022-US17-04, US-AF022-17 criterio 4): se muestra
 * `report.max_leverage_chain` como fila `A → B → C` con los ids (y títulos)
 * en orden, dentro del panel "Bloqueadas".
 *
 * - con `max_leverage_chain` poblado, se ve la cadena con sus ids (y títulos)
 *   en orden;
 * - sin cadena no hay ruido (la subsección no se pinta) y no se rompe;
 * - entradas sin título no rompen (solo el id).
 *
 * Navegador real (Chromium) contra el backend aislado; SOLO se intercambia
 * el estado de datos de `GET /backlog` (datos, no lógica). */

"use strict";

const assert = require("assert");
const { withBackend, waitVisible } = require("./harness");

const PAYLOAD_BASE = {
  empty: false,
  by_epic: [],
  items_lista: [],
  items_bloqueada: [],
  items_in_progress: [],
  max_leverage_chain: [],
};

function _interceptBacklog(page, payload) {
  return page.setRequestInterception(true).then(() => {
    page.on("request", (req) => {
      if (!req.isNavigationRequest() && req.method() === "GET" && req.url().endsWith("/backlog")) {
        req.respond({ status: 200, contentType: "application/json", body: JSON.stringify(payload) });
      } else {
        req.continue();
      }
    });
  });
}

async function _gotoBacklog(page, baseUrl) {
  await page.goto(baseUrl + "/ui/");
  await waitVisible(page, ".section-content");
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

function _chainIds(page) {
  return page.evaluate(() =>
    Array.from(document.querySelectorAll(".backlog-leverage-id")).map((el) => el.textContent.trim())
  );
}

// -------------------------------------------------------------------------
// Con `max_leverage_chain` poblado: fila `A → B → C` con ids y títulos, en
// orden (y flechas entre los elementos).
// -------------------------------------------------------------------------

async function test_cadena_con_ids_y_titulos_en_orden() {
  await withBackend(async ({ page, baseUrl }) => {
    const payload = Object.assign({}, PAYLOAD_BASE, {
      max_leverage_chain: [
        { id: "T-AF023-US03-01", title: "Tarea A" },
        { id: "US-AF023-01", title: "Historia B" },
        { id: "T-AF005-US01-09", title: "Tarea C" },
      ],
    });
    await _interceptBacklog(page, payload);
    await _gotoBacklog(page, baseUrl);

    await waitVisible(page, ".backlog-leverage-chain");

    // Ids en orden.
    const ids = await _chainIds(page);
    assert.deepStrictEqual(ids, ["T-AF023-US03-01", "US-AF023-01", "T-AF005-US01-09"]);

    // Títulos visibles junto a cada id.
    const titleTexts = await page.evaluate(() =>
      Array.from(document.querySelectorAll(".backlog-leverage-title-text")).map((el) => el.textContent.trim())
    );
    assert.deepStrictEqual(titleTexts, ["· Tarea A", "· Historia B", "· Tarea C"]);

    // Flechas entre los elementos de la cadena.
    const arrows = await page.evaluate(() =>
      Array.from(document.querySelectorAll(".backlog-leverage-arrow")).length
    );
    assert.strictEqual(arrows, 2, "deben haber N-1 flechas entre los ids de la cadena");
  });
}

// -------------------------------------------------------------------------
// Sin cadena: la subsección no se pinta y no se rompe la pantalla.
// -------------------------------------------------------------------------

async function test_sin_cadena_no_se_pinta_y_no_rompe() {
  await withBackend(async ({ page, baseUrl }) => {
    await _interceptBacklog(page, Object.assign({}, PAYLOAD_BASE, { max_leverage_chain: [] }));
    await _gotoBacklog(page, baseUrl);

    await waitVisible(page, ".section-content");
    await new Promise((r) => setTimeout(r, 700));
    const chainPresent = await page.evaluate(() => !!document.querySelector(".backlog-leverage-chain"));
    assert.strictEqual(chainPresent, false, "sin cadena no debe pintarse la subsección.");
    assert.strictEqual(
      await page.evaluate(() => document.querySelectorAll(".agent-error").length),
      0,
      "no debe haber errores."
    );
  });
}

// -------------------------------------------------------------------------
// Entradas sin título (retrocompat del shape): solo el id, sin romper.
// -------------------------------------------------------------------------

async function test_entradas_sin_titulo_no_rompen() {
  await withBackend(async ({ page, baseUrl }) => {
    const payload = Object.assign({}, PAYLOAD_BASE, {
      max_leverage_chain: [
        { id: "T-AF023-US03-01" },
        { id: "T-AF023-US03-02", title: "Con título" },
      ],
    });
    await _interceptBacklog(page, payload);
    await _gotoBacklog(page, baseUrl);

    await waitVisible(page, ".backlog-leverage-chain");
    const ids = await _chainIds(page);
    assert.deepStrictEqual(ids, ["T-AF023-US03-01", "T-AF023-US03-02"]);
    const titles = await page.evaluate(() =>
      Array.from(document.querySelectorAll(".backlog-leverage-title-text")).map((el) => el.textContent.trim())
    );
    assert.deepStrictEqual(titles, ["· Con título"]);
  });
}

module.exports = [
  {
    name: "T-AF022-US17-04 · la cadena de mayor apalancamiento se muestra con ids y títulos en orden",
    fn: test_cadena_con_ids_y_titulos_en_orden,
  },
  {
    name: "T-AF022-US17-04 · sin cadena no se pinta la subsección y no se rompe la pantalla",
    fn: test_sin_cadena_no_se_pinta_y_no_rompe,
  },
  {
    name: "T-AF022-US17-04 · entradas de la cadena sin título no rompen (solo el id)",
    fn: test_entradas_sin_titulo_no_rompen,
  },
];