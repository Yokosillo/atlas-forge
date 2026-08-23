# Getting started

Installation, configuration and first runs of Atlas Forge.

## Requirements

- **Python ≥ 3.10**
- **tmux** (runtimes run in tmux sessions; the default socket is `atlas-forge`)
- An **AI runtime** installed and available on the PATH:
  - **OpenCode** (CLI `opencode`) — supports model selection.
  - **Claude Code** (CLI `claude`) — no model flag.
- **Optional — Ollama** at `http://localhost:11434` for **Scribe** (local model, e.g. `qwen2.5-coder:14b`). Scribe is an optional token saver: everything works without it, degrading explicitly.
- **Optional — remote access** if you want to reach the backend from a mobile device.

!!! note "LLM providers"
    Atlas Forge does not run models directly: it delegates to external runtimes. The model catalog (`.atlas-forge/models.yml`) declares the available models per runtime. Codex appears in the catalog as a future (commented-out) entry — it is not yet supported as a runtime.

## Installation

```bash
cd 04-src
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

This installs the `atlas_forge` package and the `atlas_forge` and `atlas-forge-api` entrypoints.

## Running

Atlas Forge operates as **a single process of truth** (`atlas-forge-api`) that exposes the API and serves the web interface. All clients (the web) connect to it.

### 1. Start the backend

```bash
atlas-forge-api
```

- Listens on port **8000**.
- On startup it recovers the persisted active project and starts its development session (if any). If there is no project, the API responds 404 on `/project` and `/session` until you select one.

### 2. Open the web interface

Navigate to `http://<host>:8000/ui/` (or `http://127.0.0.1:8000/ui/` locally).

On first startup the web guides you: verify connectivity → choose your first project → enter the operational view. From there you can launch agents, drive the backlog pipeline with "Progresar", dispatch isolated Jobs, run scripts and trigger cross-cutting actions.

### 3. (Alternative) Install as a systemd service

```bash
sudo cp deploy/systemd/atlas-forge-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now atlas-forge-api.service
```

The service runs `atlas-forge-api` as a non-root user and restarts itself on crash (a deliberate `systemctl stop` is not restarted).

## Testing

```bash
cd 04-src
pytest
```

Full suite (more than 600 tests). To run tests without touching the network/tmux, the tests use an in-memory `TestClient` and their own tmux sockets; the suite does not require a real runtime or Ollama to pass.

## Quick verification

```bash
curl http://127.0.0.1:8000/health
# {"status": "ok", "session_id": null}  →  until you select a project
curl http://127.0.0.1:8000/projects    # list discovered Git repos
```

## Where state lives

| Data | Location |
|---|---|
| Active project | `<state_dir>/active_project.json` |
| Model preferences | `<state_dir>/model_preferences.json` |
| Session/agent/Job state | In the memory of the `atlas-forge-api` process (not persisted to disk) |
| tmux sessions | `atlas-forge` tmux server |

`state_dir` defaults to `$XDG_DATA_HOME/atlas_forge` or `~/.local/share/atlas_forge`.

!!! warning "In-memory state"
    Sessions, agents and Jobs live in the process memory. Restarting `atlas-forge-api` leaves the session blank again (the active project is recovered from disk). Session persistence across restarts is a planned User Story, not implemented.

## Next steps

- Read [Concepts](concepts.md) to understand the domain model.
- Follow the [web interface guide](interfaces-web.md) for your first real task.
