/* T-AF036-US13-03 (US-AF036-13): la línea de título de cada User Story y
 * Task del Backlog muestra la fase del roadmap y la fecha/hora de la última
 * transición de estado (`[fase: ...] [última actualización: ...]`), servidos por la
 * API (T-AF036-US13-02). Verificado en navegador real (Chromium + backend
 * real aislado), mismo patrón que el resto de la suite `10-web/tests/`.
 *
 * El backlog se siembra vía HTTP (Epic + US + Task); `fase`/`updated_at` de
 * la US y la Task se añaden reescribiendo su frontmatter con `fs` (no hay
 * endpoint que edite esos campos en un item ya creado). */

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
  throw new Error("No se encontró la pestaña 'Backlog' en la navegación.");
}

async function _seed(page, epicId, usId, taskId, priority) {
  await page.evaluate(
    async ({ epicId, usId, taskId, priority }) => {
      const base = location.origin;
      const post = async (p, b) => {
        const r = await fetch(p, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(b),
        });
        if (!r.ok) throw new Error("POST " + p + " falló: " + r.status);
      };
      await post("/backlog/epic", { id: epicId, title: "Epic " + epicId, objetivo: "O.", fase: "Fase 1.1" });
      await post("/backlog/epic/" + epicId + "/us", { id: usId, title: "US " + usId, objetivo: "H.", criterios_aceptacion: "C." });
      await post("/backlog/us/" + usId + "/task", { id: taskId, title: "Task " + taskId, objetivo: "O.", descripcion: "D.", criterios_aceptacion: "C.", priority: priority });
    },
    { epicId, usId, taskId, priority }
  );
}

// Añade campos al frontmatter de un fichero real (justo antes del segundo `---`).
function _addFrontmatterFields(filePath, fields) {
  const original = fs.readFileSync(filePath, "utf-8");
  const idx = original.indexOf("\n---");
  assert.ok(idx > 0, "frontmatter no encontrado en " + filePath);
  const newContent = original.slice(0, idx) + "\n" + fields.join("\n") + original.slice(idx);
  fs.writeFileSync(filePath, newContent);
}

// Elimina una línea del frontmatter (p. ej. para simular items sin updated_at).
function _removeFrontmatterField(filePath, field) {
  const original = fs.readFileSync(filePath, "utf-8");
  const re = new RegExp("^" + field + ":.*$\\n?", "m");
  const updated = original.replace(re, "");
  assert.notStrictEqual(updated, original, "No se encontró la línea '" + field + ":' para eliminar en " + filePath);
  fs.writeFileSync(filePath, updated);
}

function _findFile(projectPath, subdir, idPrefix) {
  const dir = path.join(projectPath, "02-backlog", subdir);
  const name = fs.readdirSync(dir).find((n) => n.startsWith(idPrefix));
  assert.ok(name, "No se encontró el fichero " + idPrefix + " en " + dir);
  return path.join(dir, name);
}

async function _openEpicDetail(page, epicId) {
  await waitVisible(page, ".backlog-epic-line");
  const clicked = await page.evaluate((id) => {
    const line = Array.from(document.querySelectorAll(".backlog-epic-line")).find((l) =>
      l.textContent.includes(id)
    );
    if (!line) return false;
    line.click();
    return true;
  }, epicId);
  assert.ok(clicked, "No se encontró la línea de la Epic '" + epicId + "'.");
}

