# API

Atlas Forge exposes its domain through an **HTTP/WebSocket API** (FastAPI) that all clients consume. Complete reference generated against the real code in `04-src/src/atlas_forge/api/`.

## Generalities

- **Base**: `http://<host>:8000` (`127.0.0.1` locally).
- **Errors**: `HTTPException` with a `detail` (message built in the domain).
- **Format**: JSON. There are no query params — only path params and JSON bodies.

## Health and infrastructure

### `GET /health`
Checks that the backend responds.

```json
{"status": "ok", "session_id": null}
```

`session_id` is `null` until a project is selected.

### `GET /ui/` (static mount)
Serves the web interface (`10-web/`). `GET /ui` redirects to `/ui/`.

## Projects

### `GET /project`
Active project.

```json
{"id": "...", "name": "...", "path": "...", "repository": "...", "workspace_id": "..."}
```

404 "There is no active project."

### `GET /projects`
Lists the Git repositories discovered in the workspace (candidates for active project).

### `POST /project`
Selects a project from `GET /projects` and gives it the process's session focus. If the project already had a live session, it is reused as-is (same `session.id`, same agents, nothing relaunched); otherwise a new one is created.

**Agents of the previously focused project are never touched or stopped.** Each project keeps its own live session in parallel (multi-session registry); switching focus back to it makes its agents reachable again through `GET /agents`/`POST /agents/{id}/stop`.

```json
{"project_id": "..."}
```

400 if the id is not in the discovered list.

## Session

### `GET /session`
Active development session.

```json
{"id": "...", "project_id": "...", "status": "active"}
```

404 "There is no active development session."

## Agents

### `GET /agents`
Agents launched in the active session, with `model` resolved from the real runtime (nullable). Runs lazy liveness: dead runtimes appear as `unavailable`.

```json
[{"id": "...", "name": "Developer-1", "role": "developer", "status": "idle", "runtime_id": "opencode", "model": null}]
```

404 without a session.

### `GET /agents/options`
Catalog of launchable role×model combinations: Cartesian product of roles × enabled models with resolved runtime. No active session required.

```json
[{"agent_role": "developer", "model_id": "opencode-go/deepseek-v4-flash", "model_name": "DeepSeek V4 Flash", "runtime_type": "opencode", "runtime_name": "OpenCode", "supports_model": true}]
```

### `POST /agents` → 201
Launches an agent. Body:

```json
{
  "role": "developer",
  "runtime_type": "opencode",
  "model_id": "opencode-go/deepseek-v4-flash",
  "initial_job_description": "optional: initial task"
}
```

`model` is a legacy alias of `model_id`. Without `initial_job_description` it returns the agent; with it, it returns `{agent, job}` (the Job may end up `failed` with the reason in `job.result`). Errors: 404 without session/project; 400 invalid runtime/model or `AgentLaunchError`.

### `POST /agents/{agent_id}/stop`
Kills the agent's tmux session. **For any role except Developer**, transitions it to `stopped` — it remains in the session, reusable/queryable. **For Developer**, the agent is removed from the session entirely (its slot in the simultaneous-Developer limit is freed immediately) — there is no `stopped` Developer to relaunch, "stop" means delete. The response always reflects the state right after the action.

### `GET /agents/{agent_id}/pane`
Current textual content of the agent's tmux pane (read-only view).

```json
{"agent_id": "...", "content": "..."}
```

### `WS /ws/agents/{agent_id}/pane`
Live stream of the agent's tmux pane content (one channel per connection). Server-side poller publishes only when the content changes; stops polling when the client disconnects. Read-only, one agent at a time per connection.

### `GET /agents/{agent_id}/model`
Active model of the agent (OpenCode only, **passive** read from its status bar — safe to call on every poll). `null` for non-OpenCode runtimes or a failed read — never an HTTP error.

### `GET /agents/{agent_id}/status-model`
Active model of a **Claude Code** agent, read on demand by sending `/status` to its pane and parsing the result (**active interaction**, unlike `GET /agents/{agent_id}/model`). Only ever called explicitly by the human — never from `GET /agents` or any polling loop, to avoid interfering with a working agent's output. 400 if the agent is `working`.

```json
{"agent_id": "...", "model": "Default (Sonnet 5 · Efficient for routine tasks)"}
```

### `PUT /agents/{agent_id}/model`
Changes the active model of a running OpenCode agent.

```json
{"model": "opencode-go/deepseek-v4-flash"}
```

