# Arquitectura

Atlas Forge es una aplicación **modular, extensible y mantenible**, diseñada para añadir nuevas capacidades sin reestructurar el proyecto.

## Idea central

El dominio (proyectos, sesiones, agentes, Jobs, backlog) vive **detrás de una única API HTTP/WebSocket** (`atlas_forge/api/`, FastAPI). Ningún cliente accede al dominio de otra forma que no sea a través de esa API.

> Un proceso de verdad (`atlas-forge-api`), un cliente: la **interfaz web**.

## Capas

```mermaid
graph TD
    subgraph Clients
        WEB[Interfaz web<br/>10-web/ · JS]
    end

    API[API HTTP/WebSocket<br/>atlas_forge/api/ · FastAPI]

    subgraph Dominio
        DISP[Dispatcher<br/>atlas_forge/dispatcher/]
        AGENTS[Agentes<br/>atlas_forge/agents/]
        CORE[Sesión<br/>atlas_forge/core/]
        RUNTIME[Runtime<br/>atlas_forge/runtime/]
        BACKLOG[Backlog<br/>atlas_forge/backlog/]
        ARCH[Arquitecto<br/>atlas_forge/architect/]
        SCRIBE[Scribe<br/>atlas_forge/local_tools/]
    end

    subgraph Infraestructura
        TMUX[tmux · libtmux]
        OLLAMA[Ollama · localhost:11434]
        GIT[Repos Git]
    end

    WEB --> API
    API --> DISP
    API --> AGENTS
    API --> CORE
    API --> BACKLOG
    API --> SCRIBE
    DISP --> AGENTS
    DISP --> SCRIBE
    AGENTS --> RUNTIME
    RUNTIME --> TMUX
    SCRIBE --> OLLAMA
    DISP --> GIT
```

### Presentación

Interfaz web (JS puro servido por el propio backend en `/ui/`). **Sin lógica de negocio**: toda la interacción pasa por la API.

### Aplicación

La API (`atlas_forge/api/routes.py`) orquesta las operaciones: lanza agentes, crea/despacha Jobs, ejecuta scripts y expone el estado del backlog. Es una capa fina sobre el dominio — no reimplementa lógica, la expone.

### Dominio

Reglas de negocio independientes de la interfaz:

- **`atlas_forge/core/`** — ciclo de vida de la sesión de desarrollo.
- **`atlas_forge/agents/`** — registro de roles, lanzamiento, ciclo de vida, liveness, stop, gobernanza.
- **`atlas_forge/runtime/`** — instancias de runtime en tmux (Claude Code, OpenCode, Codex).
- **`atlas_forge/dispatcher/`** — creación, despacho, reporte y cancelación de Jobs; el Dispatcher en segundo plano que impulsa el pipeline de backlog guiado por estados (implementación, revisión de Tasks, veredicto de Story, aterrizaje US→Tasks); disparo automático de Scribe.
- **`atlas_forge/backlog/`** — parser de backlog, informe de estado, detalle, validador, grafo de dependencias.
- **`atlas_forge/architect/`** — generadores Epic→US→Task, revisión de brechas, pipelines de auto-auditoría.
- **`atlas_forge/local_tools/`** — Scribe (resumen/indexación local vía Ollama).
- **`atlas_forge/workspace/`** — descubrimiento de proyectos, proyecto activo, scripts genéricos y de proyecto, arranque.
- **`atlas_forge/models/`** — dataclasses de dominio (Agent, Job, DevelopmentSession, Project, backlog, scripts).

### Infraestructura

- **tmux** (socket `atlas-forge`) para sesiones de runtime persistentes.
- **Git** para descubrir repositorios y ejecutar scripts.
- **Ollama** para Scribe.
- **systemd** para el servicio `atlas-forge-api`.

## Persistencia

| Dato | Dónde | Persistente |
|---|---|---|
| Proyecto activo | `~/.local/share/atlas_forge/active_project.json` | Sí |
| Preferencias de modelo | `~/.local/share/atlas_forge/model_preferences.json` | Sí |
| Sesión, agentes, Jobs | En la memoria de `atlas-forge-api` | No |
| Informes de cierre | `07-informes/<US>/<job_id>.md` | Sí (ficheros) |
| Backlog | `02-backlog/` del proyecto activo | Sí (archivos Markdown) |

## Detalle de módulos

### Sesión de desarrollo (`atlas_forge/core/`)

Una sesión es un entorno de trabajo persistente sobre un proyecto. Estados: `created` → `active` → `closed`. Se crea al seleccionar un proyecto y se cierra al cambiar de proyecto (deteniendo antes los agentes no detenidos).

