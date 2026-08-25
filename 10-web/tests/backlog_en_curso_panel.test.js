/* Tests web deterministas del panel "En curso" con el indicador de
 * en vuelo / huérfana (T-AF022-US17-03, US-AF022-17 criterio 3): el listado
 * de items `IN_PROGRESS` (`report.items_in_progress`, T-AF022-US17-01) con
 * su badge determinista —
 *   "en vuelo" (verde, `.backlog-inflight-ok`) si `in_flight: true`;
 *   "huérfana" (rojo/naranja, `.backlog-inflight-orphan`) si `in_flight: false`
 *   (IN_PROGRESS sin entrada en `dispatch_queue.json`, atascada).
 *
 * Cubre:
 * - cada item IN_PROGRESS se muestra con su badge y el `title` explicativo;
 * - un item huérfana es inmediatamente distinguible (badge + clase);
 * - al filtrar por estado IN_PROGRESS, el panel es EL listado de items en
 *   curso (visible); con otro filtro de estado se oculta; al volver a
 *   "Todos" reaparece (filtros persisten en `backlogSection`, US-AF036-21);
 * - sin items en curso, "(ningún item en curso)" sin romper la pantalla.
 *
 * Navegador real (Chromium) contra el backend aislado; SOLO se intercambia el
 * estado de datos de la respuesta `GET /backlog` (rellenar `items_in_progress`),
 * nunca la lógica del frontend bajo prueba (PRUEBAS.md). */

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

