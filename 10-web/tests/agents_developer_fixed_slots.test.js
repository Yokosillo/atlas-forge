/* T-AF005-US01-08 (2026-08-18): los Developers son "slots" FIJOS e
 * independientes — Developer-1/2/3 como agentes NO relacionados que
 * comparten rol (mismo patrón que Auditor-OSS/UX), cada uno lanzable por
 * su cuenta desde su propia fila. Matar uno (p. ej. Developer-2) NO debe:
 *  - hacer aparecer una fila "Developer-4",
 *  - mover las filas de su posición (Developer-1 y Developer-3 se quedan
 *    en su sitio),
 *  - dejar inutilizable el slot muerto: la fila Developer-2 vuelve a su
 *    estado lanzable y al lanzarla el agente nace con ESE nombre
 *    (`developer_number` en el payload de POST /agents).
 *
 * Se intercepta SOLO la respuesta de `GET /agents` (agentes reales
 * `idle` no son alcanzables sin lanzar un runtime real; mecanismo
 * explícito de `00-gobierno/DEVELOPER.md`): se devuelve Developer-1 y
 * Developer-3 vivos, simulando que Developer-2 acaba de ser detenido.
 * Para el lanzamiento se intercepta SOLO la respuesta de `POST /agents`
 * (no se lanza ningún runtime real). */

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

async function _agentNames(page) {
  return page.evaluate(() =>
    Array.from(document.querySelectorAll(".agent-name")).map((el) => el.textContent)
  );
}

async function _rowState(page, name) {
  return page.evaluate((rowName) => {
    const cards = Array.from(document.querySelectorAll(".agent-card"));
    const target = cards.find((card) => {
      const nameEl = card.querySelector(".agent-name");
      return nameEl && nameEl.textContent === rowName;
    });
    if (!target) return null;
    const launchBtn = Array.from(target.querySelectorAll("button")).find(
      (b) => b.textContent.trim() === "Lanzar"
    );
    const selects = Array.from(target.querySelectorAll(".runtime-select"));
    return {
      launchDisabled: launchBtn ? launchBtn.disabled : null,
      launchTitle: launchBtn ? launchBtn.title : null,
      hasRuntimeSelect: selects.length > 0,
      runtimeText: target.querySelector(".agent-runtime")
        ? target.querySelector(".agent-runtime").textContent
        : null,
    };
  }, name);
}

async function _selectRuntimeForRow(page, name, runtimeValue) {
  return page.evaluate((rowName, val) => {
    const cards = Array.from(document.querySelectorAll(".agent-card"));
    const target = cards.find((card) => {
      const nameEl = card.querySelector(".agent-name");
      return nameEl && nameEl.textContent === rowName;
    });
    if (!target) return false;
    const sel = target.querySelector(".runtime-select");
    if (!sel) return false;
    sel.value = val;
    sel.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  }, name, runtimeValue);
}

async function _clickLanzarOnRow(page, name) {
  return page.evaluate((rowName) => {
    const cards = Array.from(document.querySelectorAll(".agent-card"));
    const target = cards.find((card) => {
      const nameEl = card.querySelector(".agent-name");
      return nameEl && nameEl.textContent === rowName;
    });
    if (!target) return false;
    const launchBtn = Array.from(target.querySelectorAll("button")).find(
      (btn) => btn.textContent.trim() === "Lanzar" && !btn.disabled
    );
    if (!launchBtn) return false;
    launchBtn.click();
    return true;
  }, name);
}

const LIVE_1 = {
  id: "dev-live-1", role: "developer", name: "Developer-1", status: "idle",
  runtime_id: "opencode", model: "opencode-go/deepseek-v4-flash", last_command_at: null,
};
const LIVE_3 = {
  id: "dev-live-3", role: "developer", name: "Developer-3", status: "idle",
  runtime_id: "claude-code", model: "claude-code-sonnet", last_command_at: null,
};

