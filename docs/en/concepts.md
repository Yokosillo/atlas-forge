# Concepts

Factory Brain's domain model. Terminology used throughout the documentation, the API and the interfaces.

## Project

A Git repository of the workspace. It is the **main unit of work**: Factory Brain never operates on arbitrary directories. The active project is chosen at startup and persisted to disk.

- Discovery: `os.walk` of the workspace looking for `.git` directories (5s cache TTL).
- `Project`: `{id (path), name, path, repository, workspace_id}`.

## Workspace

The root where repositories are discovered (e.g. `factoria-software/`). A workspace contains multiple projects.

## Development session

A live working environment over a project. States: `created` → `active` → `closed`. When you choose a project its session starts; when you change project, not-stopped agents are stopped and the previous one is closed.

The session keeps: the active project, launched agents, the Job history and context. **It lives in the memory of the `brain-api` process** (not persisted to disk).

## Agent

An instance of a **role** running on a **runtime** in a tmux session. It is not a language model nor a generic process: it is role + prompt + runtime + state.

- Roles: `developer`, `arquitecto`, `tester`, plus `auditor_oss`/`ux` (declared in the role registry — see [Agents](agents.md)).
- States: `idle` → `working` / `unavailable` / `stopped`; `unavailable → idle`; `stopped` is terminal (must relaunch) — except Developer, which never reaches `stopped`: stopping it deletes the instance outright instead of pausing it.
- Reuse: when launching a reusable role (Architect, Tester), the existing live agent is reused instead of duplicating. Developer always creates a new instance on launch (up to a configurable simultaneous limit), never reused.

## Runtime

An external AI executable launched in tmux: **Claude Code**, **OpenCode** or **Codex**. Runtime and model are chosen explicitly at launch time — no on-the-fly switch for a live agent. See [Runtime and Scribe](runtime.md).

## Job

A unit of work sent to an agent: a text description. States: `created → running → {completed | failed | cancelled}`.

- `POST /jobs` is **blocking**: the response arrives when the Job finishes.
- The result is reported cooperatively (the agent writes its output to a file with a final marker).
- **Chaining**: you can pass `previous_job_id`; the previous Job's result is injected literally into the new Job's description. Developer→Developer is blocked.
- Full session history via `GET /jobs`.

## The Dispatcher

A single background process that polls every 5 seconds and moves work forward, driven purely by each item's `state`: queues Tasks `READY` as `TO_DEVELOP`, assigns Tasks `TO_DEVELOP` to a free Developer (`IN_PROGRESS`), hands a Task in `IN_REVIEW` to a free Tester, and a User Story with all its Tasks `DONE` to a free Architect for final validation (and a US in `TO_PLAN` to a free Architect to land it into Tasks). See [Jobs and the work pipeline](jobs.md#the-backlog-pipeline).

## Scribe

A local deterministic tool (not a conversational agent) that summarizes/indexes documentation with a local model via Ollama. Operations: `summarize_document`, `index_documents`, `resumir_estado_backlog`, `index_scripts`. Used by the Dispatcher to save tokens. See [Runtime and Scribe](runtime.md).

## Script

- **Generic** (bundled with Factory Brain, 7): `commit`, `push`, `changed_files`, `diff_stat`, `language_stats`, `backlog_status`, `run_tests`.
- **Project-specific** (of the project, `.factory-brain/scripts.yml`): e.g. `deploy-web`.

## Backlog

The set of Epics, User Stories and Tasks of the active project (`02-backlog/`), with state, dependencies, priority and phase. It is the **central control panel** of the product: work is deployed from here. See [Backlog and pipeline](backlog.md).

## Typical workflow

```mermaid
sequenceDiagram
    participant U as User
    participant B as brain-api
    participant A as Architect
    participant D as Developer
    participant T as Tester

    U->>B: Select project (POST /project)
    B->>B: Start development session
    U->>B: Click "Progresar" on a new User Story
    B->>A: Land the Story into Tasks (TO_PLAN)
    A-->>B: Tasks written, US reflects the least advanced Task
    B->>D: Dispatch each Task (TO_DEVELOP → IN_PROGRESS)
    D-->>B: Task closed → IN_REVIEW
    B->>T: Verify the Task
    T-->>B: PASS → Task DONE
    B->>A: All Tasks DONE → US IN_REVIEW (final validation)
    A-->>B: APROBADO → US DONE
```

## Quick glossary

| Term | Meaning |
|---|---|
| **Project** | Git repository, unit of work |
| **Session** | Live environment over a project |
| **Agent** | Role + runtime + prompt in tmux |
| **Runtime** | Claude Code / OpenCode / Codex |
| **Job** | Text task to an agent |
| **Dispatcher** | Background process that drives the backlog pipeline |
| **Scribe** | Local summarization/indexing via Ollama |
| **Developer** | Implements Tasks |
| **Tester** | Functionally verifies a closed Task |
| **Architect** | Lands the backlog (Epic→US→Task), issues verdicts on Tasks/Stories, and converses about existing Epics (read-only) |
