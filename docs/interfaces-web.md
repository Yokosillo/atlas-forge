# Interfaz web

La **interfaz web es la interfaz principal** de Factory Brain desde la decisión de producto de 2026-08-04 (TUI y Android quedaron en pausa para funcionalidad nueva). Se sirve desde el propio backend en `http://<host>:8000/ui/`, es JS puro sin frameworks y habla con la misma API REST + WebSocket que el resto de clientes.

## Flujo de arranque

1. **Verificación de conectividad**: `GET /health`. Si el backend no responde, muestra la guía "No hay conexión con el backend" con botón **Reintentar**.
2. **Selección de proyecto**: si no hay proyecto activo, pantalla de onboarding ("Elige tu primer proyecto") o de cambio voluntario ("Selecciona otro proyecto").
3. **Vista operativa**: barra superior con el proyecto activo (chip) + botón **Cambiar proyecto**, pestañas de navegación y el cuerpo de la sección.

## Pestañas

La barra de navegación actual contiene: **Roles, Plan, Scripts, Backlog, Modelos, Acciones**. La pestaña Backlog muestra un badge naranja con el número de Epics/US pendientes.

!!! note "Pantallas Agentes y Jobs"
    La pantalla de **Agentes** fue sustituida por la pestaña **Roles** (configuración de roles, T-FB024-US08) y la pestaña **Jobs** se fusionó en el detalle de cada User Story del Backlog (T-FB024-US09). El código de los renderizadores de Agentes/Jobs sigue existiendo en `app.js` pero no está en la barra de navegación actual.

### Roles

Configuración de los **4 roles** (Director, Arquitecto, Developer, Tester) con su descripción y modelo por defecto. "Cambiar modelo" abre un selector inline y guarda vía `PUT /models/preferences` (`default_model_by_role`).

### Plan

- **"Pedir un plan al Arquitecto"**: el objetivo es un **selector de User Stories TODO del backlog** (con respaldo de texto libre si el backlog no carga).
- La tarjeta del plan muestra los pasos propuestos (Paso N · Mecanismo · Estado) en tiempo real vía WebSocket `WS /ws/plans`.
- **Aprobar** requiere segundo clic con confirmación ("¿Aprobar plan completo? Se despacharán N pasos…") y despacha la secuencia entera.
- **Rechazar** no requiere confirmación; **Cancelar plan** está disponible mientras el plan esté aprobado con pasos pendientes.
- Histórico de planes desde `GET /plans`, recuperación automática del plan `proposed` pendiente al recargar.

### Scripts

Catálogo combinado `GET /scripts` separado en **"Genéricos (Factory Brain)"** y **"Proyecto"**. Cada tarjeta muestra descripción; el comando shell está oculto por defecto y se muestra con "▶ Ver comando". Solo el script `commit` pide un mensaje. Ejecutar muestra éxito/exit code/stdout/stderr, y formatea la salida de `backlog_status` (conteo por Epic, LISTA, BLOQUEADA, cadena de apalancamiento).

### Backlog

- Toggle **"Lista" / "Por Fase"** (agrupación por fase del roadmap).
- Listado de Epics con resumen de estados (US/Tasks TODO y DONE), **barra de calor** de grado de desbloqueo por Epic y **badge** global de trabajo pendiente.
- Desglose expandible Epic → User Story → detalle (vía `GET /backlog/{item_id}`).
- En una User Story: dependencias con su estado (bloqueo de "Lanzar desarrollo" si hay dependencias sin resolver), **historial de ejecuciones** (Jobs sobre esa Story) y formulario manual "Crear Job manual" como secundario.
- "Lanzar desarrollo" (`POST /backlog/{story_id}/launch-development`) solo para agentes Developer y con Tasks pendientes.

### Modelos

Tabla de modelos con checkboxes de **habilitado** y selector de **modelo por defecto por rol** (developer / critic / arquitecto / tester). Guarda vía `PUT /models/preferences` (`enabled_model_ids` + `default_model_by_role`).

### Acciones

Acciones transversales de proyecto (FB-025) como botones directos a `POST /project/actions/{action_id}`:

| Acción | Qué hace |
|---|---|
| **Documentar todo** | Despacha Job al Arquitecto para contrastar `01-documentacion/` contra el código real. |
| **Analizar arquitectura** | Análisis de arquitectura con evidencia de código; no escribe al backlog. |
| **Sugerir ideas para el backlog** | Propuestas informales de Epics/US candidatas (nunca escritura directa). |
| **Testear todo** | Ejecuta la suite `pytest`; resultado PASA/FALLA con detalle. |
| **Auditar UX de la web** | Ejecución headless `opencode run --auto` según `00-gobierno/UX.md`. |
| **Indexar proyecto (Scribe)** | Indexa `01-documentacion/`, `02-backlog/`, `04-src/`, `00-gobierno/` con Scribe/Ollama. |

Todas persisten sus informes con timestamp en `07-informes/US-FB025-*/` sin sobrescribir ejecuciones anteriores.

## Patrones de UX

- **Confirmación en la etiqueta del botón** para acciones destructivas (detener agente, aprobar plan, cambiar de proyecto con agentes activos) — evita reflow de layout.
- **Estados por color** (WCAG): agentes idle/working/stopped/unavailable, Jobs running/ok/failed.
- **Single-flight**: los botones que disparan llamadas bloqueantes se deshabilitan mientras la petición está en vuelo (evita doble Job/plan por doble clic).
- **Stale-data**: notas ámbar "puede que esta lista esté desactualizada…" cuando los datos pueden no reflejar el último cambio.
- **WebSocket con reconexión** (`reconnecting-websocket.js`, backoff 3s) sin limpiar el estado de la UI.
- Objetivos táctiles ≥ 48px, tarjetas expandibles in-place, resultados completos con scroll.

## Configuración del cliente

El cliente se configura con `BackendClient.setBaseUrl(...)`; por defecto usa la misma origen (servido desde `brain-api`, sin CORS). Errores: `BackendUnavailableError` (red) y `BackendRequestError` (4xx/5xx con el `detail` real del backend).
