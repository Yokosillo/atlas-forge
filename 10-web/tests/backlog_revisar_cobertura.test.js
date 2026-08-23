/* T-AF036-US05-01 (US-AF036-05): botón "Revisar cobertura" en el detalle
 * expandido de una Epic — llama `GET /backlog/epic/{epic_id}/coverage`
 * (detector determinista-aproximado del alcance v1 declarado frente a las
 * User Stories/Tasks reales) y muestra el texto crudo del alcance + los
 * huecos detectados, SIEMPRE con el aviso de que es una detección
 * aproximada, no una garantía formal (criterio 1).
 *
 * Sobre una Epic sin la sección "## Alcance v1 (mínimo)" muestra el
 * mensaje explícito "no se puede calcular cobertura", nunca un resultado
 * vacío ambiguo (criterio 2).
 *
 * Backlog sembrado vía HTTP (Epic + US reales, T-AF036-US02-01/02); la
 * sección de alcance se añade reescribiendo el fichero real de la Epic
 * con `fs` (no hay endpoint que edite un fichero de Epic existente — el
 * caso de una Epic con alcance no se puede crear solo vía HTTP). */

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
  throw new Error("No se encontró la pestaña 'Backlog' en la navegación.");
}

async function _seedEpic(page, epicId, title) {
  await page.evaluate(
    async ({ epicId, title }) => {
      await fetch("/backlog/epic", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: epicId, title: title, objetivo: "Objetivo real." }),
      });
    },
    { epicId, title }
  );
}

async function _appendAlcanceToEpicFile(projectPath, epicId, alcanceMarkdown) {
  const epicsDir = path.join(projectPath, "02-backlog", "epics");
  const filename = fs.readdirSync(epicsDir).find((name) => name.startsWith(epicId + "-"));
  assert.ok(filename, `No se encontró el fichero de la Epic ${epicId} en ${epicsDir}`);
  const epicPath = path.join(epicsDir, filename);
  const original = fs.readFileSync(epicPath, "utf-8");
  fs.writeFileSync(epicPath, original + "\n" + alcanceMarkdown + "\n");
}

async function _openEpicDetail(page, epicId) {
  const clicked = await page.evaluate((id) => {
    const line = Array.from(document.querySelectorAll(".backlog-epic-line")).find((l) =>
      l.textContent.includes(id)
    );
    if (!line) return false;
    line.click();
    return true;
  }, epicId);
  assert.ok(clicked, `No se encontró la línea de la Epic '${epicId}' para abrir su detalle.`);
}

async function _clickButtonByText(page, text) {
  const clicked = await page.evaluate((label) => {
    const btn = Array.from(document.querySelectorAll("button")).find(
      (b) => b.textContent.trim() === label
    );
    if (!btn || btn.disabled) return false;
    btn.click();
    return true;
  }, text);
  assert.ok(clicked, "No se encontró o estaba deshabilitado el botón '" + text + "'.");
}

// ---------------------------------------------------------------------
// Criterio 1: con alcance declarado, muestra texto crudo + huecos + aviso
// de aproximación.
// ---------------------------------------------------------------------

async function test_coverage_with_alcance_shows_text_gaps_and_approximate_notice() {
  await withBackend(async ({ page, baseUrl, projectPath }) => {
    assert.ok(projectPath, "El backend aislado debe exponer la ruta real del proyecto activo.");

    await page.goto(baseUrl + "/ui/");
    await _seedEpic(page, "AF-941", "Epic con alcance");

    // Una US real bajo la Epic — el punto "US-AF941-01" del alcance queda
    // cubierto por id real.
    await page.evaluate(async () => {
      await fetch("/backlog/epic/AF-941/us", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          id: "US-AF941-01", title: "Gestionar workspaces", objetivo: "H.",
          criterios_aceptacion: "C.",
        }),
      });
    });

    // Añadir la sección de alcance al fichero real de la Epic: un punto
    // cubierto (US real) y otro que apunta a una US inexistente (hueco).
    _appendAlcanceToEpicFile(
      projectPath,
      "AF-941",
      "## Alcance v1 (mínimo)\n\n"
        + "- **US-AF941-01**: gestionar los workspaces desde la interfaz.\n"
        + "- **US-AF941-99**: capacidad que nadie ha aterrizado todavia.\n"
    );

    await page.reload();
    await _goToBacklogTab(page);
    await _openEpicDetail(page, "AF-941");

    await waitVisible(page, "button");
    await _clickButtonByText(page, "Revisar cobertura");

    // El texto crudo del alcance aparece (ambos puntos) y el aviso de
    // aproximación está presente.
    await page.waitForFunction(
      () => document.querySelector(".accion-result") !== null,
      { timeout: 10000 }
    );
    const resultText = await page.evaluate(() =>
      document.querySelector(".accion-result").textContent
    );
    assert.ok(resultText.includes("US-AF941-01"), "Debe mostrarse el texto crudo con US-AF941-01.");
    assert.ok(resultText.includes("US-AF941-99"), "Debe mostrarse el texto crudo con US-AF941-99.");
    assert.ok(resultText.includes("aproximada"), "Debe incluir el aviso de detección aproximada.");

    // El hueco (US inexistente) aparece en la lista de huecos.
    const gapTexts = await page.evaluate(() =>
      Array.from(document.querySelectorAll(".accion-result-gaps li")).map((li) => li.textContent)
    );
    assert.ok(
      gapTexts.some((g) => g.startsWith("US-AF941-99")),
      `Esperaba el hueco US-AF941-99 en la lista, encontrados: ${JSON.stringify(gapTexts)}`
    );
    assert.ok(
      !gapTexts.some((g) => g.startsWith("US-AF941-01")),
      "El punto cubierto por id real no debe aparecer como hueco."
    );
  });
}

