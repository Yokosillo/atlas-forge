/* T-AF036-US07-02 (US-AF036-07, 2026-08-17 · bug real con captura de
 * pantalla): los controles de acción principal del detalle de una User
 * Story ("+ Nueva Task", "Progresar"/"Aterrizar en Tasks",
 * "Marcar toda la Story para desarrollo") deben quedar alineados en una
 * SOLA fila, compartiendo un ÚNICO contenedor flex `.accion-controls`.
 *
 * Antes cada control creaba su propio `<div class="accion-controls">` y
 * se apilaban verticalmente en bloques desproporcionados.
 *
 * Se verifica sobre una US recién creada (estado NO_TASKS), donde los
 * tres controles están visibles a la vez: que comparten el mismo padre
 * `.accion-controls`, y que ese contenedor es `display:flex` con
 * `flex-wrap:wrap` (para que en ventanas estrechas los botones que no
 * quepan pasen a la siguiente línea sin desbordar — criterio 2). */

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
      (btn) => btn.textContent.trim() === "Crear"
    );
    createBtn.click();
  });
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

// ---------------------------------------------------------------------
// T-AF036-US16-02: el botón "Marcar toda la Story para desarrollo" se
// retiró de la pantalla. El encolado de las Tasks de una US se hace vía el
// selector de estado (mover la US a TO_DEVELOP). Estos tests verifican que
// el botón ya NO aparece, que el detalle sigue renderizando sin romperse y
// que la fila `.accion-controls` (con "+ Nueva Task") sigue alineada sin
// desbordar en ventanas estrechas.
// ---------------------------------------------------------------------

const REMOVED_BUTTON = "Marcar toda la Story para desarrollo";

async function _hasButton(page, text) {
  return page.evaluate((label) =>
    Array.from(document.querySelectorAll("button")).some((b) => b.textContent.trim() === label),
    text
  );
}

async function test_removed_enqueue_all_button_is_gone_and_detail_renders() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await _goToBacklogTab(page);
    await _createEpicViaForm(page, "AF-932", "Epic sin botón de encolado masivo");
    await _createUserStoryViaForm(page, "US-AF932-01");

    await _openUserStoryDetail(page, "US-AF932-01");

    await page.waitForFunction(
      () => Array.from(document.querySelectorAll("button")).some((b) => b.textContent.trim() === "+ Nueva Task"),
      { timeout: 10000 }
    );

    // Criterio 1: el botón/acción "Marcar toda la Story para desarrollo" ya no aparece.
    assert.strictEqual(
      await _hasButton(page, REMOVED_BUTTON),
      false,
      "El botón 'Marcar toda la Story para desarrollo' no debe aparecer en la pantalla Backlog."
    );

    // El resto del detalle sigue funcionando ("+ Nueva Task" presente).
    assert.ok(
      await _hasButton(page, "+ Nueva Task"),
      "El detalle de la US debe seguir mostrando '+ Nueva Task'."
    );
  });
}

async function test_us_action_row_still_flex_and_no_overflow() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await _goToBacklogTab(page);
    await _createEpicViaForm(page, "AF-933", "Epic fila sin desborde");
    await _createUserStoryViaForm(page, "US-AF933-01");

    await page.setViewport({ width: 360, height: 800 });
    await _openUserStoryDetail(page, "US-AF933-01");

    await page.waitForFunction(
      () => Array.from(document.querySelectorAll(".accion-controls")).some(
        (el) => el.querySelector("button") && el.querySelector("button").textContent.trim() === "+ Nueva Task"
      ),
      { timeout: 10000 }
    );

    const overflow = await page.evaluate(() => {
      const row = Array.from(document.querySelectorAll(".accion-controls")).find(
        (el) => el.querySelector("button") && el.querySelector("button").textContent.trim() === "+ Nueva Task"
      );
      if (!row) return { found: false };
      const rowRect = row.getBoundingClientRect();
      const viewportW = document.documentElement.clientWidth;
      const buttons = Array.from(row.querySelectorAll("button")).map((b) => b.getBoundingClientRect());
      const maxRight = Math.max(...buttons.map((r) => r.right));
      const minLeft = Math.min(...buttons.map((r) => r.left));
      return {
        found: true,
        rowRight: Math.round(rowRect.right),
        viewportW,
        buttonsOverflowRow: maxRight > rowRect.right + 1 || minLeft < rowRect.left - 1,
        rowOverflowsViewport: rowRect.right > viewportW + 1,
        display: getComputedStyle(row).display,
        flexWrap: getComputedStyle(row).flexWrap,
      };
    });

    assert.ok(overflow.found, "Debe encontrarse la fila .accion-controls del detalle.");
    assert.strictEqual(overflow.display, "flex", "El contenedor debe seguir siendo display:flex.");
    assert.strictEqual(overflow.flexWrap, "wrap", "El contenedor debe seguir usando flex-wrap:wrap.");
    assert.strictEqual(overflow.buttonsOverflowRow, false, "Ningún botón debe desbordar el contenedor.");
    assert.strictEqual(overflow.rowOverflowsViewport, false, "La fila no debe desbordar el viewport en ventana estrecha.");
  });
}

module.exports = [
  {
    name: "T-AF036-US16-02: el botón 'Marcar toda la Story para desarrollo' ya no aparece en el detalle de la US",
    fn: test_removed_enqueue_all_button_is_gone_and_detail_renders,
  },
  {
    name: "T-AF036-US16-02: la fila .accion-controls sigue alineada y sin desbordar tras retirar el botón",
    fn: test_us_action_row_still_flex_and_no_overflow,
  },
];
