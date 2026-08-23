#!/usr/bin/env node
/* Runner de la suite Puppeteer (T-AF022-US15-03): descubre todo
 * `10-web/tests/*.test.js`, ejecuta cada test de forma secuencial
 * (nunca en paralelo — cada uno arranca su propio backend/socket tmux
 * aislado, pero correr varios Chromium headless a la vez en la misma VM
 * de forma no controlada no aporta nada y complica el reporte), y
 * reporta pasa/falla por test con salida legible. Sin dependencia de
 * Jest/Mocha (no instalados en este repo, y la Task no los pide) — un
 * runner mínimo propio es suficiente para el volumen de esta suite.
 *
 * Cada fichero `*.test.js` exporta un array de `{ name, fn }` (`fn` es
 * `async () => { ... }`, lanza si el test falla) — ver
 * `10-web/tests/README.md` para el patrón completo de cómo añadir un
 * test nuevo.
 *
 * Uso: `node 10-web/tests/run.js` (o `npm run test:ui` desde la raíz del
 * repo). Código de salida 0 si todos los tests pasan, 1 si alguno falla
 * — apto para CI. */

"use strict";

const fs = require("fs");
const path = require("path");

const TESTS_DIR = __dirname;

function discoverTestFiles() {
  return fs
    .readdirSync(TESTS_DIR)
    .filter((name) => name.endsWith(".test.js"))
    .sort()
    .map((name) => path.join(TESTS_DIR, name));
}

async function main() {
  const testFiles = discoverTestFiles();
  if (testFiles.length === 0) {
    console.log("Ningún fichero *.test.js encontrado en " + TESTS_DIR);
    process.exit(0);
  }

  let totalPassed = 0;
  let totalFailed = 0;
  const failures = [];

  for (const file of testFiles) {
    const relativeName = path.relative(TESTS_DIR, file);
    // eslint-disable-next-line global-require, import/no-dynamic-require
    const cases = require(file);
    if (!Array.isArray(cases)) {
      console.error(`${relativeName}: no exporta un array de { name, fn } — ignorado.`);
      continue;
    }

    for (const testCase of cases) {
      const label = `${relativeName} :: ${testCase.name}`;
      const startedAt = Date.now();
      try {
        await testCase.fn();
        const elapsedMs = Date.now() - startedAt;
        console.log(`✓ PASS  ${label} (${elapsedMs}ms)`);
        totalPassed++;
      } catch (error) {
        const elapsedMs = Date.now() - startedAt;
        console.error(`✗ FAIL  ${label} (${elapsedMs}ms)`);
        console.error(`        ${error && error.stack ? error.stack : error}`);
        totalFailed++;
        failures.push(label);
      }
    }
  }

  console.log("");
  console.log(`Total: ${totalPassed} passed, ${totalFailed} failed.`);
  if (failures.length > 0) {
    console.log("Fallidos:");
    failures.forEach((label) => console.log(`  - ${label}`));
  }

  process.exit(totalFailed > 0 ? 1 : 0);
}

main().catch((error) => {
  console.error("Fallo inesperado del runner:", error);
  process.exit(1);
});
