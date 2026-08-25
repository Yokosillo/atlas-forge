/* T-AF036-US09-01 (US-AF036-09): una User Story/Task en estado
 * "fuera de roadmap" se distingue visualmente en el listado y en el
 * detalle expandido del Backlog, con la etiqueta "Fuera de roadmap"
 * visible en su propia línea SIN desplegar (criterios 1 y 2), y el
 * selector de estado genérico (US-AF036-08) la incluye como opción
 * seleccionable (criterio 3).
 *
 * El vocabulario canónico tras AF-040 es `OUT_OF_SCOPE` (User Story;
 * antes `FUERA_ROADMAP`). Se siembra una Epic + User Story reales vía
 * HTTP y se reescribe el `state` de la US a `OUT_OF_SCOPE` directamente
 * en disco con `fs` (el endpoint de creación nace en `NO_TASKS`; no hay
 * endpoint HTTP que cree una US ya en OUT_OF_SCOPE — el estado se
 * gestiona por el selector, que es justo lo que este test verifica). */

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

async function _seedEpicAndUs(page, epicId, usId) {
  await page.evaluate(async ({ epicId, usId }) => {
    await fetch("/backlog/epic", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: epicId, title: "Epic postergada", objetivo: "Objetivo." }),
    });
    await fetch("/backlog/epic/" + epicId + "/us", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: usId, title: "US postergada", objetivo: "H.", criterios_aceptacion: "C." }),
    });
    // Segunda US ACTIVA (NO_TASKS) para que la Epic tenga trabajo
    // pendiente y NO quede agrupada bajo "Terminadas" (plegada e
    // invisible): una Epic cuya única US es OUT_OF_SCOPE no es
    // "pendiente" (`epicIsDone`), y su línea no se muestra.
    await fetch("/backlog/epic/" + epicId + "/us", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: "US-AF943-02", title: "US activa", objetivo: "H2.", criterios_aceptacion: "C2." }),
    });
  }, { epicId, usId });
}

async function _setUsStateToOutOfScope(projectPath, usId) {
  const storiesDir = path.join(projectPath, "02-backlog", "user-stories");
  const filename = fs.readdirSync(storiesDir).find((name) => name.startsWith(usId));
  assert.ok(filename, `No se encontró el fichero de ${usId} en ${storiesDir}`);
  const usPath = path.join(storiesDir, filename);
  const original = fs.readFileSync(usPath, "utf-8");
  assert.ok(original.includes("state: NO_TASKS"), `Frontmatter inesperado: ${original.split("\n").find((l) => l.includes("state:"))}`);
  fs.writeFileSync(usPath, original.replace("state: NO_TASKS", "state: OUT_OF_SCOPE"));
}

async function _openEpicDetail(page, epicId) {
  // Vista "Lista" primero: la vista por defecto "Por Versión" agrupa las
  // Epics por versión y una Epic cuyas US todavía no tienen versión se
  // clasifica como terminada en el grupo SIN_VERSION (oculta bajo
  // "Terminadas"); la vista plana clasifica por conteos de estado reales
  // (la US NO_TASKS cuenta como pendiente), donde la Epic siempre es
  // visible.
  const listaClicked = await page.evaluate(() => {
    const btn = Array.from(document.querySelectorAll(".backlog-view-toggle")).find((b) =>
      b.textContent.trim().startsWith("Lista")
    );
    if (!btn) return false;
    btn.click();
    return true;
  });
  assert.ok(listaClicked, "Debe existir el toggle 'Lista' para fijar la vista plana.");

  await waitVisible(page, ".backlog-epic-line");
  const clicked = await page.evaluate((id) => {
    const line = Array.from(document.querySelectorAll(".backlog-epic-line")).find((l) =>
      l.textContent.includes(id)
    );
    if (!line) return false;
    line.click();
    return true;
  }, epicId);
  assert.ok(clicked, `No se encontró la línea de la Epic '${epicId}' para abrir su detalle.`);
}

