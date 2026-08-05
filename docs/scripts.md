# Scripts

Factory Brain catalogs and runs scripts from the interface, distinguishing two sources:

- **Generic**: fixed catalog bundled with Factory Brain, available in any project of the workspace.
- **Project-specific**: declared by the active project in `.factory-brain/scripts.yml`.

Both run on the active project with the same mechanism (`run_subprocess`, 30s timeout) and are exposed together in `GET /scripts`.

## Generic scripts

Fixed catalog (`brain/workspace/generic_scripts.py`, 7 identifiers):

| id | Name | What it does |
|---|---|---|
| `commit` | Commit changes | `git commit -m <message>` (requires the `message` parameter). |
| `push` | Push to remote | `git push`. |
| `changed_files` | Modified files | `git diff --name-only`. |
| `diff_stat` | Change summary per file | `git diff --stat`. |
| `language_stats` | Language and line breakdown | `cloc --json --quiet` (shows an install hint if `cloc` is missing). |
| `backlog_status` | Backlog status | Deterministic report of the active project's backlog: count per Epic, LISTA/BLOQUEADA items, max-leverage chain. Pure Python, no LLM. |
| `run_tests` | Run the project's tests | `pytest <project>/tests -v` (with `python3 -m pytest` fallback; explicit error if there is no runner or tests directory). |

Examples:

```bash
# Query the backlog status (deterministic, no LLM)
curl -X POST http://<host>:8000/scripts/backlog_status/run

# Commit with a message
curl -X POST http://<host>:8000/scripts/commit/run \
  -H "Content-Type: application/json" \
  -d '{"message": "feat: add X"}'

# Run the project test suite
curl -X POST http://<host>:8000/scripts/run_tests/run
```

## Project-specific scripts

Declared in the active project's `.factory-brain/scripts.yml`:

```yaml
scripts:
  - id: deploy-web
    name: "Deploy web (restart + verification)"
    command: >-
      sudo systemctl restart factory-brain-api.service && ...
    description: "..."
```

- Schema: `scripts:` → list of `{id, name, command, description?}`. `id`, `name` and `command` are required.
- Manifest errors (broken YAML, missing fields) → `MalformedScriptManifestError`.
- Missing manifest = empty project-specific catalog (valid).
- TTL cache 5s validated by `(mtime, size)`.

## API

- `GET /scripts` — combined catalog (generics first, without `command`; then project-specific with `command`). Each item has `origin: "generic" | "particular"` and `description`.
- `POST /scripts/{script_id}/run` — runs (blocking). Optional body `{"message": ...}` (only `commit`). Returns `{success, exit_code, stdout, stderr, error_message, data, prose}`; for `backlog_status`, `data` is the report and `prose` the optional Scribe summary.

Execution failures are returned **structurally** inside the result (never as an HTTP error), except 404 without an active project.

## In the interfaces

- **Web**: "Scripts" tab with Generic/Project groups, visible description and command hidden behind "▶ View command"; a message field only for `commit`.
- **TUI**: Scripts screen with a `[Generic]`/`[Project]` labelled selector.
- **Android app**: Scripts screen with the same catalog.

## Relationship with Scribe

`index_scripts(scripts)` (Scribe) generates a one-line description per script of the combined catalog, queryable by Developer/Architect without spending main-runtime tokens. The operation exists in Scribe's closed catalog.
