# Factory Brain

**AI-assisted software development coordination from a single platform.**

Factory Brain orchestrates projects, agents, runtimes, Jobs and development pipelines without replacing the developer's decision-making ability. It is not an IDE, not an agent framework: it is the coordination layer that keeps context alive between agents, avoids repetitive manual work and minimizes token consumption from remote models.

## What it solves

Developing with AI today requires maintaining several Claude Code sessions, launching processes in tmux, using OpenCode for other models, switching between projects and losing time rebuilding context on every task. Each tool keeps its own state and knowledge ends up scattered.

Factory Brain centralizes that flow:

- **Discovers** the Git repositories in your workspace automatically.
- **Coordinates** specialized agents (Developer, Critic, Director, Architect) on real runtimes (Claude Code, OpenCode) in persistent tmux sessions.
- **Sends Jobs** to agents and **chains** results (Developer → Critic/Architect).
- **Proposes and executes** work plans with a single human approval.
- **Automates the repetitive** with deterministic scripts before spending tokens on a model.
- **Delegates reads/summaries to a local model** (Scribe + Ollama) to reduce remote token consumption.
- **Exposes everything** through a single HTTP/WebSocket API consumed by the web interface, the TUI and the Android app.

## What sets it apart

- **Coordination over execution**: Factory Brain decides *who does what and when*; agents execute with their own runtimes and models.
- **Deterministic automation first**: scripts → automations → local model → remote model, in that priority order.
- **Persistent context**: agents are not destroyed when a Job finishes; the session and its history stay alive.
- **A single process of truth** (`brain-api`) with three parallel clients (web, TUI, Android).

## Current status

Factory Brain has completed Phases 0.1–0.4 and the bulk of Phase 1.0 of the roadmap: Workspace, Session, Runtime, Agents, Dispatcher (Jobs/plans/cancellation), Scribe, backend API, Android app, generic scripts, TUI, backlog management, web interface, backlog-centric pipeline (Director/Architect roles, Epic→US→Task generators, verdicts) and web UX improvements. Context Engine, Knowledge Engine, Capability Engine, Plugin System and Automation Engine remain in the backlog unimplemented.

See the [full roadmap](docs/roadmap.md) and the [status by Epic](docs/roadmap.md#estado-por-epic) for details.

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

The TUI (API client):

```bash
brain
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

Public documentation lives in [`/docs`](docs/index.md) and is ready to be published with [MkDocs](https://www.mkdocs.org/) or GitHub Pages:

- [Getting started](docs/getting-started.md)
- [Architecture](docs/architecture.md)
- [Concepts](docs/concepts.md)
- [CLI](docs/cli.md)
- [Configuration](docs/configuration.md)
- [API](docs/api.md)
- [Interfaces: web · TUI · Android](docs/interfaces-web.md)
- [Agents](docs/agents.md)
- [Runtime and Scribe](docs/runtime.md)
- [Jobs and plans](docs/jobs.md)
- [Scripts](docs/scripts.md)
- [Backlog and backlog-centric pipeline](docs/backlog.md)
- [Roadmap](docs/roadmap.md)
- [FAQ and troubleshooting](docs/faq.md)
- [Development](docs/development.md)

## License

Pending decision — see [roadmap](docs/roadmap.md) and the project backlog.