async function test_out_of_scope_us_is_distinguished_in_listing_and_selector() {
  await withBackend(async ({ page, baseUrl, projectPath }) => {
    assert.ok(projectPath, "El backend aislado debe exponer la ruta real del proyecto activo.");

    await page.goto(baseUrl + "/ui/");
    await _seedEpicAndUs(page, "AF-943", "US-AF943-01");
    _setUsStateToOutOfScope(projectPath, "US-AF943-01");

    await page.reload();
    await _goToBacklogTab(page);
    await _openEpicDetail(page, "AF-943");

    // Criterio 2 (decisión 2026-08-25): la US fuera de roadmap NO aparece
    // en el bloque de pendientes del detalle de la Epic — solo queda la US
    // activa (US-AF943-02) a la vista. Se localiza el encabezado colapsable
    // "Fuera de roadmap" y se despliega: la revelación y la lectura de la
    // línea se hacen en el MISMO `evaluate` (el click re-renderiza de forma
    // síncrona, sin carrera con un re-render del polling entre medias).
    await waitVisible(page, ".backlog-us-line");
    const inPendingBlock = await page.evaluate(() =>
      Array.from(document.querySelectorAll(".backlog-us-line")).some((l) =>
        l.textContent.includes("US-AF943-01")
      )
    );
    assert.strictEqual(inPendingBlock, false, "La US fuera de roadmap no debe mostrarse en el apartado de pendientes de la Epic.");

    const lineInfo = await page.evaluate(() => {
      const header = Array.from(document.querySelectorAll(".backlog-done-header")).find((h) =>
        h.textContent.includes("Fuera de roadmap")
      );
      if (!header) return { error: "no existe el encabezado colapsable 'Fuera de roadmap'" };
      header.click();
      const line = Array.from(document.querySelectorAll(".backlog-us-line")).find((l) =>
        l.textContent.includes("US-AF943-01")
      );
      if (!line) return { error: "la US postergada no aparece tras expandir el bloque" };
      return {
        text: line.textContent,
        titleText: (line.querySelector(".backlog-us-line-title") || {}).textContent || "",
        cardClass: line.parentElement.className,
        titleClass: (line.querySelector(".backlog-us-line-title") || {}).className || "",
      };
    });
    assert.ok(!lineInfo.error, lineInfo.error);
    assert.ok(
      lineInfo.text.includes("Fuera de roadmap"),
      "La línea debe mostrar 'Fuera de roadmap' sin desplegar el detalle."
    );
    // El valor crudo NO debe estar en el título de la línea (sí puede
    // aparecer en el `<select>` de estado, que muestra su valor actual).
    assert.ok(
      !lineInfo.titleText.includes("OUT_OF_SCOPE"),
      "No debe mostrarse el valor crudo 'OUT_OF_SCOPE' en el título de la línea."
    );
    assert.ok(
      lineInfo.cardClass.includes("backlog-fuera-roadmap"),
      "La tarjeta de la US debe llevar la clase distintiva 'backlog-fuera-roadmap'."
    );

    // Criterio 3: el selector de estado de la línea incluye OUT_OF_SCOPE
    // como opción seleccionable (y está seleccionado, ya que es el estado
    // actual).
    const selectInfo = await page.evaluate(() => {
      const line = Array.from(document.querySelectorAll(".backlog-us-line")).find((l) =>
        l.textContent.includes("US-AF943-01")
      );
      const select = line.querySelector(".backlog-edit-state");
      if (!select) return null;
      return {
        values: Array.from(select.options).map((o) => o.value),
        selected: select.value,
        selectClass: select.className,
      };
    });
    assert.ok(selectInfo, "No se encontró el selector de estado de la US.");
    assert.ok(
      selectInfo.values.includes("OUT_OF_SCOPE"),
      "El selector de estado debe incluir 'OUT_OF_SCOPE' como opción seleccionable."
    );
    assert.strictEqual(
      selectInfo.selected,
      "OUT_OF_SCOPE",
      "El selector debe estar seleccionado en OUT_OF_SCOPE (estado actual de la US)."
    );
    assert.ok(
      selectInfo.selectClass.includes("backlog-edit-state--out-of-scope"),
      "El selector debe llevar la clase de color distintiva del estado fuera de roadmap."
    );

    // Criterio 1: el detalle expandido también muestra "Fuera de roadmap".
    // (La `renderItemDetail` actual ya no pinta un campo "Estado:" — el
    // estado queda en la etiqueta "— Fuera de roadmap" de la propia línea,
    // visible también con el detalle desplegado.)
    const clicked = await page.evaluate(() => {
      const line = Array.from(document.querySelectorAll(".backlog-us-line")).find((l) =>
        l.textContent.includes("US-AF943-01")
      );
      line.click();
      return true;
    });
    assert.ok(clicked);
    await page.waitForFunction(
      () => {
        const lines = Array.from(document.querySelectorAll(".backlog-us-line"));
        const line = lines.find((l) => l.textContent.includes("US-AF943-01"));
        if (!line || !line.className.includes("job-line-selected")) return false;
        const title = (line.querySelector(".backlog-us-line-title") || {}).textContent || "";
        const detail = (line.closest(".job-card") || {}).textContent || "";
        return title.includes("Fuera de roadmap") && detail.includes("H.");
      },
      { timeout: 10000 }
    );
  });
}

