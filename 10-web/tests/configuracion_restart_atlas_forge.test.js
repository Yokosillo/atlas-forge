/* T-AF037-US05-02 (US-AF037-05): el botón "Reiniciar Atlas Forge" de la
 * pantalla Configuración exige confirmación de doble pulsación, llama a
 * `POST /system/restart` (fire-and-forget, 202) y hace polling a
 * `GET /agents` hasta que el backend vuelve a responder, mostrando un
 * mensaje de éxito explícito al recuperarse.
 *
 * El `POST /system/restart` se intercepta y se responde 202 de forma
 * determinista (en el backend aislado el `sudo systemctl` real no debe
 * ejecutarse nunca). El polling de `GET /agents` sí golpea el backend
 * aislado real, que devuelve el mismo nº de agentes antes y después —
 * el flujo completo termina en el mensaje de éxito. */

"use strict";

const assert = require("assert");
const { withBackend, waitVisible } = require("./harness");

async function test_restart_brain_button_requires_double_click_and_polls_until_recovery() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await waitVisible(page, ".section-tab");

    const tabs = await page.$$(".section-tab");
    let configTab = null;
    for (const tab of tabs) {
      const text = await page.evaluate((el) => el.textContent, tab);
      if (text.trim().startsWith("Configuración")) {
        configTab = tab;
        break;
      }
    }
    assert.ok(configTab, "No se encontró la pestaña 'Configuración'.");
    await configTab.click();

    // El botón "Reiniciar Atlas Forge" aparece en la sección.
    await waitVisible(page, "button");
    await page.waitForFunction(
      () =>
        Array.from(document.querySelectorAll("button")).some(
          (b) => b.textContent.trim() === "Reiniciar Atlas Forge"
        ),
      { timeout: 10000 }
    );

    // Interceptar el POST /system/restart y responder 202 (fire-and-forget).
    let restartRequested = false;
    await page.setRequestInterception(true);
    page.on("request", (req) => {
      if (req.method() === "POST" && /\/system\/restart$/.test(req.url())) {
        restartRequested = true;
        req.respond({
          status: 202,
          contentType: "application/json",
          body: JSON.stringify({ status: "restarting" }),
        });
        return;
      }
      req.continue();
    });

    // Primera pulsación: pide confirmación, no reinicia todavía.
    await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll("button")).find(
        (b) => b.textContent.trim() === "Reiniciar Atlas Forge"
      );
      btn.click();
    });
    await page.waitForFunction(
      () =>
        Array.from(document.querySelectorAll("button")).some(
          (b) => b.textContent.trim() === "¿Seguro? Confirmar reinicio"
        ),
      { timeout: 5000 }
    );
    assert.strictEqual(restartRequested, false, "No debe llamarse al endpoint antes de confirmar.");

    // Segunda pulsación: confirma y lanza el reinicio.
    await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll("button")).find(
        (b) => b.textContent.trim() === "¿Seguro? Confirmar reinicio"
      );
      btn.click();
    });

    // Tras el 202 se muestra "Reiniciando…" y arranca el polling. El POST
    // va tras capturar el nº de agentes (`getAgents`), así que se espera
    // la petición real en vez de asumir que ya llegó.
    await page.waitForRequest(
      (req) => req.method() === "POST" && /\/system\/restart$/.test(req.url()),
      { timeout: 5000 }
    );
    assert.ok(restartRequested, "Debe haberse llamado a POST /system/restart tras confirmar.");
    await page.waitForFunction(
      () => document.body.textContent.includes("Reiniciando…"),
      { timeout: 5000 }
    );

    // El polling a GET /agents (backend aislado real, mismo nº de agentes)
    // termina en el mensaje de éxito explícito.
    await page.waitForFunction(
      () => document.body.textContent.includes("Reinicio completado"),
      { timeout: 15000 }
    );
  });
}

async function test_restart_brain_agent_count_mismatch_shows_reconciliation_warning() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await waitVisible(page, ".section-tab");

    const tabs = await page.$$(".section-tab");
    let configTab = null;
    for (const tab of tabs) {
      const text = await page.evaluate((el) => el.textContent, tab);
      if (text.trim().startsWith("Configuración")) {
        configTab = tab;
        break;
      }
    }
    assert.ok(configTab, "No se encontró la pestaña 'Configuración'.");
    await configTab.click();

    await page.waitForFunction(
      () =>
        Array.from(document.querySelectorAll("button")).some(
          (b) => b.textContent.trim() === "Reiniciar Atlas Forge"
        ),
      { timeout: 10000 }
    );

    // Interceptar la red para simular un reinicio con cambio de nº de
    // agentes: el `POST /system/restart` responde 202, y los `GET /agents`
    // tras el reinicio devuelven un número distinto del inicial.
    let agentsCalls = 0;
    await page.setRequestInterception(true);
    page.on("request", (req) => {
      if (req.method() === "POST" && /\/system\/restart$/.test(req.url())) {
        req.respond({
          status: 202,
          contentType: "application/json",
          body: JSON.stringify({ status: "restarting" }),
        });
        return;
      }
      if (req.method() === "GET" && /\/agents$/.test(req.url())) {
        agentsCalls += 1;
        // Primera llamada (antes del reinicio): 2 agentes. Posteriores
        // (polling tras reiniciar): 1 agente -> número distinto.
        const count = agentsCalls === 1 ? 2 : 1;
        req.respond({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(
            Array.from({ length: count }, (_, i) => ({
              id: "agent-" + i,
              name: "Agente " + (i + 1),
              role: "developer",
              status: "idle",
            }))
          ),
        });
        return;
      }
      req.continue();
    });

    // Doble pulsación: Reiniciar Atlas Forge -> ¿Seguro? Confirmar reinicio.
    await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll("button")).find(
        (b) => b.textContent.trim() === "Reiniciar Atlas Forge"
      );
      btn.click();
    });
    await page.waitForFunction(
      () =>
        Array.from(document.querySelectorAll("button")).some(
          (b) => b.textContent.trim() === "¿Seguro? Confirmar reinicio"
        ),
      { timeout: 5000 }
    );
    await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll("button")).find(
        (b) => b.textContent.trim() === "¿Seguro? Confirmar reinicio"
      );
      btn.click();
    });

    // El nº de agentes cambió tras el reinicio -> aviso explícito con la
    // referencia al log de reconciliación.
    await page.waitForFunction(
      () => document.body.textContent.includes("el número de agentes ha cambiado"),
      { timeout: 15000 }
    );
    await page.waitForFunction(
      () => document.body.textContent.includes("reconciliation_log.jsonl"),
      { timeout: 5000 }
    );
  });
}

module.exports = [
  {
    name: "el botón Reiniciar Atlas Forge exige doble pulsación, llama al endpoint y muestra éxito al recuperarse",
    fn: test_restart_brain_button_requires_double_click_and_polls_until_recovery,
  },
  {
    name: "un reinicio con cambio en el número de agentes muestra el aviso con referencia al log de reconciliación",
    fn: test_restart_brain_agent_count_mismatch_shows_reconciliation_warning,
  },
];