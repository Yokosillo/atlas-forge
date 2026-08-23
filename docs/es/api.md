# API

Atlas Forge expone su dominio a través de una **API HTTP/WebSocket** (FastAPI) que consumen todos los clientes. Referencia completa generada contra el código real en `04-src/src/atlas_forge/api/`.

## Generalidades

- **Base**: `http://<host>:8000` (`127.0.0.1` en local).
- **Errores**: `HTTPException` con un `detail` (mensaje construido en el dominio).
- **Formato**: JSON. No hay query params — solo path params y cuerpos JSON.

## Salud e infraestructura

### `GET /health`
Comprueba que el backend responde.

```json
{"status": "ok", "session_id": null}
```

`session_id` es `null` hasta que se selecciona un proyecto.

### `GET /ui/` (montaje estático)
Sirve la interfaz web (`10-web/`). `GET /ui` redirige a `/ui/`.

## Proyectos

### `GET /project`
Proyecto activo.

```json
{"id": "...", "name": "...", "path": "...", "repository": "...", "workspace_id": "..."}
```

404 "There is no active project." ("No hay proyecto activo.")

### `GET /projects`
Lista los repositorios Git descubiertos en el workspace (candidatos a proyecto activo).

### `POST /project`
Selecciona un proyecto de `GET /projects` y le da el foco de sesión del proceso. Si el proyecto ya tenía una sesión viva, se reutiliza tal cual (mismo `session.id`, mismos agentes, nada relanzado); en caso contrario se crea una nueva.

**Los agentes del proyecto con foco anterior nunca se tocan ni se detienen.** Cada proyecto mantiene su propia sesión viva en paralelo (registro multi-sesión); volver a darle foco hace sus agentes alcanzables de nuevo vía `GET /agents`/`POST /agents/{id}/stop`.

```json
{"project_id": "..."}
```

400 si el id no está en la lista descubierta.

## Sesión

### `GET /session`
Sesión de desarrollo activa.

```json
{"id": "...", "project_id": "...", "status": "active"}
```

404 "There is no active development session." ("No hay sesión de desarrollo activa.")

## Agentes

### `GET /agents`
Agentes lanzados en la sesión activa, con `model` resuelto del runtime real (nullable). Ejecuta liveness perezoso: los runtimes muertos aparecen como `unavailable`.

```json
[{"id": "...", "name": "Developer-1", "role": "developer", "status": "idle", "runtime_id": "opencode", "model": null}]
```

404 sin sesión.

### `GET /agents/options`
Catálogo de combinaciones lanzables rol×modelo: producto cartesiano de roles × modelos habilitados con runtime resuelto. No requiere sesión activa.

```json
[{"agent_role": "developer", "model_id": "opencode-go/deepseek-v4-flash", "model_name": "DeepSeek V4 Flash", "runtime_type": "opencode", "runtime_name": "OpenCode", "supports_model": true}]
```

### `POST /agents` → 201
Lanza un agente. Cuerpo:

```json
{
  "role": "developer",
  "runtime_type": "opencode",
  "model_id": "opencode-go/deepseek-v4-flash",
  "initial_job_description": "opcional: tarea inicial"
}
```

`model` es un alias legacy de `model_id`. Sin `initial_job_description` devuelve el agente; con él devuelve `{agent, job}` (el Job puede acabar `failed` con el motivo en `job.result`). Errores: 404 sin sesión/proyecto; 400 runtime/modelo inválido o `AgentLaunchError`.

### `POST /agents/{agent_id}/stop`
Mata la sesión de tmux del agente. **Para cualquier rol excepto Developer**, lo transiciona a `stopped` — permanece en la sesión, reutilizable/consultable. **Para Developer**, el agente se elimina de la sesión por completo (su slot en el límite de Developers simultáneos se libera inmediatamente) — no existe un Developer `stopped` que relanzar, "stop" significa borrar. La respuesta siempre refleja el estado justo después de la acción.

### `GET /agents/{agent_id}/pane`
Contenido textual actual del pane de tmux del agente (vista de solo lectura).

```json
{"agent_id": "...", "content": "..."}
```

### `WS /ws/agents/{agent_id}/pane`
Stream en vivo del contenido del pane de tmux del agente (un canal por conexión). El poller del servidor publica solo cuando el contenido cambia; deja de sondear cuando el cliente se desconecta. Solo lectura, un agente a la vez por conexión.