async function test_fixed_slots_no_developer_4_and_independent_launch() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.setRequestInterception(true);
    let captured = [];
    page.on("request", (req) => {
      if (req.method() === "GET" && /\/agents$/.test(req.url())) {
        req.respond({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([LIVE_1, LIVE_3]),
        });
        return;
      }
      if (req.method() === "POST" && /\/agents$/.test(req.url())) {
        try {
          captured.push(JSON.parse(req.postData() || "{}"));
        } catch (_e) {
          captured.push({});
        }
        req.respond({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({
            id: "dev-live-2", role: "developer", status: "idle",
            runtime_id: "opencode", model: null,
            session_name: "developer-2-proj", name: "Developer-2",
          }),
        });
        return;
      }
      req.continue();
    });

    await page.goto(baseUrl + "/ui/");
    await _goToAgentsTab(page);

    await page.waitForFunction(
      () => Array.from(document.querySelectorAll(".agent-name")).some(
        (el) => el.textContent === "Developer-3"
      ),
      { timeout: 10000 }
    );

    // C1: filas fijas e independientes — Developer-1, -2 y -3 presentes,
    // en su posición, y NUNCA aparece "Developer-4".
    const names = await _agentNames(page);
    assert.ok(names.indexOf("Developer-1") !== -1, "Developer-1 debe estar presente: " + JSON.stringify(names));
    assert.ok(names.indexOf("Developer-2") !== -1, "Developer-2 debe estar presente (slot libre): " + JSON.stringify(names));
    assert.ok(names.indexOf("Developer-3") !== -1, "Developer-3 debe estar presente: " + JSON.stringify(names));
    assert.ok(names.indexOf("Developer-4") === -1, "NUNCA debe aparecer Developer-4: " + JSON.stringify(names));
    assert.ok(names.indexOf("Developer-1") < names.indexOf("Developer-2"), "Developer-1 debe ir antes que Developer-2 (posición estable): " + JSON.stringify(names));
    assert.ok(names.indexOf("Developer-2") < names.indexOf("Developer-3"), "Developer-2 debe ir antes que Developer-3 (posición estable): " + JSON.stringify(names));

    // C2: los vivos Developer-1/3 se muestran como instancias reales (sin
    // selector de runtime, runtime como texto), y el slot libre
    // Developer-2 como fila sintética con selector.
    const st1 = await _rowState(page, "Developer-1");
    assert.strictEqual(st1.hasRuntimeSelect, false, "Developer-1 vivo no debe tener selector de runtime.");
    assert.ok(st1.runtimeText && st1.runtimeText.indexOf("OpenCode") !== -1, "Developer-1 debe mostrar su runtime: " + JSON.stringify(st1));
    const st3 = await _rowState(page, "Developer-3");
    assert.strictEqual(st3.hasRuntimeSelect, false, "Developer-3 vivo no debe tener selector de runtime.");
    assert.ok(st3.runtimeText && st3.runtimeText.indexOf("Claude") !== -1, "Developer-3 debe mostrar su runtime: " + JSON.stringify(st3));
    const st2 = await _rowState(page, "Developer-2");
    assert.strictEqual(st2.hasRuntimeSelect, true, "Developer-2 (slot libre) debe ofrecer selector de runtime: " + JSON.stringify(st2));

    // C3: Developer-2 se lanza de forma INDEPENDIENTE desde su propia
    // fila — runtime obligatorio primero, luego Lanzar habilitado, y el
    // payload lleva developer_number=2 (el agente nace como Developer-2,
    // no como Developer-4 ni renumerando a los vivos).
    assert.strictEqual(st2.launchDisabled, true, "Lanzar de Developer-2 debe estar deshabilitado sin runtime.");
    const runtimeSelected = await _selectRuntimeForRow(page, "Developer-2", "opencode");
    assert.ok(runtimeSelected, "No se encontró el selector de runtime en la fila Developer-2.");
    await new Promise((r) => setTimeout(r, 200));
    const st2after = await _rowState(page, "Developer-2");
    assert.strictEqual(st2after.launchDisabled, false, "Lanzar de Developer-2 debe habilitarse al elegir runtime: " + JSON.stringify(st2after));

    const clicked = await _clickLanzarOnRow(page, "Developer-2");
    assert.ok(clicked, "No se encontró el botón 'Lanzar' habilitado en la fila Developer-2.");

    await new Promise((r) => setTimeout(r, 1000));

    assert.ok(captured.length >= 1, "Debe capturarse al menos un payload de POST /agents.");
    const payload = captured[0];
    assert.strictEqual(payload.role, "developer", "El payload debe ser de rol developer: " + JSON.stringify(payload));
    assert.strictEqual(
      payload.developer_number, 2,
      "El payload debe llevar developer_number=2 (la fila pulsada), no el que el conteo decida: " + JSON.stringify(payload)
    );
  });
}

async function test_tester_launch_enables_when_runtime_selected() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await _goToAgentsTab(page);

    await page.waitForFunction(
      () => Array.from(document.querySelectorAll(".agent-name")).some(
        (el) => el.textContent === "Tester"
      ),
      { timeout: 10000 }
    );

    // Sin runtime: Lanzar deshabilitado (T-AF005-US07-03).
    let st = await _rowState(page, "Tester");
    assert.strictEqual(st.launchDisabled, true, "Lanzar de Tester debe estar deshabilitado sin runtime: " + JSON.stringify(st));
    assert.strictEqual(st.hasRuntimeSelect, true, "La fila Tester debe ofrecer selector de runtime: " + JSON.stringify(st));

    // Bug corregido (2026-08-18): el rol tester SÍ está registrado en el
    // backend — elegir runtime habilita el botón Lanzar (antes quedaba
    // siempre deshabilitado como si el rol no existiera).
    const runtimeSelected = await _selectRuntimeForRow(page, "Tester", "opencode");
    assert.ok(runtimeSelected, "No se encontró el selector de runtime en la fila Tester.");
    await new Promise((r) => setTimeout(r, 200));
    st = await _rowState(page, "Tester");
    assert.strictEqual(st.launchDisabled, false, "Lanzar de Tester debe habilitarse al elegir runtime: " + JSON.stringify(st));
  });
}

module.exports = [
  {
    name: "slots fijos de Developer: tras matar Developer-2 no aparece Developer-4, las posiciones no se mueven y el slot se relanza con developer_number=2",
    fn: test_fixed_slots_no_developer_4_and_independent_launch,
  },
  {
    name: "Tester: elegir runtime habilita el botón Lanzar (rol registrado en el backend)",
    fn: test_tester_launch_enables_when_runtime_selected,
  },
];