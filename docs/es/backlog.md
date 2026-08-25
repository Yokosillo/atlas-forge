# Backlog y pipeline centrado en el backlog

Atlas Forge trata el **backlog** (`02-backlog/` del proyecto activo) como una fuente estructurada y consultable: lo parsea, lo valida, genera informes de estado y permite **generar** Epics→User Stories→Tasks y **conducir su desarrollo** desde la interfaz. El backlog es el **panel de control central**: todo el trabajo se despliega desde aquí, no escribiendo Markdown a mano ni conversando con cada agente por separado.

## Esquema del backlog

Estructura canónica (ver `02-backlog/README.md`): Roadmap → Epic (`AF-NNN`) → User Story (`US-AFNNN-nn`) → Task (`T-AFNNN-USnn-mm`). Cada fichero es **frontmatter YAML + cuerpo Markdown**: el bloque frontmatter (delimitado por `---`) contiene los campos estructurados, el cuerpo Markdown contiene prosa libre (`## Objetivo`, `## Criterios de aceptación`, etc.).

Campos comunes del frontmatter: `id`, `type` (`epic | user_story | task`), `title`, `state`, `dependencies` (una lista YAML de IDs — sin markup en negrita, sin texto libre). Opcionales: `priority` (User Story/Task), `version` (versión de entrega de la User Story, p. ej. `0.9`). Las User Stories y Tasks también llevan `epic` (y las Tasks además `user_story`) apuntando a su padre.

