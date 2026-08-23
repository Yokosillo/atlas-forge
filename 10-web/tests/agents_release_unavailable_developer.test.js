/* T-AF024-US11-16 (2026-08-19): botón "Liberar" y aviso de conexión
 * perdida para un Developer `unavailable` (proceso caído fuera de atlas_forge).
 *
 * Se intercepta SOLO `GET /agents` (devolver un agente `unavailable` real no
 * es alcanzable de forma segura contra el backend sin matar un runtime real;
 * mecanismo explícito de `00-gobierno/DEVELOPER.md`) y `POST
 * /agents/{id}/release` (no se invoca un runtime real). La lógica de la UI
 * bajo prueba es la real de `app.js`.
 *
 * Criterios cubiertos:
 *  1. Un Developer `unavailable` muestra "caído · conexión perdida" como
 *     estado y el aviso en el detalle, no el texto crudo "unavailable".
 *  2. El botón de esa fila es "Liberar"; pulsarlo llama a `releaseAgent`
 *     (`POST /agents/{id}/release`) y tras éxito la fila queda lanzable
 *     (sintética "stopped") con su nombre original.
 *  3. Tras liberar, el botón vuelve a ser "Lanzar" sin recargar la página.
 *  4. Si `POST /agents/{id}/release` falla, se muestra el error del backend
 *     sin romper la fila (sigue "Liberar" + estado unavailable). */

"use strict";

const assert = require("assert");
const { withBackend, waitVisible } = require("./harness");

const UNAVAILABLE_1 = {
  id: "dev-caido-1", role: "developer", name: "Developer-1", status: "unavailable",
  runtime_id: "opencode", model: null, last_command_at: null, session_name: "developer-1-proj",
};

async function _goToAgentsTab(page) {
  await waitVisible(page, ".section-tab");
  const clicked = await page.evaluate(() => {
    const tabs = Array.from(document.querySelectorAll(".section-tab"));
    const target = tabs.find((el) => el.textContent.trim().startsWith("Agentes"));
    if (!target) return false;
    target.click();
    return true;
  });
  if (!clicked) throw new Error("No se encontró la pestaña 'Agentes' en la navegación.");
}

async function _row(page, name) {
  return page.evaluate((rowName) => {
    const cards = Array.from(document.querySelectorAll(".agent-card"));
    const target = cards.find((card) => {
      const nameEl = card.querySelector(".agent-name");
      return nameEl && nameEl.textContent === rowName;
    });
    if (!target) return null;
    return {
      statusText: target.querySelector(".status-text")
        ? target.querySelector(".status-text").textContent : null,
      noteText: target.querySelector(".agent-unavailable-note")
        ? target.querySelector(".agent-unavailable-note").textContent : null,
      buttons: Array.from(target.querySelectorAll("button")).map((b) => b.textContent.trim()),
    };
  }, name);
}

async function _clickButtonInRow(page, name, label) {
  return page.evaluate((rowName, btnLabel) => {
    const cards = Array.from(document.querySelectorAll(".agent-card"));
    const target = cards.find((card) => {
      const nameEl = card.querySelector(".agent-name");
      return nameEl && nameEl.textContent === rowName;
    });
    if (!target) return false;
    const btn = Array.from(target.querySelectorAll("button")).find(
      (b) => b.textContent.trim() === btnLabel
    );
    if (!btn || btn.disabled) return false;
    btn.click();
    return true;
  }, name, label);
}

async function test_unavailable_developer_shows_release_button_and_notice() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.setRequestInterception(true);
    page.on("request", (req) => {
      if (req.method() === "GET" && /\/agents$/.test(req.url())) {
        req.respond({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([UNAVAILABLE_1]),
        });
        return;
      }
      req.continue();
    });

    await page.goto(baseUrl + "/ui/");
    await _goToAgentsTab(page);

    await page.waitForFunction(
      () => Array.from(document.querySelectorAll(".agent-name")).some(
        (el) => el.textContent === "Developer-1"
      ),
      { timeout: 10000 }
    );

    const row = await _row(page, "Developer-1");
    assert.ok(row, "Debe existir la fila Developer-1.");

    // Criterio 1: estado legible + aviso, NO el valor crudo "unavailable".
    assert.ok(
      row.statusText && row.statusText.indexOf("caído · conexión perdida") !== -1,
      "El estado debe mostrar 'caído · conexión perdida': " + JSON.stringify(row.statusText)
    );
    assert.ok(row.statusText.indexOf("unavailable") === -1,
      "El estado no debe mostrar el valor crudo 'unavailable': " + JSON.stringify(row.statusText));
    assert.ok(
      row.noteText && row.noteText.indexOf("se ha perdido la conexión") !== -1,
      "El detalle debe incluir el aviso de conexión perdida: " + JSON.stringify(row.noteText)
    );

    // Criterio 2: el botón es "Liberar", no "Lanzar".
    assert.ok(row.buttons.indexOf("Liberar") !== -1,
      "La fila debe ofrecer el botón 'Liberar': " + JSON.stringify(row.buttons));
    assert.ok(row.buttons.indexOf("Lanzar") === -1,
      "Un Developer unavailable NO debe ofrecer 'Lanzar': " + JSON.stringify(row.buttons));
  });
}

