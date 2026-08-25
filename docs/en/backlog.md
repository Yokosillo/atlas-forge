# Backlog and backlog-centric pipeline

Atlas Forge treats the **backlog** (`02-backlog/` of the active project) as a structured, queryable source: it parses it, validates it, generates status reports and allows **generating** Epics→User Stories→Tasks and **driving their development** from the interface. The backlog is the **central control panel**: all work is deployed from here, not by writing Markdown by hand or conversing with each agent separately.

## Backlog schema

Canonical structure (see `02-backlog/README.md`): Roadmap → Epic (`AF-NNN`) → User Story (`US-AFNNN-nn`) → Task (`T-AFNNN-USnn-mm`). Each file is **YAML frontmatter + Markdown body**: the frontmatter block (delimited by `---`) holds the structured fields, the Markdown body holds free prose (`## Objetivo`, `## Criterios de aceptación`, etc.).

Common frontmatter fields: `id`, `type` (`epic | user_story | task`), `title`, `state`, `dependencies` (a YAML list of IDs — no bold markup, no free text). Optional: `priority` (User Story/Task), `version` (delivery version of the User Story, e.g. `0.9`). User Stories and Tasks also carry `epic` (and Tasks additionally `user_story`) pointing to their parent.

Task `state`: `READY | TO_DEVELOP | IN_PROGRESS | IN_REVIEW | DONE` (a Task can **never** be `OUT_OF_SCOPE`). User Story `state`: initial own states `NO_TASKS | TO_PLAN`; once its Tasks are created, the state is **derived** (the least advanced Task, `READY` < `TO_DEVELOP` < `IN_PROGRESS` < `IN_REVIEW` < `DONE`), and with all its Tasks `DONE` the US moves to `IN_REVIEW` pending Architect validation before `DONE`. `OUT_OF_SCOPE` is exclusive to User Stories — see [Jobs and the work pipeline](jobs.md#the-backlog-pipeline) for what each state means and how the Dispatcher moves items through them. The source of truth for the state vocabulary and transitions is `core/state_machines.py` (AF-040).

The version scheme lives in `.atlas-forge/version.yml`: each User Story declares which version it belongs to (`version:`), and Epics are versioned likewise. `version` is the canonical delivery field (in place of the previous `fase`).

## Deterministic parser (`atlas_forge/backlog/parser.py`)

- Extracts per file: id, type, `state`, `dependencies` (parsed directly from the YAML list), priority, `version`, difficulty, parent references — all read from the frontmatter, no regex over free-form Markdown.
- `load_backlog(backlog_path) → BacklogGraph`: parses the three subdirectories; malformed files are collected in `graph.errors` without aborting the rest.
- `classify_todo_items(graph)`: splits ready (READY) items into **LISTA** (all dependencies DONE) and **BLOQUEADA** (some pending/missing dependency).
- `calculate_unblock_degree(graph, epic)`: ratio of a Epic's US/Tasks whose dependencies are all resolved (basis of the heat map).
- `find_max_leverage_chain(graph)`: the chain [root + cascade] that unlocks the most items.

## Status report (`atlas_forge/backlog/report.py`)

`build_backlog_report(backlog_path) → dict` (JSON-serializable):

- `empty` / `total` (counts per type and state + errors).
- `by_epic` (per Epic: US/Task counts + `unblock_degree` + `version`).
- `items_lista` (READY LISTA ordered by priority) and `items_bloqueada` (with `blocking_dependencies`).
- `max_leverage_chain`.
- `errors`.

Accessible by two equivalent paths: `GET /backlog` and the `backlog_status` generic script. Deterministic ordering: `(priority, id)`.

## Item detail (`atlas_forge/backlog/detail.py`)

`GET /backlog/{item_id}` returns the detail by section (`## Objetivo`/`## Historia`, `## Criterios de aceptación`, dependencies with their state). For a User Story it includes its Tasks and (AF-024-US09) the execution history (Jobs) of that Story. IDs of the type `AF-xxx` resolve as an Epic.

## Format validator (`atlas_forge/backlog/validator_v2.py`)

Deterministic schema validator for the YAML frontmatter format: required frontmatter fields per type (`id`, `type`, `title`, `state`, `dependencies`, plus `epic`/`user_story` where applicable), closed `state` set, dependency IDs well-formed, id matching the filename prefix. `ValidationResultV2{valid, errors}`.

## Backlog-centric pipeline

Mechanism to generate and execute work by the Architect, without writing Markdown by hand.

### Epic→User Story→Task generator (`atlas_forge/architect/`)

Architect flow with **mandatory deterministic validator + self-audit**:

1. **Propose User Stories** (`propose_user_stories.py`): loads an Epic's context (objective, v1 scope, deferred to v2, dependencies).
2. **US pipeline** (`us_pipeline.py`): validates format → self-audit with external view → human approval → writing `US-*.md` files, born in `NO_TASKS`. Verdicts `APROBADO | APROBADO_CON_OBSERVACIONES | RECHAZADO`.
3. **Gap review** (`review_user_story.py`): detects missing sections, empty stories, absent criteria; `ready_for_tasks` if there are no gaps.
4. **Propose Tasks** (`propose_tasks.py`): only for a User Story in `TO_PLAN`; generates `T-*.md` and from then on the US reflects the derived state of its Tasks (the least advanced one).
5. **Tasks pipeline** (`task_pipeline.py`): validation + self-audit + writing.

Human comments on a US are processed as targeted adjustments (`architect/comments.py`).

### Driving a User Story through the Dispatcher

Once a User Story has Tasks, the single **"Progresar"** button is no longer needed: the Story automatically reflects the state of its Tasks, and the Dispatcher queues them as `TO_DEVELOP`, hands them to Developers (`IN_PROGRESS`), verifies them with the Tester (`IN_REVIEW`) and, once all are `DONE`, the US moves to `IN_REVIEW` pending the Architect's final validation — see [Jobs and the work pipeline](jobs.md#the-backlog-pipeline) for the full state machine (implementation → Task review by the Tester → final Story validation by the Architect). `POST /backlog/{story_id}/launch-development` remains available as a direct, isolated-Job alternative that builds a Job from the Story's objective and pending Task titles and dispatches it to a chosen Developer (400 if there are no pending Tasks).

### Tester contract (`dispatcher/tester_input.py`)

Packages the input of a Tester Job: acceptance criteria of the Task + `git diff HEAD` + changed files + Developer report — functional verification only, never scope or architecture judgment.

## In the interfaces

- **Web**: Backlog tab — List/By-Version toggle, heat map per Epic (`unblock_degree`), global pending badge, state visual differentiation, Epic→US→detail breakdown with dependencies (launch blocking), execution history per US, the "Progresar" flow and creation forms (including natural-language creation with the Architect request queue).

## Item creation

Besides the Architect's Epic→US→Task generator, the backlog can be extended from the web:

- **Direct forms**: `POST /backlog/epic`, `POST /backlog/epic/{epic_id}/us`, `POST /backlog/us/{us_id}/task` create items with validated format.
- **From natural language**: `POST /backlog/epic/from-description`, `POST /backlog/epic/{epic_id}/from-description-us` and `POST /backlog/us/{us_id}/from-description-task` send a creation request to a **request queue** (`creation_queue.py`); the Architect processes it and writes the item. Request state is queried via `GET /backlog/creation-requests`.

## Parallelizable development thread analysis

`atlas_forge/backlog/dependency_graph.py` computes, for an Epic, which groups of US/Tasks are mutually independent (parallelizable threads) and in what order to tackle them, based on the real dependency graph — so development can be split across several Developers with an actual basis instead of guesswork. Exposed as `POST /backlog/epic/{epic_id}/analyze-threads` (accepts the number of target agents as a query param); the result is persisted as a report.

## Backlog audit against the code

Two cross-cutting project actions audit the backlog against the real code (see [Actions](interfaces-web.md#cross-cutting-actions)):
- `auditar-backlog`: the Architect crosses the declared `## Estado` of each item against the real code evidence and persists a dated report in `07-informes/`.
- `verificar-auditoria`: the Auditor-OSS role verifies each finding of the previous step and issues a concrete action per finding (`corregir_estado` / `crear_task_correccion` / `descartar`).

## Planned (not implemented)

- **Full Epic→US generator in the product**: the pipeline generates User Stories and Tasks with validator + self-audit; content generation for entire Epics is sketched as scaffolding.
