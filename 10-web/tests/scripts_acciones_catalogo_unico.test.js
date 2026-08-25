/* Tests de la fusión Scripts + Acciones en un único catálogo (T-AF034-US01-02):
 * navegador real contra el backend aislado que ya sirve el catálogo combinado
 * (`GET /scripts` = genéricos + particulares + accciones, T-AF034-US01-01).
 * Cubre los criterios 1/2/4 del catálogo (UNA sección, sin `ACCIONES`
 * hardcodeada, proyecto sin particulares sin romper) y el criterio 5
 * (single-flight global + panel de resultado único). El criterio 3 (mismo
 * backend de ejecución) se verifica interceptando la red SOLO en la respuesta
 * del POST de ejecución (para no lanzar subprocesos/jobs reales) y
 * comprobando que cada tipo de entrada dispara su endpoint correspondiente
 * (`POST /scripts/{id}/run` y `POST /project/actions/{id}`).
 *
 * Se usa Chromium real + backend real aislado (patrón de `harness.js`);
 * la interceptación solo sustituye el estado de datos de la respuesta de
 * ejecución, nunca la lógica de la pantalla bajo prueba (PRUEBAS.md). */

"use strict";

const assert = require("assert");
const { withBackend, waitVisible } = require("./harness");

async function gotoScriptsTab(page, baseUrl) {
  await page.goto(baseUrl + "/ui/scripts");
  await waitVisible(page, ".section-content");
  await waitVisible(page, ".script-card", { timeout: 10000 });
}

async function navTabTexts(page) {
  return page.evaluate(() =>
    Array.from(document.querySelectorAll(".section-tab")).map((el) => el.textContent.trim())
  );
}

async function runButtonsState(page) {
  return page.evaluate(() =>
    Array.from(document.querySelectorAll(".scripts-body .script-run")).map((btn) => ({
      text: btn.textContent.trim(),
      disabled: btn.disabled,
    }))
  );
}

async function resultBoxesInCatalog(page) {
  return page.evaluate(() =>
    Array.from(document.querySelectorAll(".scripts-body .script-result, .scripts-body .accion-result")).length
  );
}

// ---------------------------------------------------------------------
// Criterio 1 y 2: UNA sola sección — sin pestaña "Acciones", el catálogo
// combinado dibuja Scripts genéricos y Acciones en la misma pantalla, sin
// la constante ACCIONES hardcodeada, y el proyecto (sin manifiesto) no
// pinta "Proyecto" ni rompe (criterio 4).
// ---------------------------------------------------------------------

async function test_unica_seccion_dibuja_scripts_y_acciones() {
  await withBackend(async ({ page, baseUrl }) => {
    await gotoScriptsTab(page, baseUrl);

    // Criterio 1: UNA única pestaña — existe "Scripts", NO existe "Acciones".
    const tabs = await navTabTexts(page);
    assert.ok(tabs.includes("Scripts"), "La pestaña Scripts debe seguir existiendo.");
    assert.ok(
      !tabs.includes("Acciones"),
      "La pestaña 'Acciones' debe haber desaparecido: " + JSON.stringify(tabs)
    );

    // `/ui/acciones` ya no es una ruta válida: cae a la sección por defecto.
    await page.goto(baseUrl + "/ui/acciones");
    await waitVisible(page, ".section-content");
    const defTitle = await page.evaluate(() => document.querySelector(".section-content h3").textContent);
    assert.ok(
      defTitle !== "Acciones",
      "La ruta directa /ui/acciones no debe renderizar una sección Acciones."
    );

    // Volver a la pestaña única de catálogo.
    await gotoScriptsTab(page, baseUrl);

    // Criterio 2: el catálogo combinado dibuja genéricos (scripts) y acciones.
    const titles = await page.evaluate(() =>
      Array.from(document.querySelectorAll(".scripts-body .scripts-group-title")).map((el) => el.textContent.trim())
    );
    assert.ok(titles.includes("Genéricos (Atlas Forge)"), "Debe existir el grupo de scripts genéricos.");
    assert.ok(
      titles.includes("Acciones transversales"),
      "Debe existir el grupo de acciones transversales en la MISMA sección: " + JSON.stringify(titles)
    );

    const cardNames = await page.evaluate(() =>
      Array.from(document.querySelectorAll(".scripts-body .script-name")).map((el) => el.textContent.trim())
    );
    assert.ok(
      cardNames.includes("Commit de cambios"),
      "Un script genérico debe seguir listándose: " + JSON.stringify(cardNames)
    );
    assert.ok(
      cardNames.includes("Documentar todo"),
      "Una acción transversal debe listarse desde el catálogo combinado (no hardcodeada): " + JSON.stringify(cardNames)
    );

    // Criterio 4: sin manifiesto no hay grupo "Proyecto" ni errores.
    assert.ok(
      !titles.includes("Proyecto"),
      "Un proyecto sin scripts particulares no debe pintar el grupo 'Proyecto'."
    );
    const errorShown = await page.evaluate(() =>
      document.querySelectorAll(".scripts-body .agent-error").length > 0
    );
    assert.ok(!errorShown, "El catálogo no debe mostrar errores con proyecto sin manifiesto.");
  });
}

// ---------------------------------------------------------------------
// Criterio 5 (y 3 para scripts): single-flight global — al ejecutar un
// script, TODAS las tarjetas (scripts y acciones) se deshabilitan, y el
// resultado se muestra en UN solo panel.
// ---------------------------------------------------------------------

