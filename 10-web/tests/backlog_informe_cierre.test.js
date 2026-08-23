/* T-AF036-US06-01 (US-AF036-06): el detalle expandido de una User Story
 * carga AUTOMÁTICAMENTE (sin clic explícito) su informe de cierre real vía
 * `GET /backlog/us/{us_id}/report` y lo muestra bajo el bloque de Tasks.
 *
 * Criterios cubiertos:
 * 1. Expandir una US con informe real de cierre muestra su contenido
 *    completo automáticamente, sin clic adicional.
 * 2. El backend resuelve el fichero real dentro de `07-informes/<us_id>/`
 *    por GLOB: el nombre del fichero NO coincide con `<story_id>.md` (se
 *    siembra `informe-cierre-2026-08-18.md`).
 * 3. Enlace por Task cerrada (`## <task_id> · ...`) que hace scroll a su
 *    sección dentro del bloque ya cargado, SIN fetch adicional.
 * 4. US sin ninguna Task cerrada -> texto explícito de ausencia, nunca un
 *    hueco vacío ni un mensaje de error.
 * 5. Error real de carga -> mensaje verbatim, distinguible del caso
 *    "informe ausente".
 *
 * Backlog sembrado vía HTTP (Epic + US + Task reales); el informe y el
 * estado `DONE` de la Task se escriben con `fs` sobre el proyecto aislado
 * (no hay endpoint que escriba `07-informes/`). */

"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const { withBackend, waitVisible } = require("./harness");

async function _goToBacklogTab(page) {
  await waitVisible(page, ".section-tab");
  const clicked = await page.evaluate(() => {
    const tab = Array.from(document.querySelectorAll(".section-tab")).find((el) =>
      el.textContent.trim().startsWith("Backlog")
    );
    if (!tab) return false;
    tab.click();
    return true;
  });
  assert.ok(clicked, "No se encontró la pestaña 'Backlog' en la navegación.");
}

async function _seedEpicWithUs(page, epicId, usId) {
  await page.evaluate(
    async ({ epicId, usId }) => {
      await fetch("/backlog/epic", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: epicId, title: "Epic de prueba", objetivo: "Objetivo real." }),
      });
      await fetch("/backlog/epic/" + epicId + "/us", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          id: usId,
          title: "Gestionar cola",
          objetivo: "H.",
          criterios_aceptacion: "C.",
        }),
      });
    },
    { epicId, usId }
  );
}

async function _seedDoneTask(page, projectPath, usId, taskId) {
  await page.evaluate(
    async ({ usId, taskId }) => {
      await fetch("/backlog/us/" + usId + "/task", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          id: taskId,
          title: "Implementar cola",
          objetivo: "Implementar la cola.",
          descripcion: "Cola de mensajes interna.",
          criterios_aceptacion: "- La cola encola y desencola.",
          priority: "Alta",
        }),
      });
    },
    { usId, taskId }
  );
  // La Task se crea en `READY` (create.py) — se marca `DONE` escribiendo
  // el fichero real, igual que lo haría el cierre del pipeline.
  const tasksDir = path.join(projectPath, "02-backlog", "tasks");
  const filename = fs.readdirSync(tasksDir).find((name) => name.startsWith(taskId + "-"));
  assert.ok(filename, `No se encontró el fichero de la Task ${taskId} en ${tasksDir}`);
  const taskPath = path.join(tasksDir, filename);
  const original = fs.readFileSync(taskPath, "utf-8");
  fs.writeFileSync(taskPath, original.replace(/^state: .*$/m, "state: DONE"));
}

function _writeClosingReport(projectPath, usId, reportName, content) {
  const reportsDir = path.join(projectPath, "07-informes", usId);
  fs.mkdirSync(reportsDir, { recursive: true });
  fs.writeFileSync(path.join(reportsDir, reportName), content);
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
  assert.ok(clicked, `No se encontró la línea de la Epic '${epicId}' para abrir su detalle.`);
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
  assert.ok(clicked, `No se encontró la línea de la User Story '${usId}' para abrir su detalle.`);
}

// ---------------------------------------------------------------------
// Criterios 1-3: informe real (nombre de fichero DISTINTO de `<us_id>.md`)
// se muestra automáticamente + enlace por Task con scroll sin fetch.
// ---------------------------------------------------------------------

