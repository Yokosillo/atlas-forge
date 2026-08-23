/* T-AF036-US03-03 (US-AF036-03, "validar el flujo completo"): verificación
 * del flujo real completo de "Aterrizar Epic en User Stories" desde la web
 * — botón "Proponer User Stories" → `POST /backlog/epic/{epic_id}/propose-
 * stories` → módulo de dominio `plan_epic_landing` (T-AF036-US03-01/02) →
 * escritura a disco → refresco del detalle sin recargar la página.
 *
 * A diferencia del test de éxito de `backlog_propose_stories_tasks.test.js`
 * (que simula la respuesta de red), AQUÍ NO se mockea la respuesta: el
 * backend real genera y escribe la User Story, y el navegador la ve aparecer
 * en el detalle. La única intercepción de red es para SOSTENER la petición
 * unos instantes y poder verificar de forma determinista los criterios 2
 * (botón deshabilitado con "Proponiendo User Stories…" en vuelo) y 5
 * (single-flight: un segundo clic en vuelo NO dispara una segunda
 * generación), y después se deja pasar (continue) contra el backend real.
 *
 * Criterios de la US cubiertos: 1 (botón visible en detalle de Epic),
 * 2 (in-flight deshabilitado), 3 (lista de US generadas + refresco del
 * detalle), 4 (motivo verbatim en fallo, cubierto en el caso sin alcance),
 * 5 (single-flight). */

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

async function _seedEpicWithAlcance(page, baseUrl, projectPath, epicId) {
  await page.evaluate(
    async ({ epicId }) => {
      await fetch("/backlog/epic", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: epicId, title: "Epic con alcance real", objetivo: "Objetivo real." }),
      });
    },
    { epicId }
  );

  // El endpoint de creación no escribe la sección de alcance — se añade
  // al fichero real de la Epic directamente.
  const epicsDir = path.join(projectPath, "02-backlog", "epics");
  const filename = fs.readdirSync(epicsDir).find((name) => name.startsWith(epicId + "-"));
  assert.ok(filename, `No se encontró el fichero de la Epic ${epicId} en ${epicsDir}`);
  const epicPath = path.join(epicsDir, filename);
  const original = fs.readFileSync(epicPath, "utf-8");
  fs.writeFileSync(
    epicPath,
    original + "\n## Alcance v1 (mínimo)\n\n- Crear la cola de mensajes interna.\n"
  );
}

async function _openEpicDetail(page, epicId) {
  await waitVisible(page, ".backlog-epic-line");
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

async function test_real_approved_flow_with_inflight_and_single_flight() {
  await withBackend(async ({ page, baseUrl, projectPath }) => {
    assert.ok(projectPath, "El backend aislado debe exponer la ruta real del proyecto activo.");

    await page.goto(baseUrl + "/ui/");
    await _seedEpicWithAlcance(page, baseUrl, projectPath, "AF-951");

    await page.reload();
    await _goToBacklogTab(page);
    await _openEpicDetail(page, "AF-951");

    // Criterio 1: botón visible en el detalle de la Epic expandida.
    await waitVisible(page, "button");

    // Intercepción: sostener la petición real para observar el estado en
    // vuelo, sin mockear la respuesta.
    await page.setRequestInterception(true);
    let proposeRequests = 0;
    let heldRequest = null;
    let releaseHeld = null;
    const releasePromise = new Promise((resolve) => { releaseHeld = resolve; });
    page.on("request", (req) => {
      if (req.method() === "POST" && /\/backlog\/epic\/AF-951\/propose-stories$/.test(req.url())) {
        proposeRequests += 1;
        heldRequest = req;
        releasePromise.then(() => req.continue());
        return;
      }
      req.continue();
    });

    await _clickButtonByText(page, "Proponer User Stories");

    // Criterio 2: en vuelo, el botón queda deshabilitado con el texto
    // "Proponiendo User Stories…".
    const inflight = await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll("button")).find((b) =>
        b.textContent.trim() === "Proponiendo User Stories…"
      );
      return btn ? { disabled: btn.disabled } : null;
    });
    assert.ok(inflight, "En vuelo debe mostrarse el botón 'Proponiendo User Stories…'.");
    assert.strictEqual(inflight.disabled, true, "El botón debe estar deshabilitado en vuelo.");

    // Criterio 5: un segundo clic en vuelo no dispara una segunda petición.
    await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll("button")).find((b) =>
        b.textContent.includes("Proponiendo")
      );
      if (btn) btn.click();
    });
    assert.strictEqual(
      proposeRequests, 1,
      "El single-flight debe impedir una segunda generación (1 sola petición)."
    );

    // Liberar la petición -> el backend real genera, valida y escribe la US.
    // La intercepción permanece activa (el handler sigue haciendo
    // `req.continue()` para el resto de peticiones, incluido el refresco
    // del detalle que sigue a la generación).
    assert.ok(heldRequest, "La petición real debió quedar retenida por la intercepción.");
    releaseHeld();

    // Criterio 3: resumen de la US generada + la US real aparece en el
    // detalle refrescado sin recargar la página.
    await page.waitForFunction(
      () =>
        Array.from(document.querySelectorAll(".backlog-us-line-title")).some((l) =>
          l.textContent.includes("US-AF951-01")
        ),
      { timeout: 15000 }
    );

    const hint = await page.evaluate(() =>
      Array.from(document.querySelectorAll(".job-hint")).some((h) =>
        h.textContent.includes("User Story propuesta")
      )
    );
    assert.ok(hint, "Se debe mostrar el resumen de User Stories propuestas.");

    // Y el fichero real existe en disco (el flujo completo escribió la US).
    const storiesDir = path.join(projectPath, "02-backlog", "user-stories");
    const written = fs.readdirSync(storiesDir).filter((name) => name.startsWith("US-AF951-01"));
    assert.strictEqual(written.length, 1, "El flujo real debe escribir la User Story a disco.");
  });
}

module.exports = [
  {
    name: "flujo real completo: Proponer User Stories con backend real genera/escribe la US, refresca el detalle, con in-flight y single-flight",
    fn: test_real_approved_flow_with_inflight_and_single_flight,
  },
];