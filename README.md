# Factory Brain

**AI-assisted software development coordination from a single platform.**

Factory Brain orchestrates projects, agents, runtimes, Jobs and development pipelines without replacing the developer's decision-making ability. It is not an IDE, not an agent framework: it is the coordination layer that keeps context alive between agents, avoids repetitive manual work and minimizes token consumption from remote models.

## What it solves

Factory Brain centralizes that flow:

- **Discovers** the Git repositories in your workspace automatically.
- **Coordinates** specialized agents (Developer, Architect, and other governance roles) on real runtimes (Claude Code, OpenCode) in persistent tmux sessions.
- **Sends Jobs** to agents and **chains** results (Developer → Architect).
- **Proposes and executes** work plans with a single human approval.
- **Automates the repetitive** with deterministic scripts before spending tokens on a model.
- **Delegates reads/summaries to a local model** (Scribe + Ollama) to reduce remote token consumption.
- **Exposes everything** through a single HTTP/WebSocket API consumed by the web interface.

## What Factory Brain really is

Factory Brain is a **coordination layer between defined work and the agents that execute it** — not another project tracker, and not another coding agent. The backlog (Epic → User Story → Task) is the language used to describe work; the persistent development session, Jobs and pipelines are the mechanism used to execute and verify it.

- **vs. Jira/Linear**: those describe work for humans to do. Here the backlog is *executable* — a Task can go from a Markdown file to verified, tested code without a human writing a line.
- **vs. Claude Code/Codex/OpenCode**: those execute work but don't know what work exists, don't persist across sessions, and don't validate their own output. Factory Brain is the layer that turns a coding agent into a factory.
- **What's genuinely differential**: the adversarial verification cycle (Developer implements → Architect independently re-verifies with real evidence → structured verdict) and "deterministic automation first" as a real operating discipline, not a slogan.

See [What Factory Brain really is](docs/en/index.md#what-factory-brain-really-is) in the full documentation for the complete picture, including market positioning.

## What sets it apart

- **Coordination over execution**: Factory Brain decides *who does what and when*; agents execute with their own runtimes and models.
- **Deterministic automation first**: scripts → automations → local model → remote model, in that priority order.
- **Persistent context**: agents are not destroyed when a Job finishes; the session and its history stay alive.
- **A single process of truth** (`brain-api`) with a single client (the web interface).

## Current status

Factory Brain has completed Phases 0.1–0.4 and the bulk of Phase 1.0 of the roadmap: Workspace, Session, Runtime, Agents, Dispatcher (Jobs/plans/cancellation), Scribe, backend API, generic scripts, backlog management, web interface, backlog-centric pipeline (Architect role, Epic→US→Task generators, verdicts, structured backlog format), simultaneous multi-project sessions, agent reconciliation on backend restart, live agent log in the web, and web UX improvements. Context Engine, Knowledge Engine, Capability Engine, Plugin System and Automation Engine remain in the backlog unimplemented.

See the [full roadmap](docs/en/roadmap.md) and the [status by Epic](docs/en/roadmap.md#estado-por-epic) for details.

## Quick start

Requirements: Python ≥ 3.10, `tmux`, an AI runtime (Claude Code or OpenCode), and optionally Ollama for Scribe.

```bash
cd 04-src
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

## Running

The backend (single process of truth, exposes API + web interface):

```bash
brain-api
```

The web interface is served from the backend itself at `http://<tailscale-ip>:8000/ui/`. On a `systemd` system it is installed as a service:

```bash
sudo cp deploy/systemd/factory-brain-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now factory-brain-api.service
```

## Testing

```bash
cd 04-src
pytest
```

## Documentation

Public documentation lives in [`/docs`](docs/en/index.md) and is ready to be published with [MkDocs](https://www.mkdocs.org/) or GitHub Pages:

- [Getting started](docs/en/getting-started.md)
- [Architecture](docs/en/architecture.md)
- [Concepts](docs/en/concepts.md)
- [Configuration](docs/en/configuration.md)
- [API](docs/en/api.md)
- [Interfaces: web](docs/en/interfaces-web.md)
- [Agents](docs/en/agents.md)
- [Runtime and Scribe](docs/en/runtime.md)
- [Jobs and plans](docs/en/jobs.md)
- [Scripts](docs/en/scripts.md)
- [Backlog and backlog-centric pipeline](docs/en/backlog.md)
- [Roadmap](docs/en/roadmap.md)
- [FAQ and troubleshooting](docs/en/faq.md)
- [Development](docs/en/development.md)

The documentation is available in [English](docs/en/index.md) and [Spanish](docs/es/index.md).

## License

Pending decision — see [roadmap](docs/en/roadmap.md) and the project backlog.
