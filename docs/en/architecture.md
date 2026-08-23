# Architecture

Atlas Forge is a **modular, extensible and maintainable** application, designed to add new capabilities without restructuring the project.

## Core idea

The domain (projects, sessions, agents, Jobs, backlog) lives **behind a single HTTP/WebSocket API** (`atlas_forge/api/`, FastAPI). No client accesses the domain any other way than through that API.

> One process of truth (`atlas-forge-api`), one client: the **web interface**.

## Layers

```mermaid
graph TD
    subgraph Clients
        WEB[Web interface<br/>10-web/ · JS]
    end

    API[HTTP/WebSocket API<br/>atlas_forge/api/ · FastAPI]

    subgraph Domain
        DISP[Dispatcher<br/>atlas_forge/dispatcher/]
        AGENTS[Agents<br/>atlas_forge/agents/]
        CORE[Session<br/>atlas_forge/core/]
        RUNTIME[Runtime<br/>atlas_forge/runtime/]
        BACKLOG[Backlog<br/>atlas_forge/backlog/]
        ARCH[Architect<br/>atlas_forge/architect/]
        SCRIBE[Scribe<br/>atlas_forge/local_tools/]
    end

    subgraph Infrastructure
        TMUX[tmux · libtmux]
        OLLAMA[Ollama · localhost:11434]
        GIT[Git repos]
    end

    WEB --> API
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
```

### Presentation

Web interface (plain JS served by the backend itself at `/ui/`). **No business logic**: all interaction goes through the API.

### Application

The API (`atlas_forge/api/routes.py`) orchestrates operations: it launches agents, creates/dispatches Jobs, runs scripts and exposes the backlog state. It is a thin layer over the domain — it does not reimplement logic, it exposes it.

### Domain

Interface-independent business rules:

- **`atlas_forge/core/`** — development session lifecycle.
- **`atlas_forge/agents/`** — role registry, launching, lifecycle, liveness, stop, governance.
- **`atlas_forge/runtime/`** — runtime instances in tmux (Claude Code, OpenCode, Codex).
- **`atlas_forge/dispatcher/`** — Job creation, dispatch, reporting, cancellation; the background Dispatcher that drives the state-based backlog pipeline (implementation, Task review, Story verdict, US→Tasks landing); automatic Scribe triggering.
- **`atlas_forge/backlog/`** — backlog parser, status report, detail, validator, dependency graph.
- **`atlas_forge/architect/`** — Epic→US→Task generators, gap review, self-auditing pipelines.
- **`atlas_forge/local_tools/`** — Scribe (local summarization/indexing via Ollama).
- **`atlas_forge/workspace/`** — project discovery, active project, generic and project scripts, startup.
- **`atlas_forge/models/`** — domain dataclasses (Agent, Job, DevelopmentSession, Project, backlog, scripts).

### Infrastructure

- **tmux** (`atlas-forge` socket) for persistent runtime sessions.
- **Git** to discover repositories and run scripts.
- **Ollama** for Scribe.
- **systemd** for the `atlas-forge-api` service.

## Persistence

| Data | Where | Persistent |
|---|---|---|
| Active project | `~/.local/share/atlas_forge/active_project.json` | Yes |
| Model preferences | `~/.local/share/atlas_forge/model_preferences.json` | Yes |
| Session, agents, Jobs | In the memory of `atlas-forge-api` | No |
| Closing reports | `07-informes/<US>/<job_id>.md` | Yes (files) |
| Backlog | `02-backlog/` of the active project | Yes (Markdown files) |

## Module detail

### Development session (`atlas_forge/core/`)

A session is a persistent working environment over a project. States: `created` → `active` → `closed`. It is created when you select a project and closed when you change project (stopping any not-stopped agents first).

### Runtimes (`atlas_forge/runtime/`)

Each launched agent is a **runtime instance** in its own tmux session (`runtime/agent_model.py`):
- **Claude Code**: `claude --dangerously-skip-permissions [--model <model>]` + prompt as positional argument.
- **OpenCode**: `opencode --auto [--model provider/model]` + `--prompt "..."`.
- **Codex**: `codex -a never -s workspace-write [--model <model>]` + prompt as positional argument.

The `agent_runtime_registry` maps `agent_id → RuntimeInstance`. Liveness is checked lazily when queried (no polling).

### Agents (`atlas_forge/agents/`)

Registered roles: `developer`, `arquitecto`, `tester`, `documentador`, `ux`, `auditor_oss`. Each role defines a base prompt + governance file + registration function. See [Agents](agents.md).

### Dispatcher (`atlas_forge/dispatcher/`)

- **Job**: `create → running → {completed | failed | cancelled}`. Result reporting is **cooperative**: the agent writes its result to a temp file plus a final marker; the dispatcher waits for that file.
- **Chaining**: `previous_job` injects the previous Job's result literally into the next Job's description. Developer→Developer is blocked (must go through the Architect).
- **Backlog pipeline**: a single background worker polls every 5 seconds and drives each item forward purely by its `state` — queues Tasks `READY` as `TO_DEVELOP`, assigns a Task `TO_DEVELOP` to a Developer (`IN_PROGRESS`), hands a Task in `IN_REVIEW` to a free Tester, a User Story with all its Tasks `DONE` to a free Architect for final validation, and a US `TO_PLAN` to a free Architect for its US→Tasks landing. See [Jobs and the work pipeline](jobs.md#the-backlog-pipeline).
- **Automatic Scribe**: the dispatcher decides to invoke Scribe (by description size > 4000 chars or ≥ 10 consecutive Jobs) to pre-process context, saving remote runtime tokens.
- **Verdict**: on a User Story in `IN_REVIEW` (all its Tasks `DONE`), the assigned Architect emits `APROBADO` / `APROBADO_CON_OBSERVACIONES` / `RECHAZADO`; approved moves the Story to `DONE`, rejected adds a new Task to the same Story instead of promoting it.

### Backlog (`atlas_forge/backlog/`)

Deterministic parser of `02-backlog/` (Epics, User Stories, Tasks) → a graph of items with state, dependencies, priority and phase. Status report (`build_backlog_report`) with counts per Epic, LISTA/BLOQUEADA items, max-leverage chain and unblock degree. Schema validator for the backlog format.

### API (`atlas_forge/api/`)

FastAPI with REST endpoints + WebSocket `/ws/jobs`, static `/ui/` and `/health`. See [API](api.md).

## Directory structure

```text
PROD-006-atlas-forge/
├── 00-gobierno/       # project governance (METODOLOGIA, roles)
├── 02-backlog/        # canonical backlog: epics/, user-stories/, tasks/, roadmap.md
├── 04-src/            # source code (atlas_forge package) and tests
├── 07-informes/       # closing Job reports and analyses
├── 10-web/            # web interface (served by atlas-forge-api at /ui/)
└── deploy/            # systemd units
```

## Module isolation

The project verifies by test (`04-src/tests/test_module_boundaries.py`) that clients do not access the domain directly except for bounded, documented exceptions (static agent catalog, local disk configuration). An interface without a local process (web) depends entirely on the API.
