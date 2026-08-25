/* Tests web deterministas del panel "Bloqueadas" de la pantalla Backlog
 * (T-AF022-US17-02, US-AF022-17 criterio 2): reintroduce sobre el patrón
 * del deprecated `renderBacklogFocusPanel` una sección colapsable que
 * muestra cada item de `items_bloqueada` con su dependencia pendiente y el
 * estado actual de esa dependencia.
 *
 * - con items en `items_bloqueada`: el panel los lista con
 *   `← espera a <dep_id> [<estado>]` y `[no existe]` cuando el dep no está
 *   en el grafo (state null);
 * - sin items bloqueadas: muestra "(ninguna bloqueada)" sin romper la
 *   pantalla (sin `.agent-error` ni excepciones);
 * - colapsable/expandible sin afectar al resto de la vista.
 *
 * Navegador real (Chromium) contra el backend aislado; SOLO se intercambia
 * el estado de datos de la respuesta `GET /backlog` (rellenar
 * `items_bloqueada`/`by_epic`), nunca la lógica del frontend bajo prueba
 * (PRUEBAS.md: la interceptación sustituye datos, no lógica). */

"use strict";

const assert = require("assert");
const { withBackend, waitVisible } = require("./harness");

const BACKLOG_PAYLOAD_BASE = {
  empty: false,
  by_epic: [],
  items_lista: [],
  items_bloqueada: [],
  max_leverage_chain: [],
};

function _blockedPayload(items) {
  return Object.assign({}, BACKLOG_PAYLOAD_BASE, {
    items_bloqueada: items,
  });
}