async function _writeTaskOutOfScope(projectPath, usId, taskId, taskTitle) {
  const tasksDir = path.join(projectPath, "02-backlog", "tasks");
  fs.mkdirSync(tasksDir, { recursive: true });
  const slug = taskTitle.toLowerCase().replace(/\s+/g, "-");
  const taskPath = path.join(tasksDir, taskId + "-" + slug + ".md");
  fs.writeFileSync(
    taskPath,
    "---\n" +
      "id: " + taskId + "\n" +
      "type: task\n" +
      "title: " + taskTitle + "\n" +
      "epic: AF-943\n" +
      "user_story: " + usId + "\n" +
      "state: OUT_OF_SCOPE\n" +
      "dependencies: []\n" +
      "priority: Media\n" +
      "---\n"
  );
}

async function test_out_of_scope_task_is_distinguished_in_listing() {
  await withBackend(async ({ page, baseUrl, projectPath }) => {
    assert.ok(projectPath, "El backend aislado debe exponer la ruta real del proyecto activo.");

    await page.goto(baseUrl + "/ui/");
    await _seedEpicAndUs(page, "AF-943", "US-AF943-01");
    _writeTaskOutOfScope(projectPath, "US-AF943-01", "T-AF943-US01-01", "Task postergada");
    // Reescritura del estado de la US a OUT_OF_SCOPE (sin endpoint HTTP);
    // la Task ya nace OUT_OF_SCOPE.
    _setUsStateToOutOfScope(projectPath, "US-AF943-01");

    await page.reload();
    await _goToBacklogTab(page);
    await _openEpicDetail(page, "AF-943");
    await waitVisible(page, ".backlog-us-line");

    // La US fuera de roadmap vive bajo el bloque colapsable "Fuera de
    // roadmap", no en el apartado de pendientes (decisión 2026-08-25) — se
    // expande el bloque en el MISMO `evaluate` en que se localiza la US,
    // para abrir su detalle a continuación sin carrera con un re-render.
    const openedUs = await page.evaluate(() => {
      const header = Array.from(document.querySelectorAll(".backlog-done-header")).find((h) =>
        h.textContent.includes("Fuera de roadmap")
      );
      if (header) header.click();
      const line = Array.from(document.querySelectorAll(".backlog-us-line")).find((l) =>
        l.textContent.includes("US-AF943-01")
      );
      if (!line) return false;
      line.click();
      return true;
    });
    assert.ok(openedUs, "No se pudo abrir el detalle de la US para ver sus Tasks.");

    // Criterio 1 (Task): la línea de la Task en OUT_OF_SCOPE muestra la
    // etiqueta "Fuera de roadmap" sin desplegar su detalle y lleva la clase
    // distintiva de color.
    await waitVisible(page, ".backlog-task-line-title");
    const taskInfo = await page.evaluate(() => {
      const line = Array.from(document.querySelectorAll(".backlog-task-line-title")).find((t) =>
        t.textContent.includes("T-AF943-US01-01")
      );
      if (!line) return null;
      return {
        text: line.textContent,
        titleClass: line.className,
        cardClass: line.closest(".job-card").className,
      };
    });
    assert.ok(taskInfo, "No se encontró la línea de la Task postergada.");
    assert.ok(
      taskInfo.text.includes("Fuera de roadmap"),
      "La línea de la Task debe mostrar 'Fuera de roadmap' sin desplegar."
    );
    assert.ok(
      !taskInfo.text.includes("OUT_OF_SCOPE"),
      "No debe mostrarse el valor crudo 'OUT_OF_SCOPE' en la línea de la Task."
    );
    assert.ok(
      taskInfo.titleClass.includes("backlog-us-line-title--fuera-roadmap"),
      "El título de la Task debe llevar la clase distintiva de fuera de roadmap."
    );
    assert.ok(
      taskInfo.cardClass.includes("backlog-fuera-roadmap"),
      "La tarjeta de la Task debe llevar la clase 'backlog-fuera-roadmap'."
    );
  });
}

module.exports = [
  {
    name: "una User Story en OUT_OF_SCOPE se distingue con 'Fuera de roadmap', clase propia y selector con la opción",
    fn: test_out_of_scope_us_is_distinguished_in_listing_and_selector,
  },
  {
    name: "una Task en OUT_OF_SCOPE se distingue con 'Fuera de roadmap' y clase propia en la lista de Tasks de su US",
    fn: test_out_of_scope_task_is_distinguished_in_listing,
  },
];
