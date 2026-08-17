/* Regresión de T-FB024-US11-03 (US-FB024-11): pulsar "Cambiar modelo" en
 * una fila sintética Developer-N (sin instancia lanzada) debe abrir el
 * editor inline SOLO en esa fila — antes del fix, las filas sintéticas
 * compartían `id: null` y `rolesSection.editingAgentId` no distinguía
 * entre ellas, así que el editor se abría a la vez en todas las filas
 * Developer-N. Ver `07-informes/US-FB024-11/corregir-editor-modelo-filas-sinteticas.md`.
 *
 * Backend aislado sin ningún agente lanzado: `buildUnifiedRows` (`app.js`)
 * rellena hasta `DEFAULT_MAX_SIMULTANEOUS_DEVELOPERS` (3) filas sintéticas
 * "Developer-1"/"Developer-2"/"Developer-3" automáticamente — no hace
 * falta sembrar nada más para reproducir el escenario del bug. */

"use strict";

const assert = require("assert");
const { withBackend, waitVisible } = require("./harness");

async function test_editor_opens_only_on_the_clicked_synthetic_row() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await waitVisible(page, ".section-tab");

    // Ir a la pestaña Agentes (rótulo real de la sección `roles`).
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

    // Esperar a que las 3 filas sintéticas de Developer estén presentes
    // (nombre visible "Developer-1"/"Developer-2"/"Developer-3").
    await page.waitForFunction(
      () => {
        const names = Array.from(document.querySelectorAll(".agent-name")).map(
          (el) => el.textContent
        );
        return (
          names.includes("Developer-1") &&
          names.includes("Developer-2") &&
          names.includes("Developer-3")
        );
      },
      { timeout: 10000 }
    );

    // Localizar la tarjeta (`.agent-card`) de "Developer-2" y pulsar su
    // botón "Cambiar modelo" — identificado por posición dentro de esa
    // tarjeta concreta, nunca por selector global (eso es precisamente lo
    // que el bug original rompía: todas las filas compartían identidad).
    const clicked = await page.evaluate(() => {
      const cards = Array.from(document.querySelectorAll(".agent-card"));
      const target = cards.find((card) => {
        const nameEl = card.querySelector(".agent-name");
        return nameEl && nameEl.textContent === "Developer-2";
      });
      if (!target) return false;
      const changeBtn = Array.from(target.querySelectorAll("button")).find(
        (btn) => btn.textContent.trim() === "Cambiar modelo"
      );
      if (!changeBtn) return false;
      changeBtn.click();
      return true;
    });
    assert.ok(clicked, "No se pudo pulsar 'Cambiar modelo' en la fila Developer-2.");

    await waitVisible(page, ".agent-editor-row select");

    // Criterio: el editor inline (`.agent-editor-row`) existe en EXACTAMENTE
    // una tarjeta, y esa tarjeta es la de Developer-2 — ninguna otra fila
    // Developer-N tiene el editor abierto a la vez.
    const rowsWithEditorOpen = await page.evaluate(() => {
      const cards = Array.from(document.querySelectorAll(".agent-card"));
      return cards
        .filter((card) => card.querySelector(".agent-editor-row"))
        .map((card) => {
          const nameEl = card.querySelector(".agent-name");
          return nameEl ? nameEl.textContent : null;
        });
    });

    assert.deepStrictEqual(
      rowsWithEditorOpen,
      ["Developer-2"],
      `Esperado el editor abierto SOLO en Developer-2, pero está abierto en: ${JSON.stringify(rowsWithEditorOpen)}`
    );
  });
}

module.exports = [
  {
    name: "el editor de modelo se abre solo en la fila sintética pulsada (Developer-2), nunca en las demás",
    fn: test_editor_opens_only_on_the_clicked_synthetic_row,
  },
];
