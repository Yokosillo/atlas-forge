/* T-AF036-US21-02 (US-AF036-21): el buscador de texto coincide también con
 * el TÍTULO de los items (Epic via `epic_label`, US/Task via `title` expuesto
 * en el informe raíz) — no solo con el ID — y el selector de estado incluye el
 * vocabulario completo del modelo (NO_TASKS, TO_PLAN, OUT_OF_SCOPE), además
 * de "Bloqueadas" como opción especial. Verificado en navegador real
 * (Chromium) contra el backend aislado. */

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
    await post("/backlog/epic", { id: "AF-997", title: "Auditoría de seguridad", objetivo: "Auditar el producto." });
    await post("/backlog/epic/AF-997/us", { id: "US-AF997-01", title: "Gestión de auditorías", objetivo: "Centralizar hallazgos.", criterios_aceptacion: "C." });
    await post("/backlog/us/US-AF997-01/task", {
      id: "T-AF997-US01-01", title: "Persistencia de hallazgos de auditoría",
      objetivo: "Guardar hallazgos.", descripcion: "D.", criterios_aceptacion: "C.", priority: "Alta",
    });
  });
}

async function _epicRowsText(page) {
  return page.evaluate(() =>
    Array.from(document.querySelectorAll(".backlog-epic-line")).map((l) => l.textContent)
  );
}

// ── Criterio: buscar por una palabra del TÍTULO de una US/Task/Epic ──

async function test_busqueda_coincide_con_titulo() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await _seed(page);
    await _goToBacklogTab(page);
    await waitVisible(page, ".backlog-epic-line");

    // Búsqueda por una palabra del título de la Epic ("seguridad").
    await page.click(".backlog-filter-search");
    await page.type(".backlog-filter-search", "seguridad");
    await page.waitForFunction(() => {
      const bar = document.querySelector(".backlog-filter-bar");
      return bar && bar.querySelector(".backlog-filter-clear");
    }, { timeout: 10000 });
    let rows = await _epicRowsText(page);
    assert.ok(rows.some((t) => t.includes("AF-997")), "Buscar por título de Epic debe encontrar AF-997: " + JSON.stringify(rows));

    // Búsqueda por una palabra del título de la US ("auditorías").
    await page.click(".backlog-filter-search");
    await page.evaluate(() => {
      const i = document.querySelector(".backlog-filter-search");
      i.value = "";
      i.dispatchEvent(new Event("input"));
    });
    await page.type(".backlog-filter-search", "auditorías");
    await page.waitForFunction(() => {
      const i = document.querySelector(".backlog-filter-search");
      return i && i.value === "auditorías";
    }, { timeout: 10000 });
    await page.waitForFunction(() => {
      const bar = document.querySelector(".backlog-filter-bar");
      return bar && bar.querySelector(".backlog-filter-clear");
    }, { timeout: 10000 });
    rows = await _epicRowsText(page);
    assert.ok(rows.some((t) => t.includes("AF-997")), "Buscar por título de US debe encontrar AF-997: " + JSON.stringify(rows));

    // Búsqueda por una palabra del título de la Task ("hallazgos").
    await page.evaluate(() => {
      const i = document.querySelector(".backlog-filter-search");
      i.value = "";
      i.dispatchEvent(new Event("input"));
    });
    await page.type(".backlog-filter-search", "hallazgos");
    await page.waitForFunction(() => {
      const bar = document.querySelector(".backlog-filter-bar");
      return bar && bar.querySelector(".backlog-filter-clear");
    }, { timeout: 10000 });
    rows = await _epicRowsText(page);
    assert.ok(rows.some((t) => t.includes("AF-997")), "Buscar por título de Task debe encontrar AF-997: " + JSON.stringify(rows));
  });
}

// ── Criterio: el selector de estado incluye NO_TASKS/TO_PLAN/OUT_OF_SCOPE ──

async function test_selector_estado_incluye_vocabulario_completo() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await _seed(page);
    await _goToBacklogTab(page);
    await waitVisible(page, ".backlog-filter-bar");

    const stateOptions = await page.evaluate(() => {
      const bar = document.querySelector(".backlog-filter-bar");
      const sel = bar && bar.querySelector("select.backlog-filter-select");
      if (!sel) return [];
      return Array.from(sel.querySelectorAll("option")).map((o) => o.value);
    });
    for (const v of ["NO_TASKS", "TO_PLAN", "OUT_OF_SCOPE"]) {
      assert.ok(stateOptions.includes(v), "El selector de estado debe incluir '" + v + "': " + JSON.stringify(stateOptions));
    }
    assert.ok(stateOptions.includes("blocked"), "Debe mantenerse la opción especial 'Bloqueadas': " + JSON.stringify(stateOptions));

    // Filtrar por OUT_OF_SCOPE no rompe (opción seleccionable, sin resultados = limpiar).
    await page.evaluate(() => {
      const bar = document.querySelector(".backlog-filter-bar");
      const sel = bar.querySelector("select.backlog-filter-select");
      sel.value = "OUT_OF_SCOPE";
      sel.dispatchEvent(new Event("change"));
    });
    await page.waitForFunction(() => {
      const bar = document.querySelector(".backlog-filter-bar");
      return bar && bar.querySelector(".backlog-filter-clear");
    }, { timeout: 10000 });
    const filterEmptyShown = await page.evaluate(() =>
      Array.from(document.querySelectorAll(".section-note")).some((n) =>
        n.textContent.includes("Sin resultados para este filtro")
      )
    );
    assert.ok(filterEmptyShown, "Filtrar por OUT_OF_SCOPE (sin coincidencias) debe mostrar el estado 'sin resultados' sin romper");
  });
}

module.exports = [
  {
    name: "T-AF036-US21-02: buscar por una palabra del título de Epic/US/Task encuentra la Epic",
    fn: test_busqueda_coincide_con_titulo,
  },
  {
    name: "T-AF036-US21-02: el selector de estado incluye NO_TASKS/TO_PLAN/OUT_OF_SCOPE y Bloqueadas",
    fn: test_selector_estado_incluye_vocabulario_completo,
  },
];