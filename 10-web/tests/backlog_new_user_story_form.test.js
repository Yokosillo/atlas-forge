/* T-AF036-US02-05 (US-AF036-02): botón "+ Nueva User Story" al final de
 * la lista de User Stories de una Epic expandida, consumiendo
 * `POST /backlog/epic/{epic_id}/us` (`T-AF036-US02-02`) — estados 5/8 y
 * Transiciones T8/T10/T11 de
 * `07-informes/AF-036/especificacion-ux-backlog.md`.
 *
 * Flujo real end-to-end contra el backend real aislado: crea una Epic
 * real primero (vía `POST /backlog/epic`, ya cerrado en `T-AF036-US02-01`),
 * la expande, pulsa "+ Nueva User Story", confirma que `epic_id` está
 * fijado y no editable, crea la User Story y confirma que aparece en el
 * detalle expandido sin recargar la página. Un segundo test cubre el
 * caso de ID duplicado (409 verbatim). Un tercero confirma que cancelar
 * no dispara ninguna llamada de red. Ningún endpoint se mockea. */

"use strict";

const assert = require("assert");
const { withBackend, waitVisible, sleep } = require("./harness");

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
      return lines.some((line) => line.textContent.includes(id) && line.getAttribute("aria-expanded") === "true");
    },
    { timeout: 10000 },
    epicId
  );
}

async function test_new_user_story_button_opens_form_with_fixed_epic_id() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await _goToBacklogTab(page);
    await _createEpicViaForm(page, "AF-910", "Epic para User Stories");

    // "+ Nueva User Story" debe estar al final de la lista de User
    // Stories, dentro del detalle ya expandido de la Epic.
    const usBtnExists = await page.evaluate(() => {
      const buttons = Array.from(document.querySelectorAll(".backlog-new-epic-btn"));
      return buttons.some((b) => b.textContent.trim() === "+ Nueva User Story");
    });
    assert.ok(usBtnExists, "No se encontró el botón '+ Nueva User Story'.");

    const clicked = await page.evaluate(() => {
      const buttons = Array.from(document.querySelectorAll(".backlog-new-epic-btn"));
      const btn = buttons.find((b) => b.textContent.trim() === "+ Nueva User Story");
      if (!btn) return false;
      btn.click();
      return true;
    });
    assert.ok(clicked);

    await page.waitForFunction(
      () => Array.from(document.querySelectorAll(".jobs-form-title")).some((t) => t.textContent === "Nueva User Story"),
      { timeout: 10000 }
    );

    // Criterio de aceptación explícito: epic_id ya fijado y NO editable
    // — mostrado como texto, no como <input>.
    const epicShownNotEditable = await page.evaluate(() => {
      const forms = Array.from(document.querySelectorAll(".jobs-form"));
      const usForm = forms.find((f) => f.querySelector(".jobs-form-title").textContent === "Nueva User Story");
      if (!usForm) return false;
      const text = usForm.textContent;
      const hasEpicIdText = text.includes("AF-910");
      const epicIsInput = Array.from(usForm.querySelectorAll("input")).some((i) => i.value === "AF-910");
      return hasEpicIdText && !epicIsInput;
    });
    assert.ok(epicShownNotEditable, "epic_id debe mostrarse fijado, sin ningún <input> editable con ese valor.");
  });
}

