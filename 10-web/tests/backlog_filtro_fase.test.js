/* T-AF036-US11-01 (US-AF036-11): el filtro por fase del roadmap en la
 * barra de filtros del Backlog — selector dinámico con "Todas" + fases
 * presentes + "SIN_ASIGNAR", aplicación del filtro sobre el listado en las
 * vistas plana y "Por Fase", combinación con los filtros de texto, estado y
 * prioridad, y reset por "Limpiar". Verificado en navegador real (Chromium)
 * contra un backend real aislado (mismo patrón que el resto de la suite
 * `10-web/tests/`, `withBackend` del `tests/README.md`).
 *
 * El backlog se siembra vía HTTP (Epic + US + Task reales, T-AF036-US02-01/02/03);
 * el estado IN_PROGRESS de una Task se fija reescribiendo su fichero real con
 * `fs` (no hay endpoint HTTP que cambie el estado de una Task — el estado se
 * gestiona por la web, que es justo lo que este test NO quiere perturbar). */

"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const { withBackend, waitVisible, sleep } = require("./harness");

async function _goToTab(page, labelPrefix) {
  await waitVisible(page, ".section-tab");
  const tabs = await page.$$(".section-tab");
  for (const tab of tabs) {
    const text = await page.evaluate((el) => el.textContent, tab);
    if (text.trim().startsWith(labelPrefix)) {
      await tab.click();
      return;
    }
  }
  throw new Error(`No se encontró la pestaña '${labelPrefix}' en la navegación.`);
}

async function _seedEpic(page, epicId, title, fase) {
  await page.evaluate(
    async ({ epicId, title, fase }) => {
      const resp = await fetch("/backlog/epic", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          id: epicId,
          title: title,
          objetivo: "Objetivo real.",
          fase: fase,
        }),
      });
      if (!resp.ok) {
        throw new Error(
          "POST /backlog/epic falló: " + resp.status + " " + (await resp.text())
        );
      }
    },
    { epicId, title, fase }
  );
}

// T-AF036-US18-01: `POST /backlog/epic` ya NO almacena `fase` (la Epic se
// versiona con `version`). Para simular una Epic LEGACY que aún declara su
// fase en el fichero — que es lo que la vista "Por Fase" y el filtro siguen
// consumiendo hasta que US-AF036-15-06 migre a VERSION — se reescribe el
// frontmatter del fichero real con `fs` (mismo patrón que `_setUsFase` de
// `backlog_por_fase_filtra_us.test.js`).
function _writeEpicFase(projectPath, epicId, fase) {
  const epicsDir = path.join(projectPath, "02-backlog", "epics");
  const filename = fs.readdirSync(epicsDir).find((n) => n.startsWith(epicId + "-"));
  assert.ok(filename, "No se encontró el fichero de la Epic " + epicId + " en " + epicsDir);
  const epicPath = path.join(epicsDir, filename);
  const original = fs.readFileSync(epicPath, "utf-8");
  const idx = original.indexOf("\n---");
  assert.ok(idx > 0, "frontmatter no encontrado en " + epicPath);
  fs.writeFileSync(epicPath, original.slice(0, idx) + "\nfase: " + fase + original.slice(idx));
}

async function _seedUs(page, epicId, usId) {
  await page.evaluate(
    async ({ epicId, usId }) => {
      const resp = await fetch("/backlog/epic/" + epicId + "/us", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          id: usId,
          title: "US de " + epicId,
          objetivo: "H.",
          criterios_aceptacion: "C.",
          priority: null,
        }),
      });
      if (!resp.ok) {
        throw new Error(
          "POST /backlog/epic/{id}/us falló: " + resp.status + " " + (await resp.text())
        );
      }
    },
    { epicId, usId }
  );
}

