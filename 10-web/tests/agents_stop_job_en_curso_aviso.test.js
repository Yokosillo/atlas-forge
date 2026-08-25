/* Tests web deterministas del aviso "Job en curso" en el flujo de detener
 * (T-AF021-US03-04, US-AF021-03 criterio 3): antes de la confirmación final
 * de detener un agente (Developer y Arquitecto), si el agente tiene un Job
 * `running` (`GET /jobs`, agente objetivo + estado running) se muestra un
 * aviso explícito junto a la confirmación; sin Jobs en curso no hay aviso
 * (sin ruido); un fallo del fetch NO bloquea la detención.
 *
 * Navegador real (Chromium) contra el backend aislado. SOLO se intercambia el
 * estado de datos de `GET /agents` y `GET /jobs` (no la lógica del frontend
 * bajo prueba — PRUEBAS.md): agentes sintéticos con id conocido y Jobs con
 * `agent_id`/`status` fabricados. No se confirma la detención (no se ejecuta
 * `stopAgent` ni se lanza ningún agente real). */

"use strict";

const assert = require("assert");
const { withBackend, waitVisible } = require("./harness");

const DEV_AGENT = {
  id: "dev-1",
  name: "Developer-1",
  role: "developer",
  status: "idle",
  runtime_id: "opencode",
  model: "atlas-forge/gpt-mini",
  last_command_at: null,
  session_name: null,
  prompt: "p",
};

const ARQ_AGENT = {
  id: "arq-1",
  name: "Arquitecto",
  role: "arquitecto",
  status: "idle",
  runtime_id: "opencode",
  model: null,
  last_command_at: null,
  session_name: null,
  prompt: "p",
};

function _runningJob(jobId, agentId) {
  return {
    id: jobId,
    agent_id: agentId,
    status: "running",
    description: "Desarrolla la Task de prueba",
    session_id: "s1",
    created_at: "2026-08-24T00:00:00+00:00",
  };
}

function _intercept(page, jobsRespond) {
  return page.setRequestInterception(true).then(() => {
    page.on("request", (req) => {
      const url = req.url();
      if (req.method() === "GET" && url.endsWith("/agents")) {
        req.respond({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([DEV_AGENT, ARQ_AGENT]),
        });
      } else if (req.method() === "GET" && url.endsWith("/jobs")) {
        jobsRespond(req);
      } else {
        req.continue();
      }
    });
  });
}

async function _gotoAgentes(page, baseUrl) {
  await page.goto(baseUrl + "/ui/");
  await waitVisible(page, ".section-tab");
  const tabs = await page.$$(".section-tab");
  for (const tab of tabs) {
    const text = await page.evaluate((el) => el.textContent, tab);
    if (text.trim().startsWith("Agentes")) {
      await tab.click();
      return;
    }
  }
  throw new Error("No se encontró la pestaña 'Agentes'.");
}

function _rowNotices(page, rowName) {
  return page.evaluate((name) => {
    const cards = Array.from(document.querySelectorAll(".agent-card"));
    const card = cards.find((c) => {
      const nameEl = c.querySelector(".agent-name");
      return nameEl && nameEl.textContent.trim() === name;
    });
    if (!card) return [];
    return Array.from(card.querySelectorAll(".agent-stop-notice")).map((el) => el.textContent.trim());
  }, rowName);
}

async function _clickButtonInRow(page, rowName, label) {
  await page.evaluate((name, lbl) => {
    const cards = Array.from(document.querySelectorAll(".agent-card"));
    const card = cards.find((c) => {
      const nameEl = c.querySelector(".agent-name");
      return nameEl && nameEl.textContent.trim() === name;
    });
    if (!card) throw new Error("No se encontró la fila " + name);
    const btn = Array.from(card.querySelectorAll("button")).find(
      (b) => b.textContent.trim() === lbl
    );
    if (!btn) throw new Error(`No se encontró el botón '${lbl}' en ${name}`);
    btn.click();
  }, rowName, label);
}

// -------------------------------------------------------------------------
// Criterio 1: Developer con Job running muestra el aviso en la confirmación.
// -------------------------------------------------------------------------

