/* Tests web deterministas de los chips de tipo de ejecución y origen del
 * catálogo combinado (T-AF034-US01-03, US-AF034-01 criterio 2): cada
 * entrada (Script genérico/particular y Acción) muestra, SIN pulsarla, su
 * tipo de ejecución (derivado de `execution_type`) y su origen
 * ('Genérico' / 'De este proyecto').
 *
 * - cada entrada muestra su tipo como etiqueta visible (derivada de
 *   `execution_type`) y su origen ('Genérico'/'De este proyecto');
 * - retrocompat: una entrada sin `execution_type` muestra 'no clasificado'
 *   y no rompe el render (sin `.agent-error`);
 * - el chip de tipo se muestra SIEMPRE, también con una sola entrada.
 *
 * Navegador real (Chromium) contra el backend aislado; SOLO se intercambia
 * el estado de datos de `GET /scripts` (PRUEBAS.md: datos, no lógica). */

"use strict";

const assert = require("assert");
const { withBackend, waitVisible } = require("./harness");

function _interceptScripts(page, payload) {
  return page.setRequestInterception(true).then(() => {
    page.on("request", (req) => {
      // SOLO la llamada fetch de la app a `GET /scripts` (nunca la
      // navegación a `/ui/scripts`, que también termina en '/scripts').
      if (
        !req.isNavigationRequest() &&
        req.method() === "GET" &&
        req.url().endsWith("/scripts")
      ) {
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

async function _gotoScripts(page, baseUrl) {
  await page.goto(baseUrl + "/ui/scripts");
  await waitVisible(page, ".section-content");
  await waitVisible(page, ".script-card", { timeout: 10000 });
}

function _cardChips(page) {
  return page.evaluate(() =>
    Array.from(document.querySelectorAll(".script-card")).map((card) => ({
      name: card.querySelector(".script-name").textContent.trim(),
      type: card.querySelector(".script-type").textContent.trim(),
      origin: card.querySelector(".script-origin").textContent.trim(),
    }))
  );
}

// -------------------------------------------------------------------------
// Criterio: cada entrada muestra tipo + origen visibles (sin pulsar).
// -------------------------------------------------------------------------

async function test_chips_tipo_y_origen_en_cada_entrada() {
  await withBackend(async ({ page, baseUrl }) => {
    await _interceptScripts(page, [
      { id: "commit", name: "Commit de cambios", command: null, origin: "generic", description: "C.", execution_type: "script" },
      { id: "deploy01", name: "Desplegar", command: "scripts/deploy.sh", origin: "particular", description: "P.", execution_type: "script" },
      { id: "testear", name: "Testear todo", origin: "generic", description: "T.", execution_type: "script" },
      { id: "documentar", name: "Documentar todo", origin: "generic", description: "D.", execution_type: "agent_job" },
      { id: "indexar", name: "Indexar proyecto (Scribe)", origin: "generic", description: "I.", execution_type: "external_process" },
    ]);
    await _gotoScripts(page, baseUrl);

    const chips = await _cardChips(page);
    const byName = {};
    chips.forEach((c) => { byName[c.name] = c; });

    // Tipo visible en TODAS las entradas, derivado de `execution_type`.
    assert.strictEqual(byName["Commit de cambios"].type, "Script · segundos");
    assert.strictEqual(byName["Desplegar"].type, "Script · segundos");
    assert.strictEqual(byName["Testear todo"].type, "Script · segundos");
    assert.strictEqual(byName["Documentar todo"].type, "Acción · agente, minutos");
    assert.strictEqual(byName["Indexar proyecto (Scribe)"].type, "Acción · proceso externo");

    // Origen visible en cada entrada.
    assert.strictEqual(byName["Commit de cambios"].origin, "Genérico");
    assert.strictEqual(byName["Desplegar"].origin, "De este proyecto");
    assert.strictEqual(byName["Documentar todo"].origin, "Genérico");

    // Ninguna entrada se queda sin chip de tipo.
    assert.ok(
      chips.every((c) => c.type.length > 0),
      "Toda entrada debe tener chip de tipo visible."
    );
    assert.strictEqual(
      await page.evaluate(() => document.querySelectorAll(".agent-error").length),
      0,
      "No debe haber errores."
    );
  });
}

// -------------------------------------------------------------------------
// Retrocompat: sin `execution_type` el render no rompe; etiqueta por defecto.
// -------------------------------------------------------------------------

async function test_retrocompat_sin_execution_type_muestra_no_clasificado() {
  await withBackend(async ({ page, baseUrl }) => {
    await _interceptScripts(page, [
      { id: "legacy", name: "Acción legacy", origin: "generic", description: "Sin execution_type." },
    ]);
    await _gotoScripts(page, baseUrl);

    const chips = await _cardChips(page);
    assert.strictEqual(chips.length, 1);
    assert.strictEqual(chips[0].type, "no clasificado");
    assert.strictEqual(chips[0].origin, "Genérico");
    assert.strictEqual(
      await page.evaluate(() => document.querySelectorAll(".agent-error").length),
      0,
      "La entrada sin execution_type no debe romper el render."
    );
  });
}

// -------------------------------------------------------------------------
// El chip de tipo se muestra SIEMPRE, también con una sola entrada.
// -------------------------------------------------------------------------

async function test_chip_tipo_siempre_con_una_sola_entrada() {
  await withBackend(async ({ page, baseUrl }) => {
    await _interceptScripts(page, [
      { id: "testear", name: "Testear todo", origin: "generic", description: "Único.", execution_type: "script" },
    ]);
    await _gotoScripts(page, baseUrl);

    const chips = await _cardChips(page);
    assert.strictEqual(chips.length, 1);
    assert.strictEqual(chips[0].type, "Script · segundos");
  });
}

module.exports = [
  {
    name: "T-AF034-US01-03 · cada entrada muestra chips de tipo de ejecución y origen visibles sin pulsar",
    fn: test_chips_tipo_y_origen_en_cada_entrada,
  },
  {
    name: "T-AF034-US01-03 · retrocompat: sin execution_type muestra 'no clasificado' y no rompe",
    fn: test_retrocompat_sin_execution_type_muestra_no_clasificado,
  },
  {
    name: "T-AF034-US01-03 · el chip de tipo se muestra siempre, también con una sola entrada",
    fn: test_chip_tipo_siempre_con_una_sola_entrada,
  },
];