`state` de Task: `READY | TO_DEVELOP | IN_PROGRESS | IN_REVIEW | DONE` (una Task **nunca** puede tener `OUT_OF_SCOPE`). `state` de User Story: estados propios iniciales `NO_TASKS | TO_PLAN`; una vez creadas sus Tasks, el estado es **derivado** (la Task menos avanzada, `READY` < `TO_DEVELOP` < `IN_PROGRESS` < `IN_REVIEW` < `DONE`), y con todas sus Tasks `DONE` la US pasa a `IN_REVIEW` pendiente de la validación del Arquitecto antes de `DONE`. `OUT_OF_SCOPE` es exclusivo de User Story — ver [Jobs y el pipeline de trabajo](jobs.md#el-pipeline-de-backlog) para qué significa cada estado y cómo mueve el Dispatcher los ítems por ellos. La fuente de verdad del vocabulario de estados y transiciones es `core/state_machines.py` (AF-040).

El esquema de versiones vive en `.atlas-forge/version.yml`: cada User Story declara a qué versión pertenece (`version:`), y las Epics se versionan igualmente. `version` es el campo canónico de entrega (en lugar del anterior `fase`).

## Parser determinista (`atlas_forge/backlog/parser.py`)

- Extrae por fichero: id, type, `state`, `dependencies` (parseadas directamente de la lista YAML), prioridad, `version`, dificultad, referencias al padre — todo leído del frontmatter, sin regex sobre Markdown de forma libre.
- `load_backlog(backlog_path) → BacklogGraph`: parsea los tres subdirectorios; los ficheros malformados se recogen en `graph.errors` sin abortar el resto.
- `classify_todo_items(graph)`: divide los ítems listos (READY) en **LISTA** (todas las dependencias DONE) y **BLOQUEADA** (alguna dependencia pendiente/ausente).
- `calculate_unblock_degree(graph, epic)`: ratio de US/Tasks de un Epic cuyas dependencias están todas resueltas (base del mapa de calor).
- `find_max_leverage_chain(graph)`: la cadena [raíz + cascada] que desbloquea más ítems.

## Informe de estado (`atlas_forge/backlog/report.py`)

`build_backlog_report(backlog_path) → dict` (serializable a JSON):

- `empty` / `total` (conteos por tipo y estado + errores).
- `by_epic` (por Epic: conteos de US/Task + `unblock_degree` + `version`).
- `items_lista` (READY LISTA ordenados por prioridad) y `items_bloqueada` (con `blocking_dependencies`).
- `max_leverage_chain`.
- `errors`.

Accesible por dos rutas equivalentes: `GET /backlog` y el script genérico `backlog_status`. Ordenación determinista: `(priority, id)`.

## Detalle de ítem (`atlas_forge/backlog/detail.py`)

`GET /backlog/{item_id}` devuelve el detalle por sección (`## Objetivo`/`## Historia`, `## Criterios de aceptación`, dependencias con su estado). Para una User Story incluye sus Tasks y (AF-024-US09) el historial de ejecución (Jobs) de esa Story. Los IDs del tipo `AF-xxx` se resuelven como Epic.

## Validador de formato (`atlas_forge/backlog/validator_v2.py`)

Validador de esquema determinista para el formato del frontmatter YAML: campos de frontmatter obligatorios por tipo (`id`, `type`, `title`, `state`, `dependencies`, más `epic`/`user_story` donde aplique), conjunto de `state` cerrado, IDs de dependencias bien formados, id coincidiendo con el prefijo del nombre de fichero. `ValidationResultV2{valid, errors}`.

## Pipeline centrado en el backlog

Mecanismo para generar y ejecutar trabajo por el Arquitecto, sin escribir Markdown a mano.

### Generador Epic→User Story→Task (`atlas_forge/architect/`)

Flujo del Arquitecto con **validador determinista obligatorio + auto-auditoría**:

1. **Proponer User Stories** (`propose_user_stories.py`): carga el contexto de un Epic (objetivo, alcance v1, diferido a v2, dependencias).
2. **Pipeline de US** (`us_pipeline.py`): valida formato → auto-auditoría con vista externa → aprobación humana → escritura de los ficheros `US-*.md`, nacidos en `NO_TASKS`. Veredictos `APROBADO | APROBADO_CON_OBSERVACIONES | RECHAZADO`.
3. **Revisión de brechas** (`review_user_story.py`): detecta secciones faltantes, historias vacías, criterios ausentes; `ready_for_tasks` si no hay brechas.
4. **Proponer Tasks** (`propose_tasks.py`): solo para una User Story en `TO_PLAN`; genera `T-*.md` y a partir de ahí la US pasa a reflejar el estado derivado de sus Tasks (la menos avanzada).
5. **Pipeline de Tasks** (`task_pipeline.py`): validación + auto-auditoría + escritura.

Los comentarios humanos sobre una US se procesan como ajustes dirigidos (`architect/comments.py`).

### Conducir una User Story a través del Dispatcher

Una vez que una User Story tiene Tasks, el único botón **"Progresar"** ya no es necesario: la Story refleja automáticamente el estado de sus Tasks, y el Dispatcher las encola en `TO_DEVELOP`, las entrega a Developers en `IN_PROGRESS`, las verifica con el Tester en `IN_REVIEW` y, cuando todas están `DONE`, la US pasa a `IN_REVIEW` pendiente de la validación final del Arquitecto — ver [Jobs y el pipeline de trabajo](jobs.md#el-pipeline-de-backlog) para la máquina de estados completa (implementación → revisión de Task por el Tester → validación final de Story por el Arquitecto). `POST /backlog/{story_id}/launch-development` sigue disponible como alternativa directa de Job aislado que construye un Job a partir del objetivo de la Story y los títulos de las Tasks pendientes y lo despacha a un Developer elegido (400 si no hay Tasks pendientes).

### Contrato del Tester (`dispatcher/tester_input.py`)

Empaqueta la entrada de un Job de Tester: criterios de aceptación de la Task + `git diff HEAD` + archivos cambiados + informe del Developer — verificación funcional únicamente, nunca juicio de alcance o arquitectura.

## En las interfaces

- **Web**: pestaña Backlog — toggle Lista/Por-Versión, mapa de calor por Epic (`unblock_degree`), badge global de pendientes, diferenciación visual de estados, desglose Epic→US→detalle con dependencias (bloqueo de lanzamiento), historial de ejecución por US, el flujo "Progresar" y formularios de creación (incluida la creación desde lenguaje natural con la cola de peticiones al Arquitecto).

## Creación de items

Además del generador Epic→US→Task del Arquitecto, el backlog se puede ampliar desde la web:

- **Formularios directos**: `POST /backlog/epic`, `POST /backlog/epic/{epic_id}/us`, `POST /backlog/us/{us_id}/task` crean items con formato validado.
- **Desde lenguaje natural**: `POST /backlog/epic/from-description`, `POST /backlog/epic/{epic_id}/from-description-us` y `POST /backlog/us/{us_id}/from-description-task` envían una petición de creación a una **cola de peticiones** (`creation_queue.py`); el Arquitecto la procesa y escribe el item. El estado de las peticiones se consulta en `GET /backlog/creation-requests`.

## Análisis de hilos de desarrollo paralelizables

`atlas_forge/backlog/dependency_graph.py` calcula, para un Epic, qué grupos de US/Tasks son mutuamente independientes (hilos paralelizables) y en qué orden abordarlos, basándose en el grafo de dependencias real — para que el desarrollo pueda dividirse entre varios Developers con una base real en lugar de suposiciones. Expuesto como `POST /backlog/epic/{epic_id}/analyze-threads` (acepta el número de agentes objetivo como query param); el resultado se persiste como informe.

## Auditoría del backlog contra el código

Dos acciones transversales de proyecto auditan el backlog frente al código real (ver [Acciones](interfaces-web.md#acciones-transversales)):
- `auditar-backlog`: el Arquitecto cruza el `## Estado` declarado de cada item contra la evidencia real del código y persiste un informe con fecha en `07-informes/`.
- `verificar-auditoria`: el rol Auditor-OSS verifica cada hallazgo del paso anterior y emite una acción concreta por hallazgo (`corregir_estado` / `crear_task_correccion` / `descartar`).

## Planificado (no implementado)

- **Generador Epic→US completo en el producto**: el pipeline genera User Stories y Tasks con validador + auto-auditoría; la generación de contenido para Epics enteros está esbozada como scaffolding.