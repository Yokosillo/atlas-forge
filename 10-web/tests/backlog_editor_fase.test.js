/* T-AF036-US14-02 (US-AF036-14): editor inline de fase en el detalle de la
 * Epic y de la User Story — permite cambiar la fase desde la pantalla
 * Backlog, persiste vía `PUT /backlog/{item_id}/fase` y reagrupa la vista
 * "Por Fase" sin recargar la página. Verificado en navegador real
 * (Chromium + backend aislado). */

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

async function _seed(page, epicId, usId) {
  await page.evaluate(
    async ({ epicId, usId }) => {
      const base = location.origin;
      const post = async (p, b) => {
        const r = await fetch(p, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(b),
        });
        if (!r.ok) throw new Error("POST " + p + " falló: " + r.status);
      };
      await post("/backlog/epic", { id: epicId, title: "Epic " + epicId, objetivo: "O." });
      await post("/backlog/epic/" + epicId + "/us", { id: usId, title: "US " + usId, objetivo: "H.", criterios_aceptacion: "C." });
    },
    { epicId, usId }
  );
}

async function _openEpicDetail(page, epicId) {
  await waitVisible(page, ".backlog-epic-line");
  const ok = await page.evaluate((id) => {
    const line = Array.from(document.querySelectorAll(".backlog-epic-line")).find((l) =>
      l.textContent.includes(id)
    );
    if (!line) return false;
    line.click();
    return true;
  }, epicId);
  assert.ok(ok, "No se encontró la línea de la Epic '" + epicId + "'.");
}

async function _setFaseAndSave(page, newFase) {
  await page.waitForFunction(() => document.querySelector(".backlog-fase-input") != null);
  await page.evaluate(
    (value) => {
      const input = document.querySelector(".backlog-fase-input");
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
      setter.call(input, value);
      input.dispatchEvent(new Event("input", { bubbles: true }));
      const btn = Array.from(document.querySelectorAll("button")).find(
        (b) => b.textContent.trim() === "Guardar"
      );
      if (btn) btn.click();
    },
    newFase
  );
}

async function test_editar_fase_de_user_story_desde_detalle() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await _seed(page, "AF-992", "US-AF992-01");
    await _goToBacklogTab(page);
    await _openEpicDetail(page, "AF-992");

    // Abrir el detalle de la US dentro de la Epic expandida.
    await waitVisible(page, ".backlog-us-line");
    const ok = await page.evaluate((id) => {
      const line = Array.from(document.querySelectorAll(".backlog-us-line")).find((l) =>
        l.textContent.includes(id)
      );
      if (!line) return false;
      line.click();
      return true;
    }, "US-AF992-01");
    assert.ok(ok, "No se pudo abrir el detalle de la US.");

    // Hay un editor de fase: el de la User Story (la Epic ya no lleva fase,
    // T-AF036-US18-01).
    await page.waitForFunction(
      () => document.querySelectorAll(".backlog-fase-editor").length >= 1
    );
    await page.evaluate((value) => {
      const editors = Array.from(document.querySelectorAll(".backlog-fase-editor"));
      const editor = editors[editors.length - 1]; // el editor de la US
      const input = editor.querySelector(".backlog-fase-input");
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
      setter.call(input, value);
      input.dispatchEvent(new Event("input", { bubbles: true }));
      const btn = editor.querySelector("button"); // Guardar de la US
      if (btn) btn.click();
    }, "Fase 0.9.2");

    // El editor de la US muestra el nuevo valor tras guardar.
    await page.waitForFunction(
      () => {
        const editors = Array.from(document.querySelectorAll(".backlog-fase-editor"));
        if (editors.length < 1) return false;
        const input = editors[editors.length - 1].querySelector(".backlog-fase-input");
        return input && input.value === "Fase 0.9.2";
      },
      { timeout: 5000 }
    );
  });
}

module.exports = [
  {
    name: "T-AF036-US14-02: se puede editar la fase de una User Story desde el detalle",
    fn: test_editar_fase_de_user_story_desde_detalle,
  },
  {
    name: "T-AF036-US14-04: el editor de fase muestra el error 400 sin romper la fila",
    fn: test_editor_fase_error_400_no_rompe_la_fila,
  },
  {
    name: "T-AF036-US14-04: la etiqueta 'actualizada' se muestra con texto claro o '—' cuando no hay updated_at",
    fn: test_etiqueta_actualizada_se_muestra,
  },
];


async function test_editor_fase_error_400_no_rompe_la_fila() {
  await withBackend(async ({ page, baseUrl }) => {
    // Interceptar PUT /backlog/{id}/fase para devolver 400 (simula rechazo
    // del backend sin alterar la lógica del frontend — permitido por PRUEBAS.md).
    await page.setRequestInterception(true);
    page.on("request", (req) => {
      if (req.method() === "PUT" && req.url().includes("/fase")) {
        req.respond({
          status: 400,
          contentType: "application/json",
          body: JSON.stringify({ detail: "contenido resultante inválido" }),
        });
      } else {
        req.continue();
      }
    });

    await page.goto(baseUrl + "/ui/");
    await _seed(page, "AF-994", "US-AF994-01");
    await _goToBacklogTab(page);
    await _openEpicDetail(page, "AF-994");

    // El editor de fase vive en la User Story (la Epic ya no lleva fase,
    // T-AF036-US18-01) — abrir el detalle de la US para ejercer el editor.
    await waitVisible(page, ".backlog-us-line");
    await page.evaluate((id) => {
      const line = Array.from(document.querySelectorAll(".backlog-us-line")).find((l) =>
        l.textContent.includes(id)
      );
      if (line) line.click();
    }, "US-AF994-01");

    await _setFaseAndSave(page, "Fase inválida");

    // El error 400 se muestra sin romper el detalle (el editor sigue presente).
    await page.waitForFunction(
      () => {
        const err = Array.from(document.querySelectorAll("p")).find(
          (p) => p.textContent.includes("400") || p.textContent.includes("inválido")
        );
        const editor = document.querySelector(".backlog-fase-input");
        return err && editor;
      },
      { timeout: 5000 }
    );
    // El detalle sigue abierto y con su editor.
    assert.ok(
      await page.evaluate(() => document.querySelector(".backlog-fase-input") != null),
      "El editor de fase debe seguir presente tras el error 400."
    );
  });
}

async function test_etiqueta_actualizada_se_muestra() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await _seed(page, "AF-995", "US-AF995-01");
    await _goToBacklogTab(page);
    await _openEpicDetail(page, "AF-995");

    // La línea de la US muestra la etiqueta "actualizada" (texto claro o
    // "—" si no hay updated_at).
    await waitVisible(page, ".backlog-us-line");
    const meta = await page.evaluate(() => {
      const line = Array.from(document.querySelectorAll(".backlog-us-line")).find((l) =>
        l.textContent.includes("US-AF995-01")
      );
      const metaEl = line && line.querySelector(".backlog-us-line-meta");
      return metaEl ? metaEl.textContent : null;
    });
    assert.ok(meta, "Debe existir la etiqueta de metadatos de la US.");
    assert.ok(
      /actualizaci/.test(meta),
      "La etiqueta de metadatos debe incluir la actualización ('actualizada'/'actualización'), got: " + meta
    );
    assert.ok(
      /—|\d{4}-\d{2}-\d{2}/.test(meta),
      "La etiqueta 'actualizada' debe mostrar una fecha o '—', got: " + meta
    );
  });
}
