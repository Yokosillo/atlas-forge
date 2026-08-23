/* T-AF008-US15-02 (US-AF008-15, 2026-08-17 · "PIPELINE OPERATIVO Y
 * RECONCILIACIÓN"): botón único "Progresar" en el detalle de una User
 * Story, que sustituye al viejo "Aterrizar en Tasks" (llamaba SIEMPRE
 * de forma síncrona al endpoint desde el navegador, sin pasar por el
 * Dispatcher — ver histórico en `backlog_propose_stories_tasks.test.js`,
 * DEPRECATED en ese punto).
 *
 * El botón cambia de acción según el `state` real de la US:
 *   - `NO_TASKS` -> "Progresar" marca `TO_PLAN` (el Dispatcher
 *     reparte el aterrizaje US→Tasks al Arquitecto libre,
 *     `run_us_landing_dispatch_cycle`).
 *   - `TO_PLAN` -> el botón queda deshabilitado con el texto
 *     "Esperando al Arquitecto." — no hay ninguna acción del usuario en
 *     este estado, es una señal para el Dispatcher, no un click.
 *
 * Caso real (sin mockear nada): una User Story recién creada vía el
 * formulario real nace en `NO_TASKS` — se verifica que el botón
 * aparece con el texto correcto, y que pulsarlo marca `TO_PLAN` de
 * verdad en el fichero real (visible en el propio detalle tras el
 * refresco, sin recargar la página).
 *
 * Aterrizaje real US→Tasks (transición `TO_PLAN` -> `READY`) es
 * responsabilidad del Dispatcher en segundo plano (`run_us_landing_dispatch_cycle`,
 * `04-src/tests/test_dispatch_queue_worker.py`) — no se ejercita aquí,
 * fuera del alcance de "verificar el botón desde la web". */

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

async function _createEpicViaForm(page, epicId, title) {
  await waitVisible(page, ".backlog-new-epic-btn");
  await page.click(".backlog-new-epic-btn");
  await waitVisible(page, ".jobs-form");
  const inputs = await page.$$(".backlog-new-epic-input");
  await inputs[0].type(epicId);
  await inputs[1].type(title);
  await inputs[2].type("Objetivo real de la Epic.");
  const clicked = await page.evaluate(() => {
    const form = document.querySelector(".jobs-form");
    const createBtn = Array.from(form.querySelectorAll("button")).find(
      (btn) => btn.textContent.trim() === "Crear"
    );
    createBtn.click();
    return true;
  });
  assert.ok(clicked);
  await page.waitForFunction(
    (id) => {
      const lines = Array.from(document.querySelectorAll(".backlog-epic-line"));
      return lines.some(
        (line) => line.textContent.includes(id) && line.getAttribute("aria-expanded") === "true"
      );
    },
    { timeout: 10000 },
    epicId
  );
}

async function _createUserStoryViaForm(page, usId) {
  await page.waitForFunction(
    () =>
      Array.from(document.querySelectorAll(".backlog-new-epic-btn")).some(
        (b) => b.textContent.trim() === "+ Nueva User Story"
      ),
    { timeout: 10000 }
  );
  await page.evaluate(() => {
    const btn = Array.from(document.querySelectorAll(".backlog-new-epic-btn")).find(
      (b) => b.textContent.trim() === "+ Nueva User Story"
    );
    btn.click();
  });
  await page.waitForFunction(
    () =>
      Array.from(document.querySelectorAll(".jobs-form-title")).some(
        (t) => t.textContent === "Nueva User Story"
      ),
    { timeout: 10000 }
  );
  await page.evaluate((id) => {
    const forms = Array.from(document.querySelectorAll(".jobs-form"));
    const usForm = forms.find(
      (f) => f.querySelector(".jobs-form-title").textContent === "Nueva User Story"
    );
    const inputs = usForm.querySelectorAll("input[type=text]");
    const textareas = usForm.querySelectorAll("textarea");
    inputs[0].value = id;
    inputs[0].dispatchEvent(new Event("input", { bubbles: true }));
    inputs[1].value = "US de prueba";
    inputs[1].dispatchEvent(new Event("input", { bubbles: true }));
    textareas[0].value = "Como usuario quiero X para lograr Y.";
    textareas[0].dispatchEvent(new Event("input", { bubbles: true }));
    textareas[1].value = "- Criterio uno.";
    textareas[1].dispatchEvent(new Event("input", { bubbles: true }));
  }, usId);
  const submitted = await page.evaluate(() => {
    const forms = Array.from(document.querySelectorAll(".jobs-form"));
    const usForm = forms.find(
      (f) => f.querySelector(".jobs-form-title").textContent === "Nueva User Story"
    );
    const createBtn = Array.from(usForm.querySelectorAll("button")).find(
      (b) => b.textContent.trim() === "Crear"
    );
    if (!createBtn || createBtn.disabled) return false;
    createBtn.click();
    return true;
  });
  assert.ok(submitted, "No se pudo enviar el formulario de Nueva User Story.");
  await page.waitForFunction(
    (id) =>
      Array.from(document.querySelectorAll(".backlog-us-line-title")).some((l) =>
        l.textContent.includes(id)
      ),
    { timeout: 10000 },
    usId
  );
}

