/* T-FB005-US07-03 (US-FB005-07), reescrito en T-FB024-US11-13
 * (2026-08-17, tercera revisión de esa Task): el modelo se elige AL
 * LANZAR, para OpenCode Y Claude Code — no solo OpenCode como antes, y
 * ya no hay ningún cambio de modelo EN CALIENTE (el mecanismo real
 * resultó frágil en ambos runtimes: atajos de teclado desactualizados en
 * OpenCode, diálogo de confirmación no siempre predecible en Claude
 * Code — queda bloqueado para investigar en una Task aparte).
 *
 * C1 (agente NO lanzado): el runtime es una elección OBLIGATORIA y
 * visible (selector) — el lanzamiento se bloquea hasta elegirlo. Tras
 * elegir un runtime que admite modelo (OpenCode/Claude Code), aparece un
 * segundo selector de modelo (opcional: sin elegir nada, se lanza sin
 * `model_id`, el runtime arranca con su propio default).
 *
 * C2 (agente VIVO): el runtime se muestra FIJO como texto, y el modelo
 * también como texto plano — nunca un selector ni botón de cambio en
 * caliente, para ningún runtime.
 *
 * Para el caso "vivo" se intercepta SOLO la respuesta de `GET /agents`
 * (un agente real `idle` no es alcanzable de forma segura sin lanzar un
 * runtime real; mecanismo explícito de `00-gobierno/DEVELOPER.md`). */

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

async function _rowState(page, devName) {
  return page.evaluate((name) => {
    const cards = Array.from(document.querySelectorAll(".agent-card"));
    const target = cards.find((card) => {
      const nameEl = card.querySelector(".agent-name");
      return nameEl && nameEl.textContent === name;
    });
    if (!target) return null;
    const launchBtn = Array.from(target.querySelectorAll("button")).find(
      (b) => b.textContent.trim() === "Lanzar"
    );
    const selects = Array.from(target.querySelectorAll(".runtime-select"));
    const hasRuntimeSelect = selects.length > 0;
    // El selector de modelo (si aparece) es el SEGUNDO .runtime-select
    // de la fila, tras el de runtime — ambos comparten la misma clase de
    // estilo (T-FB024-US11-13: ya no existe ningún selector "inline en
    // caliente" que distinguir por separado).
    const hasModelSelect = selects.length > 1;
    const runtimeText = target.querySelector(".agent-runtime")
      ? target.querySelector(".agent-runtime").textContent
      : null;
    const hasChangeModelButton = Array.from(target.querySelectorAll("button")).some(
      (b) => b.textContent.trim() === "Cambiar modelo"
    );
    return {
      launchDisabled: launchBtn ? launchBtn.disabled : null,
      launchTitle: launchBtn ? launchBtn.title : null,
      hasRuntimeSelect,
      hasModelSelect,
      runtimeText,
      hasChangeModel: hasChangeModelButton,
    };
  }, devName);
}

async function test_not_launched_requires_runtime_and_offers_model_selector() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await _goToAgentsTab(page);

    await page.waitForFunction(
      () =>
        Array.from(document.querySelectorAll(".agent-name")).some(
          (el) => el.textContent === "Developer-1"
        ),
      { timeout: 10000 }
    );

    // Sin runtime elegido: lanzamiento BLOQUEADO con aviso explícito, y
    // no hay ni "Cambiar modelo" ni selector de modelo (aún no aplica).
    let st = await _rowState(page, "Developer-1");
    assert.strictEqual(st.launchDisabled, true, "Lanzar debe estar deshabilitado sin runtime elegido.");
    assert.ok(
      (st.launchTitle || "").indexOf("Elige un runtime") !== -1,
      "El aviso debe pedir elegir runtime: " + JSON.stringify(st)
    );
    assert.strictEqual(st.hasChangeModel, false, "No debe haber botón 'Cambiar modelo' — ese control ya no existe.");
    assert.strictEqual(st.hasModelSelect, false, "No debe haber selector de modelo antes de elegir runtime.");

    // Elegir Claude Code → lanzamiento habilitado, y aparece el selector
    // de modelo (T-FB024-US11-13: Claude Code también admite elegir
    // modelo al lanzar, ya no solo OpenCode).
    await _selectRuntimeForRow(page, "Developer-1", "claude-code");
    await new Promise((r) => setTimeout(r, 200));
    st = await _rowState(page, "Developer-1");
    assert.strictEqual(st.launchDisabled, false, "Lanzar debe habilitarse al elegir un runtime.");
    assert.strictEqual(st.hasModelSelect, true, "Claude Code debe ofrecer selector de modelo al lanzar: " + JSON.stringify(st));

    // Elegir OpenCode → también ofrece selector de modelo, lanzamiento
    // sigue habilitado.
    await _selectRuntimeForRow(page, "Developer-1", "opencode");
    await new Promise((r) => setTimeout(r, 200));
    st = await _rowState(page, "Developer-1");
    assert.strictEqual(st.hasModelSelect, true, "OpenCode debe ofrecer selector de modelo al lanzar: " + JSON.stringify(st));
    assert.strictEqual(st.launchDisabled, false, "Lanzar debe seguir habilitado con OpenCode elegido.");
  });
}

async function test_live_agent_shows_runtime_and_model_as_fixed_text() {
  // Interceptar GET /agents para simular un agente VIVO (idle) — sin
  // lanzar un runtime real. Verifica que un agente vivo NUNCA muestra
  // ningún selector ni botón de cambio de modelo, para ningún runtime
  // (T-FB024-US11-13: cambio en caliente bloqueado por completo).
  await withBackend(async ({ page, baseUrl }) => {
    await page.setRequestInterception(true);
    const liveAgent = {
      id: "dev-live-1", role: "developer", name: "Developer-1", status: "idle",
      runtime_id: "opencode", model: "opencode-go/deepseek-v4-flash",
      last_command_at: null,
    };
    page.on("request", (req) => {
      if (req.method() === "GET" && /\/agents$/.test(req.url())) {
        req.respond({ status: 200, contentType: "application/json", body: JSON.stringify([liveAgent]) });
        return;
      }
      req.continue();
    });

    await page.goto(baseUrl + "/ui/");
    await _goToAgentsTab(page);

    await page.waitForFunction(
      () => document.querySelectorAll(".agent-name").length > 0,
      { timeout: 10000 }
    );

    let st = await _rowState(page, "Developer-1");
    assert.strictEqual(st.hasRuntimeSelect, false, "Un agente vivo no debe tener selector de runtime (queda fijo).");
    assert.ok(st.runtimeText && st.runtimeText.indexOf("OpenCode") !== -1, "Debe mostrar el runtime como texto: " + JSON.stringify(st));
    assert.strictEqual(st.hasModelSelect, false, "Un agente vivo no debe ofrecer selector de modelo (cambio en caliente bloqueado).");
    assert.strictEqual(st.hasChangeModel, false, "Un agente vivo no debe ofrecer el botón 'Cambiar modelo'.");
    assert.strictEqual(st.launchDisabled, null, "Un agente vivo no debe mostrar un botón 'Lanzar'.");
  });
}

module.exports = [
  {
    name: "agente no lanzado: runtime obligatorio y selector de modelo tras elegirlo (OpenCode y Claude Code)",
    fn: test_not_launched_requires_runtime_and_offers_model_selector,
  },
  {
    name: "agente vivo: runtime y modelo como texto fijo, sin ningún control de cambio en caliente",
    fn: test_live_agent_shows_runtime_and_model_as_fixed_text,
  },
];