async function _openUsDetail(page, usId) {
  await waitVisible(page, ".backlog-us-line");
  const clicked = await page.evaluate((id) => {
    const line = Array.from(document.querySelectorAll(".backlog-us-line")).find((l) =>
      l.textContent.includes(id)
    );
    if (!line) return false;
    line.click();
    return true;
  }, usId);
  assert.ok(clicked, "No se pudo abrir el detalle de la US '" + usId + "'.");
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

// Calcula el formato esperado de la fecha con la misma lógica que la web
// (formato local YYYY-MM-DD HH:MM), para que la aserción no dependa de la
// zona horaria del entorno.
function _expectedFormat(ts) {
  const when = new Date(ts);
  const y = when.getFullYear();
  const m = String(when.getMonth() + 1).padStart(2, "0");
  const d = String(when.getDate()).padStart(2, "0");
  const hh = String(when.getHours()).padStart(2, "0");
  const mm = String(when.getMinutes()).padStart(2, "0");
  return y + "-" + m + "-" + d + " " + hh + ":" + mm;
}

async function test_encabezado_us_muestra_fase_y_fecha() {
  await withBackend(async ({ page, baseUrl, projectPath }) => {
    assert.ok(projectPath, "El backend aislado debe exponer la ruta real del proyecto activo.");
    const TS = "2026-08-19T12:34:00+00:00";

    await page.goto(baseUrl + "/ui/");
    await _seed(page, "AF-981", "US-AF981-01", "T-AF981-US01-01", "Alta");
    _addFrontmatterFields(_findFile(projectPath, "user-stories", "US-AF981-01"), [
      "fase: Fase 1.1",
      "updated_at: " + TS,
    ]);
    _addFrontmatterFields(_findFile(projectPath, "tasks", "T-AF981-US01-01"), [
      "fase: Fase 1.1",
      "updated_at: " + TS,
    ]);

    await page.reload();
    await _goToBacklogTab(page);
    await _openEpicDetail(page, "AF-981");
    await waitVisible(page, ".backlog-us-line");

    const expected = _expectedFormat(TS);
    const usMeta = await page.evaluate(() => {
      const line = Array.from(document.querySelectorAll(".backlog-us-line")).find((l) =>
        l.textContent.includes("US-AF981-01")
      );
      const meta = line && line.querySelector(".backlog-us-line-meta");
      return meta ? meta.textContent : null;
    });
    assert.ok(usMeta, "Debe existir el fragmento .backlog-us-line-meta en la línea de la US.");
    assert.ok(
      usMeta.includes("[fase: Fase 1.1]"),
      "La US debe mostrar '[fase: Fase 1.1]' en su encabezado, got: " + usMeta
    );
    assert.ok(
      usMeta.includes("[última actualización: " + expected + "]"),
      "La US debe mostrar '[última actualización: " + expected + "]', got: " + usMeta
    );

    // Abrir la US para ver su Task anidada.
    await _openUsDetail(page, "US-AF981-01");
    await waitVisible(page, ".backlog-task-line-meta");
    const taskMeta = await page.evaluate(() => {
      const line = Array.from(document.querySelectorAll(".job-line")).find((l) =>
        l.querySelector(".backlog-task-line-title") &&
        l.querySelector(".backlog-task-line-title").textContent.includes("T-AF981-US01-01")
      );
      const meta = line && line.querySelector(".backlog-task-line-meta");
      return meta ? meta.textContent : null;
    });
    assert.ok(taskMeta, "Debe existir .backlog-task-line-meta para la Task.");
    assert.ok(
      taskMeta.includes("[fase: Fase 1.1]"),
      "La Task debe mostrar '[fase: Fase 1.1]', got: " + taskMeta
    );
    assert.ok(
      taskMeta.includes("[última actualización: " + expected + "]"),
      "La Task debe mostrar '[última actualización: " + expected + "]', got: " + taskMeta
    );
  });
}

async function test_encabezado_con_datos_ausentes_muestra_sin_asignar_y_guion() {
  await withBackend(async ({ page, baseUrl, projectPath }) => {
    assert.ok(projectPath, "El backend aislado debe exponer la ruta real del proyecto activo.");

    await page.goto(baseUrl + "/ui/");
    // US sin fase ni updated_at -> fase "SIN_ASIGNAR" y actualizada "—".
    await _seed(page, "AF-982", "US-AF982-01", "T-AF982-US01-01", "Alta");
    // Al crear la Task, la US transiciona NO_TASKS->READY y el backend escribe
    // `updated_at` (T-AF036-US13-01); quitarlo para verificar la
    // retrocompatibilidad con items sin `updated_at`.
    _removeFrontmatterField(_findFile(projectPath, "user-stories", "US-AF982-01"), "updated_at");

    await page.reload();
    await _goToBacklogTab(page);
    await _openEpicDetail(page, "AF-982");
    await waitVisible(page, ".backlog-us-line");

    const usMeta = await page.evaluate(() => {
      const line = Array.from(document.querySelectorAll(".backlog-us-line")).find((l) =>
        l.textContent.includes("US-AF982-01")
      );
      const meta = line && line.querySelector(".backlog-us-line-meta");
      return meta ? meta.textContent : null;
    });
    assert.ok(usMeta, "Debe existir .backlog-us-line-meta para la US sin fase.");
    assert.ok(
      usMeta.includes("[fase: SIN_ASIGNAR]"),
      "US sin fase debe mostrar '[fase: SIN_ASIGNAR]', got: " + usMeta
    );
    assert.ok(
      usMeta.includes("[última actualización: —]"),
      "US sin updated_at debe mostrar '[última actualización: —]', got: " + usMeta
    );

    await _openUsDetail(page, "US-AF982-01");
    await waitVisible(page, ".backlog-task-line-meta");
    const taskMeta = await page.evaluate(() => {
      const line = Array.from(document.querySelectorAll(".job-line")).find((l) =>
        l.querySelector(".backlog-task-line-title") &&
        l.querySelector(".backlog-task-line-title").textContent.includes("T-AF982-US01-01")
      );
      const meta = line && line.querySelector(".backlog-task-line-meta");
      return meta ? meta.textContent : null;
    });
    assert.ok(taskMeta, "Debe existir .backlog-task-line-meta para la Task sin fase.");
    assert.ok(
      taskMeta.includes("[fase: SIN_ASIGNAR]") && taskMeta.includes("[última actualización: —]"),
      "Task sin fase/updated_at debe mostrar SIN_ASIGNAR y '—', got: " + taskMeta
    );
  });
}

async function test_encabezado_se_muestra_en_vista_por_fase() {
  await withBackend(async ({ page, baseUrl, projectPath }) => {
    assert.ok(projectPath, "El backend aislado debe exponer la ruta real del proyecto activo.");
    const TS = "2026-08-19T09:05:00+00:00";

    await page.goto(baseUrl + "/ui/");
    await _seed(page, "AF-983", "US-AF983-01", "T-AF983-US01-01", "Alta");
    // T-AF036-US18-01: POST /backlog/epic ya no almacena `fase` (la Epic se
    // versiona) — se escribe la fase LEGACY en el fichero para que la Epic
    // se agrupe en "Fase 1.1" en la vista "Por Fase".
    _addFrontmatterFields(_findFile(projectPath, "epics", "AF-983"), ["fase: Fase 1.1"]);
    _addFrontmatterFields(_findFile(projectPath, "user-stories", "US-AF983-01"), [
      "fase: Fase 1.1",
      "updated_at: " + TS,
    ]);

    await page.reload();
    await _goToBacklogTab(page);
    await _clickButtonByText(page, "Por Fase");

    await _openEpicDetail(page, "AF-983");
    await waitVisible(page, ".backlog-us-line");
    const expected = _expectedFormat(TS);
    const usMeta = await page.evaluate(() => {
      const line = Array.from(document.querySelectorAll(".backlog-us-line")).find((l) =>
        l.textContent.includes("US-AF983-01")
      );
      const meta = line && line.querySelector(".backlog-us-line-meta");
      return meta ? meta.textContent : null;
    });
    assert.ok(usMeta, "En vista 'Por Fase' debe existir .backlog-us-line-meta para la US.");
    assert.ok(
      usMeta.includes("[fase: Fase 1.1]") && usMeta.includes("[última actualización: " + expected + "]"),
      "En vista 'Por Fase' la US debe mostrar fase y fecha, got: " + usMeta
    );
  });
}

module.exports = [
  {
    name: "la línea de US y Task muestra fase y fecha de última transición",
    fn: test_encabezado_us_muestra_fase_y_fecha,
  },
  {
    name: "sin fase/updated_at el encabezado muestra 'SIN_ASIGNAR' y '—' sin romper el render",
    fn: test_encabezado_con_datos_ausentes_muestra_sin_asignar_y_guion,
  },
  {
    name: "el encabezado con fase/fecha se muestra también en la vista 'Por Fase'",
    fn: test_encabezado_se_muestra_en_vista_por_fase,
  },
];