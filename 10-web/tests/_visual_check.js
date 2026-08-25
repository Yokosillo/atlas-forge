/* Verificación visual temporal: botón como 3ª columna, columnas alineadas. */
"use strict";
const { launchBackend } = require("./harness");

const QUEUE = {
  queued: [{ task_id: "T-AF900-US01-01", us_id: "US-AF900-01", priority: "Alta", enqueued_at: "2026-08-23T10:00:00Z" }],
  dispatched: [{ task_id: "T-AF900-US01-02", us_id: "US-AF900-01", priority: "Media", agent_name: "Developer-1", enqueued_at: "2026-08-23T10:05:00Z", dispatched_at: "2026-08-23T10:06:00Z" }],
  awaiting_tester: [{ task_id: "T-AF900-US01-03", us_id: "US-AF900-01", priority: "Baja", agent_name: "Developer-1", enqueued_at: "2026-08-23T10:10:00Z", dispatched_at: "2026-08-23T10:12:00Z" }],
  completed: [{ task_id: "T-AF900-US01-04", us_id: "US-AF900-01", priority: "Alta", enqueued_at: "2026-08-23T10:20:00Z", dispatched_at: "2026-08-23T10:21:00Z", finished_at: "2026-08-23T10:22:00Z" }],
  failed: [{ task_id: "T-AF900-US01-05", us_id: "US-AF900-01", priority: "Crítica", enqueued_at: "2026-08-23T10:30:00Z", dispatched_at: "2026-08-23T10:31:00Z", finished_at: "2026-08-23T10:32:00Z", result: "Timeout" }],
};

async function _clickTab(page, labelPrefix) {
  await page.waitForSelector(".section-tab", { visible: true });
  const tabs = await page.$$(".section-tab");
  for (const tab of tabs) {
    const text = await page.evaluate((el) => el.textContent, tab);
    if (text.trim().startsWith(labelPrefix)) { await tab.click(); return; }
  }
  throw new Error("No tab");
}

(async () => {
  const backend = await launchBackend();
  const browser = await require("puppeteer").launch({ headless: "new", args: ["--no-sandbox", "--disable-setuid-sandbox"] });
  try {
    const page = await browser.newPage();
    await page.setRequestInterception(true);
    page.on("request", (req) => {
      if (req.url().includes("/backlog/queue") && req.method() === "GET") {
        req.respond({ status: 200, contentType: "application/json", body: JSON.stringify(QUEUE) });
      } else req.continue();
    });
    await page.goto(backend.baseUrl + "/ui/");
    await _clickTab(page, "Pipeline");
    await page.waitForFunction(() => document.querySelector(".backlog-queue-table"), { timeout: 20000 });
    const info = await page.evaluate(() => {
      const table = document.querySelector(".backlog-queue-table");
      const rows = Array.from(table.querySelectorAll("tbody tr.backlog-queue-row"));
      const headers = Array.from(table.querySelectorAll("thead th")).map((t) => t.textContent.trim() || "(btn)");
      const firstRowCells = Array.from(rows[0].cells).map((c) => c.textContent.trim().slice(0, 18));
      // ¿3ª columna (índice 2) es el botón en todas las filas?
      const actionsIdx = [];
      rows.forEach((r, i) => {
        const cell = r.cells[2];
        actionsIdx.push(!!cell.querySelector(".backlog-focus-toggle"));
      });
      // alineación vertical de las columnas de fecha (4,5,6) entre filas
      const colIdxMap = { Encolada: 3, Despachada: 4, Terminada: 5 };
      const colAlign = {};
      Object.keys(colIdxMap).forEach((label) => {
        const firstX = rows[0].cells[colIdxMap[label]].getBoundingClientRect().x;
        colAlign[label] = rows.every((r) => Math.abs(r.cells[colIdxMap[label]].getBoundingClientRect().x - firstX) < 2);
      });
      const buttons = Array.from(table.querySelectorAll(".backlog-focus-toggle"));
      return { headers, firstRowCells, actionsIdx, colAlign, buttonHeights: buttons.map((b) => Math.round(b.getBoundingClientRect().height)) };
    });
    console.log("INFO:", JSON.stringify(info, null, 2));
  } finally {
    await browser.close();
    await backend.stop();
  }
})().catch((e) => { console.error("ERR", e); process.exit(1); });