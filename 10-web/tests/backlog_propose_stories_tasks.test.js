/* T-AF036-US10-01 (US-AF036-10): exponer en la web "Proponer User
 * Stories" en el detalle de Epic → `POST /backlog/epic/{epic_id}/propose-stories`.
 *
 * DEPRECATED (T-AF008-US15-02, 2026-08-17): este fichero cubría también
 * "Aterrizar en Tasks" (US→Tasks), que llamaba SIEMPRE de forma síncrona
 * al endpoint desde el navegador. Ese botón fue sustituido por "Progresar"
 * (marca `TO_PLAN`, el Dispatcher reparte el aterrizaje al Arquitecto
 * libre) — los tests de ese flujo viejo se movieron/reescribieron en
 * `backlog_progresar_user_story.test.js`. Solo queda aquí "Proponer User
 * Stories" (Epic→US), que esta reorganización NO toca.
 *
 * Casos reales contra el backend real aislado (sin mockear lógica):
 *   1. Pipeline no aprobado ("Proponer User Stories" sobre una Epic sin
 *      alcance) → el motivo verbatim del backend aparece, nada se escribió.
 *
 * Caso de éxito (APROBADO) simulando SOLO la respuesta de red del
 * endpoint de propuesta y del refresco del detalle (mecanismo explícito
 * de `00-gobierno/DEVELOPER.md` para estados no alcanzables de forma
 * segura contra el backend real — el backend de propuesta hoy falla su
 * validación de formato contra el validador antiguo, bug preexistente
 * documentado en el informe): se verifica la lógica real del HTML/JS —
 * que el botón invoca el endpoint, termina el single-flight y refresca el
 * listado del detalle sin recargar la página.
 *
 * Ninguna de estas pruebas recarga la página: el refresco posterior al
 * éxito ocurre en el mismo `document`. */

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
  // La Epic recién creada queda expandida (`aria-expanded="true"`).
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
  // La Epic ya está expandida (creada justo antes), así que el botón
  // "+ Nueva User Story" está visible en su detalle.
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
// Caso real: pipeline no aprobado — Epic sin alcance v1 → RECHAZADO.
// ---------------------------------------------------------------------

async function test_propose_stories_rejected_shows_verbatim_reason() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await _goToBacklogTab(page);
    // Epic creada por el formulario real: solo tiene `## Objetivo`, sin
    // `## Alcance v1` — el pipeline determinista no genera ninguna US y la
    // autoauditoría la RECHAZA ("No se generó ninguna User Story.").
    await _createEpicViaForm(page, "AF-920", "Epic sin alcance");

    await page.waitForFunction(
      () =>
        Array.from(document.querySelectorAll("button")).some(
          (b) => b.textContent.trim() === "Proponer User Stories"
        ),
      { timeout: 10000 }
    );
    await _clickButtonByText(page, "Proponer User Stories");

    // Criterio 3: el motivo REAL del backend aparece verbatim
    // (`self_audit.justification`), no un mensaje genérico.
    await page.waitForFunction(
      () =>
        Array.from(document.querySelectorAll(".agent-error")).some((e) =>
          e.textContent.includes("No se generó ninguna User Story")
        ),
      { timeout: 15000 }
    );

    // Nada se escribió a disco: el detalle sigue sin ninguna User Story.
    const hasUs = await page.evaluate(() =>
      Array.from(document.querySelectorAll(".backlog-us-line-title")).some((l) =>
        l.textContent.includes("US-AF920")
      )
    );
    assert.strictEqual(hasUs, false, "No debe aparecer ninguna User Story cuando el pipeline no aprobó.");
  });
}

// ---------------------------------------------------------------------
// Éxito (APROBADO) simulado solo a nivel de red: el botón invoca el
// endpoint, termina el single-flight y refresca el listado de US de la
// Epic sin recargar la página.
// ---------------------------------------------------------------------

async function test_propose_stories_approved_refreshes_epic_list() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await _goToBacklogTab(page);
    await _createEpicViaForm(page, "AF-922", "Epic con alcance");

    const proposedStories = [
      { id: "US-AF922-01", title: "Registrar un tipo de agente nuevo", epic_id: "AF-922",
        description: "Registrar.", criteria: ["Criterio."], priority: "Alta" },
      { id: "US-AF922-02", title: "Generar User Stories", epic_id: "AF-922",
        description: "Generar.", criteria: ["Criterio."], priority: "Alta" },
    ];
    const proposeResponse = {
      epic: "AF-922",
      num_stories: 2,
      stories: proposedStories,
      notes: [],
      validation_valid: true,
      validation_errors: [],
      self_audit: { status: "APROBADO", justification: "La propuesta pasa la autoauditoría sin observaciones.", suggestions: [] },
    };

    await page.setRequestInterception(true);
    page.on("request", (req) => {
      if (req.method() === "POST" && /\/backlog\/epic\/AF-922\/propose-stories$/.test(req.url())) {
        req.respond({ status: 200, contentType: "application/json", body: JSON.stringify(proposeResponse) });
        return;
      }
      if (req.method() === "GET" && /\/backlog\/AF-922$/.test(req.url())) {
        req.respond({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            id: "AF-922",
            kind: "epic",
            objetivo: "Objetivo real de la Epic.",
            user_stories: [
              { id: "US-AF922-01", state: "READY", priority: "Alta", task_count: 0 },
              { id: "US-AF922-02", state: "READY", priority: "Alta", task_count: 0 },
            ],
          }),
        });
        return;
      }
      req.continue();
    });

    await _clickButtonByText(page, "Proponer User Stories");

    // El refresco del detalle (GET /backlog/AF-922) muestra las US
    // propuestas en el MISMO documento, sin `page.goto`/`page.reload`.
    await page.waitForFunction(
      () =>
        Array.from(document.querySelectorAll(".backlog-us-line-title")).some((l) =>
          l.textContent.includes("US-AF922-01")
        ),
      { timeout: 10000 }
    );

    const hint = await page.evaluate(() =>
      Array.from(document.querySelectorAll(".job-hint")).some((h) =>
        h.textContent.includes("2 User Stories propuestas")
      )
    );
    assert.ok(hint, "Se debe mostrar el resumen de User Stories propuestas.");
  });
}

module.exports = [
  {
    name: "Proponer User Stories sobre una Epic sin alcance muestra el motivo verbatim del backend (pipeline no aprobado, nada escrito)",
    fn: test_propose_stories_rejected_shows_verbatim_reason,
  },
  {
    name: "Proponer User Stories aprobado refresca el listado de User Stories de la Epic sin recargar la página",
    fn: test_propose_stories_approved_refreshes_epic_list,
  },
];