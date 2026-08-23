/* T-AF036-US19-02 (US-AF036-19): la fila de cada User Story y Task muestra
 * `ID + nombre` (título), y el estado aparece una sola vez (en el `<select>`
 * de estado, no en el texto de la línea). El `title` lo expone el backend
 * (T-AF036-US19-01). */

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
    await post("/backlog/epic", { id: "AF-995", title: "Epic", objetivo: "O." });
    await post("/backlog/epic/AF-995/us", { id: "US-AF995-01", title: "US de prueba", objetivo: "H.", criterios_aceptacion: "C." });
    await post("/backlog/us/US-AF995-01/task", {
      id: "T-AF995-US01-01", title: "Task de prueba", objetivo: "O.", descripcion: "D.",
      criterios_aceptacion: "C.", priority: "Alta",
    });
  });
}

async function _openEpic(page, epicId) {
  await waitVisible(page, ".backlog-epic-line");
  await page.evaluate((id) => {
    const line = Array.from(document.querySelectorAll(".backlog-epic-line")).find((l) =>
      l.textContent.includes(id)
    );
    if (line) line.click();
  }, epicId);
}

async function test_us_row_shows_id_and_title_once() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await _seed(page);
    await _goToBacklogTab(page);
    await _openEpic(page, "AF-995");

    await page.waitForFunction(
      () => document.querySelector(".backlog-us-line-title") !== null,
      { timeout: 10000 }
    );
    const info = await page.evaluate(() => {
      const title = document.querySelector(".backlog-us-line-title").textContent;
      const meta = document.querySelector(".backlog-us-line-meta").textContent;
      return { title, meta };
    });
    assert.ok(
      info.title.includes("US-AF995-01") && info.title.includes("US de prueba"),
      "La fila de US debe mostrar ID + nombre, got: " + info.title
    );
    assert.ok(!/Pendiente|En curso|Terminada/.test(info.title), "El estado no debe ir en el texto de la línea: " + info.title);
    // La meta conserva fase y última actualización.
    assert.ok(/\[fase:/.test(info.meta), "La meta debe conservar la fase: " + info.meta);
  });
}

async function test_task_row_shows_id_and_title_once() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await _seed(page);
    await _goToBacklogTab(page);
    await _openEpic(page, "AF-995");
    // Esperar a que la línea de la US esté visible antes de abrirla.
    await page.waitForFunction(
      () => document.querySelector(".backlog-us-line") !== null,
      { timeout: 10000 }
    );
    // Abrir la US para ver su Task anidada.
    await page.evaluate(() => {
      const line = Array.from(document.querySelectorAll(".backlog-us-line")).find((l) =>
        l.textContent.includes("US-AF995-01")
      );
      if (line) line.click();
    });
    await page.waitForFunction(
      () => document.querySelector(".backlog-task-line-title") !== null,
      { timeout: 15000 }
    );
    const title = await page.evaluate(() => document.querySelector(".backlog-task-line-title").textContent);
    assert.ok(
      title.includes("T-AF995-US01-01") && title.includes("Task de prueba"),
      "La fila de Task debe mostrar ID + nombre, got: " + title
    );
    assert.ok(!/Pendiente|En curso|Terminada/.test(title), "El estado no debe ir en el texto de la línea: " + title);
  });
}

/* T-AF036-US19-03 (caso borde): una US/Task sin `title` en frontmatter se
 * renderiza SOLO con el ID, sin romper la fila. Ningún endpoint HTTP
 * permite crear un item sin `title` (campo obligatorio en los formularios
 * de creación), así que el frontmatter se escribe directamente en disco
 * vía `projectPath` (mismo patrón que `backlog_fuera_roadmap.test.js`) —
 * sin mockear ninguna lógica del backend real. */