### `GET /agents/{agent_id}/model`
Modelo activo del agente (solo OpenCode, lectura **pasiva** de su barra de estado — segura de llamar en cada poll). `null` para runtimes no-OpenCode o lectura fallida — nunca un error HTTP.

### `GET /agents/{agent_id}/status-model`
Modelo activo de un agente de **Claude Code**, leído bajo demanda enviando `/status` a su pane y parseando el resultado (**interacción activa**, a diferencia de `GET /agents/{agent_id}/model`). Solo la llama explícitamente el humano — nunca desde `GET /agents` ni desde ningún bucle de polling, para evitar interferir con la salida de un agente trabajando. 400 si el agente está `working`.

```json
{"agent_id": "...", "model": "Default (Sonnet 5 · Efficient for routine tasks)"}
```

### `PUT /agents/{agent_id}/model`
Cambia el modelo activo de un agente OpenCode en ejecución.

```json
{"model": "opencode-go/deepseek-v4-flash"}
```

Devuelve `{agent_id, model, changed}`. 400 para runtime no-OpenCode o modelo vacío.

### `GET /agents/{agent_id}/available-models`
Modelos disponibles para cambiar en el agente.

```json
{"agent_id": "...", "supports_model": true, "models": [{"id": "...", "name": "...", "runtime": "opencode"}]}
```

## Preferencias de modelo

### `GET /models/preferences`
Catálogo completo con habilitación y valores por defecto por rol.

```json
{"models": [{"id": "...", "name": "...", "runtime": "opencode", "enabled": true}], "defaults": {"developer": "..."}}
```

`enabled_model_ids` vacío = todos habilitados.

### `PUT /models/preferences`
Actualiza preferencias (parcial: solo los campos enviados).

```json
{"enabled_model_ids": ["..."], "default_model_by_role": {"developer": "..."}}
```

## Preferencias del sistema

### `GET /system/preferences`
Valores de configuración a nivel de sistema, persistidos independientemente de cualquier proyecto individual.

```json
{"max_simultaneous_developers": 3}
```

### `PUT /system/preferences`
Actualiza una preferencia del sistema (parcial). `max_simultaneous_developers` debe ser un entero positivo; un valor inválido se rechaza con un motivo explícito, nunca se persiste en silencio.

```json
{"max_simultaneous_developers": 4}
```

## Jobs

### `POST /jobs` → 201
Crea y **despacha sincrónicamente** un Job. La respuesta llega cuando el Job termina.

```json
{"agent_id": "...", "description": "...", "previous_job_id": "opcional"}
```

Devuelve `{id, session_id, agent_id, description, status, result}`. `previous_job_id` encadena el resultado del Job anterior (Developer→Developer bloqueado). Publica `job_status` en `WS /ws/jobs`.

### `GET /jobs`
Historial completo de Jobs de la sesión activa.

### `GET /jobs/{job_id}`
Estado/resultado de un Job específico.

### `POST /jobs/{job_id}/cancel`
Cancela un Job **en vuelo** (`running`). Espera la transición real del hilo del dispatcher (hasta 5s). 400 si el Job no está `running`.

## Backlog

### `GET /backlog`
Informe estructurado del backlog del proyecto activo (`02-backlog/`): conteos por Epic (con `unblock_degree` y `fase`), ítems LISTA/BLOQUEADA, cadena de máximo apalancamiento, errores de parseo.

### `GET /backlog/{item_id}`
Detalle de un ítem. Los IDs del tipo `AF-xxx` se resuelven como Epic; cualquier otra cosa como Task/User Story. Incluye objetivo/historia, criterios de aceptación, dependencias (con su estado) y, para User Stories, sus Tasks y (AF-024-US09) historial de ejecución. 404 con un motivo de parseo si el fichero existe pero no pudo parsearse.

### `POST /backlog/{story_id}/launch-development` → 201
Ruta de Job aislado (sin encolar las Tasks en `TO_DEVELOP`): construye el Job a partir de la story real + Tasks pendientes (`READY`) y lo despacha al agente indicado. 400 si la Story no tiene Tasks pendientes. Publica `job_status`.

```json
{"agent_id": "..."}
```

