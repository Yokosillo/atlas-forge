/* T-FB005-US07-02 (US-FB005-07): el lanzamiento de un agente desde la
 * pantalla Agentes (pestaña `roles`, el camino operativo real — la fila
 * sintética "Developer-N" pulsa su botón "Lanzar") debe enviar a
 * `POST /agents` un `runtime_type` EXPLÍCITO, nunca dejar que el backend
 * lo infiera del modelo (contrato: runtime separado del modelo).
 *
 * Se intercepta SOLO la respuesta de red de `POST /agents` (no se lanza
 * un runtime real): se captura el payload que el frontend construye y se
 * responde un 201 simulado para que el flujo complete. Verifica la lógica
 * real del HTML/JS del camino de lanzamiento operativo contra el backend
 * real aislado (catálogo `GET /agents/options`/`GET /models/preferences`
 * reales alimentan el estado). */

"use strict";

const assert = require("assert");
const { withBackend, waitVisible } = require("./harness");

async function _goToAgentsTab(page) {
  await waitVisible(page, ".section-tab");
  const tabs = await page.$$(".section-tab");
  for (const tab of tabs) {
    const text = await page.evaluate((el) => el.textContent, tab);
    if (text.trim().startsWith("Agentes")) {
      await tab.click();
      return;
    }
  }
  throw new Error("No se encontró la pestaña 'Agentes' en la navegación.");
}

async function _selectRuntimeForRow(page, devName, runtimeValue) {
  return page.evaluate((name, val) => {
    const cards = Array.from(document.querySelectorAll(".agent-card"));
    const target = cards.find((card) => {
      const nameEl = card.querySelector(".agent-name");
      return nameEl && nameEl.textContent === name;
    });
    if (!target) return false;
    const sel = target.querySelector(".runtime-select");
    if (!sel) return false;
    sel.value = val;
    sel.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  }, devName, runtimeValue);
}

async function _clickLanzarOnDeveloperRow(page, devName) {
  return page.evaluate((name) => {
    const cards = Array.from(document.querySelectorAll(".agent-card"));
    const target = cards.find((card) => {
      const nameEl = card.querySelector(".agent-name");
      return nameEl && nameEl.textContent === name;
    });
    if (!target) return false;
    const launchBtn = Array.from(target.querySelectorAll("button")).find(
      (btn) => btn.textContent.trim() === "Lanzar" && !btn.disabled
    );
    if (!launchBtn) return false;
    launchBtn.click();
    return true;
  }, devName);
}

async function test_operative_launch_sends_explicit_runtime() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await _goToAgentsTab(page);

    // Esperar a que aparezcan las filas sintéticas de Developer.
    await page.waitForFunction(
      () =>
        Array.from(document.querySelectorAll(".agent-name")).some(
          (el) => el.textContent === "Developer-1"
        ),
      { timeout: 10000 }
    );

    let captured = [];
    await page.setRequestInterception(true);
    page.on("request", (req) => {
      if (req.method() === "POST" && /\/agents$/.test(req.url())) {
        try {
          captured.push(JSON.parse(req.postData() || "{}"));
        } catch (_e) {
          captured.push({});
        }
        // Simular un agente lanzado para que el flujo complete (no se
        // lanza ningún runtime real en este test).
        req.respond({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({
            id: "dev-test", role: "developer", status: "idle",
            runtime_id: "opencode", model: null,
            session_name: "developer-1-proj", name: "Developer-1",
          }),
        });
        return;
      }
      req.continue();
    });

    // T-FB005-US07-03: el lanzamiento exige elegir runtime primero — el
    // botón "Lanzar" está deshabilitado hasta que se elija uno. Se elige
    // OpenCode en el selector de la fila y entonces se lanza.
    const runtimeSelected = await _selectRuntimeForRow(page, "Developer-1", "opencode");
    assert.ok(runtimeSelected, "No se encontró el selector de runtime en la fila Developer-1.");

    const clicked = await _clickLanzarOnDeveloperRow(page, "Developer-1");
    assert.ok(clicked, "No se encontró el botón 'Lanzar' habilitado en la fila Developer-1.");

    // La llamada a `POST /agents` va tras un refresh de la lista
    // (`pollRolesAgents`) — dar margen a que el payload se capture.
    await new Promise((r) => setTimeout(r, 1000));

    assert.ok(captured.length >= 1, "Debe capturarse al menos un payload de POST /agents.");
    const payload = captured[0];
    // Criterio 1 (lado cliente): el runtime se manda SIEMPRE explícito.
    assert.ok(
      ["opencode", "claude-code", "codex"].indexOf(payload.runtime_type) !== -1,
      "El payload de lanzamiento debe llevar runtime_type explícito: " + JSON.stringify(payload)
    );
    // El rol siempre va presente.
    assert.strictEqual(payload.role, "developer");
    // T-FB005-US01-08 (2026-08-18): al lanzar desde la fila "Developer-1"
    // se envía el número de slot — el agente nace con ESE nombre, no con
    // el que el conteo del backend decida.
    assert.strictEqual(
      payload.developer_number, 1,
      "El payload de lanzamiento debe llevar developer_number=1 (fila Developer-1): " + JSON.stringify(payload)
    );
  });
}

module.exports = [
  {
    name: "el lanzamiento operativo desde la pantalla Agentes envía runtime_type explícito a POST /agents",
    fn: test_operative_launch_sends_explicit_runtime,
  },
];