async function test_developer_con_job_running_muestra_aviso() {
  await withBackend(async ({ page, baseUrl }) => {
    await _intercept(page, (req) => {
      req.respond({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([_runningJob("job-running-1", "dev-1")]),
      });
    });
    await _gotoAgentes(page, baseUrl);

    // Fila Developer-1 (sintética pero "viva"): botón "Detener".
    await waitVisible(page, ".agent-card");
    await page.waitForFunction(
      () => {
        const cards = Array.from(document.querySelectorAll(".agent-card"));
        const card = cards.find((c) => {
          const n = c.querySelector(".agent-name");
          return n && n.textContent.trim() === "Developer-1";
        });
        return !!card && Array.from(card.querySelectorAll("button")).some(
          (b) => b.textContent.trim() === "Detener"
        );
      },
      { timeout: 15000 }
    );

    await _clickButtonInRow(page, "Developer-1", "Detener");

    // Confirmación con el aviso explícito (id y estado del Job).
    await page.waitForFunction(
      () => {
        const cards = Array.from(document.querySelectorAll(".agent-card"));
        const card = cards.find((c) => {
          const n = c.querySelector(".agent-name");
          return n && n.textContent.trim() === "Developer-1";
        });
        return !!card && Array.from(card.querySelectorAll("button")).some(
          (b) => b.textContent.trim().indexOf("Confirmar detener") !== -1
        );
      },
      { timeout: 5000 }
    );

    const notices = await _rowNotices(page, "Developer-1");
    assert.ok(notices.length >= 1, "Debe mostrarse el aviso de Job en curso.");
    assert.ok(
      notices.join(" ").indexOf("Job en curso") !== -1 &&
        notices.join(" ").indexOf("job-running-1") !== -1,
      "El aviso debe mencionar el id y estado del Job en curso: " + JSON.stringify(notices)
    );
    const hasConfirm = await page.evaluate(() => {
      const cards = Array.from(document.querySelectorAll(".agent-card"));
      const card = cards.find((c) => {
        const n = c.querySelector(".agent-name");
        return n && n.textContent.trim() === "Developer-1";
      });
      return card && Array.from(card.querySelectorAll("button")).some(
        (b) => b.textContent.trim() === "¿Seguro? Confirmar detener"
      );
    });
    assert.strictEqual(hasConfirm, true, "La confirmación de detener debe seguir presente.");
  });
}

// -------------------------------------------------------------------------
// Criterio 1 (Arquitecto) y criterio 2 (sin Jobs en curso → sin aviso).
// -------------------------------------------------------------------------

async function test_arquitecto_con_job_running_muestra_aviso() {
  await withBackend(async ({ page, baseUrl }) => {
    await _intercept(page, (req) => {
      req.respond({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([_runningJob("verdicto-running-9", "arq-1")]),
      });
    });
    await _gotoAgentes(page, baseUrl);

    await page.waitForFunction(
      () => {
        const cards = Array.from(document.querySelectorAll(".agent-card"));
        const card = cards.find((c) => {
          const n = c.querySelector(".agent-name");
          return n && n.textContent.trim() === "Arquitecto";
        });
        return !!card && Array.from(card.querySelectorAll("button")).some(
          (b) => b.textContent.trim() === "Detener"
        );
      },
      { timeout: 15000 }
    );

    await _clickButtonInRow(page, "Arquitecto", "Detener");

    await page.waitForFunction(
      () => {
        const cards = Array.from(document.querySelectorAll(".agent-card"));
        const card = cards.find((c) => {
          const n = c.querySelector(".agent-name");
          return n && n.textContent.trim() === "Arquitecto";
        });
        return !!card && Array.from(card.querySelectorAll("button")).some(
          (b) => b.textContent.trim() === "Confirmar detener"
        );
      },
      { timeout: 5000 }
    );

    const notices = await _rowNotices(page, "Arquitecto");
    assert.ok(notices.length >= 1, "El Arquitecto con Job en curso debe mostrar el aviso.");
    assert.ok(
      notices.join(" ").indexOf("verdicto-running-9") !== -1,
      "El aviso debe citar el id del Job en curso del Arquitecto: " + JSON.stringify(notices)
    );
  });
}