Returns `{agent_id, model, changed}`. 400 for non-OpenCode runtime or empty model.

### `GET /agents/{agent_id}/available-models`
Models available for changing on the agent.

```json
{"agent_id": "...", "supports_model": true, "models": [{"id": "...", "name": "...", "runtime": "opencode"}]}
```

## Model preferences

### `GET /models/preferences`
Full catalog with enablement and per-role defaults.

```json
{"models": [{"id": "...", "name": "...", "runtime": "opencode", "enabled": true}], "defaults": {"developer": "..."}}
```

Empty `enabled_model_ids` = all enabled.

### `PUT /models/preferences`
Updates preferences (partial: only the fields sent).

```json
{"enabled_model_ids": ["..."], "default_model_by_role": {"developer": "..."}}
```

## System preferences

### `GET /system/preferences`
System-wide configuration values, persisted independently of any single project.

```json
{"max_simultaneous_developers": 3}
```

### `PUT /system/preferences`
Updates a system preference (partial). `max_simultaneous_developers` must be a positive integer; an invalid value is rejected with an explicit reason, never silently persisted.

```json
{"max_simultaneous_developers": 4}
```

## Jobs

### `POST /jobs` → 201
Creates and **dispatches synchronously** a Job. The response arrives when the Job finishes.

```json
{"agent_id": "...", "description": "...", "previous_job_id": "optional"}
```

Returns `{id, session_id, agent_id, description, status, result}`. `previous_job_id` chains the previous Job's result (Developer→Developer blocked). Publishes `job_status` on `WS /ws/jobs`.

### `GET /jobs`
Full Job history of the active session.

### `GET /jobs/{job_id}`
State/result of a specific Job.

### `POST /jobs/{job_id}/cancel`
Cancels an **in-flight** (`running`) Job. Waits for the real dispatcher-thread transition (up to 5s). 400 if the Job is not `running`.

## Backlog

### `GET /backlog`
Structured report of the active project's backlog (`02-backlog/`): counts per Epic (with `unblock_degree` and `version`), LISTA/BLOQUEADA items, max-leverage chain, parse errors.

### `GET /backlog/{item_id}`
Detail of an item. IDs of the type `AF-xxx` resolve as an Epic; anything else as Task/User Story. Includes objective/story, acceptance criteria, dependencies (with their state) and, for User Stories, its Tasks and (AF-024-US09) execution history. 404 with a parse reason if the file exists but could not be parsed.

### `POST /backlog/{story_id}/launch-development` → 201
Isolated-Job path (no queueing of Tasks as `TO_DEVELOP`): builds the Job from the real story + pending (`READY`) Tasks and dispatches it to the indicated agent. 400 if the Story has no pending Tasks. Publishes `job_status`.

```json
{"agent_id": "..."}
```

### `PUT /backlog/{item_id}/state`
Changes a Task/User Story's `state` directly. For a User Story, operational states (`READY`/`TO_DEVELOP`/`IN_PROGRESS`/`IN_REVIEW`) are not set by hand: they are derived from its Tasks; setting `DONE` triggers automatic Epic promotion if all its User Stories are now `DONE`.

### `POST /backlog/{task_id}/enqueue` → 201
Marks a `READY` Task as `TO_DEVELOP`, making it eligible for the Dispatcher. 400 if the Task is not `READY`.

### `POST /backlog/{us_id}/enqueue-all` → 201
Same as above for every pending Task of a User Story in one call.

### `DELETE /backlog/{task_id}/enqueue`
Reverts a `TO_DEVELOP` Task back to `READY`, only if the Dispatcher has not picked it up yet.

### `GET /backlog/queue`
Current dispatch-queue entries with `effective_status` grouped (`queued / dispatched / awaiting_tester / completed / failed`) — the real-time pipeline viewer (auxiliary FIFO ordering/audit data; `state` on the real files is the source of truth for eligibility).

### `DELETE /backlog/queue/history`
Deletes the dispatch-queue history.

### `DELETE /backlog/queue/completed`
Bulk-deletes only `completed` queue entries.

### `DELETE /backlog/queue/entry/{task_id}`
Removes a specific queue entry.

### `POST /backlog/queue/entry/{task_id}/requeue`
Re-queues a queue entry.

### `GET /backlog/creation-requests`
State of the natural-language Epic/US/Task creation requests pending the Architect.