async function _seedTask(page, usId, taskId, priority) {
  await page.evaluate(
    async ({ usId, taskId, priority }) => {
      const resp = await fetch("/backlog/us/" + usId + "/task", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          id: taskId,
          title: "Task de " + usId,
          objetivo: "Objetivo.",
          descripcion: "Descripción.",
          criterios_aceptacion: "Criterios.",
          priority: priority,
        }),
      });
      if (!resp.ok) {
        throw new Error(
          "POST /backlog/us/{id}/task falló: " + resp.status + " " + (await resp.text())
        );
      }
    },
    { usId, taskId, priority }
  );
}

// Siembra el escenario base del filtro de fase: dos Epics con fase distinta
// y una tercera sin fase.
async function _seedTresEpicsConFases(page, projectPath) {
  await _seedEpic(page, "AF-951", "Epic fase uno", "Fase 1.1");
  _writeEpicFase(projectPath, "AF-951", "Fase 1.1");
  await _seedUs(page, "AF-951", "US-AF951-01");
  await _seedTask(page, "US-AF951-01", "T-AF951-US01-01", "Crítica");

  await _seedEpic(page, "AF-952", "Epic fase dos", "Fase 2.0");
  _writeEpicFase(projectPath, "AF-952", "Fase 2.0");
  await _seedUs(page, "AF-952", "US-AF952-01");
  await _seedTask(page, "US-AF952-01", "T-AF952-US01-01", "Media");

  await _seedEpic(page, "AF-953", "Epic sin fase", null);
  await _seedUs(page, "AF-953", "US-AF953-01");
  await _seedTask(page, "US-AF953-01", "T-AF953-US01-01", "Crítica");
}

// Devuelve la info del select de la barra de filtros que tenga una opción con
// el valor marcador `markerValue` (fase -> "SIN_ASIGNAR", estado -> "blocked",
// prioridad -> "none"). Si no existe, devuelve null.
async function _selectInfo(page, markerValue) {
  return page.evaluate(
    (markerValue) => {
      const bar = document.querySelector(".backlog-filter-bar");
      if (!bar) return null;
      const selects = Array.from(bar.querySelectorAll("select.backlog-filter-select"));
      const sel = selects.find((s) =>
        Array.from(s.options).some((o) => o.value === markerValue)
      );
      if (!sel) return null;
      return {
        values: Array.from(sel.options).map((o) => o.value),
        value: sel.value,
      };
    },
    markerValue
  );
}

async function _setSelectValue(page, markerValue, newValue) {
  const applied = await page.evaluate(
    ({ markerValue, newValue }) => {
      const bar = document.querySelector(".backlog-filter-bar");
      if (!bar) return false;
      const selects = Array.from(bar.querySelectorAll("select.backlog-filter-select"));
      const sel = selects.find((s) =>
        Array.from(s.options).some((o) => o.value === markerValue)
      );
      if (!sel) return false;
      sel.value = newValue;
      sel.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    },
    { markerValue, newValue }
  );
  assert.ok(
    applied,
    `No se encontró el select con la opción '${markerValue}' para seleccionar '${newValue}'.`
  );
}

async function _setSearchText(page, text) {
  await page.evaluate(
    (text) => {
      const input = document.querySelector(
        ".backlog-filter-bar input.backlog-filter-search"
      );
      if (!input) return;
      input.value = text;
      input.dispatchEvent(new Event("input", { bubbles: true }));
    },
    text
  );
  // Debounce de 200ms en `app.js` (T-AF036-US01-01) + margen.
  await sleep(350);
}

async function _visibleEpicIds(page) {
  return page.evaluate(() => {
    return Array.from(document.querySelectorAll(".backlog-epic-line"))
      .map((line) => {
        const t = (line.querySelector(".backlog-epic-line-title") || {}).textContent || "";
        const m = /AF-\d+/.exec(t);
        return m ? m[0] : null;
      })
      .filter(Boolean);
  });
}

