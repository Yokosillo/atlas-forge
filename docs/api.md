# API

Factory Brain exposes its domain through an **HTTP/WebSocket API** (FastAPI) that all clients consume. Complete reference generated against the real code in `04-src/src/brain/api/`.

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

### `GET /apk`
Serves `releases/factory-brain-latest.apk` (Android app download). 404 if the APK does not exist.

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
Selects the active project and **hot-restarts the development session** (stops not-stopped agents, invalidates caches, starts a new session).

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
Catalog of launchable role×model combinations: Cartesian product of roles × enabled models with resolved runtime. Critic+OpenCode combinations are filtered.

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
Stops an agent: kills its tmux session and transitions it to `stopped`.

### `GET /agents/{agent_id}/pane`
Current textual content of the agent's tmux pane (read-only view).

```json
{"agent_id": "...", "content": "..."}
```

### `GET /agents/{agent_id}/model`
Active model of the agent (OpenCode only). `null` for non-OpenCode runtimes or a failed read — never an HTTP error.

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

## Architect plans

### `POST /plans` → 201
Asks the Architect for a breakdown plan for a User Story. **Dispatches nothing.**

```json
{"goal": "US-FB020-01"}
```

Returns `{plan_id, goal, status: "proposed", steps: [{description, mechanism, status}]}`. Publishes `plan_progress` on `WS /ws/plans`.

### `GET /plans`
All plans registered in the process (including decided ones), to recover a lost `plan_id`.

### `GET /plans/{plan_id}`
Progress of a specific plan.

### `POST /plans/{plan_id}/approve`
Approves and **dispatches the whole plan** end to end (blocking). Idempotent: only the first request transitions `proposed→approved`; concurrent ones return `already_decided: true`. Publishes an event per step on `WS /ws/plans`.

Returns `{plan_id, already_decided, goal, status, steps}`.

### `POST /plans/{plan_id}/reject`
Rejects a proposed plan (dispatches nothing). Idempotent like approve.

### `POST /plans/{plan_id}/cancel`
Cancels an **approved and in-flight** plan. Waits for the real transition (up to 5s). 400 if the plan is not `approved` or has no pending/running steps.

## Backlog

### `GET /backlog`
Structured report of the active project's backlog (`02-backlog/`): counts per Epic (with `unblock_degree` and `fase`), LISTA/BLOQUEADA items, max-leverage chain, parse errors.

### `GET /backlog/{item_id}`
Detail of an item. IDs of the type `FB-xxx` resolve as an Epic; anything else as Task/User Story. Includes objective/story, acceptance criteria, dependencies (with their state) and, for User Stories, its Tasks and (FB-024-US09) execution history. 404 with a parse reason if the file exists but could not be parsed.

### `POST /backlog/{story_id}/launch-development` → 201
Launches the development of a User Story: builds the Job from the real story + pending (`TODO`) Tasks and dispatches it to the indicated agent. 400 if the Story has no pending Tasks. Publishes `job_status`.

```json
{"agent_id": "..."}
```

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
Dispatches a complete project action (blocking). `action_id` ∈ `documentar | analizar-arquitectura | sugerir-ideas | testear | auditar-ux | indexar`. Persists the report in `07-informes/US-FB025-*/` without overwriting. 400 for an unknown action; 404 without an active session (agent actions).

## WebSockets

Server→client connections. The client sends nothing; `receive_text()` only blocks until disconnect.

### `WS /ws/jobs`
Events `{"event": "job_status", id, session_id, agent_id, description, status, result}`:
- `created` — before dispatch (exposes the real `job_id`, needed to be able to cancel).
- `completed` / `failed` — on finish.

### `WS /ws/plans`
Events `{"event": "plan_progress", plan_id, goal, status, steps, already_decided?}`:
- On plan creation.
- On approval/rejection/cancellation.
- During dispatch, after each step state change.

## States (summary)

| Entity | States |
|---|---|
| Agent | `idle`, `working`, `unavailable`, `stopped` |
| Job | `created`, `running`, `completed`, `failed`, `cancelled` |
| Plan | `proposed`, `approved`, `rejected`, `blocked`, `cancelled` |
| Step | `pending`, `running`, `completed`, `failed`, `cancelled` |
| Session | `created`, `active`, `closed` |
