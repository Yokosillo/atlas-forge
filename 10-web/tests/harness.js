/* Harness reutilizable de la suite Puppeteer (T-FB022-US15-03,
 * US-FB022-15 · "El Tester verifica la interfaz web real"): arranca un
 * `brain-api` real y completamente aislado (state_dir/socket tmux
 * temporales, proyecto activo preseleccionado — mismo patrón ya usado
 * por varios Developer para verificar cambios de `10-web/` en esta
 * sesión, ver `07-informes/US-FB024-11/corregir-editor-modelo-filas-sinteticas.md`),
 * navega esa web real con Chromium headless, y cierra todo limpiamente
 * al terminar. Nunca toca el proceso de producción (`:8000` real) ni
 * ninguna sesión tmux de agentes reales — el backend de cada test corre
 * en un puerto local libre elegido por el propio proceso Python, con su
 * propio socket tmux aislado que se destruye al cerrar.
 *
 * Un test típico:
 *
 *   const { withBackend } = require("./harness");
 *
 *   test("mi test", async () => {
 *     await withBackend(async ({ page, baseUrl }) => {
 *       await page.goto(baseUrl + "/ui/#roles");
 *       // ... interactuar con `page` (API de Puppeteer) ...
 *     });
 *   });
 *
 * El callback también recibe `projectPath`: ruta real en disco del
 * proyecto activo sembrado por el backend aislado (segundo token de la
 * línea `READY <base_url> <project_path>`, ver
 * `run_isolated_test_backend.py`). Solo hace falta cuando el escenario
 * necesita un estado que ningún endpoint HTTP permite crear hoy — p. ej.
 * `dependencies` en una User Story, campo que `CreateUserStoryRequest`
 * no acepta (T-FB036-US01-10) — y el test escribe el frontmatter
 * directamente con `fs`, en vez de mockear nada del backend real.
 *
 * `withBackend` se encarga de: arrancar el backend aislado (subproceso
 * Python, `scripts/run_isolated_test_backend.py`), lanzar Chromium
 * headless, crear una página nueva, ejecutar el callback, y cerrar todo
 * (página, navegador, backend) incluso si el callback lanza una
 * excepción — un test que falla nunca deja un backend/Chromium huérfano
 * corriendo en background. */

"use strict";

const { spawn } = require("child_process");
const path = require("path");
const puppeteer = require("puppeteer");

const REPO_ROOT = path.resolve(__dirname, "..", "..");
const PYTHON_BIN = path.join(REPO_ROOT, "04-src", ".venv", "bin", "python3");
const BACKEND_SCRIPT = path.join(
  REPO_ROOT,
  "04-src",
  "scripts",
  "run_isolated_test_backend.py"
);

// Cuánto esperar a que el backend aislado imprima `READY <url>` antes de
// darlo por fallido — el arranque real (uvicorn + resolución de sesión)
// tarda del orden de cientos de ms, este margen es generoso a propósito
// para no volver la suite intermitente en una VM cargada.
const BACKEND_READY_TIMEOUT_MILLIS = 15000;

/** Arranca el backend aislado como subproceso Python, y resuelve con
 * `{ baseUrl, stop }` en cuanto imprime `READY <url>` por stdout.
 * `stop()` cierra su stdin (EOF) para que el propio script dispare su
 * cierre limpio (apaga uvicorn, mata el socket tmux aislado), y espera
 * a que el proceso termine de verdad antes de resolver — un test que
 * llama `stop()` y sigue adelante inmediatamente no debe arriesgar
 * dejar el puerto/socket todavía en uso para el siguiente test.
 *
 * `options.launchAgentRoles` (array de strings, p. ej.
 * `["arquitecto", "developer"]`): si se indica, el propio script Python
 * lanza esos roles como agentes REALES (tmux real, doble cooperativo de
 * `cooperative_agent_sim.sh` — nunca un runtime real) antes de imprimir
 * READY, para tests que necesitan comparar filas ya lanzadas y no solo
 * sintéticas (`--launch-agent-roles`, ver
 * `04-src/scripts/run_isolated_test_backend.py`). El arranque tarda algo
 * más en ese caso (crear las sesiones tmux reales), por eso el timeout
 * de espera de READY es generoso (ver `BACKEND_READY_TIMEOUT_MILLIS`). */
