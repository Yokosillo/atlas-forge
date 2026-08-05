# Factory Brain

**AI-assisted software development coordination from a single platform.**

Factory Brain is the operating system of an AI-based development factory. It coordinates projects, agents, runtimes, Jobs and work pipelines, keeping operational context alive across the whole development cycle.

It is not an IDE. It is not an agent framework. It does not replace the developer's decision-making: it coordinates *who* does *what* and *when*, and agents execute with their own runtimes and models.

## How it works in 30 seconds

1. **Discovers** the Git repositories in your workspace automatically.
2. **Selects** an active project (a single development session per project).
3. **Uses the backlog as the control panel**: work is deployed from the backlog (Epic → User Story → Task → Implement) with buttons, not by writing Markdown by hand or talking to each agent separately.
4. **Runs the pipeline**: the Director converses about Epics, the Architect decomposes them into User Stories and Tasks and emits verdicts, and the Developer implements them. A single human approval dispatches a whole sequence of Jobs.
5. **Sends Jobs** to an agent and **chains** results (Developer → Architect); you can also **cancel** in-flight work.
6. **Automates the repetitive** with deterministic scripts (commit, push, tests, backlog status) and delegates reads/summaries to **Scribe**, a local model (Ollama) that does not consume tokens from your remote runtimes.

Everything is operated from **three clients** that consume a single HTTP/WebSocket API: the **web interface** (recommended, main interface since 2026-08-04), the **terminal TUI** and the **Android app**.

## What problem it solves

Developing with AI today requires keeping several Claude Code sessions open, launching processes with tmux, using OpenCode for certain models, switching between projects and rebuilding context by hand on every task. Each tool keeps its own state; knowledge ends up scattered; time is lost and more tokens are consumed than necessary.

Factory Brain centralizes that flow: the active project, the live session, the launched agents, the Job history, the plans, the scripts and the backlog state all live in a single process (`brain-api`) to which any interface connects.

## Design principles

| Principle | What it means |
|---|---|
| **Coordination over execution** | Factory Brain coordinates; agents execute with their own runtimes and models. The system does not generate code directly. |
| **Deterministic automation first** | Deterministic scripts → local automations → local model (Ollama) → remote model. Never an LLM for something a script can do. |
| **Persistent context** | The session keeps the project, agents, runtimes, history and context. Agents are not destroyed when a Job finishes. |
| **Backlog-centric pipeline** | The backlog is the central control panel: all work is deployed from it, not from scattered manual commands. |
| **Capability-based architecture** *(in backlog)* | The Dispatcher asks for capabilities, not specific models. The Capability Engine (FB-010) is planned, not implemented. |
| **One process, three clients** | Web, TUI and Android consume the same API; the domain does not belong to any client. |

## Project status

See the [roadmap](roadmap.md) for full detail.

- **Phases 0.1 to 0.4: complete.** Workspace, Session, Runtime (Claude Code and OpenCode), Agents, manual Dispatcher (Jobs, chaining, plans, cancellation), Scribe, backend API, Android app, generic scripts, TUI, backlog management and web interface.
- **Phase 1.0 (backlog-centric pipeline): in progress.** Director/Architect roles and Epic→US→Task generators are implemented (Tasks DONE); the Epic files have not yet been updated to `DONE` (a backlog metadata discrepancy noted in the [roadmap](roadmap.md#status-by-epic)).
- **Planned, not implemented:** Context Engine (FB-006), Knowledge Engine (FB-007), Capability Engine (FB-010), Plugin System (FB-011), Automation Engine (FB-009/012), Config Management (FB-013), lifecycle supervision (FB-023), thread analysis (FB-026). **There is no plugin system or MCP yet.**

## Getting started

- [Getting started](getting-started.md) — requirements, installation, running and testing.
- [Concepts](concepts.md) — project, session, agent, Job, plan.
- [Architecture](architecture.md) — system design with diagrams.

## Documentation

| Section | Content |
|---|---|
| [Web interface](interfaces-web.md) | The main interface: Roles, Plan, Scripts, Backlog, Models, Actions. |
| [TUI](interfaces-tui.md) | Terminal client (Textual). |
| [Android app](interfaces-android.md) | Remote client. |
| [API](api.md) | Complete REST + WebSocket reference. |
| [Agents](agents.md) | Roles, launching, lifecycle, governance. |
| [Runtime and Scribe](runtime.md) | Claude Code, OpenCode, tmux, Scribe/Ollama. |
| [Jobs and plans](jobs.md) | Job lifecycle, chaining, Architect plans. |
| [Scripts](scripts.md) | Generic and project-specific scripts. |
| [Backlog and pipeline](backlog.md) | Backlog management, validator, Epic→US→Task generators. |
| [Configuration](configuration.md) | `models.yml`, `scripts.yml`, model preferences. |
| [CLI](cli.md) | The `brain` CLI commands. |
| [Roadmap](roadmap.md) | Phases, status by Epic, backlog hold. |
| [FAQ and troubleshooting](faq.md) | Frequently asked questions and problem solving. |
| [Development](development.md) | Guide for new developers. |

## Repository

- Code: [`04-src/`](https://github.com/factoria-software/factory-brain/tree/main/04-src) — the `brain` Python package.
- Canonical backlog: [`02-backlog/`](https://github.com/factoria-software/factory-brain/tree/main/02-backlog).
- Internal project documentation: [`01-documentacion/`](https://github.com/factoria-software/factory-brain/tree/main/01-documentacion) (may be outdated; the `/docs` of this site are the public source).
