/* T-AF036-US22-02 (US-AF036-22): el selector de estado de la web
 * deshabilita las opciones que NO son transiciones legales desde el estado
 * actual del item (adelante y atrás), según la réplica en cliente de
 * `can_transition`. La fuente de verdad sigue siendo el backend
 * (T-AF036-US22-01 lo rechaza con 400).
 *
 * Se siembra una Epic + US (READY) + Task (READY), se expande el detalle y
 * se inspeccionan los `<select class="backlog-edit-state">`:
 * - US en READY: habilitadas READY/TO_DEVELOP/IN_PROGRESS/IN_REVIEW/
 *   OUT_OF_SCOPE; deshabilitadas NO_TASKS/TO_PLAN/DONE.
 * - Task en READY: habilitadas READY/TO_DEVELOP; deshabilitadas el resto. */

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
    await post("/backlog/epic", { id: "AF-990", title: "Epic", objetivo: "O." });
    await post("/backlog/epic/AF-990/us", { id: "US-AF990-01", title: "US", objetivo: "H.", criterios_aceptacion: "C." });
    await post("/backlog/us/US-AF990-01/task", {
      id: "T-AF990-US01-01", title: "Task", objetivo: "O.", descripcion: "D.",
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

// Devuelve {enabled: [states], disabled: [states]} del primer select de
// estado dentro de la línea que contenga `text`.
async function _stateSelectInfo(page, rowText) {
  return page.evaluate((text) => {
    const row = Array.from(document.querySelectorAll(".backlog-us-line, .job-line")).find((l) =>
      l.textContent.includes(text)
    );
    const sel = row && row.querySelector("select.backlog-edit-state");
    if (!sel) return null;
    return Array.from(sel.options).reduce(
      (acc, o) => {
        if (o.disabled) acc.disabled.push(o.value);
        else acc.enabled.push(o.value);
        return acc;
      },
      { enabled: [], disabled: [] }
    );
  }, rowText);
}

async function test_us_selector_disables_illegal_transitions() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await _seed(page);
    await _goToBacklogTab(page);
    await _openEpic(page, "AF-990");
    await waitVisible(page, ".backlog-edit-state");

    const usInfo = await _stateSelectInfo(page, "US-AF990-01");
    assert.ok(usInfo, "Debe existir el selector de estado de la US.");
    assert.deepStrictEqual(
      usInfo.enabled.sort(),
      ["IN_PROGRESS", "IN_REVIEW", "OUT_OF_SCOPE", "READY", "TO_DEVELOP"],
      "US en READY: habilitadas las transiciones legales."
    );
    assert.deepStrictEqual(
      usInfo.disabled.sort(),
      ["DONE", "NO_TASKS", "TO_PLAN"],
      "US en READY: deshabilitadas las ilegales."
    );
  });
}

async function test_task_selector_disables_illegal_transitions() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await _seed(page);
    await _goToBacklogTab(page);
    await _openEpic(page, "AF-990");
    await waitVisible(page, ".backlog-edit-state");
    // Abrir la US para ver su Task anidada.
    await page.evaluate(() => {
      const line = Array.from(document.querySelectorAll(".backlog-us-line")).find((l) =>
        l.textContent.includes("US-AF990-01")
      );
      if (line) line.click();
    });
    await page.waitForFunction(
      () => Array.from(document.querySelectorAll("select.backlog-edit-state")).length >= 2,
      { timeout: 10000 }
    );

    const taskInfo = await _stateSelectInfo(page, "T-AF990-US01-01");
    assert.ok(taskInfo, "Debe existir el selector de estado de la Task.");
    assert.deepStrictEqual(
      taskInfo.enabled.sort(),
      ["READY", "TO_DEVELOP"],
      "Task en READY: habilitadas READY y TO_DEVELOP."
    );
    assert.ok(taskInfo.disabled.includes("DONE"), "Task en READY: DONE debe estar deshabilitado.");
    assert.ok(taskInfo.disabled.includes("IN_PROGRESS"), "Task en READY: IN_PROGRESS debe estar deshabilitado.");
  });
}


async function test_selector_recalculates_after_state_change() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await _seed(page);
    await _goToBacklogTab(page);
    await _openEpic(page, "AF-990");
    await waitVisible(page, ".backlog-edit-state");

    // Cambiar la US de READY a TO_DEVELOP (legal) vía el selector real.
    const changed = await page.evaluate(() => {
      const row = Array.from(document.querySelectorAll(".backlog-us-line")).find((l) =>
        l.textContent.includes("US-AF990-01")
      );
      const sel = row && row.querySelector("select.backlog-edit-state");
      if (!sel) return false;
      sel.value = "TO_DEVELOP";
      sel.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    });
    assert.ok(changed, "Debe existir el selector de estado de la US.");

    // El selector se reconstruye desde el nuevo estado TO_DEVELOP: READY e
    // IN_PROGRESS legales (habilitados), DONE sigue ilegal (deshabilitado).
    await page.waitForFunction(
      () => {
        const row = Array.from(document.querySelectorAll(".backlog-us-line")).find((l) =>
          l.textContent.includes("US-AF990-01")
        );
        const sel = row && row.querySelector("select.backlog-edit-state");
        if (!sel || sel.value !== "TO_DEVELOP") return false;
        const opts = Array.from(sel.options).reduce(
          (acc, o) => {
            if (o.disabled) acc.disabled.push(o.value);
            else acc.enabled.push(o.value);
            return acc;
          },
          { enabled: [], disabled: [] }
        );
        return opts.enabled.includes("READY")
          && opts.enabled.includes("IN_PROGRESS")
          && opts.disabled.includes("DONE");
      },
      { timeout: 10000 }
    );
  });
}

module.exports = [
  {
    name: "T-AF036-US22-02: el selector de estado de una US en READY deshabilita las transiciones ilegales",
    fn: test_us_selector_disables_illegal_transitions,
  },
  {
    name: "T-AF036-US22-02: el selector de estado de una Task en READY deshabilita las transiciones ilegales",
    fn: test_task_selector_disables_illegal_transitions,
  },
  {
    name: "T-AF036-US22-03: al cambiar de estado, el selector recalcula las opciones desde el nuevo estado",
    fn: test_selector_recalculates_after_state_change,
  },
];