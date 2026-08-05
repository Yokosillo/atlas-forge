# TUI

La TUI es el cliente de terminal de Factory Brain, construida con [Textual](https://textual.textualize.io/). Es un **cliente de la API** como cualquier otro: asume que `brain-api` está corriendo y no gestiona estado de dominio propio.

!!! note "Pausa de desarrollo"
    Desde la decisión de producto de 2026-08-04, toda funcionalidad nueva se expone en la web; la TUI queda en pausa para capacidades nuevas (las Tasks de modelo activo en TUI están `POSTERGADA`). Lo que se documenta aquí es lo ya implementado y operativo.

## Arranque

```bash
brain
```

El comando `brain` arranca la TUI. Al montarse:

1. **ConnectivityCheckScreen**: sondea `GET /session`.
2. Si conecta: recupera el proyecto activo (`resolve_startup_project`) y salta al **Dashboard** o a la pantalla **Workspace** (si no hay proyecto).
3. Si no conecta: muestra error + **Reintentar**.

## Pantallas

Navegación por teclado nativa de Textual (botones, `ListView`, `Select`, tabulación).

### Workspace

Lista los proyectos descubiertos (`discover_projects` local). Al elegir uno, selecciona el proyecto activo y vuelve al Dashboard. Diferencia entre onboarding ("Selecciona un proyecto:") y cambio voluntario ("Volver al Dashboard").

### Dashboard

Centro de navegación y estado: proyecto activo, sesión (id/estado), agentes lanzados con estado, y resumen de Jobs por estado. Botones: **Ver Agentes, Ver Jobs, Ver Plan, Ver Scripts, Ver Backlog, Cambiar de proyecto**.

### Agentes

- Lista de agentes lanzados con estado.
- Selector de rol+runtime (filtra Critic+OpenCode, decisión de producto) + campo de modelo opcional (solo OpenCode) → **Lanzar**.
- **Detener** por agente con confirmación de segundo clic ("¿Seguro? Tiene un Job en curso — se interrumpirá. Confirmar detener").

### Jobs

- Descripción (`TextArea`) + agente (`Select`) → **Enviar** (llamada bloqueante `POST /jobs` en worker).
- **Cancelar Job** mediante un localizador que busca el Job por descripción en `GET /jobs`.
- **Encadenar a Critic/Arquitecto**: aparece tras completarse un Job de Developer si hay un Critic/Arquitecto lanzado.
- Histórico recomuesto desde `GET /jobs`.

### Plan

- Selecciona el plan `proposed` más reciente de `GET /plans`; muestra objetivo/estado/pasos.
- **Aprobar plan completo** (confirmación con número de pasos), **Rechazar**, **Cancelar plan** (disponible desde el inicio del despacho, ya que `plan_id` se conoce de antemano).

### Scripts

- Selector del catálogo con prefijo `[Genérico]`/`[Proyecto]`.
- Campo de mensaje solo para `commit`.
- Ejecución en background vía `POST /scripts/{id}/run`; formatea la salida de `backlog_status`.

### Backlog

Desglose de tres niveles (Epic → Epic detail → item detail) con `push_screen`/`pop_screen`:

- Colores Rich: `[green]` DONE, `[dark_orange]` TODO, `[bright_black]` desconocido.
- Barras de progreso proporcionales (p. ej. `███░░░░░░░ 3/10 US DONE`).
- Advertencias `⚠` para items con errores de parseo.
- En una User Story: **Lanzar desarrollo** con selector de agente Developer.

## Backend client

`brain.tui.backend_client` es un cliente `requests` síncrono con `DEFAULT_BACKEND_URL = http://127.0.0.1:8000`, timeout 10s (60s para llamadas bloqueantes de despacho/aprobación/scripts). Métodos: `get_session`, `get_agents`, `launch_agent`, `stop_agent`, `get_jobs`, `create_and_dispatch_job`, `cancel_job`, `get_plans`, `get_plan`, `approve_plan`, `reject_plan`, `cancel_plan`, `get_backlog`, `get_backlog_item`, `launch_development`, `get_scripts`, `run_script`.

Excepciones de cliente: 404 en agentes/jobs/scripts → lista vacía; 404 en backlog → error real (propagado).

## Limitaciones conocidas

- La TUI no inicia `brain-api` por sí misma; depende de que el servicio esté corriendo (systemd u otro).
- Keyboard-first: no es adecuada para uso táctil desde el móvil (de ahí la app Android / la web).
