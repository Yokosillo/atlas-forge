# Jobs y el pipeline de trabajo

## Ciclo de vida de un Job

Un **Job** es una unidad de trabajo (una descripción de texto) enviada a un agente. Estados:

```
created → running → { completed | failed | cancelled }
```

### Creación (`dispatcher/job_creation.py`)

Precondiciones (cada rechazo lanza `JobCreationError` con un mensaje explícito):
- Sesión activa.
- El agente pertenece a la sesión.
- El agente está `idle` (un agente `working` no recibe un Job nuevo).

### Despacho (`dispatcher/job_dispatch.py`)

Mecanismo de **reporte cooperativo** (ni marcador de fin de shell ni heurísticas de silencio):

1. `mark_running(job)` + `mark_working(agent)`.
2. Se añade una instrucción a la descripción: el agente debe escribir su resultado completo en un fichero temporal único (`atlas-forge-job-<uuid>.txt`) más un **marcador final** (`___ATLAS_FORGE_JOB_DONE___`) en su propia línea.
3. La instrucción se envía al pane de tmux del agente (`run_command`).
4. El dispatcher sondea el fichero (timeout de 30s por defecto para Jobs cortos/deterministas; el trabajo despachado a través del pipeline de backlog usa un timeout mucho mayor adecuado al trabajo de implementación real), con reintentos de lectura para `OSError`s transitorios.
5. `completed` (resultado leído) | `failed` (timeout `JobReportTimeoutError`) | `cancelled` (`JobCancelledError` si el usuario pidió la cancelación).
6. En `finally`: borra el fichero temporal y limpia la petición de cancelación. El agente vuelve a `idle`.

!!! note "Limitación conocida"
    El despacho depende de que el agente siga la instrucción de reporte. `POST /jobs` es bloqueante: la respuesta HTTP llega cuando el Job termina.

### Pre-procesamiento de Scribe

Antes de enviar, `_resolve_job_description` puede enriquecer la descripción con contexto de Scribe (por tamaño o cantidad) — ver [Runtime y Scribe](runtime.md). `job.description` nunca se muta.

## Encadenamiento de Jobs

El encadenamiento es **manual y explícito**:

- Al crear un Job con `previous_job_id`, el resultado del Job anterior (debe estar `completed` y con resultado no vacío) se inyecta **literalmente** en la descripción del nuevo Job.
- **Guardia de rol**: Developer→Developer está bloqueado — el resultado de un Developer debe encadenarse al Arquitecto para revisión. Todas las demás combinaciones están permitidas.
- Uso principal: el Developer produce → se encadena al Arquitecto para revisión.

## Historial e informes

- `GET /jobs` devuelve el historial completo de la sesión (nunca se purga).
- `write_job_report(job)` persiste un **informe de cierre** por `job_id` en `07-informes/<story_id>/<job_id>.md`. Si el Job no tiene `story_id`, va a `07-informes/_sin-story/`.

## Cancelación de Jobs

- `POST /jobs/{job_id}/cancel` solo es válido en un Job `running` (`JobCancellationRejectedError` en caso contrario).
- Mecanismo: `request_cancellation` establece un `threading.Event`; la transición real a `cancelled` la hace el hilo del dispatcher en su siguiente ciclo de polling. Esto evita escrituras concurrentes en `job.status`.
- **No mata el proceso de tmux**: el runtime puede seguir pensando (limitación documentada).
- El endpoint espera (hasta 5s) la transición real y devuelve el estado confirmado.

## El pipeline de backlog

El trabajo por encima del nivel de un Job individual se impulsa enteramente por el campo `state` de una User Story, y lo orquesta un único Dispatcher en segundo plano (`dispatcher/dispatch_queue_worker.py`) que sondea cada 5 segundos y reasigna el trabajo a cualquier agente libre.

### Estados de User Story

```
NO_TASKS → (el usuario hace clic en "Progresar") → TO_PLAN
    → (el Dispatcher asigna un Arquitecto libre, aterrizaje US→Tasks)
    → (derivado de sus Tasks: READY | TO_DEVELOP | IN_PROGRESS | IN_REVIEW)
    → (todas sus Tasks llegan a DONE) → IN_REVIEW
    → (el Arquitecto valida la US completa) → DONE
```

- **`NO_TASKS`**: cada User Story nueva nace en este estado — sin Tasks todavía.
- **`TO_PLAN`**: el usuario hizo clic en el único botón **"Progresar"**; la Story ahora es una señal para el Dispatcher, que la asigna a un Arquitecto libre para ejecutar el aterrizaje US→Tasks (un pipeline determinista, sin gastar un Job de agente). Una vez escrita al menos una Task, la Story deja de tener estado de planificación propio y pasa a reflejar el estado de sus Tasks.
- **Estado derivado**: con Tasks creadas, la US refleja siempre la **Task menos avanzada** (`READY` < `TO_DEVELOP` < `IN_PROGRESS` < `IN_REVIEW` < `DONE`) — no es un estado operativo independiente.
- **`IN_REVIEW` (US)**: se dispara automáticamente una vez que **todas** las Tasks de la Story están `DONE`. Aquí significa que la US completa está pendiente de **validación por el Arquitecto**; no pasa automáticamente a `DONE`.