async function _clickButtonByText(page, text) {
  const clicked = await page.evaluate((label) => {
    const btn = Array.from(document.querySelectorAll("button")).find(
      (b) => b.textContent.trim() === label
    );
    if (!btn || btn.disabled) return false;
    btn.click();
    return true;
  }, text);
  assert.ok(clicked, "No se encontró o estaba deshabilitado el botón '" + text + "'.");
}

async function _rewriteTaskState(projectPath, taskId, newState) {
  const tasksDir = path.join(projectPath, "02-backlog", "tasks");
  const filename = fs.readdirSync(tasksDir).find((name) => name.startsWith(taskId));
  assert.ok(filename, `No se encontró el fichero de la Task ${taskId} en ${tasksDir}`);
  const taskPath = path.join(tasksDir, filename);
  const original = fs.readFileSync(taskPath, "utf-8");
  assert.ok(
    original.includes("state: READY"),
    `Frontmatter inesperado en ${taskId}: ${original.split("\n").find((l) => l.includes("state:"))}`
  );
  fs.writeFileSync(taskPath, original.replace("state: READY", "state: " + newState));
}

// ---------------------------------------------------------------------
// Criterio 1: el selector de fase aparece con "Todas", las fases presentes
// y "SIN_ASIGNAR", y su valor por defecto es "all".
// ---------------------------------------------------------------------
async function test_selector_fase_opciones_dinamicas() {
  await withBackend(async ({ page, baseUrl, projectPath }) => {
    await page.goto(baseUrl + "/ui/");
    await _seedTresEpicsConFases(page, projectPath);
    await page.reload();
    await _goToTab(page, "Backlog");
    await waitVisible(page, ".backlog-filter-bar");

    const fase = await _selectInfo(page, "SIN_ASIGNAR");
    assert.ok(fase, "No se encontró el selector de fase (debe incluir la opción SIN_ASIGNAR).");
    assert.deepStrictEqual(
      fase.values,
      ["all", "Fase 1.1", "Fase 2.0", "SIN_ASIGNAR"],
      "Las opciones del selector de fase deben ser Todas + fases presentes ordenadas + SIN_ASIGNAR."
    );
    assert.strictEqual(
      fase.value,
      "all",
      "El valor por defecto del selector de fase debe ser 'all' (Todas)."
    );
  });
}

// ---------------------------------------------------------------------
// Criterio 2: seleccionar una fase filtra el listado en la vista plana.
// ---------------------------------------------------------------------
async function test_seleccionar_fase_filtra_vista_plana() {
  await withBackend(async ({ page, baseUrl, projectPath }) => {
    await page.goto(baseUrl + "/ui/");
    await _seedTresEpicsConFases(page, projectPath);
    await page.reload();
    await _goToTab(page, "Backlog");
    await waitVisible(page, ".backlog-filter-bar");

    const ids = await _visibleEpicIds(page);
    assert.deepStrictEqual(
      ids.sort(),
      ["AF-951", "AF-952", "AF-953"],
      "Sin filtro de fase deben verse las tres Epics."
    );

    await _setSelectValue(page, "SIN_ASIGNAR", "Fase 1.1");
    assert.deepStrictEqual(
      await _visibleEpicIds(page),
      ["AF-951"],
      "Filtrar por 'Fase 1.1' debe dejar solo la Epic AF-951."
    );

    await _setSelectValue(page, "SIN_ASIGNAR", "Fase 2.0");
    assert.deepStrictEqual(
      await _visibleEpicIds(page),
      ["AF-952"],
      "Filtrar por 'Fase 2.0' debe dejar solo la Epic AF-952."
    );

    await _setSelectValue(page, "SIN_ASIGNAR", "SIN_ASIGNAR");
    assert.deepStrictEqual(
      await _visibleEpicIds(page),
      ["AF-953"],
      "Filtrar por 'SIN_ASIGNAR' debe dejar solo la Epic sin fase (AF-953)."
    );

    await _setSelectValue(page, "SIN_ASIGNAR", "all");
    assert.deepStrictEqual(
      (await _visibleEpicIds(page)).sort(),
      ["AF-951", "AF-952", "AF-953"],
      "Seleccionar 'Todas' debe volver a mostrar las tres Epics."
    );
  });
}