async function _seedNoTitle(page, projectPath, epicId, usId, taskId) {
  await page.evaluate(async ({ epicId }) => {
    const post = async (p, b) => {
      const r = await fetch(p, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(b),
      });
      if (!r.ok) throw new Error("POST " + p + " falló: " + r.status);
    };
    await post("/backlog/epic", { id: epicId, title: "Epic", objetivo: "O." });
  }, { epicId });

  const storiesDir = path.join(projectPath, "02-backlog", "user-stories");
  fs.mkdirSync(storiesDir, { recursive: true });
  fs.writeFileSync(
    path.join(storiesDir, usId + "-sin-titulo.md"),
    "---\n" +
      "id: " + usId + "\n" +
      "type: user_story\n" +
      "state: READY\n" +
      "dependencies: []\n" +
      "epic: " + epicId + "\n" +
      "priority: Media\n" +
      "---\n\n" +
      "## Historia\n\nHistoria.\n\n## Criterios de aceptación\n\n1. Y.\n"
  );

  const tasksDir = path.join(projectPath, "02-backlog", "tasks");
  fs.mkdirSync(tasksDir, { recursive: true });
  fs.writeFileSync(
    path.join(tasksDir, taskId + "-sin-titulo.md"),
    "---\n" +
      "id: " + taskId + "\n" +
      "type: task\n" +
      "state: READY\n" +
      "dependencies: []\n" +
      "epic: " + epicId + "\n" +
      "user_story: " + usId + "\n" +
      "priority: Alta\n" +
      "---\n\n" +
      "## Objetivo\n\nObjetivo.\n\n## Criterios de aceptación\n\n1. Y.\n"
  );
}

async function test_us_row_without_title_shows_only_id() {
  await withBackend(async ({ page, baseUrl, projectPath }) => {
    assert.ok(projectPath, "El backend aislado debe exponer la ruta real del proyecto activo.");
    await page.goto(baseUrl + "/ui/");
    await _seedNoTitle(page, projectPath, "AF-994", "US-AF994-01", "T-AF994-US01-01");
    await page.reload();
    await _goToBacklogTab(page);
    await _openEpic(page, "AF-994");

    await page.waitForFunction(
      () => document.querySelector(".backlog-us-line-title") !== null,
      { timeout: 10000 }
    );
    const title = await page.evaluate(() => document.querySelector(".backlog-us-line-title").textContent);
    assert.strictEqual(title, "US-AF994-01", "La fila de US sin title debe mostrar SOLO el ID, got: " + title);
  });
}

async function test_task_row_without_title_shows_only_id() {
  await withBackend(async ({ page, baseUrl, projectPath }) => {
    assert.ok(projectPath, "El backend aislado debe exponer la ruta real del proyecto activo.");
    await page.goto(baseUrl + "/ui/");
    await _seedNoTitle(page, projectPath, "AF-994", "US-AF994-01", "T-AF994-US01-01");
    await page.reload();
    await _goToBacklogTab(page);
    await _openEpic(page, "AF-994");

    await page.waitForFunction(
      () => document.querySelector(".backlog-us-line") !== null,
      { timeout: 10000 }
    );
    // Abrir la US para ver su Task anidada.
    await page.evaluate(() => {
      const line = Array.from(document.querySelectorAll(".backlog-us-line")).find((l) =>
        l.textContent.includes("US-AF994-01")
      );
      if (line) line.click();
    });
    await page.waitForFunction(
      () => document.querySelector(".backlog-task-line-title") !== null,
      { timeout: 15000 }
    );
    const title = await page.evaluate(() => document.querySelector(".backlog-task-line-title").textContent);
    assert.strictEqual(title, "T-AF994-US01-01", "La fila de Task sin title debe mostrar SOLO el ID, got: " + title);
  });
}

module.exports = [
  {
    name: "T-AF036-US19-02: la fila de la User Story muestra ID + nombre y el estado solo en el control",
    fn: test_us_row_shows_id_and_title_once,
  },
  {
    name: "T-AF036-US19-02: la fila de la Task muestra ID + nombre y el estado solo en el control",
    fn: test_task_row_shows_id_and_title_once,
  },
  {
    name: "T-AF036-US19-03: la fila de la User Story sin title muestra solo el ID sin romper",
    fn: test_us_row_without_title_shows_only_id,
  },
  {
    name: "T-AF036-US19-03: la fila de la Task sin title muestra solo el ID sin romper",
    fn: test_task_row_without_title_shows_only_id,
  },
];