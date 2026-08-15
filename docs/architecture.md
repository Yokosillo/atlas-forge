# Architecture

Factory Brain is a **modular, extensible and maintainable** application, designed to add new capabilities without restructuring the project.

## Core idea

The domain (projects, sessions, agents, Jobs, plans, backlog) lives **behind a single HTTP/WebSocket API** (`brain/api/`, FastAPI). No client accesses the domain any other way than through that API — including the TUI itself, which is an HTTP client like any other.

> One process of truth (`brain-api`), three clients: **web interface**, **TUI** and **Android app**.

## Layers

```mermaid
graph TD
    subgraph Clients
        WEB[Web interface<br/>10-web/ · JS]
        TUI[TUI · Textual<br/>brain/tui/]
        AND[Android app<br/>10-android/ · Kotlin/Compose]
    end

    API[HTTP/WebSocket API<br/>brain/api/ · FastAPI]

    subgraph Domain
        DISP[Dispatcher<br/>brain/dispatcher/]
        AGENTS[Agents<br/>brain/agents/]
        CORE[Session<br/>brain/core/]
        RUNTIME[Runtime<br/>brain/runtime/]
        BACKLOG[Backlog<br/>brain/backlog/]
        ARCH[Architect<br/>brain/architect/]
        SCRIBE[Scribe<br/>brain/local_tools/]
    end

    subgraph Infrastructure
        TMUX[tmux · libtmux]
        OLLAMA[Ollama · localhost:11434]
        GIT[Git repos]
        CLIS[CLI · brain<br/>brain/cli/]
    end

    WEB --> API
    TUI --> API
    AND --> API
    API --> DISP
    API --> AGENTS
    API --> CORE
    API --> BACKLOG
    API --> SCRIBE
    DISP --> AGENTS
    DISP --> SCRIBE
    AGENTS --> RUNTIME
    RUNTIME --> TMUX
    SCRIBE --> OLLAMA
    DISP --> GIT
    CLIS --> BACKLOG
    CLIS --> SCRIBE
```

### Presentation

Web interface (plain JS served by the backend itself at `/ui/`), TUI (Textual) and Android app (Kotlin/Compose). **No business logic**: all interaction goes through the API.

### Application

The API (`brain/api/routes.py`) orchestrates operations: it launches agents, creates/dispatches Jobs, manages plans, runs scripts and exposes the backlog state. It is a thin layer over the domain — it does not reimplement logic, it exposes it.

### Domain

Interface-independent business rules:

- **`brain/core/`** — development session lifecycle.
- **`brain/agents/`** — role registry, launching, lifecycle, liveness, stop, governance.
- **`brain/runtime/`** — runtime instances in tmux (Claude Code, OpenCode).
- **`brain/dispatcher/`** — Job creation, dispatch, reporting, cancellation; Architect plans; verdicts; automatic Scribe triggering; FIFO verdict queue.
- **`brain/backlog/`** — backlog parser, status report, detail, validator, dependency graph.
- **`brain/architect/`** — Epic→US→Task generators, gap review, self-auditing pipelines.
- **`brain/local_tools/`** — Scribe (local summarization/indexing via Ollama).
- **`brain/workspace/`** — project discovery, active project, generic and project scripts, startup.
- **`brain/models/`** — domain dataclasses (Agent, Job, JobPlan, DevelopmentSession, Project, backlog, scripts).

### Infrastructure

- **tmux** (`factory-brain` socket) for persistent runtime sessions.
- **Git** to discover repositories and run scripts.
- **Ollama** for Scribe.
- **systemd** for the `brain-api` service.

## Persistence

| Data | Where | Persistent |
|---|---|---|
| Active project | `~/.local/share/brain/active_project.json` | Yes |
| Model preferences | `~/.local/share/brain/model_preferences.json` | Yes |
| Session, agents, Jobs, plans | In the memory of `brain-api` | No |
| Closing reports | `07-informes/<US>/<job_id>.md` | Yes (files) |
| Backlog | `02-backlog/` of the active project | Yes (Markdown files) |

## Module detail

### Development session (`brain/core/`)

A session is a persistent working environment over a project. States: `created` → `active` → `closed`. It is created when you select a project and closed when you change project (stopping any not-stopped agents first).

### Runtimes (`brain/runtime/`)

Each launched agent is a **runtime instance** in its own tmux session (`runtime/agent_model.py`):
- **Claude Code**: `claude --dangerously-skip-permissions` + prompt as positional argument.
- **OpenCode**: `opencode --auto [--model provider/model]` + `--prompt "..."`.

The `agent_runtime_registry` maps `agent_id → RuntimeInstance`. Liveness is checked lazily when queried (no polling).

### Agents (`brain/agents/`)

Registered roles (4): `developer`, `critic`, `director`, `arquitecto`. Each role defines a base prompt + governance file + registration function. See [Agents](agents.md).

### Dispatcher (`brain/dispatcher/`)

- **Job**: `create → running → {completed | failed | cancelled}`. Result reporting is **cooperative**: the agent writes its result to a temp file plus a final marker; the dispatcher waits for that file.
- **Chaining**: `previous_job` injects the previous Job's result literally into the next Job's description. Developer→Developer is blocked (must go through the Architect).
- **Plan**: the Architect proposes a sequence of steps (`proposed`), the human approves once (`approved`) and it is dispatched end to end. States: `proposed → {approved, rejected}`, `approved → {blocked, cancelled}`.
- **Automatic Scribe**: the dispatcher decides to invoke Scribe (by description size > 4000 chars or ≥ 10 consecutive Jobs) to pre-process context, saving remote runtime tokens.
- **Verdict**: after dispatching a plan, a verdict Job is queued to the Architect (FIFO queue, one worker) that emits `APROBADO` / `APROBADO_CON_OBSERVACIONES` / `RECHAZADO` and, if approved, marks the Tasks as `DONE`.

### Backlog (`brain/backlog/`)

Deterministic parser of `02-backlog/` (Epics, User Stories, Tasks) → a graph of items with state, dependencies, priority and phase. Status report (`build_backlog_report`) with counts per Epic, LISTA/BLOQUEADA items, max-leverage chain and unblock degree. Schema validator for the backlog format.

### API (`brain/api/`)

FastAPI with ~30 REST endpoints + 2 WebSockets (`/ws/jobs`, `/ws/plans`), static `/ui/`, `/health` and `/apk`. See [API](api.md).

## Directory structure

```text
PROD-006-factory-brain/
├── 00-gobierno/       # project governance (METODOLOGIA, roles)
├── 01-documentacion/  # internal documentation (may be outdated)
├── 02-backlog/        # canonical backlog: epics/, user-stories/, tasks/, roadmap.md
├── 04-src/            # source code (brain package) and tests
├── 07-informes/       # closing Job reports and analyses
├── 10-android/        # Android app (Kotlin/Compose)
├── 10-web/            # web interface (served by brain-api at /ui/)
└── deploy/            # systemd units
```

## Module isolation

The project verifies by test (`04-src/tests/test_module_boundaries.py`) that clients do not access the domain directly except for bounded, documented exceptions (static agent catalog, local disk configuration). An interface without a local process (web) depends entirely on the API.
