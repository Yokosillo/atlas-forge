# TUI

The TUI is Factory Brain's terminal client, built with [Textual](https://textual.textualize.io/). It is an **API client** like any other: it assumes `brain-api` is running and does not manage its own domain state.

!!! note "Development pause"
    Since the 2026-08-04 product decision, all new functionality is exposed on the web; the TUI is paused for new capabilities (the active-model Tasks in the TUI are `POSTERGADA`). What is documented here is already implemented and operational.

## Startup

```bash
brain
```

The `brain` command starts the TUI. On mount:

1. **ConnectivityCheckScreen**: probes `GET /session`.
2. If it connects: recovers the active project (`resolve_startup_project`) and jumps to the **Dashboard** or the **Workspace** screen (if there is no project).
3. If it does not connect: shows an error + **Retry**.

## Screens

Textual-native keyboard navigation (buttons, `ListView`, `Select`, tabbing).

### Workspace

Lists the discovered projects (`discover_projects` local). Choosing one selects the active project and returns to the Dashboard. Distinguishes onboarding ("Select a project:") from voluntary change ("Back to Dashboard").

### Dashboard

Navigation and state center: active project, session (id/state), launched agents with state, and a summary of Jobs by state. Buttons: **View Agents, View Jobs, View Scripts, View Backlog, Change project**.

### Agents

- List of launched agents with state.
- Role+runtime selector (product decision) + optional model field (OpenCode only) → **Launch**.
- **Stop** per agent with second-click confirmation ("Are you sure? It has a Job in flight — it will be interrupted. Confirm stop").

### Jobs

- Description (`TextArea`) + agent (`Select`) → **Send** (blocking `POST /jobs` call in a worker).
- **Cancel Job** via a locator that finds the Job by description in `GET /jobs`.
- History rebuilt from `GET /jobs`.

### Scripts

- Catalog selector with a `[Generic]`/`[Project]` prefix.
- Message field only for `commit`.
- Background execution via `POST /scripts/{id}/run`; formats the `backlog_status` output.

### Backlog

Three-level breakdown (Epic → Epic detail → item detail) with `push_screen`/`pop_screen`:

- Rich colors: `[green]` DONE, `[dark_orange]` TO_DO, `[bright_black]` unknown.
- Proportional progress bars (e.g. `███░░░░░░░ 3/10 US DONE`).
- `⚠` warnings for items with parse errors.
- In a User Story: **Launch development** with a Developer agent selector.

## Backend client

`brain.tui.backend_client` is a synchronous `requests` client with `DEFAULT_BACKEND_URL = http://127.0.0.1:8000`, timeout 10s (60s for blocking dispatch/scripts calls). Methods: `get_session`, `get_agents`, `launch_agent`, `stop_agent`, `get_jobs`, `create_and_dispatch_job`, `cancel_job`, `get_backlog`, `get_backlog_item`, `launch_development`, `get_scripts`, `run_script`.

Client exceptions: 404 on agents/jobs/scripts → empty list; 404 on backlog → real error (propagated).

## Known limitations

- The TUI does not start `brain-api` itself; it depends on the service running (systemd or other).
- Keyboard-first: not suitable for touch use from mobile (hence the Android app / the web).
