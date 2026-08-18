# Factory Brain

**AI-assisted software development coordination from a single platform.**

Factory Brain is the operating system of an AI-based development factory. It coordinates projects, agents, runtimes, Jobs and work pipelines, keeping operational context alive across the whole development cycle.

It is not an IDE. It is not an agent framework. It does not replace the developer's decision-making: it coordinates *who* does *what* and *when*, and agents execute with their own runtimes and models.

## How it works in 30 seconds

1. **Discovers** the Git repositories in your workspace automatically.
2. **Selects** an active project (a single development session per project).
3. **Uses the backlog as the control panel**: work is deployed from the backlog (Epic → User Story → Task → Implement) with a single "Progresar" button per User Story, not by writing Markdown by hand or talking to each agent separately.
4. **Runs the pipeline**: the Architect lands Epics into User Stories and Tasks; a background Dispatcher then hands each Task to a free Developer, each closed Task to a free Tester for verification, and each fully-done Story to a free Architect for a final verdict — automatically, with no manual re-dispatch per step.
5. **Sends isolated Jobs** to a specific agent when you need one-off work outside the state-driven pipeline, and **chains** results (Developer → Architect); you can also **cancel** in-flight work.
6. **Automates the repetitive** with deterministic scripts (commit, push, tests, backlog status) and delegates reads/summaries to **Scribe**, a local model (Ollama) that does not consume tokens from your remote runtimes.

Everything is operated from a single HTTP/WebSocket API; the **web interface** is the primary client.

## What problem it solves

Developing with AI today requires keeping several Claude Code sessions open, launching processes with tmux, using OpenCode for certain models, switching between projects and rebuilding context by hand on every task. Each tool keeps its own state; knowledge ends up scattered; time is lost and more tokens are consumed than necessary.

Factory Brain centralizes that flow: the active project, the live session, the launched agents, the Job history, the scripts and the backlog state all live in a single process (`brain-api`) to which any interface connects.

## What Factory Brain really is

Factory Brain is a **coordination layer between defined work and the agents that execute it**. Its own vision statement is the clearest definition available: *"Factory Brain automates the execution of work, not the decisions about what work to do."*

The core concept is not the backlog and it is not the agents themselves — it is the **persistent development session**: agents that survive between jobs, carrying accumulated context, coordinated by a dispatcher, running on interchangeable runtimes. The backlog (Epic → User Story → Task) is the *language* used to describe work; Jobs and pipelines are the *mechanism* used to execute it.

**How it differs from a traditional project management tool:** Jira describes work for humans to do. Here the backlog is *executable* — a Task can go from a Markdown file to verified, tested code without a human writing a single line, with the system updating the backlog's own state on closure.

**How it differs from a coding agent:** Claude Code does the work but does not know what work exists, does not persist across sessions on its own, does not coordinate with other agents, and does not validate its own output. Factory Brain is the layer a coding agent needs to become a *factory* instead of a tool.

### Where it fits

- **It does not compete with Jira/Linear** — and it shouldn't try to. Its Markdown-file-plus-validator backlog model is functional, but it is the least differentiated part of the product.
- **It does not compete with Claude Code / Codex / OpenCode** — it consumes them as runtimes, which is exactly the right relationship.
- Its closest real neighbor is the emerging category of **coding-agent orchestrators** (Factory.ai, GitHub Copilot's coding agent, GitLab Duo). The observable difference: those are single-provider/single-runtime; Factory Brain is runtime-agnostic by design, and adds a verdict/validation layer (the Developer → Architect cycle) that those tools don't treat as a first-class concept.
- Natural integration points: upstream with work-management tools (importing issues), downstream with runtimes. Today there is no upstream integration — the entire backlog is native to the system.

### What is genuinely differential (with real evidence, not just design intent)

- **The adversarial verification cycle**: Developer implements → Architect independently verifies (re-running tests, reading the actual code, reproducing the result live) → structured verdict. This cycle has caught real bugs the Developer itself didn't see. None of the products above have this as a core mechanism.
- **"Deterministic first"**: format validators, state promotion, pre-commit hooks — the system spends LLM calls only where they add value. This is a real operating discipline verified in daily use, not a slogan.

## Design principles

| Principle | What it means |
|---|---|
| **Coordination over execution** | Factory Brain coordinates; agents execute with their own runtimes and models. The system does not generate code directly. |
| **Deterministic automation first** | Deterministic scripts → local automations → local model (Ollama) → remote model. Never an LLM for something a script can do. |
| **Persistent context** | The session keeps the project, agents, runtimes, history and context. Agents are not destroyed when a Job finishes. |
| **Backlog-centric pipeline** | The backlog is the central control panel: all work is deployed from it, not from scattered manual commands. |
| **Capability-based architecture** *(in backlog)* | The Dispatcher asks for capabilities, not specific models. The Capability Engine (FB-010) is planned, not implemented. |
| **One process, one client** | Web consumes the API; the domain does not belong to any client. |

## Project status

See the [roadmap](roadmap.md) for full detail.

- **Phases 0.1 to 0.4: complete.** Workspace, Session, Runtime (Claude Code, OpenCode, Codex), Agents, isolated Jobs (chaining, cancellation), Scribe, backend API, generic scripts, backlog management and web interface.
- **Phase 1.0 (backlog-centric pipeline): in progress.** Architect and Tester roles, Epic→US→Task generators, the state-driven Developer→Tester→Architect pipeline, structured backlog format, cross-cutting actions (FB-025), parallelizable thread analysis (FB-026), simultaneous multi-project sessions, agent reconciliation on backend restart, and live agent log in the web are implemented and in production.
- **Planned, not implemented:** Context Engine (FB-006), Knowledge Engine (FB-007), Capability Engine (FB-010), Plugin System (FB-011), Automation Engine (FB-009/012), Config Management (FB-013), automatic stuck-agent detection (FB-023), persistent control bar for critical agents (FB-028). **There is no plugin system or MCP yet.**

## Getting started

- [Getting started](getting-started.md) — requirements, installation, running and testing.
- [Concepts](concepts.md) — project, session, agent, Job.
- [Architecture](architecture.md) — system design with diagrams.

## Documentation

| Section | Content |
|---|---|
| [Web interface](interfaces-web.md) | The main interface: Backlog, Agentes, Arquitecto, Scripts, Acciones, Configuración. |
| [API](api.md) | Complete REST + WebSocket reference. |
| [Agents](agents.md) | Roles, launching, lifecycle, governance. |
| [Runtime and Scribe](runtime.md) | Claude Code, OpenCode, Codex, tmux, Scribe/Ollama. |
| [Jobs and the work pipeline](jobs.md) | Job lifecycle, chaining, the state-driven backlog pipeline. |
| [Scripts](scripts.md) | Generic and project-specific scripts. |
| [Backlog and pipeline](backlog.md) | Backlog management, validator, Epic→US→Task generators. |
| [Configuration](configuration.md) | `models.yml`, `scripts.yml`, model preferences. |
| [Roadmap](roadmap.md) | Phases, status by Epic, backlog hold. |
| [FAQ and troubleshooting](faq.md) | Frequently asked questions and problem solving. |
| [Development](development.md) | Guide for new developers. |

## Repository

- Code: [`04-src/`](https://github.com/factoria-software/factory-brain/tree/main/04-src) — the `brain` Python package.
- Canonical backlog: [`02-backlog/`](https://github.com/factoria-software/factory-brain/tree/main/02-backlog).
