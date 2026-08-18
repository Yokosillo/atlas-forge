/* T-FB037-US05-02 (US-FB037-05): el botón "Reiniciar Brain" de la
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

    // El botón "Reiniciar Brain" aparece en la sección.
    await waitVisible(page, "button");
    await page.waitForFunction(
      () =>
        Array.from(document.querySelectorAll("button")).some(
          (b) => b.textContent.trim() === "Reiniciar Brain"
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
        (b) => b.textContent.trim() === "Reiniciar Brain"
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

module.exports = [
  {
    name: "el botón Reiniciar Brain exige doble pulsación, llama al endpoint y muestra éxito al recuperarse",
    fn: test_restart_brain_button_requires_double_click_and_polls_until_recovery,
  },
];