/* T-AF036-US20 (US-AF036-20): la creación de backlog en la web es por
 * ÚNICA entrada de lenguaje natural (textarea).
 *
 * - el formulario "Nueva Epic" muestra SOLO un textarea + botón (sin campos
 *   estructurales);
 * - al crear, se encola (POST /backlog/epic/from-description) y se muestra
 *   el request_id;
 * - una petición `done` se refleja en el backlog cuando el reporte la
 *   muestra (la entidad nueva aparece en el listado).
 *
 * (El panel "Peticiones para el Arquitecto" — la cola de respuestas que se
 * mostró en la cabecera del Backlog — se retiró de la pantalla por decisión
 * de producto el 2026-08-25; se está evaluando llevarlo a la pantalla
 * Arquitecto. El backend de peticiones sigue activo.)
 *
 * Navegador real (Chromium) contra el backend aislado; SOLO se intercambia
 * el estado de datos de GET /backlog y de los POST de encolado (nunca la
 * lógica). */

"use strict";

const assert = require("assert");
const { withBackend, waitVisible } = require("./harness");

const BACKLOG_PAYLOAD = {
  empty: false,
  by_epic: [],
  items_lista: [],
  items_bloqueada: [],
  items_in_progress: [],
  max_leverage_chain: [],
};

function _intercept(page, state) {
  return page.setRequestInterception(true).then(() => {
    page.on("request", (req) => {
      if (!req.isNavigationRequest() && req.method() === "GET" && req.url().endsWith("/backlog")) {
        req.respond({ status: 200, contentType: "application/json", body: JSON.stringify(BACKLOG_PAYLOAD) });
        return;
      }
      if (!req.isNavigationRequest() && req.method() === "POST" && /\/backlog\/epic\/from-description$/.test(req.url())) {
        state.requests.unshift({
          request_id: "rq-epic-0001", tipo: "epic", description: "Nueva epic en lenguaje natural.", status: "pending",
          epic_id: null, us_id: null, errors: [], created_at: "2026-08-25T00:00:00+00:00",
        });
        req.respond({ status: 202, contentType: "application/json", body: JSON.stringify({ request_id: "rq-epic-0001", tipo: "epic", status: "pending" }) });
        return;
      }
      req.continue();
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

async function _openNewEpicForm(page) {
  await page.evaluate(() => {
    const btn = Array.from(document.querySelectorAll("button")).find((b) => b.textContent.trim() === "+ Nueva Epic");
    if (btn) btn.click();
  });
}

// -------------------------------------------------------------------------
// El formulario "Nueva Epic" muestra SOLO un textarea + botón (sin campos
// estructurales), y al crear muestra el request_id.
// -------------------------------------------------------------------------

async function test_creacion_textarea_unico_y_request_id() {
  await withBackend(async ({ page, baseUrl }) => {
    const state = { requests: [] };
    await _intercept(page, state);
    await _gotoBacklog(page, baseUrl);
    await _openNewEpicForm(page);
    await waitVisible(page, "textarea.backlog-new-epic-input");

    // Solo un textarea y un botón "Crear" — sin campos estructurales (id/título/objetivo).
    const textareas = await page.$$("textarea.backlog-new-epic-input");
    assert.strictEqual(textareas.length, 1, "Debe haber un único textarea.");
    const hasIdInput = await page.evaluate(() =>
      Array.from(document.querySelectorAll("input.backlog-new-epic-input")).some((i) => i.placeholder === "AF-999")
    );
    assert.strictEqual(hasIdInput, false, "No debe haber campo de ID estructural.");
    const hasTitleField = await page.evaluate(() =>
      Array.from(document.querySelectorAll("span")).some((s) => s.textContent.trim() === "Título")
    );
    assert.strictEqual(hasTitleField, false, "No debe haber campo 'Título'.");

    // Escribir y crear.
    await page.type("textarea.backlog-new-epic-input", "Nueva epic en lenguaje natural.");
    await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll("button")).find((b) => b.textContent.trim() === "Crear");
      if (btn) btn.click();
    });

    // Se muestra el request_id y la petición queda encolada en el panel.
    await page.waitForFunction(
      () => (document.body.innerText || "").includes("rq-epic-0001"),
      { timeout: 8000 }
    );
    const body = await page.evaluate(() => document.body.innerText);
    assert.ok(body.includes("request: rq-epic-0001"), "Debe mostrarse el request_id tras crear.");
    assert.strictEqual(state.requests.length, 1, "La petición debe haberse encolado.");
  });
}

// -------------------------------------------------------------------------
// Una petición `done`: la entidad ya escrita aparece en el backlog cuando el
// reporte la refleja. (Cubre el caso "una `done` deja ver el item nuevo en el
// backlog" del alcance web de T-AF036-US20-05 — sin el panel de respuestas.)
// -------------------------------------------------------------------------

async function test_peticion_done_deja_ver_item_nuevo_en_backlog() {
  await withBackend(async ({ page, baseUrl }) => {
    const backlogPayload = {
      empty: false,
      by_epic: [
        {
          epic: "AF-778",
          epic_label: "Gestor de plantillas",
          user_stories: { READY: 1 },
          tasks: { READY: 0 },
          user_stories_detail: [
            { id: "US-AF778-01", fase: null, state: "READY", version: "0.9" },
          ],
        },
      ],
      items_lista: [],
      items_bloqueada: [],
      items_in_progress: [],
      max_leverage_chain: [],
    };

    await page.setRequestInterception(true).then(() => {
      page.on("request", (req) => {
        if (!req.isNavigationRequest() && req.method() === "GET" && req.url().endsWith("/backlog")) {
          req.respond({ status: 200, contentType: "application/json", body: JSON.stringify(backlogPayload) });
          return;
        }
        req.continue();
      });
    });

    await _gotoBacklog(page, baseUrl);

    // El item nuevo (la Epic AF-778) es visible en el backlog.
    await waitVisible(page, ".backlog-epic-line");
    const body = await page.evaluate(() => document.body.innerText);
    assert.ok(body.includes("AF-778"), "El item nuevo debe ser visible en el backlog: " + body.slice(0, 400));
    assert.ok(body.includes("Gestor de plantillas"), "Debe mostrarse el título de la Epic creada.");
  });
}

module.exports = [
  {
    name: "T-AF036-US20-04 · el formulario de creación es un único textarea y muestra el request_id al encolar",
    fn: test_creacion_textarea_unico_y_request_id,
  },
  {
    name: "T-AF036-US20-05 · una petición done deja ver el item nuevo en el backlog (epic visible)",
    fn: test_peticion_done_deja_ver_item_nuevo_en_backlog,
  },
];