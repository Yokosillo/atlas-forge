/* T-AF036-US16-04 (US-AF036-16): tests web deterministas de la limpieza de
 * la pantalla Backlog — los botones "Progresar" y "Marcar toda la Story para
 * desarrollo" y el panel "Próximo foco" han desaparecido; el despacho por
 * estado (mover una US a TO_DEVELOP) sigue funcionando; y los botones del
 * Backlog tienen altura reducida (~28px). */

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

async function _seed(page, epicId, usId, taskId) {
  await page.evaluate(
    async ({ epicId, usId, taskId }) => {
      const post = async (p, b) => {
        const r = await fetch(p, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(b),
        });
        if (!r.ok) throw new Error("POST " + p + " falló: " + r.status);
      };
      await post("/backlog/epic", { id: epicId, title: "Epic " + epicId, objetivo: "O." });
      await post("/backlog/epic/" + epicId + "/us", { id: usId, title: "US " + usId, objetivo: "H.", criterios_aceptacion: "C." });
      await post("/backlog/us/" + usId + "/task", { id: taskId, title: "Task " + taskId, objetivo: "O.", descripcion: "D.", criterios_aceptacion: "C.", priority: "Alta" });
    },
    { epicId, usId, taskId }
  );
}

async function _openEpicDetail(page, epicId) {
  await waitVisible(page, ".backlog-epic-line");
  const ok = await page.evaluate((id) => {
    const line = Array.from(document.querySelectorAll(".backlog-epic-line")).find((l) =>
      l.textContent.includes(id)
    );
    if (!line) return false;
    line.click();
    return true;
  }, epicId);
  assert.ok(ok, "No se encontró la línea de la Epic '" + epicId + "'.");
}

async function _openUsDetail(page, usId) {
  await waitVisible(page, ".backlog-us-line");
  const ok = await page.evaluate((id) => {
    const line = Array.from(document.querySelectorAll(".backlog-us-line")).find((l) =>
      l.textContent.includes(id)
    );
    if (!line) return false;
    line.click();
    return true;
  }, usId);
  assert.ok(ok, "No se pudo abrir el detalle de la US '" + usId + "'.");
}

async function _hasButton(page, text) {
  return page.evaluate((label) =>
    Array.from(document.querySelectorAll("button")).some((b) => b.textContent.trim() === label),
    text
  );
}

async function test_obsolete_buttons_are_not_rendered() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await _seed(page, "AF-981", "US-AF981-01", "T-AF981-US01-01");
    await _goToBacklogTab(page);
    await _openEpicDetail(page, "AF-981");
    await _openUsDetail(page, "US-AF981-01");

    await page.waitForFunction(
      () => Array.from(document.querySelectorAll("button")).some((b) => b.textContent.trim() === "+ Nueva Task"),
      { timeout: 10000 }
    );

    // Criterio 1 y 2 de US-AF036-16: los botones obsoletos no se renderizan.
    assert.strictEqual(
      await _hasButton(page, "Progresar"),
      false,
      "El botón 'Progresar' no debe aparecer en la pantalla Backlog."
    );
    assert.strictEqual(
      await _hasButton(page, "Marcar toda la Story para desarrollo"),
      false,
      "El botón 'Marcar toda la Story para desarrollo' no debe aparecer."
    );
    // El control por estado sigue presente (sustituye a esos botones).
    assert.ok(
      await page.evaluate(() => document.querySelector(".backlog-edit-state") != null),
      "El selector de estado debe seguir presente."
    );
  });
}

async function test_proximo_foco_panel_is_not_rendered_even_with_data() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");

    // Interceptar GET /backlog para inyectar max_leverage_chain con datos
    // (simula que el backend SÍ calcula la cadena) — el panel NO debe pintarse.
    await page.setRequestInterception(true);
    page.on("request", (req) => {
      if (req.method() === "GET" && req.url().endsWith("/backlog")) {
        req.respond({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            empty: false,
            max_leverage_chain: [
              { id: "T-AF982-US01-01", kind: "T", epic: "AF-982", priority: "Alta", fase: null },
            ],
            by_epic: [],
          }),
        });
      } else {
        req.continue();
      }
    });

    await _seed(page, "AF-982", "US-AF982-01", "T-AF982-US01-01");
    await _goToBacklogTab(page);
    await waitVisible(page, ".backlog-body");

    // El panel "Próximo foco" no debe existir aunque max_leverage_chain tenga datos.
    const panelPresent = await page.evaluate(
      () => document.querySelector(".backlog-focus-panel") != null
    );
    assert.strictEqual(
      panelPresent,
      false,
      "El panel 'Próximo foco' no debe renderizarse aunque max_leverage_chain tenga datos."
    );
  });
}

async function test_moving_us_to_to_develop_enqueues_tasks() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await _seed(page, "AF-983", "US-AF983-01", "T-AF983-US01-01");
    await _goToBacklogTab(page);

    // Cambiar el selector de estado de la US a TO_DEVELOP (despacho por estado).
    await _openEpicDetail(page, "AF-983");
    await waitVisible(page, ".backlog-us-line");
    await page.evaluate((id) => {
      const line = Array.from(document.querySelectorAll(".backlog-us-line")).find((l) =>
        l.textContent.includes(id)
      );
      const select = line && line.querySelector(".backlog-edit-state");
      if (!select) return;
      select.value = "TO_DEVELOP";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    }, "US-AF983-01");

    // La Task encolada aparece en la cola de despacho (el despacho por estado
    // sigue funcionando y el Dispatcher podrá recogerla).
    await page.waitForFunction(
      () =>
        Array.from(document.querySelectorAll(".backlog-queue-row")).some((r) =>
          r.textContent.includes("T-AF983-US01-01")
        ),
      { timeout: 10000 }
    );
  });
}

async function test_backlog_buttons_have_reduced_height() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await _goToBacklogTab(page);
    await waitVisible(page, ".backlog-new-epic-btn");

    const h = await page.evaluate(() =>
      Math.round(document.querySelector(".backlog-new-epic-btn").getBoundingClientRect().height)
    );
    assert.ok(
      h <= 32,
      "Los botones del Backlog deben tener altura reducida (~28px), obtuvo: " + h
    );
  });
}

module.exports = [
  {
    name: "T-AF036-US16-04: los botones 'Progresar' y 'Marcar toda la Story para desarrollo' no se renderizan",
    fn: test_obsolete_buttons_are_not_rendered,
  },
  {
    name: "T-AF036-US16-04: el panel 'Próximo foco' no se renderiza aunque max_leverage_chain tenga datos",
    fn: test_proximo_foco_panel_is_not_rendered_even_with_data,
  },
  {
    name: "T-AF036-US16-04: mover una US a TO_DEVELOP encola sus Tasks (el despacho por estado sigue funcionando)",
    fn: test_moving_us_to_to_develop_enqueues_tasks,
  },
  {
    name: "T-AF036-US16-03: los botones del Backlog tienen altura reducida (~28px)",
    fn: test_backlog_buttons_have_reduced_height,
  },
];