function _interceptBacklog(page, payload) {
  return page.setRequestInterception(true).then(() => {
    page.on("request", (req) => {
      if (req.method() === "GET" && req.url().endsWith("/backlog")) {
        req.respond({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(payload),
        });
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

function _panelTexts(page, selector) {
  return page.evaluate(
    (sel) => Array.from(document.querySelectorAll(sel)).map((el) => el.textContent.trim()),
    selector
  );
}

function _itemAbsentTexts(page, id) {
  return page.evaluate((itemId) => {
    const item = Array.from(document.querySelectorAll(".backlog-bloqueadas-item")).find((el) =>
      el.querySelector(".backlog-bloqueadas-label")
        ? el.querySelector(".backlog-bloqueadas-label").textContent.trim() === itemId
        : false
    );
    if (!item) return [];
    return Array.from(item.querySelectorAll(".backlog-bloqueadas-dep")).map((el) => el.textContent.trim());
  }, id);
}

// -------------------------------------------------------------------------
// Criterio 1: con items en `items_bloqueada`, el panel los lista con su
// dependencia pendiente y su estado actual (`[no existe]` si el dep no está
// en el grafo). La pantalla no se rompe (`.section-content` presente).
// -------------------------------------------------------------------------

async function test_panel_lista_items_con_dependencia_y_estado() {
  await withBackend(async ({ page, baseUrl }) => {
    const payload = _blockedPayload([
      {
        id: "T-AF023-US03-02",
        kind: "T",
        epic: "AF-023",
        title: "Segunda tarea bloqueada",
        priority: "Alta",
        version: "0.9",
        blocking_dependencies: [
          { id: "T-AF023-US03-01", state: "IN_PROGRESS" },
          { id: "T-AF005-US01-99", state: null },
        ],
      },
      {
        id: "US-AF023-01",
        kind: "US",
        epic: "AF-023",
        title: "Historia bloqueada",
        priority: "Alta",
        blocking_dependencies: [{ id: "T-AF023-US03-01", state: "TO_DEVELOP" }],
      },
    ]);
    await _interceptBacklog(page, payload);
    await _gotoBacklog(page, baseUrl);

    await waitVisible(page, ".backlog-bloqueadas-panel");

    const labels = await _panelTexts(page, ".backlog-bloqueadas-label");
    assert.ok(labels.includes("T-AF023-US03-02"), "Debe listarse la Task bloqueada: " + JSON.stringify(labels));
    assert.ok(labels.includes("US-AF023-01"), "Debe listarse la US bloqueada: " + JSON.stringify(labels));

    const titleTexts = await _panelTexts(page, ".backlog-bloqueadas-title-text");
    assert.ok(
      titleTexts.includes("Segunda tarea bloqueada"),
      "Debe mostrarse el título del item: " + JSON.stringify(titleTexts)
    );

    const deps02 = await _itemAbsentTexts(page, "T-AF023-US03-02");
    assert.ok(
      deps02.includes("← espera a T-AF023-US03-01 [IN_PROGRESS]"),
      "Dependencia pendiente con su estado actual: " + JSON.stringify(deps02)
    );
    assert.ok(
      deps02.includes("← espera a T-AF005-US01-99 [no existe]"),
      "Dependencia ausente del grafo debe etiquetarse [no existe]: " + JSON.stringify(deps02)
    );

    const depsUS = await _itemAbsentTexts(page, "US-AF023-01");
    assert.ok(
      depsUS.includes("← espera a T-AF023-US03-01 [TO_DEVELOP]"),
      "US bloqueada con estado de su dependencia: " + JSON.stringify(depsUS)
    );

    assert.ok(
      await page.evaluate(() => document.querySelector(".section-content") != null),
      "La pantalla no debe romperse."
    );
  });
}

// -------------------------------------------------------------------------
// Criterio: sin items bloqueadas, el panel muestra "(ninguna bloqueada)" y
// no rompe la pantalla (sin errores agente).
// -------------------------------------------------------------------------

async function test_panel_vacio_muestra_ninguna_bloqueada() {
  await withBackend(async ({ page, baseUrl }) => {
    await _interceptBacklog(page, _blockedPayload([]));
    await _gotoBacklog(page, baseUrl);

    await waitVisible(page, ".backlog-bloqueadas-panel");
    const empty = await _panelTexts(page, ".backlog-bloqueadas-empty");
    assert.ok(
      empty.includes("(ninguna bloqueada)"),
      "Sin items bloqueadas debe mostrarse '(ninguna bloqueada)': " + JSON.stringify(empty)
    );
    assert.strictEqual(
      await page.evaluate(() => document.querySelectorAll(".backlog-bloqueadas-item").length),
      0,
      "No debe haber items listados."
    );
    assert.strictEqual(
      await page.evaluate(() => document.querySelectorAll(".agent-error").length),
      0,
      "No debe mostrarse ningún error."
    );
    assert.ok(
      await page.evaluate(() => document.querySelector(".section-content") != null),
      "La pantalla debe seguir renderizando."
    );
  });
}

// -------------------------------------------------------------------------
// Criterio: colapsar/expandir la sección sin afectar al resto de la vista.
// -------------------------------------------------------------------------

async function test_panel_colapsa_y_expande_sin_afectar_resto() {
  await withBackend(async ({ page, baseUrl }) => {
    const payload = _blockedPayload([
      {
        id: "T-AF023-US03-02",
        kind: "T",
        epic: "AF-023",
        title: "Segunda tarea bloqueada",
        priority: "Alta",
        version: "0.9",
        blocking_dependencies: [{ id: "T-AF023-US03-01", state: "IN_PROGRESS" }],
      },
    ]);
    await _interceptBacklog(page, payload);
    await _gotoBacklog(page, baseUrl);
    await waitVisible(page, ".backlog-bloqueadas-item");

    // Resto de la vista presente ANTES de colapsar.
    assert.ok(await page.evaluate(() => document.querySelector(".section-content") != null));

    // Colapsar.
    await page.evaluate(() => {
      Array.from(document.querySelectorAll(".backlog-bloqueadas-toggle")).forEach((b) => b.click());
    });
    await page.waitForFunction(
      () => document.querySelectorAll(".backlog-bloqueadas-item").length === 0,
      { timeout: 3000 }
    );
    const toggleText = await page.evaluate(
      () => (document.querySelector(".backlog-bloqueadas-toggle") || {}).textContent
    );
    assert.strictEqual(toggleText, "Mostrar", "El toggle debe quedar en 'Mostrar' al colapsar.");

    // El resto de la vista sigue presente (colapso no rompe el listado).
    assert.ok(
      await page.evaluate(() => document.querySelector(".section-content") != null),
      "Colapsar no debe romper el resto de la vista."
    );

    // Expandir de nuevo.
    await page.evaluate(() => {
      Array.from(document.querySelectorAll(".backlog-bloqueadas-toggle")).forEach((b) => b.click());
    });
    await waitVisible(page, ".backlog-bloqueadas-item");
    const deps = await _itemAbsentTexts(page, "T-AF023-US03-02");
    assert.ok(
      deps.includes("← espera a T-AF023-US03-01 [IN_PROGRESS]"),
      "Al expandir deben reaparecer los items con sus dependencias."
    );
  });
}

module.exports = [
  {
    name: "T-AF022-US17-02 · el panel Bloqueadas lista items con dependencia pendiente y su estado",
    fn: test_panel_lista_items_con_dependencia_y_estado,
  },
  {
    name: "T-AF022-US17-02 · sin items bloqueadas muestra '(ninguna bloqueada)' y no rompe",
    fn: test_panel_vacio_muestra_ninguna_bloqueada,
  },
  {
    name: "T-AF022-US17-02 · el panel colapsa/expande sin afectar al resto de la vista",
    fn: test_panel_colapsa_y_expande_sin_afectar_resto,
  },
];