async function _openUserStoryDetail(page, usId) {
  const clicked = await page.evaluate((id) => {
    const line = Array.from(document.querySelectorAll(".backlog-us-line")).find((l) =>
      l.textContent.includes(id)
    );
    if (!line) return false;
    line.click();
    return true;
  }, usId);
  assert.ok(clicked, `No se encontró la línea de la User Story '${usId}' para abrir su detalle.`);
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
// Caso real: US recién creada nace en NO_TASKS, botón "Progresar"
// visible, click la marca TO_PLAN de verdad (sin recargar la página).
// ---------------------------------------------------------------------

async function test_progresar_button_is_removed_and_selector_still_works() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await _goToBacklogTab(page);
    await _createEpicViaForm(page, "AF-930", "Epic para progresar");
    await _createUserStoryViaForm(page, "US-AF930-01");

    await _openUserStoryDetail(page, "US-AF930-01");

    // T-AF036-US16-01: el botón "Progresar" se eliminó de la pantalla
    // Backlog — no debe existir en el detalle de la User Story (el avance
    // se controla con el estado TO_DEVELOP y la derivación).
    await page.waitForFunction(
      () =>
        Array.from(document.querySelectorAll(".accion-controls button")).some(
          (b) => b.textContent.trim() === "+ Nueva Task"
        ),
      { timeout: 10000 }
    );
    const hasProgresarBtn = await page.evaluate(() =>
      Array.from(document.querySelectorAll("button")).some(
        (b) => b.textContent.trim() === "Progresar"
      )
    );
    assert.strictEqual(
      hasProgresarBtn, false,
      "El botón 'Progresar' no debe existir en la pantalla Backlog (T-AF036-US16-01)."
    );

    // El selector de estado genérico sigue permitiendo mover la US (p. ej.
    // a TO_PLAN) — el avance no depende del botón eliminado.
    const stateOptions = await page.evaluate((id) => {
      const line = Array.from(document.querySelectorAll(".backlog-us-line")).find((l) =>
        l.textContent.includes(id)
      );
      const select = line ? line.querySelector(".backlog-edit-state") : null;
      return select ? Array.from(select.options).map((o) => o.value) : null;
    }, "US-AF930-01");
    assert.ok(stateOptions && stateOptions.includes("TO_PLAN"),
      "El selector de estado debe seguir incluyendo 'TO_PLAN'.");
  });
}

// ---------------------------------------------------------------------
// El selector de estado genérico (US-AF036-08) también permite ver/fijar
// NO_TASKS y TO_PLAN como cualquier otro estado — confirma que ambos
// valores están en el conjunto editable, sin depender solo del botón.
// ---------------------------------------------------------------------

async function test_state_selector_includes_sin_tareas_and_to_plan_options() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await _goToBacklogTab(page);
    await _createEpicViaForm(page, "AF-931", "Epic con selector");
    await _createUserStoryViaForm(page, "US-AF931-01");

    const optionValues = await page.evaluate((id) => {
      const line = Array.from(document.querySelectorAll(".backlog-us-line")).find((l) =>
        l.textContent.includes(id)
      );
      if (!line) return null;
      const select = line.querySelector(".backlog-edit-state");
      if (!select) return null;
      return Array.from(select.options).map((o) => o.value);
    }, "US-AF931-01");

    assert.ok(optionValues, "No se encontró el selector de estado de la User Story.");
    assert.ok(optionValues.includes("NO_TASKS"), "El selector debe incluir 'NO_TASKS'.");
    assert.ok(optionValues.includes("TO_PLAN"), "El selector debe incluir 'TO_PLAN'.");
  });
}

module.exports = [
  {
    name: "El botón 'Progresar' fue eliminado (T-AF036-US16-01) y el selector de estado sigue permitiendo mover la US",
    fn: test_progresar_button_is_removed_and_selector_still_works,
  },
  {
    name: "El selector de estado genérico incluye NO_TASKS y TO_PLAN como opciones",
    fn: test_state_selector_includes_sin_tareas_and_to_plan_options,
  },
];