async function test_create_real_user_story_appears_without_full_reload() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await _goToBacklogTab(page);
    await _createEpicViaForm(page, "AF-911", "Epic con Story nueva");

    const clicked = await page.evaluate(() => {
      const buttons = Array.from(document.querySelectorAll(".backlog-new-epic-btn"));
      const btn = buttons.find((b) => b.textContent.trim() === "+ Nueva User Story");
      btn.click();
      return true;
    });
    assert.ok(clicked);
    await page.waitForFunction(
      () => Array.from(document.querySelectorAll(".jobs-form-title")).some((t) => t.textContent === "Nueva User Story"),
      { timeout: 10000 }
    );

    // Rellenar ID/Título/Objetivo/Criterios (Prioridad se deja "Sin
    // prioridad" por defecto, campo opcional).
    const fillResult = await page.evaluate(() => {
      const forms = Array.from(document.querySelectorAll(".jobs-form"));
      const usForm = forms.find((f) => f.querySelector(".jobs-form-title").textContent === "Nueva User Story");
      const inputs = usForm.querySelectorAll("input[type=text]");
      const textareas = usForm.querySelectorAll("textarea");
      if (inputs.length < 2 || textareas.length < 2) return false;
      inputs[0].value = "US-AF911-01";
      inputs[0].dispatchEvent(new Event("input", { bubbles: true }));
      inputs[1].value = "US de prueba real";
      inputs[1].dispatchEvent(new Event("input", { bubbles: true }));
      textareas[0].value = "Como usuario quiero X para lograr Y.";
      textareas[0].dispatchEvent(new Event("input", { bubbles: true }));
      textareas[1].value = "- Criterio uno.";
      textareas[1].dispatchEvent(new Event("input", { bubbles: true }));
      return true;
    });
    assert.ok(fillResult, "No se pudieron rellenar los campos del formulario de User Story.");

    const submitted = await page.evaluate(() => {
      const forms = Array.from(document.querySelectorAll(".jobs-form"));
      const usForm = forms.find((f) => f.querySelector(".jobs-form-title").textContent === "Nueva User Story");
      const createBtn = Array.from(usForm.querySelectorAll("button")).find((b) => b.textContent.trim() === "Crear");
      if (!createBtn || createBtn.disabled) return false;
      createBtn.click();
      return true;
    });
    assert.ok(submitted, "El botón 'Crear' del formulario de User Story no estaba habilitado o no se encontró.");

    // Criterio central: la Story nueva aparece en el detalle de la Epic
    // (ya expandida) sin recargar la página — mismo `document`, sin
    // `page.goto`/`page.reload` en ningún punto de este test.
    await page.waitForFunction(
      () => {
        const lines = Array.from(document.querySelectorAll(".backlog-us-line-title"));
        return lines.some((l) => l.textContent.includes("US-AF911-01"));
      },
      { timeout: 10000 }
    );

    // El formulario se cerró tras el éxito.
    const formStillOpen = await page.evaluate(() =>
      Array.from(document.querySelectorAll(".jobs-form-title")).some((t) => t.textContent === "Nueva User Story")
    );
    assert.strictEqual(formStillOpen, false, "El formulario debe cerrarse tras crear la User Story con éxito.");
  });
}

async function test_duplicate_user_story_id_shows_verbatim_error() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await _goToBacklogTab(page);
    await _createEpicViaForm(page, "AF-912", "Epic con Story duplicada");

    async function _openFormAndSubmit(id) {
      const clicked = await page.evaluate(() => {
        const buttons = Array.from(document.querySelectorAll(".backlog-new-epic-btn"));
        const btn = buttons.find((b) => b.textContent.trim() === "+ Nueva User Story");
        btn.click();
        return true;
      });
      assert.ok(clicked);
      await page.waitForFunction(
        () => Array.from(document.querySelectorAll(".jobs-form-title")).some((t) => t.textContent === "Nueva User Story"),
        { timeout: 10000 }
      );
      await page.evaluate((usId) => {
        const forms = Array.from(document.querySelectorAll(".jobs-form"));
        const usForm = forms.find((f) => f.querySelector(".jobs-form-title").textContent === "Nueva User Story");
        const inputs = usForm.querySelectorAll("input[type=text]");
        const textareas = usForm.querySelectorAll("textarea");
        inputs[0].value = usId;
        inputs[0].dispatchEvent(new Event("input", { bubbles: true }));
        inputs[1].value = "US repetida";
        inputs[1].dispatchEvent(new Event("input", { bubbles: true }));
        textareas[0].value = "Historia.";
        textareas[0].dispatchEvent(new Event("input", { bubbles: true }));
        textareas[1].value = "Criterio.";
        textareas[1].dispatchEvent(new Event("input", { bubbles: true }));
      }, id);
      await page.evaluate(() => {
        const forms = Array.from(document.querySelectorAll(".jobs-form"));
        const usForm = forms.find((f) => f.querySelector(".jobs-form-title").textContent === "Nueva User Story");
        const createBtn = Array.from(usForm.querySelectorAll("button")).find((b) => b.textContent.trim() === "Crear");
        createBtn.click();
      });
    }

    await _openFormAndSubmit("US-AF912-01");
    await page.waitForFunction(
      () => {
        const lines = Array.from(document.querySelectorAll(".backlog-us-line-title"));
        return lines.some((l) => l.textContent.includes("US-AF912-01"));
      },
      { timeout: 10000 }
    );

    // Segundo intento con el MISMO id — debe fallar con 409 verbatim, el
    // formulario permanece abierto.
    await _openFormAndSubmit("US-AF912-01");
    await page.waitForFunction(
      () => {
        const forms = Array.from(document.querySelectorAll(".jobs-form"));
        const usForm = forms.find((f) => f.querySelector(".jobs-form-title") && f.querySelector(".jobs-form-title").textContent === "Nueva User Story");
        return usForm && usForm.textContent.includes("Ya existe una User Story");
      },
      { timeout: 10000 }
    );

    const formStillOpen = await page.evaluate(() =>
      Array.from(document.querySelectorAll(".jobs-form-title")).some((t) => t.textContent === "Nueva User Story")
    );
    assert.ok(formStillOpen, "El formulario debe permanecer abierto tras un error 409.");
  });
}

