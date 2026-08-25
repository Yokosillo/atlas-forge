/* Tests web deterministas del escenario del caso real de atascos del pipeline
 * (T-AF022-US17-05, US-AF022-17 criterio 5): combinando el panel "Bloqueadas"
 * (T-AF022-US17-02) y el indicador de huérfana/en vuelo (T-AF022-US17-03,
 * T-AF022-US17-01) —
 *
 *   T-AF023-US03-01 IN_PROGRESS huérfana (sin entrada `dispatched` →
 *   `in_flight: false` → badge "huérfana") bloquea a T-AF023-US03-02, que
 *   aparece en `items_bloqueada` como `← espera a T-AF023-US03-01 [IN_PROGRESS]`.
 *
 * Cubre además los filtros por estado IN_PROGRESS y "Bloqueadas"
 * (`epicMatchesBacklogFilters`, US-AF036-21): filtrar "Bloqueadas" deja solo
 * la Epic con items en `items_bloqueada`; filtrar IN_PROGRESS deja el panel
 * En curso con su badge.
 *
 * Navegador real (Chromium) contra el backend aislado; SOLO se intercambia el
 * estado de datos de `GET /backlog` (PRUEBAS.md). */

"use strict";

const assert = require("assert");
const { withBackend, waitVisible } = require("./harness");

const PAYLOAD = {
  empty: false,
  by_epic: [
    {
      epic: "AF-023",
      epic_label: "AF-023 · Pipeline automático",
      user_stories: { IN_PROGRESS: 1 },
      tasks: { READY: 1, IN_PROGRESS: 1 },
      user_stories_detail: [
        { id: "US-AF023-03", fase: null, state: "IN_PROGRESS", version: "0.9" },
      ],
    },
    {
      epic: "AF-999",
      epic_label: "AF-999 · Otra epic sin bloqueos",
      user_stories: { READY: 1 },
      tasks: { READY: 1 },
      user_stories_detail: [
        { id: "US-AF999-01", fase: null, state: "READY", version: "0.9" },
      ],
    },
  ],
  items_lista: [],
  items_bloqueada: [
    {
      id: "T-AF023-US03-02",
      kind: "T",
      epic: "AF-023",
      title: "Herramienta de gestión de tareas",
      priority: "Alta",
      version: "0.9",
      blocking_dependencies: [{ id: "T-AF023-US03-01", state: "IN_PROGRESS" }],
    },
  ],
  items_in_progress: [
    {
      id: "T-AF023-US03-01",
      kind: "T",
      epic: "AF-023",
      title: "Backlog automatizado",
      priority: "Crítica",
      version: "0.9",
      in_flight: false,
    },
  ],
  max_leverage_chain: [
    { id: "T-AF023-US03-02", kind: "T", epic: "AF-023", priority: "Alta" },
  ],
};

function _intercept(page) {
  return page.setRequestInterception(true).then(() => {
    page.on("request", (req) => {
      if (req.method() === "GET" && req.url().endsWith("/backlog")) {
        req.respond({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(PAYLOAD),
        });
      } else {
        req.continue();
      }
    });
  });
}

