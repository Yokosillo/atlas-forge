# Backlog y pipeline backlog-céntrico

Factory Brain trata el **backlog** (`02-backlog/` del proyecto activo) como una fuente estructurada y consultable: lo parsea, lo valida, genera informes de estado y, en Fase 1.0, permite **generar** Epics→User Stories→Tasks y **lanzar su desarrollo** desde la interfaz.

## Esquema del backlog

Estructura canónica (ver `02-backlog/README.md`): Roadmap → Epic (`FB-NNN`) → User Story (`US-FBNNN-nn`) → Task (`T-FBNNN-USnn-mm`). Cada fichero tiene secciones obligatorias por tipo y un campo `## Estado` con valores cerrados `TODO | IN_PROGRESS | REVIEW | DONE`. Campos opcionales: `## Fase` (perteneciente a una Fase del roadmap) y `## Bugs encontrados` (Tasks).

## Parser determinista (`brain/backlog/parser.py`)

- Extrae por fichero: id (del prefijo del nombre), tipo, estado (`## Estado`), dependencias (`## Dependencias` con formato `**ID**`), prioridad, fase.
- `load_backlog(backlog_path) → BacklogGraph`: parsea los tres subdirectorios; los ficheros malformados se recogen en `graph.errors` sin abortar el resto.
- `classify_todo_items(graph)`: separa los items TODO en **LISTA** (todas sus dependencias DONE) y **BLOQUEADA** (alguna dependencia pendiente/ausente).
- `calculate_unblock_degree(graph, epic)`: ratio de US/Tasks de una Epic cuyas dependencias están todas resueltas (base del mapa de calor).
- `find_max_leverage_chain(graph)`: la cadena [raíz + en cascada] que desbloquea más items.

## Informe de estado (`brain/backlog/report.py`)

`build_backlog_report(backlog_path) → dict` (JSON-serializable):

- `empty` / `total` (conteos por tipo y estado + errores).
- `by_epic` (por Epic: conteos US/Task + `unblock_degree` + `fase`).
- `items_lista` (TODO LISTA ordenados por prioridad) y `items_bloqueada` (con `blocking_dependencies`).
- `max_leverage_chain`.
- `errors`.

Accesible por tres vías equivalentes: `GET /backlog`, script genérico `backlog_status`, y CLI `brain backlog-status <path> [--json]`. Orden determinista: `(prioridad, id)`.

## Detalle de item (`brain/backlog/detail.py`)

`GET /backlog/{item_id}` devuelve el detalle por sección (`## Objetivo`/`## Historia`, `## Criterios de aceptación`, dependencias con su estado). Para una User Story incluye sus Tasks y (FB-024-US09) el historial de ejecuciones (Jobs) de esa Story. Los IDs tipo `FB-xxx` se resuelven como Epic.

## Validador de formato (`brain/backlog/validator.py`)

Validador determinista del esquema: formato de título, secciones internas en H2, secciones obligatorias por tipo, campos de referencia (`**Epic:**`, `**User Story:**`), formato de `## Estado`, formato de `## Dependencias`. Usado como red de seguridad por los generadores del Arquitecto. `ValidationResult{valid, file_type, errors}`.

## Pipeline backlog-céntrico (Fase 1.0, FB-022)

Mecanismo de generación y ejecución del trabajo por el Arquitecto, sin escribir Markdown a mano.

### Generador Epic→User Story→Task (`brain/architect/`)

Flujo del Arquitecto con **validador determinista + autoauditoría obligatoria**:

1. **Proponer User Stories** (`propose_user_stories.py`): carga el contexto de una Epic (objetivo, alcance v1, diferido a v2, dependencias).
2. **Pipeline US** (`us_pipeline.py`): valida formato → autoauditoría con visión externa → aprobación humana → escritura de ficheros `US-*.md`. Veredictos `APROBADO | APROBADO_CON_OBSERVACIONES | RECHAZADO`.
3. **Revisión de huecos** (`review_user_story.py`): detecta secciones faltantes, historias vacías, criterios ausentes; `ready_for_tasks` si no hay huecos.
4. **Proponer Tasks** (`propose_tasks.py`): solo si la US está lista; genera `T-*.md`.
5. **Pipeline Tasks** (`task_pipeline.py`): validación + autoauditoría + escritura.

Los comentarios del humano a una US se procesan como ajustes dirigidos (`architect/comments.py`).

### Lanzar desarrollo de una User Story

`POST /backlog/{story_id}/launch-development` construye el Job desde la historia real + títulos de las Tasks `TODO` pendientes y lo despacha al Developer indicado. 400 si no hay Tasks pendientes.

### Verdictos Developer→Arquitecto

Tras un plan despachado, la **cola FIFO de veredictos** encola un Job al Arquitecto que emite `APROBADO`/`APROBADO_CON_OBSERVACIONES`/`RECHAZADO`. Si se aprueba, las Tasks pasan a `DONE`; si se rechaza, se persiste `_rechazo.md`. Ver [Jobs y planes](jobs.md#veredicto-automatico-del-pipeline-fb-022).

### Contrato del Tester (`dispatcher/tester_input.py`)

Empaqueta la entrada de un Job de Tester: criterios de aceptación de las Tasks + `git diff HEAD` + ficheros cambiados + informe del Developer. El rol Tester no está registrado todavía (solo el contrato).

## En las interfaces

- **Web**: pestaña Backlog — toggle Lista/Por Fase, mapa de calor por Epic (`unblock_degree`), badge global de pendientes, diferenciación visual DONE/TODO, desglose Epic→US→detalle con dependencias (bloqueo de lanzamiento), historial de ejecuciones por US y "Lanzar desarrollo".
- **TUI**: pantalla Backlog de 3 niveles con colores Rich y barras de progreso.
- **App Android**: pantalla Backlog con listado/detalle y lanzar desarrollo.

## Planificado (no implementado)

- **Generador Epic→US** completo en el producto (el pipeline actual valida el formato del esquema; la generación de contenido está esbozada como scaffolding).
- **Análisis de hilos de desarrollo paralelizables** (FB-026): análisis de grafo de dependencias por Epic con niveles topológicos y recomendación de reparto entre varios Developer. El módulo `brain/backlog/dependency_graph.py` existe en el código, pero **no tiene Tasks DONE ni interfaz que lo exponga** — se documenta como planificado.