// ---------------------------------------------------------------------
// Criterio 3: el filtro de fase se combina con texto, estado y prioridad
// (todos a la vez -> intersección).
// ---------------------------------------------------------------------
async function test_filtro_fase_se_combina_con_texto_estado_prioridad() {
  await withBackend(async ({ page, baseUrl, projectPath }) => {
    assert.ok(projectPath, "El backend aislado debe exponer la ruta real del proyecto activo.");

    await page.goto(baseUrl + "/ui/");
    // Escenario propio de combinación: AF-951 y AF-952 comparten Fase 1.1
    // (para que el filtro de fase NO sea el único que decide) y AF-953 está
    // en Fase 2.0. Las tres Tasks son READY: cada filtro de estado/prioridad
    /// texto se demuestra quitándolo uno a uno de la intersección completa.
    await _seedEpic(page, "AF-951", "Epic fase uno", "Fase 1.1");
    _writeEpicFase(projectPath, "AF-951", "Fase 1.1");
    await _seedUs(page, "AF-951", "US-AF951-01");
    await _seedTask(page, "US-AF951-01", "T-AF951-US01-01", "Crítica");

    await _seedEpic(page, "AF-952", "Epic fase uno bis", "Fase 1.1");
    _writeEpicFase(projectPath, "AF-952", "Fase 1.1");
    await _seedUs(page, "AF-952", "US-AF952-01");
    await _seedTask(page, "US-AF952-01", "T-AF952-US01-01", "Media");

    await _seedEpic(page, "AF-953", "Epic fase dos", "Fase 2.0");
    _writeEpicFase(projectPath, "AF-953", "Fase 2.0");
    await _seedUs(page, "AF-953", "US-AF953-01");
    await _seedTask(page, "US-AF953-01", "T-AF953-US01-01", "Crítica");

    await page.reload();
    await _goToTab(page, "Backlog");
    await waitVisible(page, ".backlog-filter-bar");

    // Intersección completa: fase + estado + prioridad + texto.
    await _setSelectValue(page, "SIN_ASIGNAR", "Fase 1.1");
    await _setSelectValue(page, "blocked", "READY");
    await _setSelectValue(page, "none", "Crítica");
    await _setSearchText(page, "t-af951");
    assert.deepStrictEqual(
      await _visibleEpicIds(page),
      ["AF-951"],
      "Fase 1.1 + READY + Crítica + texto 't-af951' deja solo AF-951."
    );

    // Quitar el texto -> el texto participa (cambia el resultado a vacío).
    await _setSearchText(page, "t-af952");
    assert.deepStrictEqual(
      await _visibleEpicIds(page),
      [],
      "Con texto 't-af952' (la única Crítica READY de Fase 1.1 es AF-951) no debe quedar ninguna Epic."
    );

    // Restaurar texto y quitar la prioridad -> la prioridad participa.
    await _setSearchText(page, "t-af951");
    await _setSelectValue(page, "none", "Media");
    assert.deepStrictEqual(
      await _visibleEpicIds(page),
      [],
      "Fase 1.1 + READY + Media + texto 't-af951' no deja ninguna Epic (AF-951 es Crítica)."
    );

    // Restaurar prioridad y cambiar el estado -> el estado participa.
    await _setSelectValue(page, "none", "Crítica");
    await _setSelectValue(page, "blocked", "IN_PROGRESS");
    assert.deepStrictEqual(
      await _visibleEpicIds(page),
      [],
      "Fase 1.1 + IN_PROGRESS + Crítica + texto 't-af951' no deja ninguna Epic (las tres Tasks son READY)."
    );

    // Restaurar estado y cambiar la fase -> la fase participa.
    await _setSelectValue(page, "blocked", "READY");
    await _setSelectValue(page, "SIN_ASIGNAR", "SIN_ASIGNAR");
    assert.deepStrictEqual(
      await _visibleEpicIds(page),
      [],
      "SIN_ASIGNAR + READY + Crítica + texto 't-af951' no deja ninguna Epic (AF-953 está en Fase 2.0)."
    );

    // Restaurar la fase -> vuelve la intersección completa.
    await _setSelectValue(page, "SIN_ASIGNAR", "Fase 1.1");
    assert.deepStrictEqual(
      await _visibleEpicIds(page),
      ["AF-951"],
      "Restaurar Fase 1.1 debe volver a dejar solo AF-951."
    );
  });
}

