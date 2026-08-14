# Backlog and backlog-centric pipeline

Factory Brain treats the **backlog** (`02-backlog/` of the active project) as a structured, queryable source: it parses it, validates it, generates status reports and, in Phase 1.0, allows **generating** Epics→User Stories→Tasks and **launching their development** from the interface. The backlog is the **central control panel**: all work is deployed from here, not by writing Markdown by hand or conversing with each agent separately.

## Backlog schema

Canonical structure (see `02-backlog/README.md`): Roadmap → Epic (`FB-NNN`) → User Story (`US-FBNNN-nn`) → Task (`T-FBNNN-USnn-mm`). Since FB-027 (2026-08-06), each file is **YAML frontmatter + Markdown body**: the frontmatter block (delimited by `---`) holds the structured fields, the Markdown body holds free prose (`## Objetivo`, `## Criterios de aceptación`, etc.).

Common frontmatter fields: `id`, `type` (`epic | user_story | task`), `title`, `state` (closed set: `TODO | IN_PROGRESS | REVIEW | DONE | POSTERGADA`), `dependencies` (a YAML list of IDs — no bold markup, no free text). Optional: `priority` (User Story/Task), `fase`. User Stories and Tasks also carry `epic` (and Tasks additionally `user_story`) pointing to their parent.

## Deterministic parser (`brain/backlog/parser.py`)

- Extracts per file: id, type, `state`, `dependencies` (parsed directly from the YAML list), priority, phase, parent references — all read from the frontmatter, no regex over free-form Markdown.
- `load_backlog(backlog_path) → BacklogGraph`: parses the three subdirectories; malformed files are collected in `graph.errors` without aborting the rest.
- `classify_todo_items(graph)`: splits TODO items into **LISTA** (all dependencies DONE) and **BLOQUEADA** (some pending/missing dependency).
- `calculate_unblock_degree(graph, epic)`: ratio of a Epic's US/Tasks whose dependencies are all resolved (basis of the heat map).
- `find_max_leverage_chain(graph)`: the chain [root + cascade] that unlocks the most items.

## Status report (`brain/backlog/report.py`)

`build_backlog_report(backlog_path) → dict` (JSON-serializable):

- `empty` / `total` (counts per type and state + errors).
- `by_epic` (per Epic: US/Task counts + `unblock_degree` + `fase`).
- `items_lista` (TODO LISTA ordered by priority) and `items_bloqueada` (with `blocking_dependencies`).
- `max_leverage_chain`.
- `errors`.

Accessible by three equivalent paths: `GET /backlog`, the `backlog_status` generic script, and the `brain backlog-status <path> [--json]` CLI. Deterministic ordering: `(priority, id)`.

## Item detail (`brain/backlog/detail.py`)

`GET /backlog/{item_id}` returns the detail by section (`## Objetivo`/`## Historia`, `## Criterios de aceptación`, dependencies with their state). For a User Story it includes its Tasks and (FB-024-US09) the execution history (Jobs) of that Story. IDs of the type `FB-xxx` resolve as an Epic.

## Format validator (`brain/backlog/validator_v2.py`)

Deterministic schema validator for the YAML frontmatter format: required frontmatter fields per type (`id`, `type`, `title`, `state`, `dependencies`, plus `epic`/`user_story` where applicable), closed `state` set, dependency IDs well-formed, id matching the filename prefix. `ValidationResultV2{valid, errors}`.

## Backlog-centric pipeline (Phase 1.0, FB-022)

Mechanism to generate and execute work by the Architect, without writing Markdown by hand.

### Epic→User Story→Task generator (`brain/architect/`)

Architect flow with **mandatory deterministic validator + self-audit**:

1. **Propose User Stories** (`propose_user_stories.py`): loads an Epic's context (objective, v1 scope, deferred to v2, dependencies).
2. **US pipeline** (`us_pipeline.py`): validates format → self-audit with external view → human approval → writing `US-*.md` files. Verdicts `APROBADO | APROBADO_CON_OBSERVACIONES | RECHAZADO`.
3. **Gap review** (`review_user_story.py`): detects missing sections, empty stories, absent criteria; `ready_for_tasks` if there are no gaps.
4. **Propose Tasks** (`propose_tasks.py`): only if the US is ready; generates `T-*.md`.
5. **Tasks pipeline** (`task_pipeline.py`): validation + self-audit + writing.

Human comments on a US are processed as targeted adjustments (`architect/comments.py`).

### Launching a User Story's development

`POST /backlog/{story_id}/launch-development` builds the Job from the real story + pending `TODO` Task titles and dispatches it to the indicated Developer. 400 if there are no pending Tasks.

### Developer→Architect verdicts

After a dispatched plan, the **FIFO verdict queue** queues a Job to the Architect that emits `APROBADO`/`APROBADO_CON_OBSERVACIONES`/`RECHAZADO`. If approved, the Tasks become `DONE`; if rejected, `_rechazo.md` is persisted. See [Jobs and plans](jobs.md#automatic-pipeline-verdict-fb-022).

### Tester contract (`dispatcher/tester_input.py`)

Packages the input of a Tester Job: acceptance criteria of the Tasks + `git diff HEAD` + changed files + Developer report. The Tester role is not yet registered (only the contract).

## In the interfaces

- **Web**: Backlog tab — List/By-Phase toggle, heat map per Epic (`unblock_degree`), global pending badge, DONE/TODO visual differentiation, Epic→US→detail breakdown with dependencies (launch blocking), execution history per US and "Launch development".
- **TUI**: 3-level Backlog screen with Rich colors and progress bars.
- **Android app**: Backlog screen with listing/detail and launch development.

## Parallelizable development thread analysis (FB-026, implemented)

`brain/backlog/dependency_graph.py` computes, for an Epic, which groups of US/Tasks are mutually independent (parallelizable threads) and in what order to tackle them, based on the real dependency graph — so development can be split across several Developers with an actual basis instead of guesswork. Exposed as `POST /backlog/epic/{epic_id}/analyze-threads` (accepts the number of target agents as a query param) and as the "Generar hilos de desarrollo" button in the web Backlog tab (Epic detail, expandable). The result is persisted as a report.

## Planned (not implemented)

- **Full Epic→US generator in the product** (the current pipeline validates the schema format; content generation is sketched as scaffolding).