### `POST /backlog/epic/{epic_id}/propose-stories`
Runs the deterministic Epic→User-Story pipeline (format validator + self-audit) and writes the approved User Stories, born in `NO_TASKS`.

### `POST /backlog/us/{us_id}/propose-tasks`
Runs the deterministic User-Story→Task pipeline. Requires the Story to be in `TO_PLAN` (400 otherwise); on success writes the Tasks and from then on the US reflects the derived state of its Tasks.

## Creation from natural language

### `POST /backlog/epic/from-description` → 202
Sends an Epic creation request from a free-form description to the request queue; the Architect processes it.

### `POST /backlog/epic/{epic_id}/from-description-us` → 202
Same, for a User Story within an Epic.

### `POST /backlog/us/{us_id}/from-description-task` → 202
Same, for a Task within a User Story.

### `GET /backlog/creation-requests`
State of the creation requests pending the Architect.

## Other backlog endpoints

### `POST /backlog/epic`, `POST /backlog/epic/{epic_id}/us`, `POST /backlog/us/{us_id}/task`
Create an Epic, a User Story or a Task with validated format (body with the frontmatter fields).

### `PUT /backlog/{item_id}/version`
Updates an item's `version` (delivery version). Rejects User Stories `DONE`/`IN_REVIEW`.

### `PUT /backlog/{item_id}/priority`
Updates an item's priority.

### `GET /backlog/epic/{epic_id}/coverage`
Coverage of an Epic's declared scope vs its US/Tasks.

### `GET /backlog/reconciliations`
Log of queue and orphaned-task reconciliations.

## Scripts

### `GET /scripts`
Combined catalog: generics first (without `command`), then project-specific ones.

```json
[{"id": "commit", "name": "Commit de cambios", "command": null, "description": "...", "origin": "generic"},
 {"id": "deploy-web", "name": "Deploy web", "command": "...", "description": "...", "origin": "particular"}]
```

### `POST /scripts/{script_id}/run`
Runs a script on the active project (blocking). Optional body: `{"message": "..."}` (only `commit` uses it).

```json
{"success": true, "exit_code": 0, "stdout": "...", "stderr": "", "error_message": null, "data": null, "prose": null}
```

For `backlog_status`: `data` is the parsed report and `prose` the optional Scribe summary (or `null` if unavailable). Script failures are returned **structurally** (never as an HTTP error), except 404 without an active project.

## Cross-cutting project actions

### `POST /project/actions/{action_id}`
Dispatches a complete project action (blocking). `action_id` ∈ `documentar | analizar-arquitectura | sugerir-ideas | testear | auditar-ux | auditar-oss | auditar-backlog | verificar-auditoria | testear-ui | indexar`. Persists the report in `07-informes/US-AF025-*/` without overwriting. 400 for an unknown action; 404 without an active session (agent actions).

## WebSockets

Server→client connections. The client sends nothing; `receive_text()` only blocks until disconnect.

### `WS /ws/jobs`
Events `{"event": "job_status", id, session_id, agent_id, description, status, result}`:
- `created` — before dispatch (exposes the real `job_id`, needed to be able to cancel).
- `completed` / `failed` — on finish.

### `WS /ws/plans`
Plan-state events (Plan approval flow; the flow is deprecated in the web, replaced by the single pipeline — the endpoints and WebSocket are kept).

See also `WS /ws/agents/{agent_id}/pane` above (live tmux pane content, not a `job_status` event).

## States (summary)

| Entity | States |
|---|---|
| Agent | `idle`, `working`, `unavailable`, `stopped` (Developer never reaches `stopped` — stopping a Developer deletes it instead; `POST /agents/{id}/release` frees a downed Developer) |
| Job | `created`, `running`, `completed`, `failed`, `cancelled` |
| Task | `READY`, `TO_DEVELOP`, `IN_PROGRESS`, `IN_REVIEW`, `DONE` (never `OUT_OF_SCOPE`) |
| User Story | `NO_TASKS`, `TO_PLAN`, plus states derived from its Tasks (`READY`/`TO_DEVELOP`/`IN_PROGRESS`/`IN_REVIEW`/`DONE`) and `OUT_OF_SCOPE` (exclusive to US) |
| Session | `created`, `active`, `closed` |
| Dispatch queue | `queued`, `dispatched`, `failed`, `completed` (+ derived `awaiting_tester`) |

The source of truth for the Task/User Story state vocabulary is `core/state_machines.py` (AF-040).
