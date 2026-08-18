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
2. Se añade una instrucción a la descripción: el agente debe escribir su resultado completo en un fichero temporal único (`factory-brain-job-<uuid>.txt`) más un **marcador final** (`___FACTORY_BRAIN_JOB_DONE___`) en su propia línea.
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
NO_TASKS → (el usuario hace clic en "Progresar") → EN_DISEÑO
    → (el Dispatcher asigna un Arquitecto libre, aterrizaje US→Tasks) → TO_DO
    → (el usuario hace clic en "Progresar") → EN_DESARROLLO
    → (todas sus Tasks llegan a DONE) → REVIEW
    → (el Arquitecto emite un veredicto) → DONE
```

- **`NO_TASKS`**: cada User Story nueva nace en este estado — sin Tasks todavía.
- **`EN_DISEÑO`**: el usuario hizo clic en el único botón **"Progresar"**; la Story ahora es una señal para el Dispatcher, que la asigna a un Arquitecto libre para ejecutar el aterrizaje US→Tasks (un pipeline determinista, sin gastar un Job de agente). Una vez escrita al menos una Task, la Story pasa a `TO_DO`.
- **`TO_DO`**: existen Tasks, esperando que el usuario progrese la Story hacia el desarrollo.
- **`EN_DESARROLLO`**: el usuario hizo clic de nuevo en "Progresar" — todas las Tasks pendientes quedan encoladas para el Dispatcher.
- **`REVIEW`**: se dispara automáticamente una vez que **todas** las Tasks de la Story están `DONE`.

El mismo botón **"Progresar"** cambia su acción según el estado actual de la Story (`NO_TASKS`→`EN_DISEÑO`, `TO_DO`→`EN_DESARROLLO`) — un único verbo que el usuario lee como "sigue avanzando".

### Revisión de Tasks — dos niveles

`REVIEW` significa algo distinto para una Task que para una User Story:

1. **Task en `REVIEW`**: el Developer cerró la implementación — el Dispatcher la asigna a un **Tester** libre, que verifica funcionalmente los criterios de aceptación de la Task.
   - PASS → la Task pasa a `DONE`.
   - FAIL → la Task vuelve **directamente al mismo Developer** vía el Dispatcher, con los hallazgos del Tester adjuntos — no se crea una Task nueva. Re-entra en `REVIEW` cuando el Developer la cierra de nuevo.
   - Mientras la Task de un Developer está en `REVIEW`, ese Developer no se considera libre para una Task `EN_DESARROLLO` nueva (configurable vía la preferencia de sistema `developer_waits_for_tester_review`) — así ningún Developer puede tener dos Tasks auto-certificándose en paralelo.

2. **User Story en `REVIEW`**: el Dispatcher la asigna a un **Arquitecto** libre, que evalúa si las Tasks de la Story cubren completamente la necesidad declarada.
   - Aprobada (con o sin notas) → la Story pasa a `DONE`.
   - Rechazada por cobertura insuficiente → el Arquitecto añade una Task nueva a la **misma** Story, entrando directamente en `EN_DESARROLLO` (saltándose `TO_DO`) — la Story no se promueve a `DONE` en este caso.

El Dispatcher repite este ciclo de polling para los cuatro niveles (aterrizaje de US, implementación, revisión de Tasks, veredicto de Story) con la misma regla de "un agente libre a la vez" en cada nivel.

## Job aislado

Fuera del pipeline guiado por estados de la Story, existe una ruta directa para despachar trabajo puntual a un agente específico sin pasar por ningún ciclo de Story: `POST /jobs` — el humano elige el agente y escribe (o la UI pre-rellena) la descripción. "Lanzar desarrollo" (contexto ya resuelto: el objetivo de una Story más sus Tasks pendientes) y "Crear Job manual" (descripción libre) usan ambos este mismo mecanismo, disponible desde la vista de detalle de una User Story en la pantalla de Backlog.

## Planificado (no implementado)

- **Dispatcher v2 completo** (FB-008): pipeline con dependencias declarativas, reintentos, coordinación multi-agente automática y resolución de capacidades (vía el Capability Engine FB-010).
- **Scheduler / cola global de Jobs**: no existe como entidad separada hoy.