async function test_us_detail_shows_real_closing_report_auto_with_task_scroll() {
  await withBackend(async ({ page, baseUrl, projectPath }) => {
    assert.ok(projectPath, "El backend aislado debe exponer la ruta real del proyecto activo.");

    await page.goto(baseUrl + "/ui/");
    await _seedEpicWithUs(page, "AF-943", "US-AF943-01");
    await _seedDoneTask(page, projectPath, "US-AF943-01", "T-AF943-US01-01");

    // Informe con nombre que NO coincide con `US-AF943-01.md` (caso real
    // confirmado, p. ej. `US-AF002-04/T-AF002-US04-01.md`), suficientemente
    // largo para que la sección de la Task quede bajo el pliegue.
    const reportLines = ["# Informe de cierre de US-AF943-01", ""];
    for (let i = 0; i < 40; i++) reportLines.push("Línea de contexto del informe " + i);
    reportLines.push("");
    reportLines.push("## T-AF943-US01-01 · Implementar cola");
    reportLines.push("La cola encola y desencola correctamente.");
    reportLines.push("Cerrada por el Developer tras verificar los criterios.");
    _writeClosingReport(projectPath, "US-AF943-01", "informe-cierre-2026-08-18.md", reportLines.join("\n"));

    await page.reload();
    await _goToBacklogTab(page);
    await _openEpicDetail(page, "AF-943");
    await _openUsDetail(page, "US-AF943-01");

    // La carga es automática: sin clic adicional, el contenido completo del
    // informe aparece bajo el bloque de Tasks.
    await page.waitForFunction(
      () => document.querySelector(".us-closing-report-content") !== null,
      { timeout: 10000 }
    );
    const contentText = await page.evaluate(() =>
      document.querySelector(".us-closing-report-content").textContent
    );
    assert.ok(
      contentText.includes("Informe de cierre de US-AF943-01"),
      "Debe mostrarse el contenido completo del informe (encabezado)."
    );
    assert.ok(
      contentText.includes("Cerrada por el Developer"),
      "Debe mostrarse el contenido completo del informe (cuerpo con saltos de línea)."
    );
    assert.ok(
      contentText.includes("T-AF943-US01-01 · Implementar cola"),
      "La sección de la Task cerrada debe aparecer en el informe."
    );

    // Enlace por Task cerrada a su sección, sin fetch adicional.
    const linkInfo = await page.evaluate(() => {
      const link = Array.from(document.querySelectorAll(".us-closing-report-task-link")).find(
        (a) => a.textContent.trim() === "T-AF943-US01-01"
      );
      if (!link) return null;
      const anchor = document.getElementById("us-report-task-T-AF943-US01-01");
      const beforeTop = anchor ? anchor.getBoundingClientRect().top : -1;
      return {
        href: link.getAttribute("href"),
        anchorId: anchor ? anchor.id : null,
        beforeTop: beforeTop,
      };
    });
    assert.ok(linkInfo, "Debe existir un enlace por la Task cerrada.");
    assert.strictEqual(linkInfo.href, "#us-report-task-T-AF943-US01-01");
    assert.strictEqual(linkInfo.anchorId, "us-report-task-T-AF943-US01-01");

    // Clic en el enlace: scroll a la sección SIN ninguna petición de red
    // nueva (el bloque ya está cargado).
    let reportRequests = 0;
    const onRequest = (req) => {
      if (/\/report$/.test(req.url())) reportRequests += 1;
    };
    page.on("request", onRequest);
    const requestsBefore = reportRequests;
    await page.evaluate(() => {
      const link = Array.from(document.querySelectorAll(".us-closing-report-task-link")).find(
        (a) => a.textContent.trim() === "T-AF943-US01-01"
      );
      link.click();
    });
    await new Promise((resolve) => setTimeout(resolve, 800));
    page.off("request", onRequest);
    assert.strictEqual(
      reportRequests, requestsBefore,
      "El scroll a la sección de la Task no debe disparar ningún fetch."
    );

    const afterTop = await page.evaluate(() => {
      const anchor = document.getElementById("us-report-task-T-AF943-US01-01");
      return anchor ? anchor.getBoundingClientRect().top : -1;
    });
    assert.ok(
      afterTop >= 0 && afterTop < 800,
      `El scroll debe llevar la sección de la Task a la vista (top=${afterTop}).`
    );
  });
}

// ---------------------------------------------------------------------
// Criterio 4: US sin ninguna Task cerrada -> mensaje explícito de
// ausencia, nunca un hueco vacío ni un error.
// ---------------------------------------------------------------------

async function test_us_without_closing_report_shows_explicit_absence() {
  await withBackend(async ({ page, baseUrl, projectPath }) => {
    assert.ok(projectPath, "El backend aislado debe exponer la ruta real del proyecto activo.");

    await page.goto(baseUrl + "/ui/");
    await _seedEpicWithUs(page, "AF-944", "US-AF944-01");

    await page.reload();
    await _goToBacklogTab(page);
    await _openEpicDetail(page, "AF-944");
    await _openUsDetail(page, "US-AF944-01");

    await page.waitForFunction(
      () => document.querySelector(".us-closing-report") !== null,
      { timeout: 10000 }
    );
    const reportText = await page.evaluate(() =>
      document.querySelector(".us-closing-report").textContent
    );
    assert.ok(
      reportText.includes("Sin informe de cierre — ninguna Task de esta User Story se ha cerrado todavía"),
      "Debe mostrarse el mensaje explícito de ausencia, no un hueco vacío."
    );
    assert.ok(
      !reportText.includes("Error del backend"),
      "El caso 'informe ausente' no debe confundirse con un error real."
    );
  });
}

