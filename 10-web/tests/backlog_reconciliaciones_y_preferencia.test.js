/* T-AF022-US18-04 (US-AF022-18, criterio 6): el toggle
 * `auto_reenqueue_orphaned` en Configuración persiste la preferencia vía
 * PUT /system/preferences y refleja el valor cargado.
 *
 * (El panel "Reconciliaciones" del Backlog — la otra mitad de la US — se
 * retiró de la pantalla por decisión de producto el 2026-08-25: mostraba
 * el histórico del `reconciliation_log.jsonl` como trazas en la cabecera.)
 *
 * Navegador real (Chromium) contra el backend aislado; SOLO se intercambia
 * el estado de datos de GET/PUT /system/preferences (nunca la lógica). */

"use strict";

const assert = require("assert");
const { withBackend, waitVisible } = require("./harness");

function _intercept(page, state) {
  return page.setRequestInterception(true).then(() => {
    page.on("request", (req) => {
      if (!req.isNavigationRequest() && req.method() === "GET" && /\/system\/preferences$/.test(req.url())) {
        req.respond({ status: 200, contentType: "application/json", body: JSON.stringify(state.prefs) });
        return;
      }
      if (!req.isNavigationRequest() && req.method() === "PUT" && /\/system\/preferences$/.test(req.url())) {
        let body = {};
        try { body = JSON.parse(req.postData() || "{}"); } catch (_e) {}
        Object.assign(state.prefs, body);
        req.respond({ status: 200, contentType: "application/json", body: JSON.stringify(state.prefs) });
        return;
      }
      req.continue();
    });
  });
}

async function _goToTab(page, labelPrefix) {
  await waitVisible(page, ".section-tab");
  const clicked = await page.evaluate((prefix) => {
    const tab = Array.from(document.querySelectorAll(".section-tab")).find((el) =>
      (el.textContent || "").trim().startsWith(prefix)
    );
    if (tab) { tab.click(); return true; }
    return false;
  }, labelPrefix);
  if (!clicked) throw new Error("No se encontró la pestaña '" + labelPrefix + "'.");
}

// -------------------------------------------------------------------------
// Toggle en Configuración: activar "Reencolar automáticamente las huérfanas"
// persiste `auto_reenqueue_orphaned: true` vía PUT.
// -------------------------------------------------------------------------

async function test_toggle_auto_reenqueue_orphaned_persiste() {
  await withBackend(async ({ page, baseUrl }) => {
    const state = {
      prefs: { max_simultaneous_developers: 3, auto_reenqueue_orphaned: false },
    };
    await _intercept(page, state);
    await page.goto(baseUrl + "/ui/");
    await _goToTab(page, "Configuración");
    await page.waitForFunction(() => {
      const labels = Array.from(document.querySelectorAll(".model-role-label, label"));
      return labels.some((l) => l.textContent.includes("Reencolar automáticamente las huérfanas"));
    }, { timeout: 10000 });

    // Marcar el checkbox (activar).
    await page.evaluate(() => {
      const label = Array.from(document.querySelectorAll("label")).find((l) =>
        l.textContent.includes("Reencolar automáticamente las huérfanas")
      );
      const cb = label ? label.querySelector('input[type="checkbox"]') : null;
      if (cb && !cb.checked) {
        cb.checked = true;
        cb.dispatchEvent(new Event("change", { bubbles: true }));
      }
    });
    await new Promise((r) => setTimeout(r, 800));

    assert.strictEqual(state.prefs.auto_reenqueue_orphaned, true, "El PUT debe persistir auto_reenqueue_orphaned=true.");
  });
}

// -------------------------------------------------------------------------
// Toggle en Configuración: con `auto_reenqueue_orphaned: true` ya cargado, el
// checkbox se pinta MARCADO (el getter de preferencias alimenta el checked).
// -------------------------------------------------------------------------

async function test_toggle_auto_reenqueue_refleja_estado_previo_true() {
  await withBackend(async ({ page, baseUrl }) => {
    const state = {
      prefs: { max_simultaneous_developers: 3, auto_reenqueue_orphaned: true },
    };
    await _intercept(page, state);
    await page.goto(baseUrl + "/ui/");
    await _goToTab(page, "Configuración");
    await page.waitForFunction(() => {
      const labels = Array.from(document.querySelectorAll(".model-role-label, label"));
      return labels.some((l) => l.textContent.includes("Reencolar automáticamente las huérfanas"));
    }, { timeout: 10000 });

    // Sin tocar nada: el checkbox debe estar marcado porque la preferencia
    // cargada desde GET /system/preferences es `true`.
    const checked = await page.evaluate(() => {
      const label = Array.from(document.querySelectorAll("label")).find((l) =>
        l.textContent.includes("Reencolar automáticamente las huérfanas")
      );
      const cb = label ? label.querySelector('input[type="checkbox"]') : null;
      return cb ? cb.checked : null;
    });
    assert.strictEqual(checked, true, "Con auto_reenqueue_orphaned=true cargado, el checkbox debe pintarse marcado.");
    assert.strictEqual(state.prefs.auto_reenqueue_orphaned, true, "No debe haberse disparado ningún PUT (lectura inicial).");
  });
}

module.exports = [
  {
    name: "T-AF022-US18-04 · el toggle auto_reenqueue_orphaned en Configuración persiste vía PUT",
    fn: test_toggle_auto_reenqueue_orphaned_persiste,
  },
  {
    name: "T-AF022-US18-04 · con auto_reenqueue_orphaned=true cargado, el checkbox se pinta marcado",
    fn: test_toggle_auto_reenqueue_refleja_estado_previo_true,
  },
];