function _inProgressPayload(items) {
  return Object.assign({}, BACKLOG_PAYLOAD_BASE, {
    items_in_progress: items,
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

function _badgeForItem(page, itemId) {
  return page.evaluate((id) => {
    const item = Array.from(document.querySelectorAll(".backlog-en-curso-item")).find((el) => {
      const label = el.querySelector(".backlog-en-curso-label");
      return label && label.textContent.trim() === id;
    });
    if (!item) return null;
    const badge = item.querySelector(".backlog-inflight-badge");
    if (!badge) return null;
    return {
      text: badge.textContent.trim(),
      cls: badge.className,
      title: badge.getAttribute("title"),
    };
  }, itemId);
}

async function _setStateFilter(page, value) {
  await page.evaluate((v) => {
    const sels = Array.from(document.querySelectorAll(".backlog-filter-select"));
    if (sels.length === 0) throw new Error("No hay selector de estado");
    const stateSel = sels[0];
    stateSel.value = v;
    stateSel.dispatchEvent(new Event("change"));
  }, value);
}

// -------------------------------------------------------------------------
// Criterio: cada item IN_PROGRESS se muestra con su badge en vuelo/huérfana
// y el `title` explicativo; la huérfana es inmediatamente distinguible.
// -------------------------------------------------------------------------

async function test_panel_muestra_badge_en_vuelo_y_huerfana() {
  await withBackend(async ({ page, baseUrl }) => {
    const payload = _inProgressPayload([
      {
        id: "T-AF999-US01-01",
        kind: "T",
        epic: "AF-999",
        title: "En vuelo con Job",
        priority: "Alta",
        in_flight: true,
      },
      {
        id: "T-AF999-US01-02",
        kind: "T",
        epic: "AF-999",
        title: "Huerfana atascada",
        priority: "Alta",
        in_flight: false,
      },
      {
        id: "US-AF999-01",
        kind: "US",
        epic: "AF-999",
        title: "Historia derivada en vuelo",
        priority: "Alta",
        in_flight: true,
      },
    ]);
    await _interceptBacklog(page, payload);
    await _gotoBacklog(page, baseUrl);

    await waitVisible(page, ".backlog-en-curso-panel");
    const labels = await _panelTexts(page, ".backlog-en-curso-label");
    assert.ok(
      labels.includes("T-AF999-US01-01") && labels.includes("T-AF999-US01-02") && labels.includes("US-AF999-01"),
      "Deben listarse los items IN_PROGRESS: " + JSON.stringify(labels)
    );

    const ok = await _badgeForItem(page, "T-AF999-US01-01");
    assert.strictEqual(ok.text, "en vuelo");
    assert.ok(String(ok.cls).includes("backlog-inflight-ok"), "Badge en vuelo debe usar la clase verde.");
    assert.strictEqual(ok.title, "Job en vuelo en la cola de despacho");

    const orphan = await _badgeForItem(page, "T-AF999-US01-02");
    assert.strictEqual(orphan.text, "huérfana");
    assert.ok(
      String(orphan.cls).includes("backlog-inflight-orphan"),
      "Badge huérfana debe usar la clase roja/naranja — inmediatamente distinguible."
    );
    assert.strictEqual(orphan.title, "sin Job en vuelo en la cola de despacho");

    const us = await _badgeForItem(page, "US-AF999-01");
    assert.strictEqual(us.text, "en vuelo", "La US derivada IN_PROGRESS también lleva su badge.");

    assert.ok(
      await page.evaluate(() => document.querySelector(".section-content") != null),
      "La pantalla no debe romperse."
    );
  });
}

// -------------------------------------------------------------------------
// Criterio: filtrando por estado IN_PROGRESS se ven los items en curso (el
// panel es el listado); con otro estado el panel se oculta; al volver a
// "Todos" reaparece (filtro persistente en `backlogSection`).
// -------------------------------------------------------------------------

async function test_filtro_in_progress_muestra_panel_con_badges() {
  await withBackend(async ({ page, baseUrl }) => {
    const payload = _inProgressPayload([
      {
        id: "T-AF999-US01-02",
        kind: "T",
        epic: "AF-999",
        title: "Huerfana atascada",
        priority: "Alta",
        in_flight: false,
      },
    ]);
    await _interceptBacklog(page, payload);
    await _gotoBacklog(page, baseUrl);
    await waitVisible(page, ".backlog-en-curso-panel");

    // Filtrar por IN_PROGRESS: el panel se mantiene como EL listado de en
    // curso, con su badge.
    await _setStateFilter(page, "IN_PROGRESS");
    await waitVisible(page, ".backlog-en-curso-item");
    const orphan = await _badgeForItem(page, "T-AF999-US01-02");
    assert.strictEqual(orphan.text, "huérfana");

    // Otro estado (READY): el panel se oculta.
    await _setStateFilter(page, "READY");
    await page.waitForFunction(
      () => document.querySelectorAll(".backlog-en-curso-panel").length === 0,
      { timeout: 3000 }
    );

    // Volver a "Todos": el panel reaparece con el badge (filtro persistente).
    await _setStateFilter(page, "all");
    await waitVisible(page, ".backlog-en-curso-item");
    const orphanAgain = await _badgeForItem(page, "T-AF999-US01-02");
    assert.strictEqual(orphanAgain.text, "huérfana");
  });
}

// -------------------------------------------------------------------------
// Criterio: sin items en curso, "(ningún item en curso)" sin romper.
// -------------------------------------------------------------------------

async function test_panel_vacio_muestra_ningun_item_en_curso() {
  await withBackend(async ({ page, baseUrl }) => {
    await _interceptBacklog(page, _inProgressPayload([]));
    await _gotoBacklog(page, baseUrl);

    await waitVisible(page, ".backlog-en-curso-panel");
    const empty = await _panelTexts(page, ".backlog-en-curso-empty");
    assert.ok(
      empty.includes("(ningún item en curso)"),
      "Sin items en curso debe mostrarse el mensaje vacío: " + JSON.stringify(empty)
    );
    assert.strictEqual(
      await page.evaluate(() => document.querySelectorAll(".backlog-en-curso-item").length),
      0,
      "No debe haber items listados."
    );
    assert.strictEqual(
      await page.evaluate(() => document.querySelectorAll(".agent-error").length),
      0,
      "No debe mostrarse ningún error."
    );
  });
}

module.exports = [
  {
    name: "T-AF022-US17-03 · el panel En curso muestra badge en vuelo/huérfana por item IN_PROGRESS",
    fn: test_panel_muestra_badge_en_vuelo_y_huerfana,
  },
  {
    name: "T-AF022-US17-03 · filtrar por IN_PROGRESS deja el panel En curso con sus badges; otros estados lo ocultan",
    fn: test_filtro_in_progress_muestra_panel_con_badges,
  },
  {
    name: "T-AF022-US17-03 · sin items en curso muestra '(ningún item en curso)' sin romper",
    fn: test_panel_vacio_muestra_ningun_item_en_curso,
  },
];