# FAQ y resolución de problemas

## Preguntas frecuentes

### ¿Es Factory Brain un IDE o un framework de agentes?

No. Es una plataforma de **coordinación**. Los agentes ejecutan con sus propios runtimes (Claude Code, OpenCode) y modelos; Factory Brain decide quién hace qué, cuándo, y mantiene el contexto vivo.

### ¿Qué runtimes soporta?

Claude Code y OpenCode (lanzados en sesiones de tmux). **Codex todavía no se soporta** — aparece en el catálogo de modelos como entrada comentada (futuro). Ver [Runtime y Scribe](runtime.md).

### ¿Necesito Ollama?

No. Scribe (Ollama) es **opcional**: es un ahorrador de tokens para lecturas/resúmenes. Sin Ollama todo sigue funcionando, degradándose explícitamente (notas en Jobs, código de salida 1 en el CLI de resumen, fallo duro solo en la acción `indexar` que usa Scribe explícitamente).

### ¿Cómo selecciono el modelo de un agente?

Al lanzar un agente eliges rol + modelo del catálogo (`GET /agents/options`). Solo OpenCode soporta un modelo. En caliente, puedes cambiar el modelo de un agente OpenCode lanzado (`PUT /agents/{agent_id}/model`). Las preferencias (habilitados + valor por defecto por rol) se gestionan en la pestaña Models / `models.yml`.

### ¿Dónde se almacena el estado?

Proyecto activo y preferencias de modelo en `~/.local/share/brain/`. Sesión, agentes y Jobs **en la memoria del proceso `brain-api`** — se pierden cuando el backend se reinicia. Ver [Configuración](configuration.md).

### ¿Hay un sistema de plugins o MCP?

**No.** El Plugin System (FB-011) está planificado pero no implementado. Cualquier integración nueva se hace por código en `04-src/`.

### ¿Por qué el backlog es el centro del producto?

Desde la Fase 1.0 (2026-08-05) el producto es **centrado en el backlog**: todo el trabajo se despliega desde el backlog (Epic → US → Task → Implementar) con botones, no escribiendo Markdown a mano ni hablando con cada agente por separado. Ver [Backlog y pipeline](backlog.md).

## Resolución de problemas

### El backend no arranca

Si `brain-api` sin `--host` no puede resolver la interfaz de red de la máquina, lanza un error con el motivo. Soluciones:
- Verifica que la interfaz de red está activa.
- Para desarrollo/local: `brain-api --host 127.0.0.1`.

### La web no conecta ("No connection to the backend")

- Confirma que `brain-api` está ejecutándose (`systemctl status factory-brain-api` o `curl http://<host>:8000/health`).
- Accede por la IP/URL correcta: la web se sirve en `/ui/` del mismo proceso, mismo origen (sin CORS).

### Un agente aparece como `unavailable`

El liveness es perezoso: si la sesión de tmux del runtime murió sin que lo pidieras, el agente transiciona a `unavailable` al consultarlo. Relanza el agente (un agente `stopped`/`unavailable` no se reutiliza; se sustituye).

### Un Job nunca termina (timeout)

`POST /jobs` es bloqueante y el reporte es cooperativo (el agente escribe un fichero con un marcador). Si el agente no sigue la instrucción de reporte, el Job falla por timeout (`JobReportTimeoutError`) tras 30s por defecto. Opciones:
- Cancela el Job (`POST /jobs/{job_id}/cancel`).
- Detén el agente (`POST /agents/{id}/stop`) si está atascado.
- Consulta el pane del agente (`GET /agents/{id}/pane`) para ver qué está haciendo.

### Una Task nunca se recoge

Confirma que su `state` es `EN_DESARROLLO` (no `TO_DO`) — el Dispatcher solo recoge estados elegibles, y una Task `TO_DO` simple espera a que un humano la progrese. Confirma también que un Developer está `idle` y que sus dependencias están todas `DONE`.

### Scribe no está disponible

- Confirma que Ollama está ejecutándose: `curl http://localhost:11434` y `ollama list` (el modelo `qwen2.5-coder:14b` debe existir).
- El resto del sistema funciona sin Scribe; solo la acción `indexar` falla explícitamente.

### Quiero cambiar el modelo de un agente

El modelo (y el runtime) se eligen en el lanzamiento — detén el agente y relánzalo con el modelo que quieras. No hay cambio de modelo en caliente para un agente vivo.

### Los scripts del proyecto no aparecen

- El manifest debe estar en `.factory-brain/scripts.yml` del **proyecto activo** (no del repositorio de Factory Brain).
- Errores de manifest → `MalformedScriptManifestError` al consultar `GET /scripts`.
- La caché TTL es de 5s; espera o consulta de nuevo.

### Preguntas sobre el backlog

- El estado canónico vive en `02-backlog/` (Epics, User Stories, Tasks). `07-informes/` contiene solo informes de cierre, no la versión actual de un Epic.
- Si `GET /backlog/{item_id}` devuelve 404 con un motivo de parseo, el fichero no cumple el esquema (ver `02-backlog/README.md`).