function launchBackend(options) {
  const launchAgentRoles = (options && options.launchAgentRoles) || [];
  const args = launchAgentRoles.length > 0
    ? [BACKEND_SCRIPT, "--launch-agent-roles", launchAgentRoles.join(",")]
    : [BACKEND_SCRIPT];

  return new Promise((resolve, reject) => {
    const child = spawn(PYTHON_BIN, args, {
      cwd: path.join(REPO_ROOT, "04-src"),
      stdio: ["pipe", "pipe", "pipe"],
    });

    let stdoutBuffer = "";
    let stderrBuffer = "";
    let settled = false;

    const timeout = setTimeout(() => {
      if (settled) return;
      settled = true;
      child.kill("SIGTERM");
      reject(
        new Error(
          `El backend aislado no imprimió READY en ${BACKEND_READY_TIMEOUT_MILLIS}ms. ` +
            `stdout: ${stdoutBuffer}\nstderr: ${stderrBuffer}`
        )
      );
    }, BACKEND_READY_TIMEOUT_MILLIS);

    child.stdout.on("data", (chunk) => {
      stdoutBuffer += chunk.toString("utf-8");
      if (settled) return;

      const readyMatch = stdoutBuffer.match(/READY (\S+)(?: (\S+))?/);
      if (readyMatch) {
        settled = true;
        clearTimeout(timeout);
        const baseUrl = readyMatch[1];
        const projectPath = readyMatch[2] || null;
        resolve({
          baseUrl,
          projectPath,
          stop: () =>
            new Promise((resolveStop) => {
              child.once("exit", () => resolveStop());
              try {
                child.stdin.end();
              } catch (_e) {
                // El proceso ya podría haber muerto — `exit` resolverá igual.
              }
              // Red de seguridad: si el cierre limpio por EOF de stdin no
              // basta (p. ej. el proceso quedó bloqueado), forzar tras un
              // margen — un test no debe colgarse indefinidamente esperando
              // el cierre de un backend que ya no necesita.
              setTimeout(() => {
                try {
                  child.kill("SIGTERM");
                } catch (_e) {
                  // ya no existe, nada que hacer
                }
              }, 5000);
            }),
        });
        return;
      }

      const errorMatch = stdoutBuffer.match(/ERROR (.+)/);
      if (errorMatch) {
        settled = true;
        clearTimeout(timeout);
        reject(new Error(`El backend aislado falló al arrancar: ${errorMatch[1]}`));
      }
    });

    child.stderr.on("data", (chunk) => {
      stderrBuffer += chunk.toString("utf-8");
    });

    child.on("error", (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      reject(new Error(`No se pudo lanzar el subproceso Python del backend aislado: ${error.message}`));
    });

    child.on("exit", (code) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      reject(
        new Error(
          `El backend aislado terminó antes de imprimir READY (código ${code}). ` +
            `stdout: ${stdoutBuffer}\nstderr: ${stderrBuffer}`
        )
      );
    });
  });
}

/** Arranca backend aislado + Chromium headless, ejecuta `callback({ page,
 * baseUrl })`, y cierra todo (página, navegador, backend) al terminar —
 * tanto en éxito como en fallo del callback, para que un test que falla
 * nunca deje procesos huérfanos corriendo. `options.launchAgentRoles`
 * se reenvía a `launchBackend` (ver su docstring) para tests que
 * necesitan agentes reales ya lanzados. */
async function withBackend(callback, options) {
  const backend = await launchBackend(options);
  const browser = await puppeteer.launch({
    headless: "new",
    args: ["--no-sandbox", "--disable-setuid-sandbox"],
  });

  try {
    const page = await browser.newPage();
    await callback({ page, baseUrl: backend.baseUrl, browser, projectPath: backend.projectPath });
  } finally {
    await browser.close();
    await backend.stop();
  }
}

/** Espera a que el elemento `selector` exista Y sea visible — envoltura
 * fina sobre `page.waitForSelector` con `visible: true`, para no repetir
 * la misma opción en cada test. */
async function waitVisible(page, selector, options) {
  return page.waitForSelector(selector, Object.assign({ visible: true }, options));
}

/** Pausa determinista de `millis` — usado deliberadamente en el test del
 * bug de polling (T-FB024-US11-07): esperar un ciclo real de
 * `POLL_INTERVAL_MILLIS` (3000ms en `app.js`) con el editor abierto es
 * el propio caso de prueba, no un `sleep` de conveniencia a evitar. */
function sleep(millis) {
  return new Promise((resolve) => setTimeout(resolve, millis));
}

module.exports = { withBackend, launchBackend, waitVisible, sleep };
