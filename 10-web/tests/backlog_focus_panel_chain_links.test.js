/* T-FB036-US01-10 (US-FB036-01): cada ID de la cadena en el panel
 * "Próximo foco" (`renderBacklogFocusPanel`) es un enlace clicable que
 * expande la Epic (y, si es una Task, también su User Story padre) y
 * hace scroll hasta ese item concreto — reutiliza
 * `expandEpicAndScrollToBlocked`/su mecanismo, extendido para apuntar a
 * un id concreto de la cadena en vez de "el primero bloqueado".
 *
 * Backlog sintético con una cadena real MIXTA (Task -> User Story), sin
 * forzar el cálculo de `find_max_leverage_chain`: una Task raíz sin
 * dependencias y una User Story que depende de ella. La US se crea vía
 * HTTP (`POST /backlog/epic/{epic}/us`) y luego su frontmatter se
 * reescribe con `fs` para fijar `dependencies: [T-FB940-US01-01]` —
 * `CreateUserStoryRequest` no tiene ese campo (a diferencia del de
 * Task), así que no hay ningún endpoint que lo permita hoy; escribir el
 * fichero directamente es la única vía sin mockear el backend ni ampliar
 * su superficie HTTP solo para un test (fuera del alcance de esta
 * Task). */

"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const { withBackend, waitVisible } = require("./harness");

async function test_chain_links_are_clickable_and_navigate_to_task_and_us() {
  await withBackend(async ({ page, baseUrl, projectPath }) => {
    assert.ok(projectPath, "El backend aislado debe exponer la ruta real del proyecto activo.");

    await page.goto(baseUrl + "/ui/");

    // Siembra del backlog real vía los endpoints ya cerrados
    // (T-FB036-US02-01/02/03): Epic -> Task raíz (sin dependencias) ->
    // User Story (sin dependencias todavía, el endpoint no lo permite).
    await page.evaluate(async () => {
      await fetch("/backlog/epic", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: "FB-940", title: "Epic de la cadena", objetivo: "Objetivo." }),
      });
      await fetch("/backlog/epic/FB-940/us", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          id: "US-FB940-01", title: "US raiz", objetivo: "H.", criterios_aceptacion: "C.",
        }),
      });
      await fetch("/backlog/us/US-FB940-01/task", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          id: "T-FB940-US01-01", title: "Task raiz", objetivo: "O.", descripcion: "D.",
          criterios_aceptacion: "C.",
        }),
      });
      await fetch("/backlog/epic/FB-940/us", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          id: "US-FB940-02", title: "US bloqueada", objetivo: "H2.", criterios_aceptacion: "C2.",
        }),
      });
    });

    // La US ya existe en disco (creada vía HTTP arriba) — se reescribe su
    // frontmatter para añadir la dependencia real hacia la Task raíz,
    // produciendo así la cadena mixta Task -> US de forma que
    // `find_max_leverage_chain` (backend real, sin tocar) la calcule de
    // forma natural en la siguiente petición.
    // El fichero real es `{us_id}-{slug(title)}.md` (ver `create_user_story`
    // en `04-src/src/brain/backlog/create.py`), no `US-FB940-02.md` a
    // secas — se localiza por glob del prefijo, mismo criterio que usa
    // `_find_existing` en el propio backend.
    const storiesDir = path.join(projectPath, "02-backlog", "user-stories");
    const usFilename = fs.readdirSync(storiesDir).find((name) => name.startsWith("US-FB940-02"));
    assert.ok(usFilename, `No se encontró el fichero de US-FB940-02 en ${storiesDir}`);
    const usPath = path.join(storiesDir, usFilename);
    const original = fs.readFileSync(usPath, "utf-8");
    assert.ok(original.includes("dependencies: []"), `Frontmatter inesperado, no se encontró 'dependencies: []': ${original}`);
    fs.writeFileSync(usPath, original.replace("dependencies: []", "dependencies: [T-FB940-US01-01]"));

    await page.reload();
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
