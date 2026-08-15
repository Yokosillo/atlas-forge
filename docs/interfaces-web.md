# Web interface

The **web interface is the main interface** of Factory Brain since the 2026-08-04 product decision (TUI and Android are paused for new functionality). It is served from the backend itself at `http://<host>:8000/ui/`, is plain JS without frameworks and talks to the same REST + WebSocket API as the rest of the clients.

## Startup flow

1. **Connectivity check**: `GET /health`. If the backend does not respond, it shows the "No connection to the backend" guide with a **Retry** button.
2. **Project selection**: if there is no active project, an onboarding screen ("Choose your first project") or voluntary change ("Select another project").
3. **Operational view**: top bar with the active project (chip) + **Change project** button, navigation tabs and the section body.

## Tabs

The current navigation bar contains: **Roles, Plan, Scripts, Backlog, Models, Actions**. The Backlog tab shows an orange badge with the number of pending Epics/US.

!!! note "Agents and Jobs screens"
    The **Agents** screen was replaced by the **Roles** tab (role configuration, T-FB024-US08) and the **Jobs** tab was merged into each User Story's detail in the Backlog (T-FB024-US09). The code for the Agents/Jobs renderers still exists in `app.js` but is not in the current navigation bar.

### Roles

Unified screen listing every governance role (Architect, Developer, Auditor-OSS, UX, Tester) with the same fields and buttons regardless of role. Architect is single-instance and reusable (pauses to `stopped` on "Stop"); Developer is multi-instance, persistent and human-managed (up to a configurable simultaneous limit — "Stop" deletes the instance and frees its slot instead of pausing it). Auditor-OSS, UX and Tester are listed with "Launch" disabled and an explicit reason while they remain unregistered in the backend. "Change model" opens an inline editor of the role's default model and saves via `PUT /models/preferences` (`default_model_by_role`) — disabled while an instance is live, to avoid interacting with a running agent's pane.

### Plan

- **"Ask the Architect for a plan"**: the goal is a **selector of TODO User Stories from the backlog** (with free-text fallback if the backlog does not load).
- The plan card shows the proposed steps (Step N · Mechanism · State) in real time via the `WS /ws/plans` WebSocket.
- **Approve** requires a second click with confirmation ("Approve the whole plan? N steps will be dispatched…") and dispatches the whole sequence.
- **Reject** does not require confirmation; **Cancel plan** is available while the plan is approved with pending steps.
- Plan history from `GET /plans`, automatic recovery of the pending `proposed` plan on reload.

### Scripts

Combined catalog `GET /scripts` split into **"Generic (Factory Brain)"** and **"Project"**. Each card shows the description; the shell command is hidden by default and shown with "▶ View command". Only the `commit` script asks for a message. Running shows success/exit code/stdout/stderr, and formats the `backlog_status` output (count per Epic, LISTA, BLOQUEADA, leverage chain).

### Backlog

- **"List" / "By Phase"** toggle (grouping by roadmap phase).
- Epic listing with state summary (US/Tasks TODO and DONE), **heat bar** of unblock degree per Epic and a global **badge** of pending work.
- Expandable Epic → User Story → detail breakdown (via `GET /backlog/{item_id}`).
- In a User Story: dependencies with their state (blocks "Launch development" if there are unresolved dependencies), **execution history** (Jobs over that Story) and a manual "Create manual Job" form as secondary.
- "Launch development" (`POST /backlog/{story_id}/launch-development`) only for Developer agents and with pending Tasks.

### Models

Model table with **enabled** checkboxes and a **default model per role** selector (developer / critic / architect / tester). Saves via `PUT /models/preferences` (`enabled_model_ids` + `default_model_by_role`).

### Actions

Cross-cutting project actions (FB-025) as direct buttons to `POST /project/actions/{action_id}`:

| Action | What it does |
|---|---|
| **Document everything** | Dispatches a Job to the Architect to contrast `01-documentacion/` against the real code. |
| **Analyze architecture** | Architecture analysis with code evidence; does not write to the backlog. |
| **Suggest ideas for the backlog** | Informal proposals of candidate Epics/US (never direct writes). |
| **Test everything** | Runs the `pytest` suite; PASS/FAIL result with detail. |
| **Audit the web UX** | Headless `opencode run --auto` run according to `00-gobierno/UX.md`. |
| **Index project (Scribe)** | Indexes `01-documentacion/`, `02-backlog/`, `04-src/`, `00-gobierno/` with Scribe/Ollama. |

All of them persist their reports with a timestamp in `07-informes/US-FB025-*/` without overwriting previous runs.

## UX patterns

- **Confirmation in the button label** for destructive actions (stop agent, approve plan, change project with active agents) — avoids layout reflow.
- **State colors** (WCAG): idle/working/stopped/unavailable agents, running/ok/failed Jobs.
- **Single-flight**: buttons that trigger blocking calls are disabled while the request is in flight (avoids a double Job/plan from a double click).
- **Stale-data**: amber notes "this list may be outdated…" when data may not reflect the latest change.
- **WebSocket with reconnection** (`reconnecting-websocket.js`, 3s backoff) without clearing UI state.
- Touch targets ≥ 48px, in-place expandable cards, full results with scroll.

## Client configuration

The client is configured with `BackendClient.setBaseUrl(...)`; by default it uses the same origin (served from `brain-api`, no CORS). Errors: `BackendUnavailableError` (network) and `BackendRequestError` (4xx/5xx with the real backend `detail`).
