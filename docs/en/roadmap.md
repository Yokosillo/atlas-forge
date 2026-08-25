# Roadmap

Real state of Atlas Forge contrasted against `02-backlog/` (canonical states) and `07-informes/` (closing reports). This document is the public view of the [canonical roadmap](https://github.com/factoria-software/atlas-forge/blob/main/02-backlog/roadmap.md) of the project.

## Version scheme

The version scheme lives in `.atlas-forge/version.yml`: each User Story declares which version it belongs to (`version:` in its frontmatter). The current open version is **0.9**; the planned future versions are **0.9.1** and **0.9.2**.

## State of version 0.9

Version 0.9 is the **backlog-centric pipeline**: the backlog is the product's central control panel and all work is deployed from it (Epic → User Story → Task → Implement) with buttons, not by writing Markdown by hand or talking to each agent separately.

### Implemented in 0.9

| Area | What it includes |
|---|---|
| **Backlog-centric pipeline** (AF-022) | Architect and Tester roles, Epic→US→Task generators with deterministic validator + self-audit, the state-driven Developer→Tester→Architect cycle, Task rework to the same Developer after a Tester `FALLO`. |
| **Structured backlog format** (AF-027) | YAML frontmatter + Markdown body for every Epic/User Story/Task; canonical `state` vocabulary for Task and User Story. |
| **Unified state machines** (AF-040) | `core/state_machines.py` as the single source of truth for states and legal Task/User Story transitions. |
| **Dispatch queue and pipeline viewer** (AF-042) | Per-project dispatch queue (`queued / dispatched / failed / completed`, plus derived `awaiting_tester`), Pipeline tab in the web showing the queue in real time. |
| **Simultaneous project sessions** (AF-029) | Multiple live sessions in parallel, one per project; switching the active project does not stop agents of other projects. |
| **Agent reconciliation on startup** (AF-031) | On `atlas-forge-api` startup, live tmux sessions are recognized by their deterministic name and re-registered as `idle` agents without relaunching their runtime. |
| **Live agent log in the web** (AF-032) | `WS /ws/agents/{agent_id}/pane`: one channel per connection, read-only, one agent at a time. |
| **Safe restart of Atlas Forge** (AF-037) | Duplicate-backend detection on startup, `POST /system/restart`, safe-restart procedure that does not kill the tmux server. |
| **Cross-cutting actions** (AF-025) | Web actions: document, analyze-architecture, suggest-ideas, test, audit-ux, audit-oss, audit-backlog, verify-audit, test-ui, index. |
| **Unified executable catalog** (AF-034) | `GET /scripts` combines generic scripts, project scripts and cross-cutting actions into a single catalog. |
| **Parallelizable thread analysis** (AF-026) | `dependency_graph.py` module, `POST /backlog/epic/{epic_id}/analyze-threads` endpoint. |
| **Unified version model** (AF-036) | `version` as the canonical delivery field (instead of `fase`), "By Version" view in the web, validator for the closed set `{0.9, 0.9.1, 0.9.2}`. |
| **Item creation from natural language** (AF-036) | `POST /backlog/epic/from-description`, `.../from-description-us`, `.../from-description-task` with a request queue for the Architect. |

### Operational base (DONE Epics)

| Epic | What it includes |
|---|---|
| **AF-001** Workspace Management | Git repo discovery, persisted active project, project scripts. |
| **AF-002** Control panel and supervision | Web interface as the only interface: projects, agents, Jobs, backlog. |
| **AF-014** Local Tools | Scribe: local summarization/indexing (Ollama), including the `index_scripts` operation. |
| **AF-016** API Backend | FastAPI: agents, Jobs, backlog, scripts, WebSockets, static `/ui/`, systemd. |
| **AF-018** Generic Scripts | 7 generic scripts catalog + Scribe prose. |
| **AF-020** Backlog Management | Listing/detail endpoints, launch development, views in the web. |
| **AF-021** Web Interface | Complete web: projects, agents, Jobs, scripts, backlog, models. |
| **AF-025** Cross-cutting actions | 10 project actions (see above). |
| **AF-026** Parallelizable thread analysis | See above. |
| **AF-029** Simultaneous project sessions | See above. |
| **AF-032** Live agent log | See above. |
| **AF-037** Safe restart | See above. |
| **AF-040** Unified state machines | See above. |

### Epics with DONE work pending formal promotion

| Epic | Note |
|---|---|
| **AF-022** Backlog-centric Pipeline | Nearly all User Stories DONE; the full pipeline is operational. |
| **AF-024** Web UX+Product improvements | Most User Stories DONE; improvements are added as real usage surfaces gaps. |
| **AF-030** Closing queue to the Architect | Implemented (append-only queue + watcher). |
| **AF-031** Agent reconciliation on startup | Implemented. |

## Planned, not implemented

### 0.9.1

| Epic | Notes |
|---|---|
| **AF-044** Operational auditor | Scope-directed or question-driven audit, finding persistence, history. |
| **AF-045** Investigator role | New role for on-demand investigation, integrated into the web. |
| **AF-046** Documenter integrated into the pipeline | Generic events → persistent jobs → queue → consumer agent mechanism, with the Documenter as first consumer. |
| **AF-047** Agent communication and control mode | Study and decision of tmux vs `opencode serve`/CLI for agent control. |
| **AF-048** Backlog response performance | Per-project `BacklogGraph` cache with `mtime` invalidation; faster YAML parser. |

### 0.9.2 and later

| Epic | Notes |
|---|---|
| **AF-006** Context Engine | Relevant-context preparation per Job. No Tasks. |
| **AF-007** Knowledge Engine | Reuse of project knowledge. No Tasks. |
| **AF-008** Dispatcher v2 | Pipeline with declarative dependencies, retries, automatic multi-agent coordination and capability resolution. |
| **AF-009** Automation Engine | Automation of repetitive operations. No Tasks. |
| **AF-010** Capability Engine | System capability catalog. No Tasks. |
| **AF-011** Plugin System | No Tasks. **There is no plugin system nor MCP.** |
| **AF-012** Development Automations | Development automations. No Tasks. |
| **AF-013** Configuration Management | On hold (backlog hold): only resumed with a real multi-user configuration need. |
| **AF-023** Lifecycle supervision | Automatic stuck-agent detection and recovery; configurable autonomous scaling. |
| **AF-028** Persistent control bar for critical agents | Existing Architect bar; extension to other agents not yet decomposed. |
| **AF-033** Real development cost per Task | Cost measurement per Task. |
| **AF-035** Creation of a new project | Create a project from scratch (not only select). |
| **AF-038** Documentation and reports in the web | Documentation and reports view in the web. |
| **AF-039** Integration with external systems | Integration with external work-management tools. |
| **AF-041** Observability and telemetry | Structured logging, metrics, analytics. |
| **AF-042** Pipeline viewer | Remaining scope (agent↔Jobs correlation, queue order and why). |
| **AF-043** Developer/Tester parallelism and rework | Tester test-planting, prioritized rework and telemetry events (basic rework already operational). |
| **AF-050** Pre-development design | Planning and architecture before development. Not decomposed. |

## Out of roadmap

| Epic | Note |
|---|---|
| **AF-015** Remote access (SSH+tmux) | Discarded: the web covers access from any device. |
| **AF-017** Native mobile app | Retired: the web is the only interface. |
| **AF-019** Terminal interface (TUI) | Retired: the web is the only interface. |
| **AF-049** Unify the version model | Deprecated: its scope was completed within 0.9 (`version` field and view). |

## Functionality criterion

Atlas Forge is considered functional when it can: manage multiple projects, keep persistent sessions, administer agents on different runtimes, coordinate Jobs through pipelines, run automations, prepare context automatically, reuse knowledge, minimize remote-model usage, incorporate capabilities through plugins and provide operational vision.

**Current state (0.9):** the state-driven backlog pipeline (Developer→Tester→Architect) with rework, multi-runtime/multi-model (Claude Code, OpenCode, Codex), token saving with Scribe and the web as the only interface are real and operational. Context/knowledge management, capabilities, plugins, telemetry and the full declarative pipeline are future work.