// ---------------------------------------------------------------------
// Criterio 4: el filtro funciona en la vista "Por Fase" (by_fase) y la
// selección persiste al alternar vistas.
// ---------------------------------------------------------------------
async function test_filtro_fase_funciona_en_vista_por_fase() {
  await withBackend(async ({ page, baseUrl, projectPath }) => {
    await page.goto(baseUrl + "/ui/");
    await _seedTresEpicsConFases(page, projectPath);
    await page.reload();
    await _goToTab(page, "Backlog");
    await waitVisible(page, ".backlog-filter-bar");

    await _setSelectValue(page, "SIN_ASIGNAR", "Fase 1.1");
    await _clickButtonByText(page, "Por Fase");

    // Solo la Epic de Fase 1.1 queda; en la vista "Por Fase" se agrupa bajo
    // su VERSION (T-AF036-US15-06 agrupa por version, las Epics creadas por
    // POST nacen con `version: 0.9`).
    const state = await page.evaluate(() => {
      const titles = Array.from(document.querySelectorAll(".backlog-fase-title")).map(
        (t) => t.textContent.trim()
      );
      return {
        titles,
        ids: Array.from(document.querySelectorAll(".backlog-epic-line"))
          .map((l) => {
            const t = (l.querySelector(".backlog-epic-line-title") || {}).textContent || "";
            const m = /AF-\d+/.exec(t);
            return m ? m[0] : null;
          })
          .filter(Boolean),
      };
    });
    assert.deepStrictEqual(
      state.titles,
      ["0.9"],
      "En vista 'Por Fase' con filtro Fase 1.1 solo debe existir el grupo '0.9' (VERSION de la Epic)."
    );
    assert.deepStrictEqual(
      state.ids,
      ["AF-951"],
      "En vista 'Por Fase' con filtro Fase 1.1 solo debe verse la Epic AF-951."
    );

    // La selección persiste al volver a la vista plana.
    await _clickButtonByText(page, "Lista");
    assert.deepStrictEqual(
      await _visibleEpicIds(page),
      ["AF-951"],
      "Volver a la vista plana debe mantener el filtro de fase Fase 1.1."
    );

    // Y la vista por fases también filtra correctamente SIN_ASIGNAR.
    await _setSelectValue(page, "SIN_ASIGNAR", "SIN_ASIGNAR");
    await _clickButtonByText(page, "Por Fase");
    const sinAsignar = await page.evaluate(() => {
      const titles = Array.from(document.querySelectorAll(".backlog-fase-title")).map(
        (t) => t.textContent.trim()
      );
      const ids = Array.from(document.querySelectorAll(".backlog-epic-line"))
        .map((l) => {
          const t = (l.querySelector(".backlog-epic-line-title") || {}).textContent || "";
          const m = /AF-\d+/.exec(t);
          return m ? m[0] : null;
        })
        .filter(Boolean);
      return { titles, ids };
    });
    assert.deepStrictEqual(
      sinAsignar.titles,
      ["0.9"],
      "En vista 'Por Fase' con filtro SIN_ASIGNAR solo debe existir el grupo '0.9' (VERSION de la Epic)."
    );
    assert.deepStrictEqual(
      sinAsignar.ids,
      ["AF-953"],
      "En vista 'Por Fase' con filtro SIN_ASIGNAR solo debe verse la Epic AF-953."
    );
  });
}