### Runtimes (`atlas_forge/runtime/`)

Cada agente lanzado es una **instancia de runtime** en su propia sesión de tmux (`runtime/agent_model.py`):
- **Claude Code**: `claude --dangerously-skip-permissions [--model <model>]` + prompt como argumento posicional.
- **OpenCode**: `opencode --auto [--model provider/model]` + `--prompt "..."`.
- **Codex**: `codex -a never -s workspace-write [--model <model>]` + prompt como argumento posicional.

El `agent_runtime_registry` mapea `agent_id → RuntimeInstance`. El liveness se comprueba de forma perezosa al consultarlo (sin polling).

### Agentes (`atlas_forge/agents/`)

Roles registrados: `developer`, `arquitecto`, `tester`, `documentador`, `ux`, `auditor_oss`. Cada rol define un prompt base + archivo de gobernanza + función de registro. Ver [Agentes](agents.md).

### Dispatcher (`atlas_forge/dispatcher/`)

- **Job**: `create → running → {completed | failed | cancelled}`. El reporte de resultados es **cooperativo**: el agente escribe su resultado en un fichero temporal más un marcador final; el dispatcher espera ese fichero.
- **Encadenamiento**: `previous_job` inyecta literalmente el resultado del Job anterior en la descripción del Job siguiente. Developer→Developer está bloqueado (debe pasar por el Arquitecto).
- **Pipeline de backlog**: un único worker en segundo plano sondea cada 5 segundos e impulsa cada ítem puramente por su `state` — encola Tasks `READY` como `TO_DEVELOP`, asigna una Task `TO_DEVELOP` a un Developer (`IN_PROGRESS`), entrega una Task en `IN_REVIEW` a un Tester libre, devuelve la misma Task al mismo Developer como retrabajo si el Tester la falla, una User Story con todas sus Tasks `DONE` a un Arquitecto libre para su validación final, y una US `TO_PLAN` a un Arquitecto libre para su aterrizaje US→Tasks. Ver [Jobs y el pipeline de trabajo](jobs.md#el-pipeline-de-backlog).
- **Scribe automático**: el dispatcher decide invocar Scribe (por tamaño de descripción > 4000 caracteres o ≥ 10 Jobs consecutivos) para pre-procesar contexto, ahorrando tokens de runtimes remotos.
- **Veredicto**: en una User Story en `IN_REVIEW` (todas sus Tasks `DONE`), el Arquitecto asignado emite `APROBADO` / `APROBADO_CON_OBSERVACIONES` / `RECHAZADO`; aprobada mueve la Story a `DONE`, rechazada añade una nueva Task a la misma Story en lugar de promoverla.
- **Cola de despacho y escalado**: mantiene una cola por proyecto (`dispatch_queue.json`) como registro FIFO/auditoría (la elegibilidad la decide el `state` real), y puede escalar/liberar agentes autónomamente según la demanda (`autonomous_scaling.py`).

### Backlog (`atlas_forge/backlog/`)

Parser determinista de `02-backlog/` (Epics, User Stories, Tasks) → un grafo de ítems con estado, dependencias, prioridad y versión de entrega. Informe de estado (`build_backlog_report`) con conteos por Epic, ítems LISTA/BLOQUEADA, cadena de máximo apalancamiento y grado de desbloqueo. Validador de esquema para el formato de backlog. La fuente de verdad de estados y transiciones es `core/state_machines.py` (AF-040).

### API (`atlas_forge/api/`)

FastAPI con endpoints REST + WebSocket `/ws/jobs`, `/ui/` estático y `/health`. Ver [API](api.md).

## Estructura de directorios

```text
PROD-006-atlas-forge/
├── 00-gobierno/       # gobernanza del proyecto (METODOLOGIA, roles)
├── 02-backlog/        # backlog canónico: epics/, user-stories/, tasks/, roadmap.md
├── 04-src/            # código fuente (paquete atlas_forge) y tests
├── 07-informes/       # informes de cierre de Jobs y análisis
├── 10-web/            # interfaz web (servida por atlas-forge-api en /ui/)
└── deploy/            # unidades systemd
```

## Aislamiento de módulos

El proyecto verifica por test (`04-src/tests/test_module_boundaries.py`) que los clientes no acceden al dominio directamente salvo excepciones acotadas y documentadas (catálogo estático de agentes, configuración de disco local). Una interfaz sin proceso local (web) depende completamente de la API.