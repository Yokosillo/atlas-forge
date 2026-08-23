/* T-AF036-US16-06 (US-AF036-16): los tres botones de acción del detalle de
 * Epic — "+ Nueva User Story", "Proponer User Stories" y "Revisar cobertura"
 * — deben quedar alineados en una SOLA fila, compartiendo un ÚNICO
 * contenedor flex `.accion-controls` (antes cada uno iba en su propio
 * contenedor y se apilaban verticalmente).
 *
 * Se verifica sobre una Epic expandida: que los tres botones existen, que
 * comparten el mismo padre `.accion-controls`, y que ese contenedor es
 * `display:flex` con `flex-wrap:wrap` (para que en ventanas estrechas los
 * botones que no quepan pasen a la siguiente línea sin desbordar). Se siembra
 * la Epic vía HTTP (POST /backlog/epic) y se navega la web real con
 * `withBackend`. */

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

async function _seedEpic(page, epicId) {
  await page.evaluate(
    async (id) => {
      const resp = await fetch("/backlog/epic", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: id, title: "Epic " + id, objetivo: "Objetivo real." }),
      });
      if (!resp.ok) throw new Error("POST /backlog/epic falló: " + resp.status);
    },
    epicId
  );
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
  assert.ok(clicked, "No se encontró la línea de la Epic '" + epicId + "' para expandir.");
}

async function test_epic_detail_buttons_share_one_accion_controls_row() {
  await withBackend(async ({ page, baseUrl }) => {
    await page.goto(baseUrl + "/ui/");
    await _seedEpic(page, "AF-970");
    await _goToBacklogTab(page);
    await _openEpicDetail(page, "AF-970");

    // Los tres botones deben estar presentes.
    await page.waitForFunction(
      () =>
        Array.from(document.querySelectorAll("button")).some((b) => b.textContent.trim() === "Revisar cobertura"),
      { timeout: 10000 }
    );

    const rowInfo = await page.evaluate(() => {
      const labels = ["+ Nueva User Story", "Proponer User Stories", "Revisar cobertura"];
      const buttons = {};
      for (const label of labels) {
        buttons[label] = Array.from(document.querySelectorAll("button")).find(
          (b) => b.textContent.trim() === label
        );
      }
      const found = Object.values(buttons).every(Boolean);
      if (!found) return { found: false, labels: Object.keys(buttons) };

      // ¿Comparten el MISMO contenedor padre `.accion-controls`?
      const parents = labels.map((label) => buttons[label].parentElement);
      const sharedParent = parents.every((p) => p && p.classList.contains("accion-controls"))
        && parents.every((p) => p === parents[0]);
      const parent = parents[0];
      const style = parent ? getComputedStyle(parent) : null;
      return {
        found: true,
        sharedParent,
        display: style ? style.display : null,
        flexWrap: style ? style.flexWrap : null,
        parentClass: parent ? parent.className : null,
      };
    });

    assert.ok(rowInfo.found, "Los tres botones de acción deben existir en el detalle de la Epic.");
    assert.ok(
      rowInfo.sharedParent,
      "Los tres botones deben compartir el MISMO contenedor `.accion-controls` (una sola fila)."
    );
    assert.strictEqual(rowInfo.display, "flex", "El contenedor debe ser display:flex.");
    assert.strictEqual(rowInfo.flexWrap, "wrap", "El contenedor debe usar flex-wrap:wrap.");
  });
}

module.exports = [
  {
    name: "T-AF036-US16-06: los tres botones de acción del detalle de Epic comparten una única fila .accion-controls (flex wrap)",
    fn: test_epic_detail_buttons_share_one_accion_controls_row,
  },
];