async function test_releasing_unavailable_developer_restores_lanzar_row() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.setRequestInterception(true);
    let released = false;
    let releaseRequestSeen = false;
    page.on("request", (req) => {
      if (req.method() === "GET" && /\/agents$/.test(req.url())) {
        req.respond({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(released ? [] : [UNAVAILABLE_1]),
        });
        return;
      }
      if (req.method() === "POST" && /\/agents\/.+\/release$/.test(req.url())) {
        releaseRequestSeen = true;
        released = true;
        req.respond({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(UNAVAILABLE_1),
        });
        return;
      }
      req.continue();
    });

    await page.goto(baseUrl + "/ui/");
    await _goToAgentsTab(page);

    await page.waitForFunction(
      () => Array.from(document.querySelectorAll(".agent-name")).some(
        (el) => el.textContent === "Developer-1"
      ),
      { timeout: 10000 }
    );

    let row = await _row(page, "Developer-1");
    assert.ok(row && row.buttons.indexOf("Liberar") !== -1,
      "Antes de liberar la fila debe tener el botón 'Liberar'.");

    const clicked = await _clickButtonInRow(page, "Developer-1", "Liberar");
    assert.ok(clicked, "No se pudo pulsar 'Liberar' en la fila Developer-1.");

    // Criterio 2: se llama al endpoint de release.
    await new Promise((r) => setTimeout(r, 1200));
    assert.ok(releaseRequestSeen, "Debe haberse llamado a POST /agents/{id}/release.");

    // Criterio 3: tras liberar, la fila queda sintética "stopped" con su
    // nombre original y vuelve a mostrar "Lanzar" (sin recargar la página).
    await page.waitForFunction(
      () => {
        const cards = Array.from(document.querySelectorAll(".agent-card"));
        const target = cards.find((card) => {
          const nameEl = card.querySelector(".agent-name");
          return nameEl && nameEl.textContent === "Developer-1";
        });
        if (!target) return false;
        return Array.from(target.querySelectorAll("button"))
          .some((b) => b.textContent.trim() === "Lanzar");
      },
      { timeout: 10000 }
    );

    row = await _row(page, "Developer-1");
    assert.ok(row, "La fila Developer-1 debe seguir existiendo tras liberar.");
    assert.ok(row.buttons.indexOf("Lanzar") !== -1,
      "Tras liberar, el botón debe volver a ser 'Lanzar': " + JSON.stringify(row.buttons));
    assert.ok(row.buttons.indexOf("Liberar") === -1,
      "Tras liberar no debe quedar el botón 'Liberar': " + JSON.stringify(row.buttons));
    // Ya no es `unavailable` (sintética "stopped"), así que no hay aviso.
    assert.ok(row.statusText && row.statusText.indexOf("detenido") !== -1,
      "Tras liberar, la fila debe mostrarse como sintética 'detenido': " + JSON.stringify(row.statusText));
  });
}

async function test_release_failure_shows_backend_error_without_breaking_row() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.setRequestInterception(true);
    page.on("request", (req) => {
      if (req.method() === "GET" && /\/agents$/.test(req.url())) {
        req.respond({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([UNAVAILABLE_1]),
        });
        return;
      }
      if (req.method() === "POST" && /\/agents\/.+\/release$/.test(req.url())) {
        req.respond({
          status: 400,
          contentType: "application/json",
          body: JSON.stringify({ detail: "El agente 'Developer-1' sigue activo." }),
        });
        return;
      }
      req.continue();
    });

    await page.goto(baseUrl + "/ui/");
    await _goToAgentsTab(page);

    await page.waitForFunction(
      () => Array.from(document.querySelectorAll(".agent-name")).some(
        (el) => el.textContent === "Developer-1"
      ),
      { timeout: 10000 }
    );

    const clicked = await _clickButtonInRow(page, "Developer-1", "Liberar");
    assert.ok(clicked, "No se pudo pulsar 'Liberar'.");

    // Criterio 4: se muestra el error del backend sin romper la fila.
    await page.waitForFunction(
      () => document.querySelector(".agent-message") !== null,
      { timeout: 10000 }
    );
    const msg = await page.evaluate(
      () => document.querySelector(".agent-message").textContent
    );
    assert.ok(
      msg && msg.indexOf("sigue activo") !== -1,
      "El error del backend debe mostrarse: " + JSON.stringify(msg)
    );

    const row = await _row(page, "Developer-1");
    assert.ok(row && row.buttons.indexOf("Liberar") !== -1,
      "Tras el fallo, la fila debe seguir con el botón 'Liberar': " + JSON.stringify(row));
    assert.ok(row.statusText && row.statusText.indexOf("caído · conexión perdida") !== -1,
      "Tras el fallo, el estado debe seguir 'caído · conexión perdida': " + JSON.stringify(row.statusText));
  });
}

module.exports = [
  {
    name: "Developer unavailable: muestra 'caído · conexión perdida', aviso y botón 'Liberar' (no 'Lanzar')",
    fn: test_unavailable_developer_shows_release_button_and_notice,
  },
  {
    name: "Liberar un Developer unavailable llama a releaseAgent y la fila vuelve a 'Lanzar' (sintética) sin recargar",
    fn: test_releasing_unavailable_developer_restores_lanzar_row,
  },
  {
    name: "Si release falla, se muestra el error del backend sin romper la fila",
    fn: test_release_failure_shows_backend_error_without_breaking_row,
  },
];
