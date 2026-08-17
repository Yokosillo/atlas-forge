/* Regresión de T-FB024-US11-07 (US-FB024-11): con el editor inline de
 * "Cambiar modelo" abierto, elegir una opción distinta al default y
 * dejar pasar un ciclo completo de polling (`POLL_INTERVAL_MILLIS`,
 * 3000ms en `app.js`) no debe resetear la selección visible al default
 * del backend — antes del fix, cada tick de `startRolesPolling`
 * reconstruía el `<select>` comparando solo contra `defaultModel`,
 * descartando en silencio lo que el usuario acababa de elegir sin haber
 * pulsado "Guardar modelo" todavía. Ver
 * `02-backlog/tasks/T-FB024-US11-07-polling-resetea-editor-modelo-abierto.md`.
 *
 * Esta es la propia verificación en navegador real que ese informe
 * documentaba como pendiente ("este entorno no tiene navegador
 * disponible... recomiendo confirmar visualmente") — con esta suite ya
 * no depende de que alguien lo haga a mano cada vez. */

"use strict";

const assert = require("assert");
const { withBackend, waitVisible, sleep } = require("./harness");

const POLL_INTERVAL_MILLIS = 3000;

async function test_selection_survives_a_full_polling_cycle_while_editor_is_open() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await waitVisible(page, ".section-tab");

    const tabs = await page.$$(".section-tab");
    let rolesTab = null;
    for (const tab of tabs) {
      const text = await page.evaluate((el) => el.textContent, tab);
      if (text.trim().startsWith("Agentes")) {
        rolesTab = tab;
        break;
      }
    }
    assert.ok(rolesTab, "No se encontró la pestaña 'Agentes' en la navegación.");
    await rolesTab.click();

    await page.waitForFunction(
      () => document.querySelectorAll(".agent-name").length > 0,
      { timeout: 10000 }
    );

    // Abrir el editor de la primera fila sintética Developer disponible
    // (sin instancia lanzada, "Cambiar modelo" habilitado).
    const clicked = await page.evaluate(() => {
      const cards = Array.from(document.querySelectorAll(".agent-card"));
      const target = cards.find((card) => {
        const nameEl = card.querySelector(".agent-name");
        return nameEl && nameEl.textContent === "Developer-1";
      });
      if (!target) return false;
      const changeBtn = Array.from(target.querySelectorAll("button")).find(
        (btn) => btn.textContent.trim() === "Cambiar modelo" && !btn.disabled
      );
      if (!changeBtn) return false;
      changeBtn.click();
      return true;
    });
    assert.ok(clicked, "No se pudo pulsar 'Cambiar modelo' en Developer-1.");

    await waitVisible(page, ".agent-editor-row select");

    // El catálogo del backend aislado trae varios modelos habilitados de
    // fábrica (sin ningún default persistido todavía) — elegir la SEGUNDA
    // opción real (índice 1: la 0 es "— sin default —") como selección
    // deliberada del usuario, distinta del estado inicial.
    const chosenLabel = await page.evaluate(() => {
      const select = document.querySelector(".agent-editor-row select");
      if (!select || select.options.length < 2) return null;
      select.selectedIndex = 1;
      select.dispatchEvent(new Event("change", { bubbles: true }));
      return select.options[select.selectedIndex].textContent;
    });
    assert.ok(chosenLabel, "El <select> del editor no tiene al menos 2 opciones reales para elegir.");

    // Confirmar que la elección quedó reflejada ANTES de esperar el
    // polling (control del propio test, no el criterio bajo prueba).
    const selectedBeforePoll = await page.$eval(
      ".agent-editor-row select",
      (el) => el.options[el.selectedIndex].textContent
    );
    assert.strictEqual(selectedBeforePoll, chosenLabel);

    // Dejar pasar un ciclo COMPLETO de polling real con el editor todavía
    // abierto — el propio caso de prueba del bug original.
    await sleep(POLL_INTERVAL_MILLIS + 500);

    const selectedAfterPoll = await page.$eval(
      ".agent-editor-row select",
      (el) => el.options[el.selectedIndex].textContent
    );

    assert.strictEqual(
      selectedAfterPoll,
      chosenLabel,
      `La selección cambió tras un ciclo de polling: antes '${chosenLabel}', después '${selectedAfterPoll}'.`
    );

    // El editor debe seguir abierto (el polling no lo cerró de rebote).
    const editorStillOpen = await page.$(".agent-editor-row select");
    assert.ok(editorStillOpen, "El editor se cerró solo tras el ciclo de polling.");
  });
}

module.exports = [
  {
    name: "la selección del editor de modelo sobrevive a un ciclo completo de polling con el editor abierto",
    fn: test_selection_survives_a_full_polling_cycle_while_editor_is_open,
  },
];
