# Web interface

The **web interface is the main (and only) interface** of Atlas Forge. It is served from the backend itself at `http://<host>:8000/ui/`, is plain JS without frameworks and talks to the same REST + WebSocket API as the rest of the clients.

## Startup flow

1. **Connectivity check**: `GET /health`. If the backend does not respond, it shows the "No connection to the backend" guide with a **Retry** button.
2. **Project selection**: if there is no active project, an onboarding screen ("Choose your first project") or voluntary change ("Select another project").
3. **Operational view**: top bar with the active project (chip) + **Change project** button, a persistent Architect status bar, navigation tabs and the section body. Each section has its own URL under `/ui/`.

## Tabs

The navigation bar contains: **Backlog, Pipeline, Agentes, Arquitecto, Scripts, Configuración**. The Backlog tab shows an orange badge with the number of pending Epics/US.

### Backlog

The control panel of the whole product — every piece of work is deployed from here.

- **"List" / "By Version"** toggle (grouping by delivery version).
- Epic listing with state summary (US/Tasks per state), **heat bar** of unblock degree per Epic and a global **badge** of pending work.
- Expandable Epic → User Story → detail breakdown (via `GET /backlog/{item_id}`).
- A User Story's detail shows its dependencies with their state, its Tasks, and a **"Progresar"** button whose action depends on the Story's current state:
  - `NO_TASKS` → marks `TO_PLAN` (the Dispatcher assigns a free Architect to land the Story into Tasks).
  - With Tasks created → the Story's state is **derived** (the least advanced Task); the button shows the current state and progress is governed by the Dispatcher and the validations (Tester per Task, Architect at the end).
- "Opciones avanzadas" (collapsed by default) exposes the isolated-Job path: "Lanzar desarrollo" (context pre-filled from the Story) and "Crear Job manual" (free-form description) — see [Jobs and the work pipeline](jobs.md).
- Forms to create an Epic, a User Story or a Task directly from the screen, including natural-language creation (with the Architect request queue), and buttons to have the Architect propose User Stories for an Epic or land a User Story into Tasks.

### Pipeline

The real-time viewer of the pipeline's **dispatch queue** (moved here from Backlog). It shows each queued Task with its effective state (`queued / dispatched / awaiting_tester / completed / failed`), allows clearing completed entries, re-queueing and removing entries, and auto-refreshes by polling while the tab is open.

### Agentes

Unified screen listing every governance role (Architect, Developer, Auditor-OSS, UX, Tester) with the same fields and buttons regardless of role. Architect is single-instance and reusable (pauses to `stopped` on "Stop"); Developer is multi-instance, persistent and human-managed (up to a configurable simultaneous limit — "Stop" deletes the instance and frees its slot instead of pausing it; "Liberar" frees a downed Developer). Auditor-OSS, UX and Tester are listed with "Launch" disabled and an explicit reason while they remain unregistered in the backend. Runtime and model are chosen explicitly at launch time (no on-the-fly runtime/model switch for a live agent, except the model on OpenCode).

### Arquitecto

A dedicated conversational tab for the Architect: pick one of its predefined orders or write a free prompt, dispatch it as a Job, and browse the history of past orders (with status, result, and expand/collapse per entry).

### Scripts

Combined catalog `GET /scripts` that brings together the **generic scripts** (Atlas Forge), the **project scripts** and the **cross-cutting actions** in a single listing (actions were merged into Scripts). Each card shows the description; the shell command is hidden by default and shown with "▶ View command". Only the `commit` script asks for a message. Running shows success/exit code/stdout/stderr, and formats the `backlog_status` output.

#### Cross-cutting actions

Available as cards inside the Scripts catalog, as direct buttons to `POST /project/actions/{action_id}`:

| Action | What it does |
|---|---|
| **Document everything** | Dispatches a Job to the Documentador to contrast `docs/` against the real code. |
| **Analyze architecture** | Architecture analysis with code evidence; does not write to the backlog. |
| **Suggest ideas for the backlog** | Informal proposals of candidate Epics/US (never direct writes). |
| **Test everything** | Runs the `pytest` suite; PASS/FAIL result with detail. |
| **Audit the web UX** | UX audit of the web on the launched UX instance (`00-gobierno/UX.md` protocol). |
| **Audit open source image** | OSS audit: public GitHub repo image + web against the backend. |
| **Audit the backlog against the code** | The Architect crosses each item's `## Estado` against the code evidence. |
| **Verify the backlog audit** | The Auditor-OSS verifies each finding of the previous step and issues an action per finding. |
| **Test web UI** | Runs the web Puppeteer suite (deterministic). |
| **Index project (Scribe)** | Indexes with Scribe/Ollama (external process, no agent tokens spent). |

All of them persist their reports with a timestamp in `07-informes/US-AF025-*/` without overwriting previous runs.

### Configuración

System preferences editable from the web: the maximum number of simultaneous Developers, whether a Developer waits for the Tester's verdict on its previous Task before receiving a new one, the model map by difficulty, the backlog multiple expansion, and the autonomous-scaling configuration (enabling, per-role limits and total maximum).

## UX patterns

- **Confirmation in the button label** for destructive actions (stop agent, change project with active agents) — avoids layout reflow.
- **State colors** (WCAG): idle/working/stopped/unavailable agents, running/ok/failed Jobs.
- **Single-flight**: buttons that trigger blocking calls are disabled while the request is in flight (avoids a double dispatch from a double click).
- **Stale-data**: amber notes "this list may be outdated…" when data may not reflect the latest change.
- **WebSocket with reconnection** (`reconnecting-websocket.js`, 3s backoff) without clearing UI state.
- Touch targets ≥ 48px, in-place expandable cards, full results with scroll.

## Client configuration

The client is configured with `BackendClient.setBaseUrl(...)`; by default it uses the same origin (served from `atlas-forge-api`, no CORS). Errors: `BackendUnavailableError` (network) and `BackendRequestError` (4xx/5xx with the real backend `detail`).