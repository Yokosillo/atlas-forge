# API

Factory Brain expone su dominio a través de una **API HTTP/WebSocket** (FastAPI) que todos los clientes consumen. Referencia completa generada contra el código real de `04-src/src/brain/api/`.

## Generalidades

- **Base**: `http://<host>:8000` (host resuelto como IP Tailscale en producción; `127.0.0.1` en local).
- **Sin autenticación propia**: el perímetro de seguridad es la pertenencia a la red Tailscale.
- **Sin CORS**: la web se sirve desde el mismo proceso (`/ui/`), same-origin.
- **Errores**: `HTTPException` con `detail` en español (mensaje construido en el dominio).
- **Formato**: JSON. No hay query params — solo path params y cuerpos JSON.

## Health e infraestructura

### `GET /health`
Comprueba que el backend responde.

```json
{"status": "ok", "session_id": null}
```

`session_id` es `null` hasta que hay proyecto seleccionado.

### `GET /apk`
Sirve `releases/factory-brain-latest.apk` (descarga de la app Android). 404 si el APK no existe.

### `GET /ui/` (mount estático)
Sirve la interfaz web (`10-web/`). `GET /ui` redirige a `/ui/`.

## Proyectos

### `GET /project`
Proyecto activo.

```json
{"id": "...", "name": "...", "path": "...", "repository": "...", "workspace_id": "..."}
```

404 "No hay ningún proyecto activo."

### `GET /projects`
Lista los repositorios Git descubiertos en el workspace (candidatos a proyecto activo).

### `POST /project`
Selecciona el proyecto activo y **reinicia en caliente la sesión de desarrollo** (detiene agentes no detenidos, invalida cachés, arranca nueva sesión).

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

404 "No hay ninguna sesión de desarrollo activa."

## Agentes

### `GET /agents`
Agentes lanzados en la sesión activa, con `model` resuelto del runtime real (nullable). Ejecuta liveness perezoso: runtimes muertos aparecen como `unavailable`.

```json
[{"id": "...", "name": "Developer-1", "role": "developer", "status": "idle", "runtime_id": "opencode", "model": null}]
```

404 sin sesión.

### `GET /agents/options`
Catálogo de combinaciones rol×modelo lanzables: producto cartesiano de roles × modelos habilitados con runtime resuelto. Se filtran las combinaciones Critic+OpenCode.

```json
[{"agent_role": "developer", "model_id": "opencode-go/deepseek-v4-flash", "model_name": "DeepSeek V4 Flash", "runtime_type": "opencode", "runtime_name": "OpenCode", "supports_model": true}]
```

### `POST /agents` → 201
Lanza un agente. Body:

```json
{
  "role": "developer",
  "runtime_type": "opencode",
  "model_id": "opencode-go/deepseek-v4-flash",
  "initial_job_description": "opcional: tarea inicial"
}
```

`model` es alias legacy de `model_id`. Sin `initial_job_description` devuelve el agente; con él devuelve `{agent, job}` (el Job puede quedar `failed` con motivo en `job.result`). Errores: 404 sin sesión/proyecto; 400 runtime/modelo inválidos o `AgentLaunchError`.

### `POST /agents/{agent_id}/stop`
Detiene un agente: mata su sesión tmux y lo transiciona a `stopped`.

### `GET /agents/{agent_id}/pane`
Contenido textual actual del pane tmux del agente (vista de solo lectura).

```json
{"agent_id": "...", "content": "..."}
```

### `GET /agents/{agent_id}/model`
Modelo activo del agente (solo OpenCode). `null` para runtime no-OpenCode o lectura fallida — nunca es un error HTTP.

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

## Preferencias de modelos

### `GET /models/preferences`
Catálogo completo con habilitación y defaults por rol.

```json
{"models": [{"id": "...", "name": "...", "runtime": "opencode", "enabled": true}], "defaults": {"developer": "..."}}
```

`enabled_model_ids` vacío = todos habilitados.

### `PUT /models/preferences`
Actualiza preferencias (parcial: solo los campos enviados).

```json
{"enabled_model_ids": ["..."], "default_model_by_role": {"developer": "..."}}
```

## Jobs

### `POST /jobs` → 201
Crea y **despacha síncronamente** un Job. La respuesta llega cuando el Job termina.

```json
{"agent_id": "...", "description": "...", "previous_job_id": "opcional"}
```

Devuelve `{id, session_id, agent_id, description, status, result}`. `previous_job_id` encadena el resultado del Job anterior (Developer→Developer bloqueado). Publica `job_status` en `WS /ws/jobs`.

### `GET /jobs`
Histórico completo de Jobs de la sesión activa.

### `GET /jobs/{job_id}`
Estado/resultado de un Job concreto.