async function test_cancel_new_user_story_form_makes_no_network_call() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await _goToBacklogTab(page);
    await _createEpicViaForm(page, "AF-913", "Epic para cancelar");

    let usPostSeen = false;
    page.on("request", (req) => {
      if (req.method() === "POST" && req.url().includes("/backlog/epic/AF-913/us")) {
        usPostSeen = true;
      }
    });

    const clicked = await page.evaluate(() => {
      const buttons = Array.from(document.querySelectorAll(".backlog-new-epic-btn"));
      const btn = buttons.find((b) => b.textContent.trim() === "+ Nueva User Story");
      btn.click();
      return true;
    });
    assert.ok(clicked);
    await page.waitForFunction(
      () => Array.from(document.querySelectorAll(".jobs-form-title")).some((t) => t.textContent === "Nueva User Story"),
      { timeout: 10000 }
    );

    await page.evaluate((usId) => {
      const forms = Array.from(document.querySelectorAll(".jobs-form"));
      const usForm = forms.find((f) => f.querySelector(".jobs-form-title").textContent === "Nueva User Story");
      const inputs = usForm.querySelectorAll("input[type=text]");
      inputs[0].value = usId;
      inputs[0].dispatchEvent(new Event("input", { bubbles: true }));
    }, "US-AF913-01");

    const cancelled = await page.evaluate(() => {
      const forms = Array.from(document.querySelectorAll(".jobs-form"));
      const usForm = forms.find((f) => f.querySelector(".jobs-form-title").textContent === "Nueva User Story");
      const cancelBtn = Array.from(usForm.querySelectorAll("button")).find((b) => b.textContent.trim() === "Cancelar");
      if (!cancelBtn) return false;
      cancelBtn.click();
      return true;
    });
    assert.ok(cancelled, "No se encontró el botón 'Cancelar' del formulario de User Story.");

    await sleep(500);

    const formStillOpen = await page.evaluate(() =>
      Array.from(document.querySelectorAll(".jobs-form-title")).some((t) => t.textContent === "Nueva User Story")
    );
    assert.strictEqual(formStillOpen, false, "El formulario debe cerrarse al cancelar.");
    assert.strictEqual(usPostSeen, false, "Cancelar no debe disparar ningún POST a /backlog/epic/{epic_id}/us.");
  });
}

module.exports = [
  {
    name: "\"+ Nueva User Story\" abre el formulario con epic_id fijado y no editable",
    fn: test_new_user_story_button_opens_form_with_fixed_epic_id,
  },
  {
    name: "crear una User Story real cierra el formulario y aparece en el detalle sin recargar la página",
    fn: test_create_real_user_story_appears_without_full_reload,
  },
  {
    name: "un id de User Story duplicado muestra el error 409 verbatim, formulario abierto",
    fn: test_duplicate_user_story_id_shows_verbatim_error,
  },
  {
    name: "cancelar el formulario de Nueva User Story no dispara ninguna llamada de red",
    fn: test_cancel_new_user_story_form_makes_no_network_call,
  },
];
