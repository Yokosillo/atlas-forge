# Suite Puppeteer de `10-web/`

Suite de tests de interacción real (navegador, no solo lectura de
código) contra la interfaz web de Factory Brain (T-FB022-US15-03,
`US-FB022-15` · "El Tester verifica la interfaz web real"). Reutilizable
y persistente: los tests se **amplían** aquí en vez de escribirse como
scripts sueltos y descartarse tras el uso (patrón anterior, ver
`07-informes/US-FB024-11/corregir-editor-modelo-filas-sinteticas.md` —
"script de verificación... descartado tras el uso").

## Qué prueba esta suite (y qué no)

Bugs de **interacción real**: identidad de fila al hacer clic, timing de
polling frente a estado en edición, estilos visuales resueltos por el
navegador — la clase de bug que un `grep` de código o un test unitario
de Python no puede detectar. No cubre diferencias visuales/pixel-diff
(diferido a v2 de `US-FB022-15`) ni navegadores distintos de Chromium.

## Cómo ejecutar la suite completa

Desde la raíz del repo:

```bash
npm run test:ui
```

Equivalente directo: `node 10-web/tests/run.js`. Código de salida 0 si
todos los tests pasan, 1 si alguno falla — apto para CI.

## Cómo ejecutar un único fichero de test

Cada fichero `*.test.js` es un módulo Node normal que exporta un array
de casos — se puede invocar directamente sin pasar por el runner:

```bash
node -e "
const cases = require('./10-web/tests/roles_editor_row_identity.test.js');
(async () => {
  for (const c of cases) { await c.fn(); console.log('PASS:', c.name); }
})();
"
```

## Contra qué corre: backend real y completamente aislado

Cada test arranca su propio `brain-api` real (mismo `create_app()` que
producción, servido con `uvicorn` real — nunca mockeado) en un puerto
local libre, con:

- `state_dir` temporal (directorio nuevo por ejecución, vía
  `tempfile.TemporaryDirectory`).
- Socket tmux propio y aislado (nunca el socket `factory-brain` real de
  producción).
- Un proyecto sintético (`.git` vacío) preseleccionado como activo, para
  que `_lifespan` resuelva una sesión sin depender del proyecto activo
  real persistido de este usuario en esta máquina.

**Cero interacción con el proceso `:8000` real ni con sesiones tmux de
producción** — verificable leyendo `04-src/scripts/run_isolated_test_backend.py`
(el script que arranca ese backend) y
`04-src/tests/fixtures/backend_server.py::running_backend` (el mecanismo
que reutiliza, mismo patrón ya usado por buena parte de la suite `pytest`
de `04-src/tests/`).

Al terminar cada test, el backend se apaga limpiamente y su socket tmux
aislado se destruye — ningún proceso ni sesión queda huérfano entre
tests, ni entre ejecuciones de la suite.

## Cómo añadir un test nuevo

1. Crear `10-web/tests/<algo>.test.js`. El runner (`run.js`) descubre
   automáticamente cualquier fichero que termine en `.test.js` en esta
   carpeta — no hace falta registrarlo en ningún sitio.
2. Exportar un array de `{ name, fn }`, donde `fn` es `async () => {...}`
   y lanza (`assert`, del módulo `assert` de Node) si el test falla:

   ```js
   "use strict";

   const assert = require("assert");
   const { withBackend, waitVisible, sleep } = require("./harness");

   async function test_mi_caso() {
     await withBackend(async ({ page, baseUrl }) => {
       await page.goto(baseUrl + "/ui/");
       await waitVisible(page, ".section-tab");
       // ... interactuar con `page` (API de Puppeteer) ...
       assert.strictEqual(/* valor real */, /* esperado */);
     });
   }

   module.exports = [
     { name: "descripción legible de lo que verifica este test", fn: test_mi_caso },
   ];
   ```

3. `withBackend(callback)` (de `./harness`) es el punto de entrada
   habitual: arranca el backend aislado + Chromium headless, ejecuta el
   callback con `{ page, baseUrl }`, y cierra todo (incluso si el test
   falla) — no hace falta gestionar el ciclo de vida a mano.

4. **Si el test necesita agentes ya lanzados** (no solo filas sintéticas
   sin instancia, que ya aparecen solas sin sembrar nada — ver
   `buildUnifiedRows`/`DEFAULT_MAX_SIMULTANEOUS_DEVELOPERS` en
   `10-web/app.js`), pasar `launchAgentRoles`:

   ```js
   await withBackend(
     async ({ page, baseUrl }) => { /* ... */ },
     { launchAgentRoles: ["arquitecto", "developer"] }
   );
   ```

   Esto lanza esos roles como agentes reales (tmux real, con el doble
   cooperativo `04-src/tests/fixtures/cooperative_agent_sim.sh`
   sustituyendo el comando real de Claude Code/OpenCode — nunca un
   runtime real) antes de navegar, mismo criterio de aislamiento que el
   resto de la suite.

5. Ejecutar `npm run test:ui` y confirmar que el test nuevo aparece en
   el reporte y pasa.

## Ficheros

- `harness.js`: arranque/cierre del backend aislado + Chromium headless,
  helpers de espera (`waitVisible`, `sleep`). Punto de entrada
  reutilizable para cualquier test nuevo.
- `run.js`: runner de la suite completa (`npm run test:ui`).
- `*.test.js`: los tests reales, uno por fichero, agrupados por lo que
  verifican.
- `../../04-src/scripts/run_isolated_test_backend.py`: el script Python
  que el harness lanza como subproceso — arranca el `brain-api` real
  aislado y opcionalmente lanza agentes reales de prueba antes de
  imprimir `READY <url>` por stdout.

## Tests existentes

- `roles_editor_row_identity.test.js` — el editor inline "Cambiar
  modelo" se abre SOLO en la fila sintética Developer pulsada, nunca en
  las demás filas Developer-N a la vez (regresión de `T-FB024-US11-03`).
- `roles_model_editor_survives_polling.test.js` — con el editor de
  modelo abierto, la selección elegida por el usuario sobrevive a un
  ciclo completo de polling (3s) sin resetearse al default del backend
  (regresión de `T-FB024-US11-07`).
- `roles_stop_button_consistent_style.test.js` — el botón
  "Detener"/"Eliminar" tiene el mismo color/fondo/borde para Arquitecto
  y Developer, ambos ya lanzados (regresión de `T-FB024-US11-04`).