### `POST /jobs/{job_id}/cancel`
Cancela un Job **en curso** (`running`). Espera la transición real del hilo despachador (hasta 5s). 400 si el Job no está `running`.

## Planes del Arquitecto

### `POST /plans` → 201
Pide al Arquitecto un plan de desglose para una User Story. **No despacha nada.**

```json
{"goal": "US-FB020-01"}
```

Devuelve `{plan_id, goal, status: "proposed", steps: [{description, mechanism, status}]}`. Publica `plan_progress` en `WS /ws/plans`.

### `GET /plans`
Todos los planes registrados en el proceso (incluye decididos), para recuperar un `plan_id` perdido.

### `GET /plans/{plan_id}`
Progreso de un plan concreto.

### `POST /plans/{plan_id}/approve`
Aprueba y **despacha el plan completo** de extremo a extremo (bloqueante). Idempotente: solo la primera petición transiciona `proposed→approved`; las concurrentes devuelven `already_decided: true`. Publica un evento por paso en `WS /ws/plans`.

Devuelve `{plan_id, already_decided, goal, status, steps}`.

### `POST /plans/{plan_id}/reject`
Rechaza un plan propuesto (no despacha nada). Idempotente como approve.

### `POST /plans/{plan_id}/cancel`
Cancela un plan **aprobado y en vuelo**. Espera la transición real (hasta 5s). 400 si el plan no está `approved` o no tiene pasos pendientes/running.

## Backlog

### `GET /backlog`
Informe estructurado del backlog del proyecto activo (`02-backlog/`): conteos por Epic (con `unblock_degree` y `fase`), items LISTA/BLOQUEADA, cadena de máximo apalancamiento, errores de parseo.

### `GET /backlog/{item_id}`
Detalle de un item. Los IDs tipo `FB-xxx` se resuelven como Epic; cualquier otra cosa como Task/User Story. Incluye objetivo/historia, criterios de aceptación, dependencias (con su estado) y, para User Stories, sus Tasks y (FB-024-US09) historial de ejecuciones. 404 con razón de parseo si el fichero existe pero no se pudo parsear.

### `POST /backlog/{story_id}/launch-development` → 201
Lanza el desarrollo de una User Story: construye el Job desde la historia real + Tasks pendientes (`TODO`) y lo despacha al agente indicado. 400 si la Story no tiene Tasks pendientes. Publica `job_status`.

```json
{"agent_id": "..."}
```

## Scripts

### `GET /scripts`
Catálogo combinado: genéricos primero (sin `command`), luego particulares del proyecto.

```json
[{"id": "commit", "name": "Commit de cambios", "command": null, "description": "...", "origin": "generic"},
 {"id": "deploy-web", "name": "Deploy web", "command": "...", "description": "...", "origin": "particular"}]
```

### `POST /scripts/{script_id}/run`
Ejecuta un script en el proyecto activo (bloqueante). Body opcional: `{"message": "..."}` (solo `commit` lo usa).

```json
{"success": true, "exit_code": 0, "stdout": "...", "stderr": "", "error_message": null, "data": null, "prose": null}
```

Para `backlog_status`: `data` es el informe parseado y `prose` el resumen opcional de Scribe (o `null` si no está disponible). Fallos de script se devuelven **estructuralmente** (nunca como error HTTP), salvo 404 sin proyecto activo.

## Acciones transversales de proyecto

### `POST /project/actions/{action_id}`
Despacha una acción de proyecto completa (bloqueante). `action_id` ∈ `documentar | analizar-arquitectura | sugerir-ideas | testear | auditar-ux | indexar`. Persiste el informe en `07-informes/US-FB025-*/` sin sobrescribir. 400 para acción desconocida; 404 sin sesión activa (acciones de agente).

## WebSockets

Conexiones servidor→cliente. El cliente no envía nada; `receive_text()` solo bloquea hasta la desconexión.

### `WS /ws/jobs`
Eventos `{"event": "job_status", id, session_id, agent_id, description, status, result}`:
- `created` — antes del despacho (expone el `job_id` real, necesario para poder cancelar).
- `completed` / `failed` — al terminar.

### `WS /ws/plans`
Eventos `{"event": "plan_progress", plan_id, goal, status, steps, already_decided?}`:
- Al crear el plan.
- En aprobación/rechazo/cancelación.
- Durante el despacho, tras cada cambio de estado de paso.

## Estados (resumen)

| Entidad | Estados |
|---|---|
| Agent | `idle`, `working`, `unavailable`, `stopped` |
| Job | `created`, `running`, `completed`, `failed`, `cancelled` |
| Plan | `proposed`, `approved`, `rejected`, `blocked`, `cancelled` |
| Step | `pending`, `running`, `completed`, `failed`, `cancelled` |
| Session | `created`, `active`, `closed` |
