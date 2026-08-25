/* T-AF036-US27-02 (US-AF036-27): la sección Configuración muestra el selector
 * de modo de expansión del backlog ("single"/"multi") con el valor cargado
 * desde GET /system/preferences, persiste vía PUT y no rompe el campo de
 * "Máximo de Developer simultáneos". Verificado en navegador real. */

"use strict";

const assert = require("assert");
const { withBackend, waitVisible } = require("./harness");

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

async function test_expansion_selector_cargado_y_guardado() {
  let prefs = { max_simultaneous_developers: 3, backlog_multiple_expansion: "single" };

  await withBackend(async ({ page, baseUrl }) => {
    await page.setRequestInterception(true);
    page.on("request", (req) => {
      if (req.method() === "GET" && /\/system\/preferences$/.test(req.url())) {
        req.respond({ status: 200, contentType: "application/json", body: JSON.stringify(prefs) });
        return;
      }
      if (req.method() === "PUT" && /\/system\/preferences$/.test(req.url())) {
        let body = {};
        try { body = JSON.parse(req.postData() || "{}"); } catch (_e) {}
        prefs = { ...prefs, ...body };
        req.respond({ status: 200, contentType: "application/json", body: JSON.stringify(prefs) });
        return;
      }
      req.continue();
    });

    await page.goto(baseUrl + "/ui/");
    await _goToTab(page, "Configuración");
    await page.waitForFunction(() => {
      const labels = Array.from(document.querySelectorAll(".model-role-label"));
      return labels.some((l) => l.textContent.includes("Despliegue del Backlog"));
    }, { timeout: 10000 });

    // El selector muestra el valor cargado ("single").
    const selectValue = await page.evaluate(() => {
      const row = Array.from(document.querySelectorAll(".model-row")).find((r) =>
        r.textContent.includes("Despliegue del Backlog")
      );
      const sel = row ? row.querySelector("select") : null;
      return sel ? sel.value : null;
    });
    assert.strictEqual(selectValue, "single", "el selector debe cargar 'single'");

    // Cambiar a "multi" y guardar -> PUT persiste y el estado refleja el valor.
    await page.evaluate(() => {
      const row = Array.from(document.querySelectorAll(".model-row")).find((r) =>
        r.textContent.includes("Despliegue del Backlog")
      );
      const sel = row.querySelector("select");
      sel.value = "multi";
      sel.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await page.waitForFunction(() => {
      const btn = Array.from(document.querySelectorAll("button")).find((b) => b.textContent.trim() === "Guardar preferencias");
      return btn && !btn.disabled;
    }, { timeout: 10000 });
    await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll("button")).find((b) => b.textContent.trim() === "Guardar preferencias");
      if (btn) btn.click();
    });
    await new Promise((r) => setTimeout(r, 800));
    assert.strictEqual(prefs.backlog_multiple_expansion, "multi", "el PUT debe persistir 'multi'");

    // Tras el éxito, el estado del formulario refleja "multi" y sin cambios pendientes.
    await page.waitForFunction(() => {
      const row = Array.from(document.querySelectorAll(".model-row")).find((r) =>
        r.textContent.includes("Despliegue del Backlog")
      );
      const sel = row ? row.querySelector("select") : null;
      return sel && sel.value === "multi";
    }, { timeout: 10000 });
    const note = await page.evaluate(() =>
      Array.from(document.querySelectorAll(".section-note")).some((n) => n.textContent.includes("Sin cambios pendientes"))
    );
    assert.ok(note, "tras guardar debe mostrarse 'Sin cambios pendientes'");
  });
}

async function test_expansion_no_rompe_campo_developer() {
  let prefs = { max_simultaneous_developers: 3, backlog_multiple_expansion: "single" };

  await withBackend(async ({ page, baseUrl }) => {
    await page.setRequestInterception(true);
    page.on("request", (req) => {
      if (req.method() === "GET" && /\/system\/preferences$/.test(req.url())) {
        req.respond({ status: 200, contentType: "application/json", body: JSON.stringify(prefs) });
        return;
      }
      if (req.method() === "PUT" && /\/system\/preferences$/.test(req.url())) {
        let body = {};
        try { body = JSON.parse(req.postData() || "{}"); } catch (_e) {}
        prefs = { ...prefs, ...body };
        req.respond({ status: 200, contentType: "application/json", body: JSON.stringify(prefs) });
        return;
      }
      req.continue();
    });

    await page.goto(baseUrl + "/ui/");
    await _goToTab(page, "Configuración");
    await page.waitForFunction(() => {
      const labels = Array.from(document.querySelectorAll(".model-role-label"));
      return labels.some((l) => l.textContent.includes("Máximo de Developer"));
    }, { timeout: 10000 });

    // El campo de máximos sigue presente e independiente.
    const maxPresent = await page.evaluate(() =>
      Array.from(document.querySelectorAll(".model-role-label")).some((l) =>
        l.textContent.includes("Máximo de Developer")
      )
    );
    assert.ok(maxPresent, "el campo 'Máximo de Developer' debe seguir presente");

    // Cambiar solo el máximo y guardar: el payload incluye max, no la expansión.
    await page.evaluate(() => {
      const input = document.querySelector('input[type="number"]');
      input.value = "5";
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await page.waitForFunction(() => {
      const btn = Array.from(document.querySelectorAll("button")).find((b) => b.textContent.trim() === "Guardar preferencias");
      return btn && !btn.disabled;
    }, { timeout: 10000 });
    await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll("button")).find((b) => b.textContent.trim() === "Guardar preferencias");
      if (btn) btn.click();
    });
    await new Promise((r) => setTimeout(r, 800));
    assert.strictEqual(prefs.max_simultaneous_developers, 5, "el PUT debe persistir el nuevo máximo");
    assert.strictEqual(prefs.backlog_multiple_expansion, "single", "la expansión no debe cambiar si no se tocó");
  });
}

module.exports = [
  {
    name: "T-AF036-US27-02: el selector de modo de expansión carga, guarda vía PUT y refleja el valor",
    fn: test_expansion_selector_cargado_y_guardado,
  },
  {
    name: "T-AF036-US27-02: el campo de Developer no se rompe y guarda de forma independiente",
    fn: test_expansion_no_rompe_campo_developer,
  },
];