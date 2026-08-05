# FAQ y troubleshooting

## Preguntas frecuentes

### ¿Factory Brain es un IDE o un framework de agentes?

No. Es una plataforma de **coordinación**. Los agentes ejecutan con sus propios runtimes (Claude Code, OpenCode) y modelos; Factory Brain decide quién hace qué, cuándo, y mantiene el contexto vivo.

### ¿Qué runtimes soporta?

Claude Code y OpenCode (lanzados en sesiones tmux). **Codex no está soportado todavía** — aparece en el catálogo de modelos como entrada comentada (futuro). Ver [Runtime y Scribe](runtime.md).

### ¿Necesito Ollama?

No. Scribe (Ollama) es **opcional**: es un ahorro de tokens para lecturas/resúmenes. Sin Ollama todo sigue funcionando, degradando explícitamente (notas en los Jobs, exit code 1 en el CLI de resumen, fallo duro solo en pasos de plan que usen explícitamente Scribe).

### ¿Cómo selecciono el modelo de un agente?

Al lanzar un agente, eliges rol + modelo del catálogo (`GET /agents/options`). Solo OpenCode soporta modelo. En caliente, puedes cambiar el modelo de un agente OpenCode lanzado (`PUT /agents/{agent_id}/model`). Las preferencias (habilitados + default por rol) se gestionan en la pestaña Modelos / `models.yml`.

### ¿Dónde se guarda el estado?

Proyecto activo y preferencias de modelos en `~/.local/share/brain/`. Sesión, agentes y Jobs **en memoria del proceso `brain-api`** — se pierden al reiniciar el backend. Ver [Configuración](configuration.md).

### ¿La app Android cómo se instala?

Descargando el APK desde el backend (`GET /apk`, sobre Tailscale). No hay Play Store. La app está en **pausa de desarrollo** (2026-08-04) pero el código existente funciona.

### ¿Hay autenticación?

No propia. El perímetro de seguridad es la **red Tailscale**. El backend nunca escucha en `0.0.0.0`; se une a la interfaz Tailscale.

### ¿Existe un sistema de plugins o MCP?

**No.** El Plugin System (FB-011) está planificado pero no implementado. Cualquier integración nueva se hace por código en `04-src/`.

## Troubleshooting

### El backend no arranca: error Tailscale

`brain-api` sin `--host` ejecuta `tailscale ip -4`. Si falla (binario ausente, comando con timeout, salida vacía) lanza `TailscaleHostUnavailableError` con el motivo. Soluciones:
- Verifica que Tailscale esté up y conectado (`tailscale status`).
- Para desarrollo/local: `brain-api --host 127.0.0.1`.

### La web no se conecta ("No hay conexión con el backend")

- Confirma que `brain-api` está corriendo (`systemctl status factory-brain-api` o `curl http://<host>:8000/health`).
- Accede por la IP/URL correcta: la web se sirve en `/ui/` del mismo proceso, same-origin (no hay CORS).
- Si probaste antes de la conexión Tailscale, reintenta tras conectar.

### Un agente aparece como `unavailable`

El liveness es perezoso: si la sesión tmux del runtime murió sin que lo pidieras, el agente pasa a `unavailable` al consultar. Relanza el agente (un agente `stopped`/`unavailable` no se reutiliza; se sustituye).

### Un Job nunca termina (timeout)

`POST /jobs` es bloqueante y el reporte es cooperativo (el agente escribe un fichero con una marca). Si el agente no sigue la instrucción de reporte, el Job falla por timeout (`JobReportTimeoutError`) a los 30s por defecto. Opciones:
- Cancela el Job (`POST /jobs/{job_id}/cancel`).
- Detén el agente (`POST /agents/{id}/stop`) si está colgado.
- Consulta el pane del agente (`GET /agents/{id}/pane`) para ver qué hace.

### El plan no despacha (queda `proposed`)

Un plan en `proposed` no ejecuta nada hasta la **aprobación humana única** (`POST /plans/{id}/approve`). Verifica también que haya agentes lanzados para los pasos `agent` y que Scribe esté disponible si hay pasos `scribe`.

### Al aprobar, el plan queda `blocked`

Un paso falló con `JobCreationError` o `ScribeUnavailableError`. Revisa `GET /plans/{plan_id}` para ver el paso fallido, lanza el agente necesario y vuelve a pedir/aprobar el plan.

### Scribe no está disponible

- Confirma Ollama corriendo: `curl http://localhost:11434` y `ollama list` (el modelo `qwen2.5-coder:14b` debe existir).
- El resto del sistema funciona sin Scribe; solo fallan explícitamente los pasos de plan `scribe` y la acción `indexar`.

### Cambio de modelo no se refleja (OpenCode)

`set_active_model` interactúa con la barra de estado de OpenCode y devuelve `False` ante cualquier fallo (runtime no-OpenCode, sesión muerta, patrón no encontrado). Reintenta o verifica que el agente esté `idle`/`working` y que el pane esté vivo.

### Los scripts del proyecto no aparecen

- El manifiesto debe estar en `.factory-brain/scripts.yml` del **proyecto activo** (no del repositorio de Factory Brain).
- Errores de manifiesto → `MalformedScriptManifestError` al consultar `GET /scripts`.
- La caché TTL es 5s; espera o vuelve a consultar.

### Preguntas sobre el backlog

- El estado canónico vive en `02-backlog/` (Epics, User Stories, Tasks). `07-informes/` contiene solo informes de cierre, no la versión vigente de una Epic.
- Si `GET /backlog/{item_id}` devuelve 404 con razón de parseo, el fichero no cumple el esquema (ver `02-backlog/README.md`).
