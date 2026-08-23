/* T-AF036-US16-03: los botones de la pantalla Backlog tienen altura reducida
 * (~28px, mismo criterio que la pantalla Agentes), y el resto de la web no se
 * ve afectado (conserva el min-height global de accesibilidad). Verificado en
 * navegador real. */

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
  throw new Error("No se encontró la pestaña 'Backlog'.");
}

async function _seed(page, epicId) {
  await page.evaluate(
    async (epicId) => {
      const r = await fetch("/backlog/epic", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: epicId, title: "Epic " + epicId, objetivo: "O." }),
      });
      if (!r.ok) throw new Error("POST epic falló: " + r.status);
    },
    epicId
  );
}

async function test_backlog_buttons_reduced_height() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await _seed(page, "AF-951");
    await page.reload();
    await _goToBacklogTab(page);

    // Esperar al botón "+ Nueva Epic" dentro del backlog.
    await page.waitForFunction(
      () => {
        const b = Array.from(document.querySelectorAll(".backlog-body button")).find((x) =>
          x.textContent.includes("Nueva Epic")
        );
        return b != null;
      },
      { timeout: 10000 }
    );

    const heights = await page.evaluate(() => {
      const backlogBtn = Array.from(document.querySelectorAll(".backlog-body button")).find((x) =>
        x.textContent.includes("Nueva Epic")
      );
      // Un botón de navegación fuera de .backlog-body (no debe verse afectado).
      const navBtn = Array.from(document.querySelectorAll(".section-tab")).find((x) =>
        x.textContent.trim().startsWith("Backlog")
      );
      return {
        backlogMinHeight: backlogBtn ? parseFloat(getComputedStyle(backlogBtn).minHeight) : null,
        navMinHeight: navBtn ? parseFloat(getComputedStyle(navBtn).minHeight) : null,
      };
    });

    assert.ok(heights.backlogMinHeight !== null, "Debe existir un botón en .backlog-body.");
    assert.ok(
      heights.backlogMinHeight <= 29,
      "Los botones del Backlog deben tener altura reducida (~28px), got: " + heights.backlogMinHeight
    );
  });
}

async function test_rest_of_web_unaffected() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await waitVisible(page, ".section-tab");

    // Un botón de navegación (fuera de .backlog-body) conserva min-height 48px.
    const navMinHeight = await page.evaluate(() => {
      const tab = Array.from(document.querySelectorAll(".section-tab")).find((x) =>
        x.textContent.trim().startsWith("Backlog")
      );
      return tab ? parseFloat(getComputedStyle(tab).minHeight) : null;
    });

    // El botón de una sección no-Backlog (ej. Agentes) también conserva 48px.
    const agentsMinHeight = await page.evaluate(() => {
      const tab = Array.from(document.querySelectorAll(".section-tab")).find((x) =>
        x.textContent.trim().startsWith("Agentes")
      );
      return tab ? parseFloat(getComputedStyle(tab).minHeight) : null;
    });

    assert.strictEqual(
      navMinHeight,
      48,
      "Los botones de navegación (fuera de .backlog-body) deben conservar min-height 48px."
    );
    assert.strictEqual(agentsMinHeight, 48, "El resto de la web no debe verse afectado (48px).");
  });
}

module.exports = [
  {
    name: "T-AF036-US16-03: los botones del Backlog tienen altura reducida (~28px)",
    fn: test_backlog_buttons_reduced_height,
  },
  {
    name: "T-AF036-US16-03: el resto de la web no se ve afectado (min-height 48px conservado)",
    fn: test_rest_of_web_unaffected,
  },
];