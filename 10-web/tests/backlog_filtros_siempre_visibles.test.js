/* T-AF036-US21-01 (US-AF036-21): la barra de búsqueda y filtros está
 * siempre visible en la vista Backlog — también con backlog vacío y
 * mientras el informe carga o no tiene items — sin depender de que haya
 * una Epic que listar ni de abrir un formulario de creación.
 *
 * Antes del fix, `renderBacklogViewToggle` (`10-web/app.js`) solo llamaba
 * a `renderBacklogFilterBar(wrap)` en la rama con report no vacío: con
 * backlog vacío o cargando la barra no se pintaba y solo aparecía al
 * crear la primera Epic.
 *
 * Este test verifica en navegador real (Chromium) contra el backend real
 * aislado (vacío de serie, `withBackend` del `tests/README.md`):
 *   - con backlog vacío la barra (búsqueda + selectores) está visible;
 *   - activar un filtro muestra "Limpiar filtros", que sigue funcionando
 *     sin que la barra desaparezca;
 *   - abrir y cancelar el formulario "+ Nueva Epic" no oculta ni resetea
 *     la barra de filtros. */

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
  throw new Error("No se encontró la pestaña 'Backlog' en la navegación.");
}

async function _countFilterSelects(page) {
  return page.evaluate(() => {
    const bar = document.querySelector(".backlog-filter-bar");
    if (!bar) return 0;
    return bar.querySelectorAll("select.backlog-filter-select").length;
  });
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
    await post("/backlog/epic", { id: "AF-998", title: "Gestión de auditorías", objetivo: "O." });
    await post("/backlog/epic/AF-998/us", { id: "US-AF998-01", title: "Centralizar hallazgos", objetivo: "H.", criterios_aceptacion: "C." });
    await post("/backlog/us/US-AF998-01/task", {
      id: "T-AF998-US01-01", title: "Persistir hallazgos", objetivo: "O.", descripcion: "D.",
      criterios_aceptacion: "C.", priority: "Alta",
    });
  });
}

async function _hasClearFilter(page) {
  return page.evaluate(() => {
    const bar = document.querySelector(".backlog-filter-bar");
    return bar !== null && bar.querySelector(".backlog-filter-clear") !== null;
  });
}

// T-AF036-US21-04: abrir/cerrar "+ Nueva User Story" y "+ Nueva Task" no debe
// ocultar ni resetear la barra de filtros (mismo criterio que "+ Nueva Epic").
async function test_formularios_us_y_task_no_ocultan_ni_resetean_filtros() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await _seed(page);
    await _goToBacklogTab(page);
    await waitVisible(page, ".backlog-filter-bar");
    await waitVisible(page, ".backlog-epic-line");

    // Activar un filtro (búsqueda) antes de abrir los formularios.
    await page.click(".backlog-filter-search");
    await page.type(".backlog-filter-search", "auditorías");
    await page.waitForFunction(() => {
      const bar = document.querySelector(".backlog-filter-bar");
      return bar !== null && bar.querySelector(".backlog-filter-clear") !== null;
    }, { timeout: 10000 });

    // Abrir la Epic y su US para llegar a los formularios.
    await page.evaluate(() => {
      const line = Array.from(document.querySelectorAll(".backlog-epic-line")).find((l) => l.textContent.includes("AF-998"));
      if (line) line.click();
    });
    await page.waitForFunction(() => document.querySelector(".backlog-us-line") !== null, { timeout: 10000 });

    // "+ Nueva User Story" (dentro del detalle de la Epic).
    await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll("button")).find((b) => b.textContent.trim() === "+ Nueva User Story");
      if (btn) btn.click();
    });
    await waitVisible(page, ".jobs-form");
    await waitVisible(page, ".backlog-filter-bar");
    assert.ok(await _hasClearFilter(page), "Abrir '+ Nueva User Story' no debe resetear el filtro activo");
    assert.strictEqual(await _countFilterSelects(page), 3, "Abrir '+ Nueva User Story' no debe ocultar los selectores");

    // Cancelar el formulario de US.
    await page.evaluate(() => {
      const form = document.querySelector(".jobs-form");
      if (!form) return;
      const btn = Array.from(form.querySelectorAll("button")).find((b) => b.textContent.trim() === "Cancelar");
      if (btn) btn.click();
    });
    await waitVisible(page, ".backlog-filter-bar");
    assert.ok(await _hasClearFilter(page), "Cancelar '+ Nueva User Story' no debe resetear el filtro activo");

    // Abrir la US para ver su lista de Tasks y el botón "+ Nueva Task".
    await page.evaluate(() => {
      const line = Array.from(document.querySelectorAll(".backlog-us-line")).find((l) => l.textContent.includes("US-AF998-01"));
      if (line) line.click();
    });
    await page.waitForFunction(() => {
      return Array.from(document.querySelectorAll("button")).some((b) => b.textContent.trim() === "+ Nueva Task");
    }, { timeout: 10000 });

    // "+ Nueva Task".
    await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll("button")).find((b) => b.textContent.trim() === "+ Nueva Task");
      if (btn) btn.click();
    });
    await waitVisible(page, ".backlog-filter-bar");
    assert.ok(await _hasClearFilter(page), "Abrir '+ Nueva Task' no debe resetear el filtro activo");
    assert.strictEqual(await _countFilterSelects(page), 3, "Abrir '+ Nueva Task' no debe ocultar los selectores");
  });
}