// ---------------------------------------------------------------------
// Criterio 5: error real de carga -> mensaje verbatim, distinguible del
// caso "informe ausente".
// ---------------------------------------------------------------------

async function test_us_closing_report_real_error_shows_verbatim() {
  await withBackend(async ({ page, baseUrl, projectPath }) => {
    assert.ok(projectPath, "El backend aislado debe exponer la ruta real del proyecto activo.");

    await page.goto(baseUrl + "/ui/");
    await _seedEpicWithUs(page, "AF-945", "US-AF945-01");

    // Interceptar la carga del informe con un error REAL del backend (500)
    // para distinguir el caso de error del caso "informe ausente".
    await page.setRequestInterception(true);
    page.on("request", (req) => {
      if (/\/backlog\/us\/US-AF945-01\/report$/.test(req.url())) {
        req.respond({ status: 500, body: "fallo real del informe de cierre" });
        return;
      }
      req.continue();
    });

    await page.reload();
    await _goToBacklogTab(page);
    await _openEpicDetail(page, "AF-945");
    await _openUsDetail(page, "US-AF945-01");

    await page.waitForFunction(
      () =>
        document.querySelector(".us-closing-report .agent-error") !== null,
      { timeout: 10000 }
    );
    const errorText = await page.evaluate(() =>
      document.querySelector(".us-closing-report .agent-error").textContent
    );
    assert.ok(
      errorText.includes("fallo real del informe de cierre"),
      "El error real debe mostrarse verbatim, no reformulado."
    );
    const reportText = await page.evaluate(() =>
      document.querySelector(".us-closing-report").textContent
    );
    assert.ok(
      !reportText.includes("Sin informe de cierre"),
      "El caso de error real debe ser distinguible del caso 'informe ausente'."
    );
  });
}

// ---------------------------------------------------------------------
// Criterio 2 de la US: mientras carga, indicador de carga bajo el bloque
// de Tasks (la petición del informe se retiene para observarlo).
// ---------------------------------------------------------------------

async function test_us_report_shows_loading_indicator_while_in_flight() {
  await withBackend(async ({ page, baseUrl, projectPath }) => {
    assert.ok(projectPath, "El backend aislado debe exponer la ruta real del proyecto activo.");

    await page.goto(baseUrl + "/ui/");
    await _seedEpicWithUs(page, "AF-946", "US-AF946-01");
    _writeClosingReport(projectPath, "US-AF946-01", "informe-cierre-2026.md", "# Informe\n\nCerrada.\n");

    // Retener la petición del informe para observar el estado de carga.
    await page.setRequestInterception(true);
    let releaseHeld = null;
    const releasePromise = new Promise((resolve) => { releaseHeld = resolve; });
    page.on("request", (req) => {
      if (/\/backlog\/us\/US-AF946-01\/report$/.test(req.url())) {
        releasePromise.then(() => req.continue());
        return;
      }
      req.continue();
    });

    await page.reload();
    await _goToBacklogTab(page);
    await _openEpicDetail(page, "AF-946");
    await _openUsDetail(page, "US-AF946-01");

    // La carga está en vuelo -> indicador bajo el bloque de Tasks.
    await page.waitForFunction(
      () => {
        const report = document.querySelector(".us-closing-report");
        return report !== null && report.textContent.includes("Cargando informe de cierre…");
      },
      { timeout: 10000 }
    );

    releaseHeld();
    // Al resolver, el contenido completo reemplaza al indicador.
    await page.waitForFunction(
      () => document.querySelector(".us-closing-report-content") !== null,
      { timeout: 10000 }
    );
    const contentText = await page.evaluate(() =>
      document.querySelector(".us-closing-report-content").textContent
    );
    assert.ok(contentText.includes("Cerrada."), "El contenido debe aparecer tras el indicador.");
  });
}

module.exports = [
  {
    name: "detalle de US con informe real (nombre distinto de <us_id>.md) lo muestra automáticamente con scroll de sección sin fetch",
    fn: test_us_detail_shows_real_closing_report_auto_with_task_scroll,
  },
  {
    name: "detalle de US sin ninguna Task cerrada muestra el mensaje explícito de ausencia de informe",
    fn: test_us_without_closing_report_shows_explicit_absence,
  },
  {
    name: "error real de carga del informe se muestra verbatim, distinguible del caso informe ausente",
    fn: test_us_closing_report_real_error_shows_verbatim,
  },
  {
    name: "mientras carga el informe se muestra el indicador bajo el bloque de Tasks",
    fn: test_us_report_shows_loading_indicator_while_in_flight,
  },
];