### `PUT /backlog/{item_id}/state`
Cambia el `state` de una Task/User Story directamente. Para una User Story, los estados operativos (`READY`/`TO_DEVELOP`/`IN_PROGRESS`/`IN_REVIEW`) no se fijan a mano: son derivados de sus Tasks; poner `DONE` dispara la promoción automática del Epic si todas sus User Stories ahora están `DONE`.

### `POST /backlog/{task_id}/enqueue` → 201
Marca una Task `READY` como `TO_DEVELOP`, haciéndola elegible para el Dispatcher. 400 si la Task no está `READY`.

### `POST /backlog/{us_id}/enqueue-all` → 201
Igual que lo anterior para todas las Tasks pendientes de una User Story en una sola llamada.

### `DELETE /backlog/{task_id}/enqueue`
Revierte una Task `TO_DEVELOP` de vuelta a `READY`, solo si el Dispatcher todavía no la ha recogido.

### `GET /backlog/queue`
Entradas actuales de la cola de despacho (datos auxiliares de ordenación FIFO/auditoría — el `state` en los ficheros reales es la fuente de verdad para la elegibilidad).

### `POST /backlog/epic/{epic_id}/propose-stories`
Ejecuta el pipeline determinista Epic→User-Story (validador de formato + auto-auditoría) y escribe las User Stories aprobadas, nacidas en `NO_TASKS`.

### `POST /backlog/us/{us_id}/propose-tasks`
Ejecuta el pipeline determinista User-Story→Task. Requiere que la Story esté en `TO_PLAN` (400 en caso contrario); en caso de éxito escribe las Tasks y a partir de ahí la US refleja el estado derivado de sus Tasks.

## Scripts

### `GET /scripts`
Catálogo combinado: primero los genéricos (sin `command`), luego los específicos de proyecto.

```json
[{"id": "commit", "name": "Commit de cambios", "command": null, "description": "...", "origin": "generic"},
 {"id": "deploy-web", "name": "Deploy web", "command": "...", "description": "...", "origin": "particular"}]
```

### `POST /scripts/{script_id}/run`
Ejecuta un script en el proyecto activo (bloqueante). Cuerpo opcional: `{"message": "..."}` (solo `commit` lo usa).

```json
{"success": true, "exit_code": 0, "stdout": "...", "stderr": "", "error_message": null, "data": null, "prose": null}
```

Para `backlog_status`: `data` es el informe parseado y `prose` el resumen opcional de Scribe (o `null` si no está disponible). Los fallos de script se devuelven **estructuralmente** (nunca como error HTTP), excepto 404 sin proyecto activo.

## Acciones transversales de proyecto

### `POST /project/actions/{action_id}`
Despacha una acción completa de proyecto (bloqueante). `action_id` ∈ `documentar | analizar-arquitectura | sugerir-ideas | testear | auditar-ux | indexar`. Persiste el informe en `07-informes/US-AF025-*/` sin sobrescribir. 400 para una acción desconocida; 404 sin sesión activa (acciones de agente).

## WebSockets

Conexiones servidor→cliente. El cliente no envía nada; `receive_text()` solo bloquea hasta la desconexión.

### `WS /ws/jobs`
Eventos `{"event": "job_status", id, session_id, agent_id, description, status, result}`:
- `created` — antes del despacho (expone el `job_id` real, necesario para poder cancelar).
- `completed` / `failed` — al terminar.

Ver también `WS /ws/agents/{agent_id}/pane` más arriba (contenido vivo del pane de tmux, no un evento `job_status`).

## Estados (resumen)

| Entidad | Estados |
|---|---|
| Agente | `idle`, `working`, `unavailable`, `stopped` (Developer nunca llega a `stopped` — detener un Developer lo borra) |
| Job | `created`, `running`, `completed`, `failed`, `cancelled` |
| Task | `READY`, `TO_DEVELOP`, `IN_PROGRESS`, `IN_REVIEW`, `DONE` (nunca `OUT_OF_SCOPE`) |
| User Story | `NO_TASKS`, `TO_PLAN`, más estados derivados de sus Tasks (`READY`/`TO_DEVELOP`/`IN_PROGRESS`/`IN_REVIEW`/`DONE`) y `OUT_OF_SCOPE` (exclusivo de US) |
| Sesión | `created`, `active`, `closed` |