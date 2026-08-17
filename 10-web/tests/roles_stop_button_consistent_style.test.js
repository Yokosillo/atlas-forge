/* Regresión de T-FB024-US11-04 (US-FB024-11): el botón "Detener"
 * (Arquitecto y otros roles) y "Eliminar" (Developer, mismo botón
 * renombrado — T-FB024-US12-02) deben compartir exactamente el mismo
 * estilo visual (clase `agent-stop`, resuelto por CSS a
 * `border: 1px solid #b3261e; color: #b3261e; background: #fff6f5`) —
 * antes del fix, el botón del Arquitecto usaba la clase específica
 * `arq-btn-stop` (roja) mientras Developer usaba `agent-stop` sin
 * ninguna regla de color, quedando con el estilo neutro por defecto.
 * Ver `02-backlog/tasks/T-FB024-US11-04-unificar-estilo-boton-detener.md`.
 *
 * Ninguno de los dos roles necesita estar realmente LANZADO para el
 * resto de esta suite — las filas sintéticas "detenidas" muestran
 * "Lanzar", no "Detener"/"Eliminar" (ese botón solo aparece cuando
 * `agent.status` no es `stopped`/`unregistered`/`unavailable`). Este
 * test SÍ necesita comparar los botones reales de ambos roles ya
 * lanzados, así que usa `launchAgentRoles` del harness (tmux real, doble
 * cooperativo de `cooperative_agent_sim.sh` — nunca un runtime real de
 * Claude Code/OpenCode, mismo criterio de aislamiento que el resto de
 * esta suite y que la suite pytest existente). */

"use strict";

const assert = require("assert");
const { withBackend, waitVisible } = require("./harness");

async function test_stop_button_has_the_same_visual_style_for_arquitecto_and_developer() {
  await withBackend(
    async ({ page, baseUrl }) => {
      await page.goto(baseUrl + "/ui/");
      await waitVisible(page, ".section-tab");

      const tabs = await page.$$(".section-tab");
      let rolesTab = null;
      for (const tab of tabs) {
        const text = await page.evaluate((el) => el.textContent, tab);
        if (text.trim().startsWith("Agentes")) {
          rolesTab = tab;
          break;
        }
      }
      assert.ok(rolesTab, "No se encontró la pestaña 'Agentes'.");
      await rolesTab.click();

      // Esperar a que ambos agentes reales (no sintéticos) aparezcan con
      // su botón de detener/eliminar visible.
      await page.waitForFunction(
        () => {
          const names = Array.from(document.querySelectorAll(".agent-name")).map(
            (el) => el.textContent
          );
          return names.includes("Arquitecto") && names.includes("Developer-1");
        },
        { timeout: 15000 }
      );

      const styles = await page.evaluate(() => {
        function stopButtonStyleFor(rowName) {
          const cards = Array.from(document.querySelectorAll(".agent-card"));
          const card = cards.find((c) => {
            const nameEl = c.querySelector(".agent-name");
            return nameEl && nameEl.textContent === rowName;
          });
          if (!card) return null;
          const btn = Array.from(card.querySelectorAll("button")).find(
            (b) => b.textContent.trim() === "Detener" || b.textContent.trim() === "Eliminar"
          );
          if (!btn) return null;
          const computed = window.getComputedStyle(btn);
          return {
            label: btn.textContent.trim(),
            color: computed.color,
            backgroundColor: computed.backgroundColor,
            borderColor: computed.borderTopColor,
          };
        }
        return {
          arquitecto: stopButtonStyleFor("Arquitecto"),
          developer: stopButtonStyleFor("Developer-1"),
        };
      });

      assert.ok(styles.arquitecto, "No se encontró el botón Detener del Arquitecto.");
      assert.ok(styles.developer, "No se encontró el botón Detener/Eliminar de Developer-1.");

      assert.strictEqual(
        styles.arquitecto.color,
        styles.developer.color,
        `Color de texto distinto: Arquitecto=${styles.arquitecto.color} Developer=${styles.developer.color}`
      );
      assert.strictEqual(
        styles.arquitecto.backgroundColor,
        styles.developer.backgroundColor,
        `Color de fondo distinto: Arquitecto=${styles.arquitecto.backgroundColor} Developer=${styles.developer.backgroundColor}`
      );
      assert.strictEqual(
        styles.arquitecto.borderColor,
        styles.developer.borderColor,
        `Color de borde distinto: Arquitecto=${styles.arquitecto.borderColor} Developer=${styles.developer.borderColor}`
      );
    },
    { launchAgentRoles: ["arquitecto", "developer"] }
  );
}

module.exports = [
  {
    name: "el botón Detener/Eliminar tiene el mismo color/fondo/borde para Arquitecto y Developer",
    fn: test_stop_button_has_the_same_visual_style_for_arquitecto_and_developer,
  },
];
