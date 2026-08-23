/* T-AF036-US15-02 (US-AF036-15): en la vista "Por Fase" las VERSIONES de las
 * Epics se ordenan naturalmente (1.0 < 1.1 < 1.2 ...) con "SIN_VERSION" al
 * final (T-AF036-US15-06: las Epics se agrupan por VERSION, no por fase), y
 * dentro de cada grupo las Epics abiertas van primero, con las terminadas y
 * las de todas-sus-US-fuera-de-roadmap colapsadas al final. Verificado en
 * navegador real (Chromium + backend aislado), mismo patrón que la suite
 * canónica.
 *
 * El backlog se siembra vía HTTP (Epic + US); el estado DONE/OUT_OF_SCOPE de
 * las US se fija reescribiendo su fichero con `fs`. */

"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");
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

async function _seedEpicUs(page, epicId, version, projectPath) {
  await page.evaluate(
    async ({ epicId, version }) => {
      const post = async (p, b) => {
        const r = await fetch(p, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(b),
        });
        if (!r.ok) throw new Error("POST " + p + " falló: " + r.status);
      };
      const usId = "US-" + epicId.replace("AF-", "AF") + "-01";
      await post("/backlog/epic", { id: epicId, title: "Epic " + epicId, objetivo: "O." });
      await post("/backlog/epic/" + epicId + "/us", {
        id: usId, title: "US de " + epicId, objetivo: "H.", criterios_aceptacion: "C.",
      });
      // Una Task bajo la US: sin Task la US DONE sería reconciliada a NO_TASKS
      // por la derivación de US13-09 y la Epic nunca parecería "terminada".
      await post("/backlog/us/" + usId + "/task", {
        id: "T-" + usId.replace("US-AF", "AF").replace("-", "-US") + "-01",
        title: "Task de " + epicId, objetivo: "O.", descripcion: "D.",
        criterios_aceptacion: "C.", priority: "Alta",
      });
    },
    { epicId, version }
  );
  // T-AF036-US18-01: `POST /backlog/epic` crea la Epic con `version: 0.9`
  // por defecto. Para simular la VERSION que agrupa esta Epic en la vista
  // "Por Fase" (T-AF036-US15-06, agrupa por VERSION), se reescribe el
  // frontmatter con `fs`.
  if (version) {
    _setEpicVersion(projectPath, epicId, version);
  } else {
    _clearEpicVersion(projectPath, epicId);
  }
}

function _clearEpicVersion(projectPath, epicId) {
  const p = _findFile(projectPath, "epics", epicId);
  const original = fs.readFileSync(p, "utf-8");
  fs.writeFileSync(p, original.replace(/\nversion:.*\n/, "\n"));
}

function _findFile(projectPath, subdir, idPrefix) {
  const dir = path.join(projectPath, "02-backlog", subdir);
  const name = fs.readdirSync(dir).find((n) => n.startsWith(idPrefix));
  assert.ok(name, "No se encontró " + idPrefix + " en " + dir);
  return path.join(dir, name);
}

function _setEpicVersion(projectPath, epicId, version) {
  const p = _findFile(projectPath, "epics", epicId);
  const original = fs.readFileSync(p, "utf-8");
  const idx = original.indexOf("\n---");
  assert.ok(idx > 0, "frontmatter no encontrado en " + p);
  fs.writeFileSync(p, original.slice(0, idx) + "\nversion: " + version + original.slice(idx));
}

function _setUsState(projectPath, usId, newState) {
  const p = _findFile(projectPath, "user-stories", usId);
  const original = fs.readFileSync(p, "utf-8");
  const m = original.match(/^state: (.*)$/m);
  assert.ok(m, "sin campo state en " + usId);
  fs.writeFileSync(p, original.replace("state: " + m[1], "state: " + newState));
}

function _setTaskState(projectPath, taskId, newState) {
  const p = _findFile(projectPath, "tasks", taskId);
  const original = fs.readFileSync(p, "utf-8");
  const m = original.match(/^state: (.*)$/m);
  assert.ok(m, "sin campo state en " + taskId);
  fs.writeFileSync(p, original.replace("state: " + m[1], "state: " + newState));
}

async function _clickButtonByText(page, text) {
  const clicked = await page.evaluate((label) => {
    const btn = Array.from(document.querySelectorAll("button")).find(
      (b) => b.textContent.includes(label)
    );
    if (!btn || btn.disabled) return false;
    btn.click();
    return true;
  }, text);
  assert.ok(clicked, "No se encontró el botón con texto que contenga '" + text + "'.");
}

async function test_por_fase_ordena_fases_naturalmente_y_sin_asignar_al_final() {
  await withBackend(async ({ page, baseUrl, projectPath }) => {
    await page.goto(baseUrl + "/ui/");
    // Versiones desordenadas a propósito: 1.1, 2.0, 1.0 y una sin version.
    await _seedEpicUs(page, "AF-901", "1.1", projectPath);
    await _seedEpicUs(page, "AF-902", "2.0", projectPath);
    await _seedEpicUs(page, "AF-903", "1.0", projectPath);
    await _seedEpicUs(page, "AF-904", null, projectPath); // SIN_VERSION

    await page.reload();
    await _goToBacklogTab(page);
    await _clickButtonByText(page, "Por Fase");
    await waitVisible(page, ".backlog-fase-title");

    const titles = await page.evaluate(() =>
      Array.from(document.querySelectorAll(".backlog-fase-title")).map((t) => t.textContent.trim())
    );
    assert.deepStrictEqual(
      titles,
      ["1.0", "1.1", "2.0", "SIN_VERSION"],
      "Las versiones deben ordenarse naturalmente (1.0 < 1.1 < 2.0) y 'SIN_VERSION' al final, got: " + JSON.stringify(titles)
    );
  });
}

