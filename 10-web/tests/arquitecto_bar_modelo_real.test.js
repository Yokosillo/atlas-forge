/* Verificación de T-AF028-US01-01: la barra del Arquitecto muestra el
 * modelo activo REAL cuando es consultable (Claude Code vía
 * `GET /agents/{id}/status-model`), en vez de caer siempre al modelo por
 * defecto configurado. Con agente parado o consulta no disponible, cae al
 * modelo por defecto (nunca un valor inventado).
 *
 * Usa el backend aislado con el Arquitecto lanzado (tmux real, doble
 * cooperativo `cooperative_agent_sim.sh` — nunca un runtime real de
 * Claude Code). La consulta `/status-model` del doble cooperativo no
 * devuelve un modelo, por lo que el test intercepta la respuesta de red
 * para simular el modelo real consultable y comprobar que la barra lo
 * refleja. */

"use strict";

const assert = require("assert");
const { withBackend, waitVisible } = require("./harness");

async function test_arquitecto_bar_shows_real_model_when_queried() {
  await withBackend(
    async ({ page, baseUrl }) => {
      // Simular el modelo real consultable: intercepta la respuesta de
      // `GET /agents/{id}/status-model` para devolver un modelo concreto
      // (el doble cooperativo no responde a /status con "Model:").
      await page.setRequestInterception(true);
      page.on("request", (req) => {
        if (req.url().includes("/status-model")) {
          req.respond({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({ model: "real-arquitecto-model" }),
          });
        } else {
          req.continue();
        }
      });

      await page.goto(baseUrl + "/ui/");
      await waitVisible(page, ".arquitecto-bar");
      await page.waitForFunction(() => {
        const el = document.querySelector(".arquitecto-bar .arq-model");
        return el && el.textContent.trim() !== "cargando…";
      });

      const modelText = await page.evaluate(
        () => document.querySelector(".arquitecto-bar .arq-model").textContent.trim()
      );

      // La barra refleja el modelo real consultado, no el default ni
      // "sin modelo".
      assert.ok(
        modelText === "real-arquitecto-model" || modelText === "Real Architecto Model",
        "la barra debe mostrar el modelo real consultado, no el default; obtuvo: " + modelText
      );
    },
    { launchAgentRoles: ["arquitecto"] }
  );
}

async function test_arquitecto_bar_falls_back_to_default_when_model_unavailable() {
  await withBackend(
    async ({ page, baseUrl }) => {
      // Sin interceptar /status-model: el doble cooperativo no devuelve
      // modelo (null) -> la barra cae al modelo por defecto o "sin
      // modelo", nunca un valor inventado.
      await page.goto(baseUrl + "/ui/");
      await waitVisible(page, ".arquitecto-bar");
      await page.waitForFunction(() => {
        const el = document.querySelector(".arquitecto-bar .arq-model");
        return el && el.textContent.trim() !== "cargando…";
      });

      const modelText = await page.evaluate(
        () => document.querySelector(".arquitecto-bar .arq-model").textContent.trim()
      );

      // No debe ser un modelo inventado ni estar vacío; muestra el default
      // configurado o el marcador "sin modelo".
      assert.ok(
        modelText !== "" && modelText !== "real-arquitecto-model",
        "sin modelo consultable la barra debe caer al default/`sin modelo`, no inventar uno"
      );
    },
    { launchAgentRoles: ["arquitecto"] }
  );
}

module.exports = [
  {
    name: "T-AF028-US01-01: la barra del Arquitecto muestra el modelo real cuando es consultable",
    fn: test_arquitecto_bar_shows_real_model_when_queried,
  },
  {
    name: "T-AF028-US01-01: la barra del Arquitecto cae al default cuando el modelo no es consultable",
    fn: test_arquitecto_bar_falls_back_to_default_when_model_unavailable,
  },
];
