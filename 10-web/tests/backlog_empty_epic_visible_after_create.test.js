/* Bug real de T-FB036-US02-04 (US-FB036-02): crear la primera Epic con
 * "+ Nueva Epic" contra el backend real dejaba un backlog con una Epic
 * SIN hijos (sin US/Tasks) que no aparecía en ningún sitio: `by_epic`
 * (`GET /backlog`) solo se poblaba desde los items hijos, así que una
 * Epic sin US/Tasks no generaba entrada → el listado seguía mostrando
 * "El backlog está vacío" y el criterio "la Epic aparece expandida tras
 * crearla" quedaba sin tarjeta que expandir.
 *
 * Este test ejerce el flujo real end-to-end: backlog vacío real (proyecto
 * aislado sin backlog sembrado) → "+ Nueva Epic" → formulario → POST
 * /backlog/epic real → refresh → tarjeta de la Epic recién creada
 * presente, activa (no oculta bajo "Terminadas" plegada) y expandida con
 * su detalle (Objetivo + "(ninguna)" User Story). Ningún endpoint se
 * mockea — la lógica de negocio es la del backend real aislado. */

"use strict";

const assert = require("assert");
const { withBackend, waitVisible } = require("./harness");

async function test_empty_epic_appears_expanded_after_create() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await waitVisible(page, ".section-tab");

    // Ir a la pestaña Backlog (rótulo real de la sección `backlog`).
    const tabs = await page.$$(".section-tab");
    let backlogTab = null;
    for (const tab of tabs) {
      const text = await page.evaluate((el) => el.textContent, tab);
      if (text.trim().startsWith("Backlog")) {
        backlogTab = tab;
        break;
      }
    }
    assert.ok(backlogTab, "No se encontró la pestaña 'Backlog' en la navegación.");
    await backlogTab.click();

    // Caso borde de la especificación UX: backlog vacío muestra el botón
    // "+ Nueva Epic" con el mensaje adaptado.
    await waitVisible(page, ".backlog-new-epic-btn");
    await page.waitForFunction(
      () => {
        const notes = Array.from(document.querySelectorAll(".section-note"));
        return notes.some((n) =>
          n.textContent.includes(
            "El backlog está vacío. Crea la primera Epic para empezar."
          )
        );
      },
      { timeout: 10000 }
    );

    // Abrir el formulario inline (T6) y rellenar los 4 campos
    // (0=id, 1=título, 2=objetivo, 3=fase, en el orden del DOM).
    await page.click(".backlog-new-epic-btn");
    await waitVisible(page, ".jobs-form");
    const inputs = await page.$$(".backlog-new-epic-input");
    assert.strictEqual(inputs.length, 4, "El formulario debe tener los 4 campos especificados.");
    await inputs[0].type("FB-900");
    await inputs[1].type("Epic de Prueba");
    await inputs[2].type("Objetivo real de prueba.");
    await inputs[3].type("Fase 1.0");

    // Pulsar "Crear" (botón del formulario, no otro botón del DOM).
    const clicked = await page.evaluate(() => {
      const form = document.querySelector(".jobs-form");
      if (!form) return false;
      const createBtn = Array.from(form.querySelectorAll("button")).find(
        (btn) => btn.textContent.trim() === "Crear"
      );
      if (!createBtn) return false;
      createBtn.click();
      return true;
    });
    assert.ok(clicked, "No se encontró el botón 'Crear' en el formulario.");

    // Criterio central: la Epic recién creada (sin hijos) aparece como
    // tarjeta activa y EXPANDIDA (`aria-expanded="true"` + detalle), con
    // su id visible — el bug la dejaba invisible bajo el mensaje de
    // backlog vacío (o bajo "Terminadas (N)" plegada sin el fix de
    // `epicIsDone`).
    await page.waitForFunction(
      () => {
        const lines = Array.from(document.querySelectorAll(".backlog-epic-line"));
        return lines.some((line) => {
          return (
            line.textContent.includes("FB-900") &&
            line.getAttribute("aria-expanded") === "true"
          );
        });
      },
      { timeout: 10000 }
    );

    // Detalle expandido con sus datos correctos (GET /backlog/FB-900 real).
    await page.waitForFunction(
      () => {
        const detail = document.querySelector(".job-detail");
        return (
          detail !== null &&
          detail.textContent.includes("Objetivo: Objetivo real de prueba.") &&
          detail.textContent.includes("User Stories:") &&
          detail.textContent.includes("(ninguna)")
        );
      },
      { timeout: 10000 }
    );

    // La Epic vacía es una tarjeta ACTIVA, nunca una "Terminada": no debe
    // quedar oculta bajo el encabezado "Terminadas (N)" plegado por
    // defecto.
    const doneHeaderVisible = await page.evaluate(() => {
      const header = document.querySelector(".backlog-done-header");
      return header !== null && header.offsetParent !== null;
    });
    assert.strictEqual(doneHeaderVisible, false, "La Epic vacía no debe agruparse bajo 'Terminadas'.");

    // El mensaje de backlog vacío ya no debe estar presente tras crear la
    // primera Epic (el backlog ya no es `empty`).
    const emptyMessageStillThere = await page.evaluate(() => {
      const notes = Array.from(document.querySelectorAll(".section-note"));
      return notes.some((n) =>
        n.textContent.includes(
          "El backlog está vacío. Crea la primera Epic para empezar."
        )
      );
    });
    assert.strictEqual(emptyMessageStillThere, false, "El mensaje de backlog vacío debe desaparecer tras crear la primera Epic.");
  });
}

module.exports = [
  {
    name: "la primera Epic creada (sin US/Tasks) aparece en el listado y queda expandida tras crearla",
    fn: test_empty_epic_appears_expanded_after_create,
  },
];