// ---------------------------------------------------------------------
// Criterio 5: "Limpiar" resetea el filtro de fase y vuelve a mostrar todo.
// ---------------------------------------------------------------------
async function test_limpiar_resetea_filtro_fase() {
  await withBackend(async ({ page, baseUrl, projectPath }) => {
    await page.goto(baseUrl + "/ui/");
    await _seedTresEpicsConFases(page, projectPath);
    await page.reload();
    await _goToTab(page, "Backlog");
    await waitVisible(page, ".backlog-filter-bar");

    await _setSelectValue(page, "SIN_ASIGNAR", "Fase 1.1");
    assert.deepStrictEqual(await _visibleEpicIds(page), ["AF-951"]);

    await _clickButtonByText(page, "Limpiar filtros");

    assert.deepStrictEqual(
      (await _visibleEpicIds(page)).sort(),
      ["AF-951", "AF-952", "AF-953"],
      "Tras 'Limpiar filtros' deben volver a verse las tres Epics."
    );
    const fase = await _selectInfo(page, "SIN_ASIGNAR");
    assert.strictEqual(fase.value, "all", "Tras 'Limpiar filtros' el selector de fase debe volver a 'all'.");
  });
}

// ---------------------------------------------------------------------
// Criterio 6 (US-AF036-11): la selección sobrevive a refreshBacklogReport()
// (navegar a otra pestaña y volver a Backlog re-fetchea el informe).
// ---------------------------------------------------------------------
async function test_seleccion_fase_sobrevive_a_refresh() {
  await withBackend(async ({ page, baseUrl, projectPath }) => {
    await page.goto(baseUrl + "/ui/");
    await _seedTresEpicsConFases(page, projectPath);
    await page.reload();
    await _goToTab(page, "Backlog");
    await waitVisible(page, ".backlog-filter-bar");

    await _setSelectValue(page, "SIN_ASIGNAR", "Fase 1.1");
    assert.deepStrictEqual(await _visibleEpicIds(page), ["AF-951"]);

    // Navegar a Agentes y volver a Backlog dispara renderBacklogInto ->
    // refreshBacklogReport() (re-fetch de GET /backlog).
    await _goToTab(page, "Agentes");
    await waitVisible(page, ".section-tab");
    await _goToTab(page, "Backlog");
    await waitVisible(page, ".backlog-filter-bar");

    const fase = await _selectInfo(page, "SIN_ASIGNAR");
    assert.strictEqual(
      fase.value,
      "Fase 1.1",
      "La selección de fase debe sobrevivir a refreshBacklogReport (volver a Backlog)."
    );
    assert.deepStrictEqual(
      await _visibleEpicIds(page),
      ["AF-951"],
      "Tras refrescar el informe, el filtro de fase debe seguir aplicado."
    );
  });
}

module.exports = [
  {
    name: "el selector de fase aparece con 'Todas', las fases presentes y 'SIN_ASIGNAR'",
    fn: test_selector_fase_opciones_dinamicas,
  },
  {
    name: "seleccionar una fase filtra el listado en la vista plana",
    fn: test_seleccionar_fase_filtra_vista_plana,
  },
  {
    name: "el filtro de fase se combina con texto, estado y prioridad (intersección)",
    fn: test_filtro_fase_se_combina_con_texto_estado_prioridad,
  },
  {
    name: "el filtro de fase funciona en la vista 'Por Fase' y la selección persiste entre vistas",
    fn: test_filtro_fase_funciona_en_vista_por_fase,
  },
  {
    name: "'Limpiar filtros' resetea el filtro de fase y vuelve a mostrar todo",
    fn: test_limpiar_resetea_filtro_fase,
  },
  {
    name: "la selección de fase sobrevive a refreshBacklogReport (navegar y volver a Backlog)",
    fn: test_seleccion_fase_sobrevive_a_refresh,
  },
];