El mismo botón **"Progresar"** solo actúa en `NO_TASKS` (→ `TO_PLAN`); a partir de ahí, el avance lo gobiernan el Dispatcher y los estados derivados — un único verbo que el usuario lee como "sigue avanzando".

### Revisión — dos niveles

`IN_REVIEW` significa algo distinto para una Task que para una User Story:

1. **Task en `IN_REVIEW`**: el Developer cerró la implementación — el Dispatcher la asigna a un **Tester** libre, que verifica funcionalmente los criterios de aceptación de la Task.
   - `EXITO` → la Task pasa a `DONE`.
   - `FALLO` → la **misma Task** vuelve directamente al mismo Developer que la cerró (retrabajo, sin crear una Task nueva): pasa de nuevo a `IN_PROGRESS` con una sección `## Corrección pendiente` anotada en el fichero, y el Job de corrección se registra como trabajo en vuelo. Re-entra en `IN_REVIEW` cuando el Developer la cierra de nuevo.
   - **Fallback**: si el Developer que cerró la Task ya no está disponible (runtime caído o fuera de sesión), la Task vuelve a `TO_DEVELOP` para que el ciclo normal la re-despache a cualquier Developer libre — nunca se bloquea.
   - Mientras la Task de un Developer está en `IN_REVIEW`, ese Developer no se considera libre para una Task nueva (preferencia de sistema `developer_waits_for_tester_review`, activa por defecto) — así ningún Developer puede tener dos Tasks auto-certificándose en paralelo.

2. **User Story en `IN_REVIEW`**: solo cuando **todas** sus Tasks están `DONE`, el Dispatcher asigna la US a un **Arquitecto** libre, que evalúa si las Tasks de la Story cubren completamente la necesidad declarada.
   - Aprobada (con o sin notas) → la Story pasa a `DONE`.
   - Rechazada por cobertura insuficiente → el Arquitecto añade una Task nueva a la **misma** Story — la Story no se promueve a `DONE` en este caso.

El Dispatcher repite este ciclo de polling para los niveles de aterrizaje de US, implementación, revisión de Tasks y validación final de Story con la misma regla de "un agente libre a la vez" en cada nivel.

### Asignación por dificultad

Al despachar una Task `TO_DEVELOP` a un Developer, el Dispatcher elige al Developer libre según la **dificultad** de la Task y el mapa `difficulty_model_map` de las preferencias del sistema (que asocia cada nivel de dificultad a un tier de modelo). Degrada automáticamente a cualquier Developer libre si el nivel no se reconoce, no hay modelos o el runtime no soporta cambio de modelo en caliente.

### Cola de despacho

Además del `state` en el fichero real (fuente de verdad de elegibilidad), el Dispatcher mantiene una **cola de despacho** por proyecto (`dispatch_queue.json`). Cada Task encolada tiene una entrada con estado `queued | dispatched | failed | completed` (más `awaiting_tester` derivado). La cola aporta el orden FIFO y la auditoría; se expone en `GET /backlog/queue` y en la pestaña **Pipeline** de la web.

### Escalado autónomo

El Dispatcher puede **escalar y liberar agentes** automáticamente según la demanda pendiente (`dispatcher/autonomous_scaling.py`, preferencia `autonomous_config.enabled`): calcula el número deseado de Developers y Testers a partir del trabajo pendiente y los límites configurados por rol, sin superar nunca un máximo total. Solo libera agentes `idle`, no persistentes, no retenidos y sin Job en vuelo.

## Job aislado

Fuera del pipeline guiado por estados de la Story, existe una ruta directa para despachar trabajo puntual a un agente específico sin pasar por ningún ciclo de Story: `POST /jobs` — el humano elige el agente y escribe (o la UI pre-rellena) la descripción. "Lanzar desarrollo" (contexto ya resuelto: el objetivo de una Story más sus Tasks pendientes) y "Crear Job manual" (descripción libre) usan ambos este mismo mecanismo, disponible desde la vista de detalle de una User Story en la pantalla de Backlog.

## Planificado (no implementado)

- **Dispatcher v2 completo** (AF-008): pipeline con dependencias declarativas, reintentos, coordinación multi-agente automática y resolución de capacidades (vía el Capability Engine AF-010).
- **Test-planting en paralelo** (AF-043): que el Tester genere tests de aceptación al entrar la Task en `TO_DEVELOP` (hoy el Tester genera tests dentro de su verificación, no como fase previa).
- **Eventos de retrabajo para telemetría** (AF-043): hoy el retrabajo se registra en el log, pero no como evento estructurado de telemetría (AF-041).
