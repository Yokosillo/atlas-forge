# Interfaz web

La **interfaz web es la interfaz principal** de Factory Brain. Se sirve desde el propio backend en `http://<host>:8000/ui/`, es JS puro sin frameworks y habla con la misma API REST + WebSocket que el resto de clientes.

## Flujo de arranque

1. **Comprobación de conectividad**: `GET /health`. Si el backend no responde, muestra la guía "No connection to the backend" con un botón **Retry**.
2. **Selección de proyecto**: si no hay proyecto activo, una pantalla de onboarding ("Elige tu primer proyecto") o cambio voluntario ("Seleccionar otro proyecto").
3. **Vista operativa**: barra superior con el proyecto activo (chip) + botón **Cambiar proyecto**, pestañas de navegación y el cuerpo de la sección.

## Pestañas

La barra de navegación contiene: **Backlog, Agentes, Arquitecto, Scripts, Acciones, Configuración**. La pestaña Backlog muestra un badge naranja con el número de Epics/US pendientes.

### Backlog

El panel de control de todo el producto — cada pieza de trabajo se despliega desde aquí.

- Toggle **"Lista" / "Por fase"** (agrupación por fase del roadmap).
- Listado de Epics con resumen de estados (US/Tasks por estado), **barra de calor** del grado de desbloqueo por Epic y un **badge** global de trabajo pendiente.
- Desglose expandible Epic → User Story → detalle (vía `GET /backlog/{item_id}`).
- El detalle de una User Story muestra sus dependencias con su estado, sus Tasks, y un botón **"Progresar"** cuya acción depende del estado actual de la Story:
  - `NO_TASKS` → marca `TO_PLAN` (el Dispatcher asigna un Arquitecto libre para aterrizar la Story en Tasks).
  - Con Tasks creadas → el estado de la US es **derivado** (la Task menos avanzada); el botón muestra el estado actual y el avance lo gobiernan el Dispatcher y las validaciones (Tester por Task, Arquitecto al final).
- "Opciones avanzadas" (colapsadas por defecto) expone la ruta de Job aislado: "Lanzar desarrollo" (contexto pre-rellenado desde la Story) y "Crear Job manual" (descripción libre) — ver [Jobs y el pipeline de trabajo](jobs.md).
- Formularios para crear una Epic, una User Story o una Task directamente desde la pantalla, y botones para que el Arquitecto proponga User Stories para una Epic o aterrice una User Story en Tasks.

### Agentes

Pantalla unificada que lista todos los roles de gobernanza (Arquitecto, Developer, Auditor-OSS, UX, Tester) con los mismos campos y botones independientemente del rol. El Arquitecto es de instancia única y reutilizable (pausa a `stopped` con "Stop"); el Developer es multi-instancia, persistente y gestionado por humanos (hasta un límite simultáneo configurable — "Stop" borra la instancia y libera su slot en lugar de pausarla). Auditor-OSS, UX y Tester se listan con "Launch" deshabilitado y un motivo explícito mientras permanezcan sin registrar en el backend. Runtime y modelo se eligen explícitamente en el lanzamiento (sin cambio de runtime/modelo en caliente para un agente vivo).

### Arquitecto

Una pestaña conversacional dedicada al Arquitecto: elige una de sus órdenes predefinidas o escribe un prompt libre, lo despacha como Job y navega por el historial de órdenes anteriores (con estado, resultado y expandir/colapsar por entrada).

### Scripts

Catálogo combinado `GET /scripts` dividido en **"Generic (Factory Brain)"** y **"Project"**. Cada tarjeta muestra la descripción; el comando shell está oculto por defecto y se muestra con "▶ View command". Solo el script `commit` pide un mensaje. La ejecución muestra éxito/código de salida/stdout/stderr, y formatea la salida de `backlog_status` (conteo por Epic, LISTA, BLOQUEADA, cadena de apalancamiento).

### Acciones

Acciones transversales de proyecto como botones directos a `POST /project/actions/{action_id}`:

| Acción | Qué hace |
|---|---|
| **Documentar todo** | Despacha un Job al Documentador para contrastar `docs/` con el código real. |
| **Analizar arquitectura** | Análisis de arquitectura con evidencia de código; no escribe en el backlog. |
| **Sugerir ideas para el backlog** | Propuestas informales de Epics/US candidatas (nunca escrituras directas). |
| **Testear todo** | Ejecuta la suite `pytest`; resultado PASS/FAIL con detalle. |
| **Auditar la UX web** | Ejecución headless de `opencode run --auto` según `00-gobierno/UX.md`. |
| **Indexar proyecto (Scribe)** | Indexa `docs/`, `02-backlog/`, `04-src/`, `00-gobierno/` con Scribe/Ollama. |

Todas persisten sus informes con marca de tiempo en `07-informes/US-FB025-*/` sin sobrescribir ejecuciones anteriores.

### Configuración

Preferencias del sistema editables desde la web: el número máximo de Developers simultáneos, y si un Developer espera el veredicto del Tester sobre su Task anterior antes de recibir una nueva.

## Patrones de UX

- **Confirmación en la etiqueta del botón** para acciones destructivas (stop de agente, cambio de proyecto con agentes activos) — evita reflow de layout.
- **Colores de estado** (WCAG): agentes idle/working/stopped/unavailable, Jobs running/ok/failed.
- **Single-flight**: los botones que disparan llamadas bloqueantes quedan deshabilitados mientras la petición está en vuelo (evita un doble despacho por doble clic).
- **Stale-data**: notas ámbar "esta lista puede estar desactualizada…" cuando los datos pueden no reflejar el último cambio.
- **WebSocket con reconexión** (`reconnecting-websocket.js`, backoff de 3s) sin limpiar el estado de la UI.
- Targets táctiles ≥ 48px, tarjetas expandibles en sitio, resultados completos con scroll.

## Configuración del cliente

El cliente se configura con `BackendClient.setBaseUrl(...)`; por defecto usa el mismo origen (servido desde `brain-api`, sin CORS). Errores: `BackendUnavailableError` (red) y `BackendRequestError` (4xx/5xx con el `detail` real del backend).