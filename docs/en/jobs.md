# Jobs and the work pipeline

## Job lifecycle

A **Job** is a unit of work (a text description) sent to an agent. States:

```
created → running → { completed | failed | cancelled }
```

### Creation (`dispatcher/job_creation.py`)

Preconditions (each rejection raises `JobCreationError` with an explicit message):
- Active session.
- The agent belongs to the session.
- The agent is `idle` (a `working` agent does not receive a new Job).

### Dispatch (`dispatcher/job_dispatch.py`)

**Cooperative reporting** mechanism (not shell-end-marker nor silence heuristics):

1. `mark_running(job)` + `mark_working(agent)`.
2. An instruction is added to the description: the agent must write its full result to a unique temp file (`atlas-forge-job-<uuid>.txt`) plus a **final marker** (`___ATLAS_FORGE_JOB_DONE___`) on its own line.
3. The instruction is sent to the agent's tmux pane (`run_command`).
4. The dispatcher polls the file (timeout 30s by default for short/deterministic Jobs; work dispatched through the backlog pipeline uses a much longer timeout suited to real implementation work), with read retries for transient `OSError`s.
5. `completed` (result read) | `failed` (timeout `JobReportTimeoutError`) | `cancelled` (`JobCancelledError` if the user requested cancellation).
6. In `finally`: deletes the temp file and clears the cancellation request. The agent returns to `idle`.

!!! note "Known limitation"
    Dispatch depends on the agent following the reporting instruction. `POST /jobs` is blocking: the HTTP response arrives when the Job finishes.

### Scribe pre-processing

Before sending, `_resolve_job_description` may enrich the description with Scribe context (by size or count) — see [Runtime and Scribe](runtime.md). `job.description` is never mutated.

## Job chaining

Chaining is **manual and explicit**:

- When creating a Job with `previous_job_id`, the previous Job's result (must be `completed` and with a non-empty result) is injected **literally** into the new Job's description.
- **Role guard**: Developer→Developer is blocked — a Developer result must be chained to the Architect for review. All other combinations are allowed.
- Primary use: Developer produces → chained to the Architect for review.

## History and reports

- `GET /jobs` returns the full session history (never purged).
- `write_job_report(job)` persists a **closing report** per `job_id` in `07-informes/<story_id>/<job_id>.md`. If the Job has no `story_id`, it goes to `07-informes/_sin-story/`.

## Job cancellation

- `POST /jobs/{job_id}/cancel` is only valid on a `running` Job (`JobCancellationRejectedError` otherwise).
- Mechanism: `request_cancellation` sets a `threading.Event`; the actual transition to `cancelled` is made by the dispatcher thread in its next polling cycle. This avoids concurrent writes on `job.status`.
- **Does not kill the tmux process**: the runtime may keep thinking (documented limitation).
- The endpoint waits (up to 5s) for the real transition and returns the confirmed state.

## The backlog pipeline

Work above the level of a single Job is driven entirely by the `state` field of a User Story, and orchestrated by a single background Dispatcher (`dispatcher/dispatch_queue_worker.py`) that polls every 5 seconds and reassigns work to whichever agent is free.

### User Story states

```
NO_TASKS → (user clicks "Progresar") → TO_PLAN
    → (Dispatcher assigns a free Architect, US→Tasks landing)
    → (derived from its Tasks: READY | TO_DEVELOP | IN_PROGRESS | IN_REVIEW)
    → (all its Tasks reach DONE) → IN_REVIEW
    → (Architect validates the full Story) → DONE
```

- **`NO_TASKS`**: every new User Story is born in this state — no Tasks yet.
- **`TO_PLAN`**: the user clicked the single **"Progresar"** button; the Story is now a signal for the Dispatcher, which assigns it to a free Architect to run the US→Tasks landing (a deterministic pipeline, no agent Job spent). Once at least one Task is written, the Story stops having its own planning state and reflects the state of its Tasks.
- **Derived state**: with Tasks created, the Story always reflects its **least advanced Task** (`READY` < `TO_DEVELOP` < `IN_PROGRESS` < `IN_REVIEW` < `DONE`) — not an independent operational state.
- **`IN_REVIEW` (User Story)**: triggered automatically once **all** of the Story's Tasks are `DONE`. Here it means the full Story is pending **Architect validation**; it does not move to `DONE` automatically.

The same **"Progresar"** button only acts in `NO_TASKS` (→ `TO_PLAN`); from then on, progress is governed by the Dispatcher and the derived states — a single verb the user reads as "keep moving forward".

### Review — two levels

`IN_REVIEW` means something different for a Task than for a User Story:

1. **Task in `IN_REVIEW`**: the Developer closed the implementation — the Dispatcher assigns it to a free **Tester**, who verifies the Task's acceptance criteria functionally.
   - Pass → the Task moves to `DONE`.
   - Fail → the Task goes **directly back to the same Developer** via the Dispatcher (back to `IN_PROGRESS`), with the Tester's findings attached — no new Task is created. It re-enters `IN_REVIEW` once the Developer closes it again.
   - While a Developer's Task is in `IN_REVIEW`, that Developer is not considered free for a new Task (configurable via the `developer_waits_for_tester_review` system preference) — so no Developer can have two Tasks self-certifying in parallel.

2. **User Story in `IN_REVIEW`**: only once **all** of its Tasks are `DONE`, the Dispatcher assigns the Story to a free **Architect**, who evaluates whether the Story's Tasks fully cover the declared need.
   - Approved (with or without notes) → the Story moves to `DONE`.
   - Rejected for missing coverage → the Architect adds a new Task to the **same** Story — the Story is not promoted to `DONE` in this case.

The Dispatcher repeats this polling cycle for all four levels (US landing, implementation, Task review, final Story validation) with the same "one free agent at a time" rule at each level.

## Job aislado (isolated Job)

Outside the Story-state pipeline, a direct path exists for dispatching one-off work to a specific agent without going through any Story cycle: `POST /jobs` — the human picks the agent and writes (or the UI pre-fills) the description. "Lanzar desarrollo" (context already resolved: a Story's objective plus its pending Tasks) and "Crear Job manual" (free-form description) both use this same mechanism, available from a User Story's detail view in the Backlog screen.

## Planned (not implemented)

- **Full Dispatcher v2** (AF-008): pipeline with declarative dependencies, retries, automatic multi-agent coordination and capability resolution (via AF-010 Capability Engine).
- **Scheduler / global Job queue**: does not exist as a separate entity today.