// ---------------------------------------------------------------------
// Criterio 2 de la US (single-flight): mientras la petición de cobertura
// está en vuelo, el botón se deshabilita y muestra "Revisando cobertura…".
// Se intercepta la respuesta GET /coverage retrasándola para poder
// observar deterministamente el estado en vuelo (mismo patrón de
// interceptación que backlog_editor_fase.test.js).
// ---------------------------------------------------------------------

async function test_coverage_single_flight_disables_button_while_in_flight() {
  await withBackend(async ({ page, baseUrl, projectPath }) => {
    assert.ok(projectPath, "El backend aislado debe exponer la ruta real del proyecto activo.");

    await page.goto(baseUrl + "/ui/");
    await _seedEpic(page, "AF-943", "Epic single-flight");
    _appendAlcanceToEpicFile(
      projectPath,
      "AF-943",
      "## Alcance v1 (mínimo)\n\n- **US-AF943-01**: capacidad cubierta.\n"
    );

    await page.reload();
    await _goToBacklogTab(page);
    await _openEpicDetail(page, "AF-943");
    await waitVisible(page, "button");

    // Retrasar la respuesta de cobertura 1500ms para observar el estado en
    // vuelo. Solo se intercepta el GET /coverage; el resto fluye normal.
    await page.setRequestInterception(true);
    let coverageRequested = false;
    page.on("request", (req) => {
      if (req.url().includes("/coverage")) {
        coverageRequested = true;
        setTimeout(() => {
          req.respond({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({
              epic_id: "AF-943",
              declared_alcance: "## Alcance v1 (mínimo)\n- **US-AF943-01**: capacidad cubierta.",
              points: ["US-AF943-01: capacidad cubierta."],
              gaps: [],
              approximate: true,
              message: "Detección aproximada de cobertura, no una garantía formal.",
            }),
          });
        }, 1500);
      } else {
        req.continue();
      }
    });

    await _clickButtonByText(page, "Revisar cobertura");

    // Mientras la petición está en vuelo, el botón muestra "Revisando
    // cobertura…" y está deshabilitado.
    await page.waitForFunction(
      () => {
        const btn = Array.from(document.querySelectorAll("button")).find(
          (b) => b.textContent.trim().startsWith("Revisando cobertura")
        );
        return btn && btn.disabled;
      },
      { timeout: 5000 }
    );
    assert.ok(
      coverageRequested,
      "La petición GET /coverage debió haberse lanzado."
    );

    // Al resolverse, el resultado se pinta (fin del estado en vuelo).
    await page.waitForFunction(
      () => document.querySelector(".accion-result") !== null,
      { timeout: 8000 }
    );
    const resultText = await page.evaluate(() =>
      document.querySelector(".accion-result").textContent
    );
    assert.ok(resultText.includes("US-AF943-01"), "Debe mostrarse el texto crudo del alcance.");
  });
}

// ---------------------------------------------------------------------
// Criterio 2: sin la sección "Alcance v1", mensaje explícito de "no se
// puede calcular cobertura", no un resultado vacío ambiguo.
// ---------------------------------------------------------------------

async function test_coverage_without_alcance_shows_explicit_message() {
  await withBackend(async ({ page, baseUrl, projectPath }) => {
    assert.ok(projectPath, "El backend aislado debe exponer la ruta real del proyecto activo.");

    await page.goto(baseUrl + "/ui/");
    await _seedEpic(page, "AF-942", "Epic sin alcance");

    await page.reload();
    await _goToBacklogTab(page);
    await _openEpicDetail(page, "AF-942");

    await waitVisible(page, "button");
    await _clickButtonByText(page, "Revisar cobertura");

    await page.waitForFunction(
      () => document.querySelector(".accion-result") !== null,
      { timeout: 10000 }
    );
    const resultText = await page.evaluate(() =>
      document.querySelector(".accion-result").textContent
    );
    assert.ok(
      resultText.includes("no se puede calcular cobertura"),
      "Debe mostrarse el mensaje explícito de que no se puede calcular cobertura."
    );
  });
}

module.exports = [
  {
    name: "'Revisar cobertura' con alcance declarado muestra texto crudo + huecos + aviso de aproximación",
    fn: test_coverage_with_alcance_shows_text_gaps_and_approximate_notice,
  },
  {
    name: "'Revisar cobertura' sin alcance declarado muestra el mensaje explícito de que no se puede calcular cobertura",
    fn: test_coverage_without_alcance_shows_explicit_message,
  },
  {
    name: "'Revisar cobertura' single-flight: botón deshabilitado y 'Revisando cobertura…' mientras la petición está en vuelo",
    fn: test_coverage_single_flight_disables_button_while_in_flight,
  },
];
