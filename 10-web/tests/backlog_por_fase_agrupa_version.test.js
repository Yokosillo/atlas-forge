/* T-AF036-US15-06 (US-AF036-15 criterio 5): la vista "Por Fase" agrupa las
 * Epics por su VERSION (US-AF036-18: la fase es de la User Story, la Epic se
 * versiona) y muestra la VERSION como cabecera de grupo, con "SIN_VERSION" al
 * final. Verificado en navegador real (Chromium + backend aislado), mismo
 * patrón que la suite canónica.
 *
 * El backlog se siembra vía HTTP (Epic + US + Task reales); la VERSION de
 * cada Epic se fija reescribiendo su frontmatter con `fs` (`POST /backlog/epic`
 * crea la Epic con `version: 0.9` por defecto). */

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

async function _seedEpicUs(page, epicId, projectPath) {
  await page.evaluate(
    async ({ epicId }) => {
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
      await post("/backlog/us/" + usId + "/task", {
        id: "T-" + usId.replace("US-AF", "AF").replace("-", "-US") + "-01",
        title: "Task de " + epicId, objetivo: "O.", descripcion: "D.",
        criterios_aceptacion: "C.", priority: "Alta",
      });
    },
    { epicId }
  );
  _setEpicVersion(projectPath, epicId, _versionFor(epicId));
}

function _versionFor(epicId) {
  const map = { "AF-971": "1.2", "AF-972": "0.9", "AF-973": "1.0" };
  return map[epicId] || null;
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
  if (version) {
    fs.writeFileSync(p, original.slice(0, idx) + "\nversion: " + version + original.slice(idx));
  } else {
    // `POST /backlog/epic` crea la Epic con `version: 0.9` por defecto. Para
    // simular una Epic SIN version (grupo "SIN_VERSION"), se elimina el campo
    // del frontmatter.
    fs.writeFileSync(p, original.replace(/\nversion:.*\n/, "\n"));
  }
}

async function _clickButtonByText(page, text) {
  const clicked = await page.evaluate((label) => {
    const btn = Array.from(document.querySelectorAll("button")).find((b) =>
      b.textContent.includes(label)
    );
    if (!btn || btn.disabled) return false;
    btn.click();
    return true;
  }, text);
  assert.ok(clicked, "No se encontró el botón con texto que contenga '" + text + "'.");
}

// Las Epics se agrupan por VERSION con cabeceras mostrando la VERSION y
// "SIN_VERSION" al final (Epics creadas sin version declarada).
async function test_por_fase_agrupa_epics_por_version() {
  await withBackend(async ({ page, baseUrl, projectPath }) => {
    assert.ok(projectPath, "El backend aislado debe exponer la ruta real del proyecto activo.");

    await page.goto(baseUrl + "/ui/");
    // Tres Epics con versiones distintas + una sin version.
    await _seedEpicUs(page, "AF-971", projectPath); // version 1.2
    await _seedEpicUs(page, "AF-972", projectPath); // version 0.9
    await _seedEpicUs(page, "AF-973", projectPath); // version 1.0
    await _seedEpicUs(page, "AF-974", projectPath); // SIN_VERSION

    await page.reload();
    await _goToBacklogTab(page);
    await _clickButtonByText(page, "Por Fase");
    await waitVisible(page, ".backlog-fase-title");

    const titles = await page.evaluate(() =>
      Array.from(document.querySelectorAll(".backlog-fase-title")).map((t) => t.textContent.trim())
    );
    assert.deepStrictEqual(
      titles,
      ["0.9", "1.0", "1.2", "SIN_VERSION"],
      "La vista 'Por Fase' debe agrupar por VERSION naturalmente (0.9 < 1.0 < 1.2) con SIN_VERSION al final, got: " + JSON.stringify(titles)
    );

    // Cada Epic queda en el grupo de su VERSION.
    const placement = await page.evaluate(() => {
      const groups = Array.from(document.querySelectorAll(".backlog-fase-group"));
      const epicIn = {};
      groups.forEach((g) => {
        const version = (g.querySelector(".backlog-fase-title") || {}).textContent.trim();
        Array.from(g.querySelectorAll(".backlog-epic-line")).forEach((l) => {
          const t = (l.querySelector(".backlog-epic-line-title") || {}).textContent || "";
          const m = /AF-\d+/.exec(t);
          if (m) epicIn[m[0]] = version;
        });
      });
      return epicIn;
    });
    assert.strictEqual(placement["AF-972"], "0.9", "AF-972 (version 0.9) debe estar en el grupo 0.9.");
    assert.strictEqual(placement["AF-973"], "1.0", "AF-973 (version 1.0) debe estar en el grupo 1.0.");
    assert.strictEqual(placement["AF-971"], "1.2", "AF-971 (version 1.2) debe estar en el grupo 1.2.");
    assert.strictEqual(placement["AF-974"], "SIN_VERSION", "AF-974 (sin version) debe estar en SIN_VERSION.");
  });
}

module.exports = [
  {
    name: "la vista 'Por Fase' agrupa las Epics por VERSION (0.9 < 1.0 < 1.2; SIN_VERSION al final)",
    fn: test_por_fase_agrupa_epics_por_version,
  },
];