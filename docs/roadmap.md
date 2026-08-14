# Roadmap

Real state of Factory Brain contrasted against `02-backlog/` (canonical states) and `07-informes/` (closing reports). This document is the public view of the [canonical roadmap](https://github.com/factoria-software/factory-brain/blob/main/02-backlog/roadmap.md) of the project.

## Summary by phase

| Phase | Content | State |
|---|---|---|
| **0.1** | First functional product: Workspace, Session, Runtime, Agents, manual Dispatcher (Jobs + chaining) | ✅ Complete |
| **0.2** | Multi-runtime/multi-model and token saving: unified TUI, Scribe, automatic Scribe triggering | ✅ Complete |
| **0.3** | Critical-dispatcher and remote access: Architect plan with single approval, backend API, Android app, Job/Plan cancellation, confirmations | ✅ Complete |
| **0.4** | Generic and project scripts: 7-script catalog, Scribe indexing | ✅ Complete |
| **1.0** | Backlog-centric pipeline: Director/Architect roles, Epic→US→Task generators, validator, verdicts, web UX improvements, cross-cutting actions | 🔶 In progress |
| **0.5–0.9** | Dispatcher v2, Capabilities, Context, Knowledge, Automation, Plugins, remaining Dashboard | ⬜ Planned |
| — | Config Management (FB-013) | ⏸️ On hold (backlog hold) |

## Status by Epic

Source: the `state` frontmatter field of each Epic in `02-backlog/epics/` (canonical) crossed with DONE Tasks and closing reports.

### DONE (implemented and operational)

| Epic | What it includes |
|---|---|
| **FB-001** Workspace Management | Git repo discovery, persisted active project, project scripts. |
| **FB-002** Dashboard | Unified TUI (Workspace/Dashboard/Agents), choose agent/runtime/model. |
| **FB-003** Development Session | Live session during execution, assigned agents. |
| **FB-004** Runtime Manager | Claude Code and OpenCode in tmux, model switching (OpenCode). |
| **FB-005** Agent Manager | Developer and Critic roles, two-layer prompts, liveness. |
| **FB-008** Dispatcher | Jobs, chaining, plans with approval, cancellation, automatic Scribe. |
| **FB-014** Local Tools | Scribe: local summarization/indexing (Ollama), including the `index_scripts` operation. |
| **FB-016** API Backend | FastAPI: agents, Jobs, plans, backlog, scripts, WebSockets, static `/ui/`, systemd. |
| **FB-017** Android App | Native app (Compose) — **paused** for new functionality (2026-08-04). |
| **FB-018** Generic Scripts | 7 generic scripts catalog + `backlog-status` CLI + Scribe prose. |
| **FB-019** TUI | Plan screen, cancel Job/Plan, confirmations, connectivity. |
| **FB-020** Backlog Management | Listing/detail endpoints, launch development, views in web/app/TUI. |
| **FB-021** Web Interface | Complete web: projects, agents, Jobs, plan, scripts, backlog, models. |
| **FB-026** Parallelizable thread analysis | `dependency_graph.py` module, `POST /backlog/epic/{epic_id}/analyze-threads` endpoint, "Generar hilos de desarrollo" button in the web Backlog tab. |

### Phase 1.0 — mostly DONE at Epic level

| Epic | Tasks | What it provides |
|---|---|---|
| **FB-022** Backlog-centric Pipeline | 34/34 DONE (US-FB022-13, 3 Tasks, still TODO) | Director/Architect roles, Epic→US→Task generators with validator+self-audit, verdicts, FIFO queue, file model catalog, Tester contract. |
| **FB-024** Web UX improvements | 23/23 DONE | DONE/TODO visual differentiation, badge, dependency blocking, Phase field, heat map, roles screen, US-detail history. |
| **FB-025** Cross-cutting actions | 10/12 DONE (US01–07) | Web actions: document, analyze-architecture, suggest-ideas, test, audit-ux, index. |

!!! note "FB-025 pending"
    `US-FB025-08` (audit OSS, 2 Tasks) is **TODO**: not implemented. The decision on `US-FB025-05` (Commit button) was **not to expose it**: commit already exists as a generic script.

### Planned, not implemented

| Epic | Notes |
|---|---|
| **FB-006** Context Engine | No Tasks. Planned (Phase 0.6). |
| **FB-007** Knowledge Engine | No Tasks. Planned (Phase 0.6). |
| **FB-009** Automation Engine | No Tasks. Planned (Phase 0.7). |
| **FB-010** Capability Engine | No Tasks. Planned (Phase 0.5). Unlocks US-FB005-03. |
| **FB-011** Plugin System | No Tasks. **There is no plugin system nor MCP.** Planned (Phase 0.8). |
| **FB-012** Development Automations | No Tasks. Planned (Phase 0.7). |
| **FB-013** Configuration Management | **On hold** (backlog hold): reviewed when a real multi-user configuration need appears. |
| **FB-023** Lifecycle supervision | Not a priority (2026-08-05 decision). `persistent` flag, stuck detection, headless `opencode serve`. |

### Postponed / discarded

| Epic | Note |
|---|---|
| **FB-015** Remote access (SSH+tmux) | **Postponed** (discarded in principle, 2026-08-02): the need was resolved by FB-016/FB-017 (a real touch app). Kept for traceability, revisited only if a real need appears that FB-016/FB-017 don't cover. |

## Technical debt and relevant decisions

- **TUI/Android pause** (2026-08-04): all new functionality is exposed on the web. Active-model Tasks in the TUI (`T-FB019-US02-01`) and Android (`T-FB017-US07-01`) marked `POSTERGADA`.
- **In-memory state**: session, agents and Jobs live in the memory of the `brain-api` process. Session recovery after restart (`US-FB003-02`) is planned, not implemented.
- **Observability** (structured logging, metrics, tracing): no assigned phase, on backlog hold.

## Functionality criterion

Factory Brain is considered functional when it can: manage multiple projects, keep persistent sessions, administer agents on different runtimes, coordinate Jobs through pipelines, run automations, prepare context automatically, reuse knowledge, minimize remote-model usage, incorporate capabilities through plugins and provide operational vision.

**State today**: Job/plan coordination, multi-runtime/multi-model and token saving are real. Context/knowledge management, capabilities, plugins and the full declarative pipeline are future work.