async function test_por_fase_agrupa_abiertas_primero_y_terminadas_fuera_colapsadas() {
  await withBackend(async ({ page, baseUrl, projectPath }) => {
    assert.ok(projectPath, "El backend aislado debe exponer la ruta real del proyecto activo.");

    await page.goto(baseUrl + "/ui/");
    // Version 1.1 con tres Epics: una abierta, una terminada (US DONE) y una con
    // todas sus US fuera del roadmap (OUT_OF_SCOPE).
    await _seedEpicUs(page, "AF-910", "1.1", projectPath); // abierta
    await _seedEpicUs(page, "AF-911", "1.1", projectPath); // terminada
    await _seedEpicUs(page, "AF-912", "1.1", projectPath); // fuera de roadmap
    _setUsState(projectPath, "US-AF911-01", "DONE");
    _setTaskState(projectPath, "T-AF911-US01-01", "DONE");
    _setUsState(projectPath, "US-AF912-01", "OUT_OF_SCOPE");
    // Otra version abierta para el orden de versiones.
    await _seedEpicUs(page, "AF-913", "2.0", projectPath);

    await page.reload();
    await _goToBacklogTab(page);
    await _clickButtonByText(page, "Por Fase");
    await waitVisible(page, ".backlog-fase-title");

    const state = await page.evaluate(() => {
      const groups = Array.from(document.querySelectorAll(".backlog-fase-group"));
      const g = groups.find((el) =>
        el.querySelector(".backlog-fase-title") &&
        el.querySelector(".backlog-fase-title").textContent.trim() === "1.1"
      );
      if (!g) return null;
      return {
        titles: Array.from(g.querySelectorAll(".backlog-fase-title")).map((t) => t.textContent.trim()),
        visibleEpics: Array.from(g.querySelectorAll(".backlog-epic-line-title")).map((t) => t.textContent.trim()),
        headers: Array.from(g.querySelectorAll(".backlog-done-header")).map((h) => h.textContent.trim()),
      };
    });
    assert.ok(state, "No se encontró el grupo '1.1'.");
    // La epic abierta se renderiza expandida (visible); la terminada y la
    // fuera-de-roadmap están colapsadas (solo sus cabeceras).
    const visibleText = state.visibleEpics.join(" ");
    assert.ok(visibleText.includes("AF-910"), "La Epic abierta AF-910 debe verse expandida, got: " + visibleText);
    assert.ok(!visibleText.includes("AF-911"), "La Epic terminada AF-911 no debe verse expandida (colapsada), got: " + visibleText);
    assert.ok(!visibleText.includes("AF-912"), "La Epic fuera-de-roadmap AF-912 no debe verse expandida (colapsada), got: " + visibleText);
    assert.ok(
      state.headers.some((h) => h.includes("Terminadas (1)")),
      "Debe existir el bloque colapsable 'Terminadas (1)', got: " + JSON.stringify(state.headers)
    );
    assert.ok(
      state.headers.some((h) => h.includes("Todas fuera de roadmap (1)")),
      "Debe existir el bloque colapsable 'Todas fuera de roadmap (1)', got: " + JSON.stringify(state.headers)
    );

    // Al desplegar "Terminadas", la Epic AF-911 aparece.
    await _clickButtonByText(page, "Terminadas (1)");
    const expanded = await page.evaluate(() =>
      Array.from(document.querySelectorAll(".backlog-epic-line-title")).map((t) => t.textContent.trim()).join(" ")
    );
    assert.ok(expanded.includes("AF-911"), "Al expandir 'Terminadas' debe aparecer AF-911.");
  });
}

async function test_por_fase_no_regresa_vista_plana() {
  await withBackend(async ({ page, baseUrl, projectPath }) => {
    await page.goto(baseUrl + "/ui/");
    await _seedEpicUs(page, "AF-920", "1.1", projectPath);
    await _seedEpicUs(page, "AF-921", "1.0", projectPath);

    await page.reload();
    await _goToBacklogTab(page);
    // Vista plana por defecto: se ven las dos epics.
    await waitVisible(page, ".backlog-epic-line");
    const flatIds = await page.evaluate(() =>
      Array.from(document.querySelectorAll(".backlog-epic-line-title")).map((t) => t.textContent.trim()).join(" ")
    );
    assert.ok(flatIds.includes("AF-920") && flatIds.includes("AF-921"), "En vista plana deben verse ambas epics, got: " + flatIds);

    // Cambiar a Por Fase y volver a Lista no rompe la vista plana.
    await _clickButtonByText(page, "Por Fase");
    await waitVisible(page, ".backlog-fase-title");
    await _clickButtonByText(page, "Lista");
    await waitVisible(page, ".backlog-epic-line");
    const backFlat = await page.evaluate(() =>
      Array.from(document.querySelectorAll(".backlog-epic-line-title")).map((t) => t.textContent.trim()).join(" ")
    );
    assert.ok(backFlat.includes("AF-920") && backFlat.includes("AF-921"), "Volver a la vista plana debe seguir mostrando ambas epics.");
  });
}

module.exports = [
  {
    name: "la vista 'Por Fase' ordena las versiones naturalmente y 'SIN_VERSION' al final",
    fn: test_por_fase_ordena_fases_naturalmente_y_sin_asignar_al_final,
  },
  {
    name: "dentro de cada fase las Epics abiertas van primero; terminadas y fuera-de-roadmap colapsadas al final",
    fn: test_por_fase_agrupa_abiertas_primero_y_terminadas_fuera_colapsadas,
  },
  {
    name: "sin regresión en la vista plana (flat) al alternar vistas",
    fn: test_por_fase_no_regresa_vista_plana,
  },
];