async function _gotoBacklog(page, baseUrl) {
  await page.goto(baseUrl + "/ui/");
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

async function _setStateFilter(page, value) {
  await page.evaluate((v) => {
    const sels = Array.from(document.querySelectorAll(".backlog-filter-select"));
    if (sels.length === 0) throw new Error("No hay selector de estado");
    const stateSel = sels[0];
    stateSel.value = v;
    stateSel.dispatchEvent(new Event("change"));
  }, value);
}

function _blockedDeps(page, itemId) {
  return page.evaluate((id) => {
    const item = Array.from(document.querySelectorAll(".backlog-bloqueadas-item")).find((el) => {
      const label = el.querySelector(".backlog-bloqueadas-label");
      return label && label.textContent.trim() === id;
    });
    if (!item) return [];
    return Array.from(item.querySelectorAll(".backlog-bloqueadas-dep")).map((el) => el.textContent.trim());
  }, itemId);
}

function _orphanBadgeInEnCurso(page, itemId) {
  return page.evaluate((id) => {
    const item = Array.from(document.querySelectorAll(".backlog-en-curso-item")).find((el) => {
      const label = el.querySelector(".backlog-en-curso-label");
      return label && label.textContent.trim() === id;
    });
    if (!item) return null;
    const badge = item.querySelector(".backlog-inflight-badge");
    if (!badge) return null;
    return { text: badge.textContent.trim(), cls: badge.className };
  }, itemId);
}

function _epicLineTexts(page) {
  return page.evaluate(() =>
    Array.from(document.querySelectorAll(".backlog-epic-line")).map((el) => el.textContent.trim())
  );
}

// -------------------------------------------------------------------------
// Caso real end-to-end: huérfana + bloqueada se ven juntas en la misma
// pantalla, con el badge y la dependencia pendiente con su estado.
// -------------------------------------------------------------------------

async function test_caso_real_huerfana_y_bloqueada() {
  await withBackend(async ({ page, baseUrl }) => {
    await _intercept(page);
    await _gotoBacklog(page, baseUrl);

    await waitVisible(page, ".backlog-bloqueadas-panel");
    await waitVisible(page, ".backlog-en-curso-panel");

    // Huérfana: T-AF023-US03-01 con badge "huérfana" (in_flight: false).
    const orphan = await _orphanBadgeInEnCurso(page, "T-AF023-US03-01");
    assert.ok(orphan, "T-AF023-US03-01 debe aparecer en el panel En curso.");
    assert.strictEqual(orphan.text, "huérfana");
    assert.ok(
      String(orphan.cls).includes("backlog-inflight-orphan"),
      "La huérfana debe usar la clase roja/naranja (distinguible al instante)."
    );

    // Bloqueada: T-AF023-US03-02 espera a la huérfana IN_PROGRESS.
    const deps = await _blockedDeps(page, "T-AF023-US03-02");
    assert.ok(
      deps.includes("← espera a T-AF023-US03-01 [IN_PROGRESS]"),
      "La bloqueada debe citar la dependencia pendiente con su estado: " + JSON.stringify(deps)
    );

    // Epic AF-023 visible (la del caso).
    const lines = await _epicLineTexts(page);
    assert.ok(
      lines.some((l) => l.indexOf("AF-023") !== -1),
      "La Epic del caso real debe estar en el listado: " + JSON.stringify(lines)
    );
  });
}

// -------------------------------------------------------------------------
// Filtros: "Bloqueadas" deja solo la Epic con items en items_bloqueada;
// IN_PROGRESS deja el panel En curso con su badge.
// -------------------------------------------------------------------------

async function test_filtros_in_progress_y_bloqueadas() {
  await withBackend(async ({ page, baseUrl }) => {
    await _intercept(page);
    await _gotoBacklog(page, baseUrl);

    await waitVisible(page, ".backlog-bloqueadas-panel");
    await waitVisible(page, ".backlog-en-curso-panel");
    await waitVisible(page, ".backlog-epic-line");

    // Por defecto hay dos Epic (AF-023 y AF-999).
    const linesAll = await _epicLineTexts(page);
    assert.ok(
      linesAll.some((l) => l.indexOf("AF-023") !== -1) && linesAll.some((l) => l.indexOf("AF-999") !== -1),
      "Sin filtro deben verse ambas Epics: " + JSON.stringify(linesAll)
    );

    // Filtrar "Bloqueadas": solo la Epic con items en items_bloqueada (AF-023).
    await _setStateFilter(page, "blocked");
    await page.waitForFunction(
      () => {
        const lines = Array.from(document.querySelectorAll(".backlog-epic-line"));
        return lines.length === 1 && lines[0].textContent.indexOf("AF-023") !== -1;
      },
      { timeout: 5000 }
    );
    const deps = await _blockedDeps(page, "T-AF023-US03-02");
    assert.ok(
      deps.includes("← espera a T-AF023-US03-01 [IN_PROGRESS]"),
      "Con el filtro Bloqueadas el panel sigue listando la bloqueada."
    );

    // Filtrar IN_PROGRESS: el panel En curso queda visible con su badge.
    await _setStateFilter(page, "IN_PROGRESS");
    await waitVisible(page, ".backlog-en-curso-item");
    const orphan = await _orphanBadgeInEnCurso(page, "T-AF023-US03-01");
    assert.strictEqual(orphan.text, "huérfana");

    // Volver a "Todos": ambas Epics reaparecen (filtros persistentes).
    await _setStateFilter(page, "all");
    await page.waitForFunction(
      () => document.querySelectorAll(".backlog-epic-line").length === 2,
      { timeout: 5000 }
    );
  });
}

module.exports = [
  {
    name: "T-AF022-US17-05 · caso real: huérfana T-AF023-US03-01 + bloqueada T-AF023-US03-02 (badge y dep con estado)",
    fn: test_caso_real_huerfana_y_bloqueada,
  },
  {
    name: "T-AF022-US17-05 · filtros por estado IN_PROGRESS y Bloqueadas sobre el escenario del caso real",
    fn: test_filtros_in_progress_y_bloqueadas,
  },
];