async function test_single_flight_global_y_panel_unico() {
  await withBackend(async ({ page, baseUrl }) => {
    await gotoScriptsTab(page, baseUrl);

    let scriptRunRequested = false;
    await page.setRequestInterception(true);
    page.on("request", (req) => {
      if (req.method() === "POST" && req.url().endsWith("/scripts/changed_files/run")) {
        scriptRunRequested = true;
        // Respuesta diferida y de estado simulado (sin ejecutar nada real):
        // se retiene en vuelo para observar el single-flight en el DOM.
        setTimeout(() => {
          req.respond({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({
              success: true,
              exit_code: 0,
              stdout: "file.txt\n",
              stderr: "",
              error_message: null,
            }),
          });
        }, 900);
        return;
      }
      req.continue();
    });

    // Pulsar "Ficheros modificados" (script genérico sin parámetro).
    await page.evaluate(() => {
      const card = Array.from(document.querySelectorAll(".script-card")).find(
        (c) => c.querySelector(".script-name").textContent.trim() === "Ficheros modificados"
      );
      card.querySelector(".script-run").click();
    });

    await page.waitForFunction(
      () => {
        const btns = Array.from(document.querySelectorAll(".scripts-body .script-run"));
        return btns.length > 0 && btns.every((b) => b.disabled);
      },
      { timeout: 5000 }
    );
    assert.ok(
      scriptRunRequested,
      "La ejecución de un script debe disparar POST /scripts/changed_files/run."
    );

    // Se usó el endpoint de scripts real (criterio 3, lado scripts).
    const states = await runButtonsState(page);
    assert.ok(
      states.some((s) => s.text === "Ejecutando…") && states.every((s) => s.disabled),
      "Single-flight global: al ejecutar un script, TODAS las tarjetas quedan deshabilitadas."
    );

    // Panel de resultado ÚNICO (criterio 5): exactamente un bloque de
    // resultado, sin duplicar el de scripts y el de acciones. (La tarjeta
    // `commit` mantiene su botón deshabilitado esperando mensaje; el vuelo
    // se considera terminado cuando la tarjeta ejecutada vuelve a "Ejecutar".)
    await page.waitForFunction(
      () => {
        const card = Array.from(document.querySelectorAll(".script-card")).find(
          (c) => c.querySelector(".script-name").textContent.trim() === "Ficheros modificados"
        );
        return card && card.querySelector(".script-run").textContent.trim() === "Ejecutar";
      },
      { timeout: 8000 }
    );
    await waitVisible(page, ".scripts-body .script-result");
    assert.strictEqual(
      await resultBoxesInCatalog(page),
      1,
      "Debe haber UN único panel de resultado tras ejecutar un script."
    );
    const resText = await page.evaluate(() => document.querySelector(".scripts-body .script-result").textContent);
    assert.ok(resText.includes("Éxito"), "Debe mostrarse el resultado del script en el panel único.");
  });
}

// ---------------------------------------------------------------------
// Criterio 3 (lado acciones): una Acción se ejecuta contra el MISMO backend
// de antes (`POST /project/actions/{id}`) dentro del mismo single-flight
// global, y su resultado aparece en el mismo panel único.
// ---------------------------------------------------------------------

async function test_accion_mismo_backend_y_single_flight() {
  await withBackend(async ({ page, baseUrl }) => {
    await gotoScriptsTab(page, baseUrl);

    let actionRequested = false;
    await page.setRequestInterception(true);
    page.on("request", (req) => {
      if (req.method() === "POST" && /\/project\/actions\/testear$/.test(req.url())) {
        actionRequested = true;
        setTimeout(() => {
          req.respond({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({
              action: "testear",
              success: true,
              exit_code: 0,
              stdout: "todos los tests pasan\n",
              stderr: "",
            }),
          });
        }, 700);
        return;
      }
      req.continue();
    });

    await page.evaluate(() => {
      const card = Array.from(document.querySelectorAll(".script-card")).find(
        (c) => c.querySelector(".script-name").textContent.trim() === "Testear todo"
      );
      card.querySelector(".script-run").click();
    });

    await page.waitForFunction(
      () => {
        const btns = Array.from(document.querySelectorAll(".scripts-body .script-run"));
        return btns.length > 0 && btns.every((b) => b.disabled);
      },
      { timeout: 5000 }
    );
    assert.ok(
      actionRequested,
      "La ejecución de una Acción debe disparar POST /project/actions/testear (mismo backend)."
    );

    await waitVisible(page, ".scripts-body .accion-result", { timeout: 8000 });
    assert.strictEqual(
      await resultBoxesInCatalog(page),
      1,
      "El resultado de la acción debe mostrarse en el mismo panel único."
    );
    const resText = await page.evaluate(() => document.querySelector(".scripts-body .accion-result").textContent);
    assert.ok(resText.includes("testear todo"), "Debe rotularse el resultado de la acción ejecutada.");
    assert.ok(resText.includes("todos los tests pasan"), "Debe mostrarse la salida real de la acción.");
  });
}

module.exports = [
  {
    name: "T-AF034-US01-02 · UNA sección dibuja scripts genéricos y acciones; sin pestaña Acciones; sin particulares no rompe",
    fn: test_unica_seccion_dibuja_scripts_y_acciones,
  },
  {
    name: "T-AF034-US01-02 · single-flight global al ejecutar un script y panel de resultado único",
    fn: test_single_flight_global_y_panel_unico,
  },
  {
    name: "T-AF034-US01-02 · una Acción usa POST /project/actions/{id} (mismo backend) y su resultado sale en el panel único",
    fn: test_accion_mismo_backend_y_single_flight,
  },
];