async function test_sin_jobs_en_curso_confirmacion_sin_aviso() {
  await withBackend(async ({ page, baseUrl }) => {
    // Jobs de OTRO agente (o no running): no hay Job en curso del objetivo.
    await _intercept(page, (req) => {
      req.respond({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          _runningJob("job-otro", "dev-999"),
          { id: "job-completado", agent_id: "dev-1", status: "completed", description: "d" },
        ]),
      });
    });
    await _gotoAgentes(page, baseUrl);

    await page.waitForFunction(
      () => {
        const cards = Array.from(document.querySelectorAll(".agent-card"));
        const card = cards.find((c) => {
          const n = c.querySelector(".agent-name");
          return n && n.textContent.trim() === "Developer-1";
        });
        return !!card && Array.from(card.querySelectorAll("button")).some(
          (b) => b.textContent.trim() === "Detener"
        );
      },
      { timeout: 15000 }
    );

    await _clickButtonInRow(page, "Developer-1", "Detener");
    await page.waitForFunction(
      () => {
        const cards = Array.from(document.querySelectorAll(".agent-card"));
        const card = cards.find((c) => {
          const n = c.querySelector(".agent-name");
          return n && n.textContent.trim() === "Developer-1";
        });
        return !!card && Array.from(card.querySelectorAll("button")).some(
          (b) => b.textContent.trim() === "¿Seguro? Confirmar detener"
        );
      },
      { timeout: 5000 }
    );

    // Sin Job en curso del agente → confirmación limpia, sin aviso (sin ruido).
    const notices = await _rowNotices(page, "Developer-1");
    assert.strictEqual(notices.length, 0, "No debe haber aviso sin Jobs en curso: " + JSON.stringify(notices));
  });
}

// -------------------------------------------------------------------------
// Criterio 3: un fallo de GET /jobs no bloquea la detención (sin aviso).
// -------------------------------------------------------------------------

async function test_fallo_get_jobs_no_bloquea_la_confirmacion() {
  await withBackend(async ({ page, baseUrl }) => {
    await _intercept(page, (req) => {
      req.respond({
        status: 404,
        contentType: "application/json",
        body: JSON.stringify({ detail: "no hay sesión" }),
      });
    });
    await _gotoAgentes(page, baseUrl);

    await page.waitForFunction(
      () => {
        const cards = Array.from(document.querySelectorAll(".agent-card"));
        const card = cards.find((c) => {
          const n = c.querySelector(".agent-name");
          return n && n.textContent.trim() === "Developer-1";
        });
        return !!card && Array.from(card.querySelectorAll("button")).some(
          (b) => b.textContent.trim() === "Detener"
        );
      },
      { timeout: 15000 }
    );

    await _clickButtonInRow(page, "Developer-1", "Detener");

    // La confirmación se muestra igual pese al fallo del fetch (best-effort).
    await page.waitForFunction(
      () => {
        const cards = Array.from(document.querySelectorAll(".agent-card"));
        const card = cards.find((c) => {
          const n = c.querySelector(".agent-name");
          return n && n.textContent.trim() === "Developer-1";
        });
        return !!card && Array.from(card.querySelectorAll("button")).some(
          (b) => b.textContent.trim() === "¿Seguro? Confirmar detener"
        );
      },
      { timeout: 5000 }
    );
    const notices = await _rowNotices(page, "Developer-1");
    assert.strictEqual(notices.length, 0, "Sin datos de jobs no debe haber aviso, solo la confirmación.");
  });
}

module.exports = [
  {
    name: "T-AF021-US03-04 · Developer con Job running muestra el aviso junto a la confirmación",
    fn: test_developer_con_job_running_muestra_aviso,
  },
  {
    name: "T-AF021-US03-04 · Arquitecto con Job running muestra el aviso en la confirmación",
    fn: test_arquitecto_con_job_running_muestra_aviso,
  },
  {
    name: "T-AF021-US03-04 · sin Jobs en curso la confirmación se muestra sin aviso (sin ruido)",
    fn: test_sin_jobs_en_curso_confirmacion_sin_aviso,
  },
  {
    name: "T-AF021-US03-04 · un fallo de GET /jobs no bloquea la confirmación (aviso best-effort)",
    fn: test_fallo_get_jobs_no_bloquea_la_confirmacion,
  },
];