async function test_filtros_visibles_con_backlog_vacio() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await _goToBacklogTab(page);

    // Backlog vacío: la barra de filtros está visible (el bug omitía la barra
    // en este caso — el criterio de aceptación 1). La vista por defecto es
    // "Por Versión" (T-AF036-US26-06), así que no se exige el mensaje del
    // listado plano.
    await waitVisible(page, ".backlog-filter-bar");

    // La barra trae la búsqueda + los selectores de estado, prioridad y
    // fase (sin la fase dinámica "SIN_ASIGNAR" al no haber Epics).
    const searchVisible = await page.evaluate(() => {
      const bar = document.querySelector(".backlog-filter-bar");
      return bar !== null && bar.querySelector("input.backlog-filter-search") !== null;
    });
    assert.ok(searchVisible, "Con backlog vacío debe haber búsqueda en la barra de filtros.");
    assert.strictEqual(await _countFilterSelects(page), 3, "Debe haber 3 selectores (estado/prioridad/fase) con backlog vacío.");

    // Activar un filtro (teclear en la búsqueda) → "Limpiar filtros" debe
    // aparecer y seguir funcionando sin que la barra desaparezca.
    await page.click(".backlog-filter-search");
    await page.type(".backlog-filter-search", "nada-que-ver");
    await page.waitForFunction(
      () => {
        const bar = document.querySelector(".backlog-filter-bar");
        return bar !== null && bar.querySelector(".backlog-filter-clear") !== null;
      },
      { timeout: 10000 }
    );
    assert.strictEqual(await _countFilterSelects(page), 3, "Los selectores deben seguir tras activar un filtro.");

    const cleared = await page.evaluate(() => {
      const bar = document.querySelector(".backlog-filter-bar");
      const btn = bar && bar.querySelector(".backlog-filter-clear");
      if (!btn) return false;
      btn.click();
      return true;
    });
    assert.ok(cleared, "Debe existir el botón 'Limpiar filtros' con un filtro activo.");

    // Tras limpiar: la barra sigue visible y el "Limpiar filtros"
    // desaparece (no hay filtros activos).
    await waitVisible(page, ".backlog-filter-bar");
    await page.waitForFunction(
      () => {
        const bar = document.querySelector(".backlog-filter-bar");
        return bar !== null && bar.querySelector(".backlog-filter-clear") === null;
      },
      { timeout: 10000 }
    );
    assert.strictEqual(await _countFilterSelects(page), 3, "La barra debe conservar sus selectores tras limpiar.");
  });
}

async function test_formulario_no_oculta_ni_resetea_filtros() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await _goToBacklogTab(page);

    // Backlog vacío con barra de filtros visible.
    await waitVisible(page, ".backlog-filter-bar");
    await waitVisible(page, ".backlog-new-epic-btn");

    // Activar un filtro antes de abrir el formulario.
    await page.click(".backlog-filter-search");
    await page.type(".backlog-filter-search", "texto");
    await page.waitForFunction(
      () => {
        const bar = document.querySelector(".backlog-filter-bar");
        return bar !== null && bar.querySelector(".backlog-filter-clear") !== null;
      },
      { timeout: 10000 }
    );

    // Abrir "+ Nueva Epic": el formulario aparece, pero la barra sigue
    // visible y conserva el filtro activo (criterio de aceptación 2).
    await page.click(".backlog-new-epic-btn");
    await waitVisible(page, ".jobs-form");
    await waitVisible(page, ".backlog-filter-bar");
    const selectorsAfterOpen = await _countFilterSelects(page);
    assert.strictEqual(selectorsAfterOpen, 3, "Abrir el formulario no debe ocultar la barra de filtros.");
    const clearStillThere = await page.evaluate(() => {
      const bar = document.querySelector(".backlog-filter-bar");
      return bar !== null && bar.querySelector(".backlog-filter-clear") !== null;
    });
    assert.ok(clearStillThere, "Abrir el formulario no debe resetear el filtro activo.");

    // Cancelar el formulario: la barra sigue visible y con su filtro.
    const cancelled = await page.evaluate(() => {
      const form = document.querySelector(".jobs-form");
      if (!form) return false;
      const btn = Array.from(form.querySelectorAll("button")).find(
        (b) => b.textContent.trim() === "Cancelar"
      );
      if (!btn) return false;
      btn.click();
      return true;
    });
    assert.ok(cancelled, "Debe existir el botón 'Cancelar' en el formulario.");
    await page.waitForFunction(
      () => document.querySelector(".jobs-form") === null,
      { timeout: 10000 }
    );
    await waitVisible(page, ".backlog-filter-bar");
    assert.strictEqual(await _countFilterSelects(page), 3, "Cancelar el formulario no debe ocultar la barra de filtros.");
    const clearAfterCancel = await page.evaluate(() => {
      const bar = document.querySelector(".backlog-filter-bar");
      return bar !== null && bar.querySelector(".backlog-filter-clear") !== null;
    });
    assert.ok(clearAfterCancel, "Cancelar el formulario no debe resetear el filtro activo.");
  });
}

module.exports = [
  {
    name: "la barra de búsqueda y filtros está visible con backlog vacío y 'Limpiar filtros' funciona",
    fn: test_filtros_visibles_con_backlog_vacio,
  },
  {
    name: "abrir y cancelar '+ Nueva Epic' no oculta ni resetea la barra de filtros",
    fn: test_formulario_no_oculta_ni_resetea_filtros,
  },
  {
    name: "T-AF036-US21-04: abrir/cancelar '+ Nueva User Story' y '+ Nueva Task' no oculta ni resetea la barra de filtros",
    fn: test_formularios_us_y_task_no_ocultan_ni_resetean_filtros,
  },
];