/* T-AF036-US26-02 (US-AF036-26): la web habla de versión (no fase) en
 * cabeceras, filtro/selector y la vista de agrupación. Verificado en
 * navegador real (Chromium) contra el backend aislado. */

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

async function _seed(page) {
  await page.evaluate(async () => {
    const post = async (p, b) => {
      const r = await fetch(p, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(b),
      });
      if (!r.ok) throw new Error("POST " + p + " falló: " + r.status);
    };
    await post("/backlog/epic", { id: "AF-996", title: "Migración a versión", objetivo: "O." });
    await post("/backlog/epic/AF-996/us", { id: "US-AF996-01", title: "Mostrar versión", objetivo: "H.", criterios_aceptacion: "C." });
    await post("/backlog/us/US-AF996-01/task", {
      id: "T-AF996-US01-01", title: "Cabecera con versión", objetivo: "O.", descripcion: "D.",
      criterios_aceptacion: "C.", priority: "Alta",
    });
  });
}

async function test_cabeceras_muestran_version_y_no_fase() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await _seed(page);
    await _goToBacklogTab(page);
    await page.evaluate(() => {
      const line = Array.from(document.querySelectorAll(".backlog-epic-line")).find((l) => l.textContent.includes("AF-996"));
      if (line) line.click();
    });
    await page.waitForFunction(() => document.querySelector(".backlog-us-line-title") !== null, { timeout: 10000 });

    const meta = await page.evaluate(() => {
      const el = document.querySelector(".backlog-us-line-meta");
      return el ? el.textContent : "";
    });
    assert.ok(/\[versión:/.test(meta), "La cabecera de US debe mostrar '[versión:': " + meta);
    assert.ok(!/\[fase:/.test(meta), "La cabecera de US no debe mostrar '[fase:': " + meta);
  });
}

async function test_vista_por_version_y_filtro_de_version() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await _seed(page);
    await _goToBacklogTab(page);
    await waitVisible(page, ".backlog-filter-bar");

    // El toggle de vista se llama "Por Versión" (no "Por Fase").
    const toggleTexts = await page.evaluate(() =>
      Array.from(document.querySelectorAll(".backlog-view-toggle")).map((b) => b.textContent.trim())
    );
    assert.ok(toggleTexts.some((t) => t === "Por Versión"), "El toggle debe llamarse 'Por Versión': " + JSON.stringify(toggleTexts));
    assert.ok(!toggleTexts.some((t) => t === "Por Fase"), "No debe haber toggle 'Por Fase'");

    // El selector de versión existe y lista versiones (0.9 + SIN VERSIÓN).
    const versionOptions = await page.evaluate(() => {
      const bar = document.querySelector(".backlog-filter-bar");
      const selects = bar ? Array.from(bar.querySelectorAll("select.backlog-filter-select")) : [];
      const ver = selects.find((s) => Array.from(s.querySelectorAll("option")).some((o) => o.value === "SIN_VERSION" || o.label === "SIN VERSIÓN"));
      return ver ? Array.from(ver.querySelectorAll("option")).map((o) => o.value) : [];
    });
    assert.ok(versionOptions.length > 0, "Debe existir un selector de versión con opciones: " + JSON.stringify(versionOptions));
    assert.ok(versionOptions.includes("0.9") || versionOptions.includes("SIN_VERSION"), "El selector debe listar versiones (0.9/SIN VERSIÓN): " + JSON.stringify(versionOptions));

    // No queda texto "fase" visible en la pantalla Backlog.
    const visibleFase = await page.evaluate(() =>
      Array.from(document.querySelectorAll(".section-content *")).some((el) => {
        const t = el.childNodes.length === 1 && el.textContent;
        return t && /fase/i.test(t);
      })
    );
    assert.strictEqual(visibleFase, false, "No debe quedar ningún texto 'fase' visible en la pantalla Backlog");
  });
}

module.exports = [
  {
    name: "T-AF036-US26-02: las cabeceras muestran versión y no '[fase:'",
    fn: test_cabeceras_muestran_version_y_no_fase,
  },
  {
    name: "T-AF036-US26-02: la vista es 'Por Versión', hay filtro de versión y no queda texto 'fase'",
    fn: test_vista_por_version_y_filtro_de_version,
  },
];