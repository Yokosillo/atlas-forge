/* T-FB036-US01-10 (US-FB036-01): cada ID de la cadena en el panel
 * "Próximo foco" (`renderBacklogFocusPanel`) es un enlace clicable que
 * expande la Epic (y, si es una Task, también su User Story padre) y
 * hace scroll hasta ese item concreto — reutiliza
 * `expandEpicAndScrollToBlocked`/su mecanismo, extendido para apuntar a
 * un id concreto de la cadena en vez de "el primero bloqueado".
 *
 * Backlog sintético con una cadena real MIXTA (Task -> User Story), sin
 * forzar el cálculo: una Task raíz sin dependencias y una User Story
 * que depende de ella — `find_max_leverage_chain` (backend real) produce
 * la cadena de forma natural. Ningún endpoint se mockea. */

"use strict";

const assert = require("assert");
const { withBackend, waitVisible } = require("./harness");

async function test_chain_links_are_clickable_and_navigate_to_task_and_us() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await waitVisible(page, ".section-tab");

    const tabs = await page.$$(".section-tab");
    let backlogTab = null;
    for (const tab of tabs) {
      const text = await page.evaluate((el) => el.textContent, tab);
      if (text.trim().startsWith("Backlog")) {
        backlogTab = tab;
        break;
      }
    }
    assert.ok(backlogTab, "No se encontró la pestaña 'Backlog'.");
    await backlogTab.click();

    // Criterio 1: cada ID de la cadena es un enlace clicable (no texto
    // plano) — la propia clase `.backlog-focus-chain-link` confirma que
    // ya no es un único <p> de texto.
    await waitVisible(page, ".backlog-focus-chain-link");
    const links = await page.evaluate(() =>
      Array.from(document.querySelectorAll(".backlog-focus-chain-link")).map((el) => el.textContent)
    );
    assert.ok(links.length >= 2, `Esperaba al menos 2 enlaces en la cadena real, encontrados: ${JSON.stringify(links)}`);

    const taskLinkText = links.find((t) => t.startsWith("T-"));
    const usLinkText = links.find((t) => t.startsWith("US-"));
    assert.ok(taskLinkText, `La cadena real debe incluir al menos una Task: ${JSON.stringify(links)}`);
    assert.ok(usLinkText, `La cadena real debe incluir al menos una User Story: ${JSON.stringify(links)}`);

    // Criterio 3: pulsar el enlace de la Task expande su Epic Y su User
    // Story padre, y hace scroll hasta esa Task concreta.
    await page.evaluate((text) => {
      const link = Array.from(document.querySelectorAll(".backlog-focus-chain-link")).find(
        (el) => el.textContent === text
      );
      link.click();
    }, taskLinkText);

    await page.waitForFunction(
      (taskId) => document.getElementById("backlog-task-" + taskId) !== null,
      { timeout: 10000 },
      taskLinkText
    );

    const epicExpandedAfterTaskClick = await page.evaluate(() => {
      const lines = Array.from(document.querySelectorAll(".backlog-epic-line"));
      const line = lines.find((l) => l.getAttribute("aria-expanded") === "true");
      return line !== undefined;
    });
    assert.ok(epicExpandedAfterTaskClick, "La Epic debe quedar expandida tras pulsar el enlace de la Task.");

    const parentUsExpanded = await page.evaluate(() => {
      const lines = Array.from(document.querySelectorAll(".backlog-us-line"));
      return lines.some((l) => l.getAttribute("aria-expanded") === "true");
    });
    assert.ok(parentUsExpanded, "La User Story padre de la Task debe quedar expandida tras pulsar su enlace.");

    // Criterio 2: pulsar el enlace de la US hace scroll hasta esa US
    // concreta (id de anclaje `backlog-us-<id>` presente en el DOM).
    await page.evaluate((text) => {
      const link = Array.from(document.querySelectorAll(".backlog-focus-chain-link")).find(
        (el) => el.textContent === text
      );
      link.click();
    }, usLinkText);

    await page.waitForFunction(
      (usId) => document.getElementById("backlog-us-" + usId) !== null,
      { timeout: 10000 },
      usLinkText
    );

    // Criterio 4: el resto del panel (título, botón Mostrar/Ocultar, nota
    // de cascada) no cambia.
    const panelIntact = await page.evaluate(() => {
      const panel = document.querySelector(".backlog-focus-panel");
      return (
        panel !== null &&
        panel.textContent.includes("Próximo foco") &&
        panel.textContent.includes("Completar el primero desbloquea los siguientes en cascada")
      );
    });
    assert.ok(panelIntact, "El resto del panel 'Próximo foco' debe permanecer intacto.");

    const toggleButtonPresent = await page.evaluate(
      () => document.querySelector(".backlog-focus-toggle") !== null
    );
    assert.ok(toggleButtonPresent, "El botón Mostrar/Ocultar debe seguir presente.");
  });
}

module.exports = [
  {
    name: "cada ID del panel 'Próximo foco' es clicable y navega a la Task/User Story real de una cadena mixta",
    fn: test_chain_links_are_clickable_and_navigate_to_task_and_us,
  },
];
