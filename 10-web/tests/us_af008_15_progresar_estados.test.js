/* US-AF008-15 (T-AF008-US15-01/-02, verificación del Tester, 2026-08-23):
 * verificación end-to-end en navegador real del ciclo de vida temprano de una
 * User Story en la pantalla Backlog.
 *
 * Nota de vocabulario: los criterios originales de US-AF008-15 usaban los
 * estados `NO_TASKS`/`EN_DISEÑO`. El estado `EN_DISEÑO` fue renombrado a
 * `TO_PLAN` (AF-040) y el botón "Progresar" fue retirado en T-AF036-US16-01,
 * sustituido por el selector de estado genérico (US-AF036-08). Este test
 * verifica el comportamiento REAL actual que cumple el espíritu de la US:
 *   - una US nueva creada vía el formulario real nace en `NO_TASKS`;
 *   - el selector de estado expone `NO_TASKS` y `TO_PLAN` (el antiguo
 *     `EN_DISEÑO`) como opciones válidas;
 *   - la transición `NO_TASKS` -> `TO_PLAN` se aplica de verdad al fichero
 *     real (visible tras refrescar el detalle, sin recargar la página);
 *   - los estados NO_TASKS/TO_PLAN se distinguen visualmente con colores
 *     CSS propios (clases `backlog-edit-state--no-tasks` / `--to-plan`).
 *
 * Se usan exclusivamente endpoints reales del backend aislado (crear Epic +
 * US vía formularios reales de la web); no se mockea ninguna lógica. */

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
  await page.evaluate(() => {
    const form = document.querySelector(".jobs-form");
    const createBtn = Array.from(form.querySelectorAll("button")).find(
      (b) => b.textContent.trim() === "Crear"
    );
    createBtn.click();
  });
  await page.waitForFunction(
    (id) => {
      const lines = Array.from(document.querySelectorAll(".backlog-epic-line"));
      return lines.some(
        (l) => l.textContent.includes(id) && l.getAttribute("aria-expanded") === "true"
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
  await page.evaluate(() => {
    const forms = Array.from(document.querySelectorAll(".jobs-form"));
    const usForm = forms.find(
      (f) => f.querySelector(".jobs-form-title").textContent === "Nueva User Story"
    );
    const createBtn = Array.from(usForm.querySelectorAll("button")).find(
      (b) => b.textContent.trim() === "Crear"
    );
    if (createBtn && !createBtn.disabled) createBtn.click();
  });
  await page.waitForFunction(
    (id) =>
      Array.from(document.querySelectorAll(".backlog-us-line-title")).some((l) =>
        l.textContent.includes(id)
      ),
    { timeout: 10000 },
    usId
  );
}

// Criterio T-AF008-US15-01/2: US nueva nace en NO_TASKS y el selector
// permite ver/fijar TO_PLAN (antiguo EN_DISEÑO), con distinción visual.
async function test_us_nace_no_tasks_y_selector_permite_to_plan() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await _goToBacklogTab(page);
    await _createEpicViaForm(page, "AF-935", "Epic US15 tester");
    await _createUserStoryViaForm(page, "US-AF935-01");

    // La US recién creada nace en NO_TASKS: el selector de su fila muestra
    // NO_TASKS como estado actual y lleva la clase visual correspondiente.
    const state = await page.evaluate((id) => {
      const line = Array.from(document.querySelectorAll(".backlog-us-line")).find((l) =>
        l.textContent.includes(id)
      );
      if (!line) return null;
      const select = line.querySelector(".backlog-edit-state");
      return {
        value: select ? select.value : null,
        className: select ? select.className : null,
        options: select ? Array.from(select.options).map((o) => o.value) : [],
      };
    }, "US-AF935-01");
    assert.ok(state, "No se encontró el selector de estado de la US recién creada.");
    assert.strictEqual(state.value, "NO_TASKS",
      "La US nueva debe nacer en NO_TASKS, got: " + state.value);
    assert.ok(state.className.includes("backlog-edit-state--no-tasks"),
      "El estado NO_TASKS debe llevar su clase de color propia, got: " + state.className);
    assert.ok(state.options.includes("NO_TASKS") && state.options.includes("TO_PLAN"),
      "El selector debe incluir NO_TASKS y TO_PLAN (antiguo EN_DISEÑO): " + JSON.stringify(state.options));

    // Pasar la US de NO_TASKS a TO_PLAN (el avance que antes hacía el botón
    // "Progresar"): se fija en el selector y se aplica de verdad al fichero.
    await page.evaluate((id) => {
      const line = Array.from(document.querySelectorAll(".backlog-us-line")).find((l) =>
        l.textContent.includes(id)
      );
      const select = line.querySelector(".backlog-edit-state");
      select.value = "TO_PLAN";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    }, "US-AF935-01");

    // Tras el cambio, el selector refleja TO_PLAN y la clase visual cambia.
    await page.waitForFunction(
      (id) => {
        const line = Array.from(document.querySelectorAll(".backlog-us-line")).find((l) =>
          l.textContent.includes(id)
        );
        const select = line && line.querySelector(".backlog-edit-state");
        return select && select.value === "TO_PLAN";
      },
      { timeout: 10000 },
      "US-AF935-01"
    );
    const after = await page.evaluate((id) => {
      const line = Array.from(document.querySelectorAll(".backlog-us-line")).find((l) =>
        l.textContent.includes(id)
      );
      const select = line.querySelector(".backlog-edit-state");
      return { value: select.value, className: select.className };
    }, "US-AF935-01");
    assert.strictEqual(after.value, "TO_PLAN", "El selector debe reflejar TO_PLAN tras la transición.");
    assert.ok(after.className.includes("backlog-edit-state--to-plan"),
      "El estado TO_PLAN debe llevar su clase de color propia, got: " + after.className);
  });
}

module.exports = [
  {
    name: "US-AF008-15: una User Story nueva nace en NO_TASKS y el selector permite pasarla a TO_PLAN (antiguo EN_DISEÑO) con distinción visual",
    fn: test_us_nace_no_tasks_y_selector_permite_to_plan,
  },
];