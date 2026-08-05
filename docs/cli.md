# CLI

The `brain` entrypoint (`04-src/src/brain/cli/main.py`) starts the TUI by default and exposes two subcommands. The loose CLI commands to launch agents were removed in T-FB002-US02-05: that functionality lives in the Agents screen of the unified TUI.

## `brain` — starts the TUI

```bash
brain
```

Without a subcommand, it starts the Textual application. It checks connectivity against `brain-api` (`http://127.0.0.1:8000` by default), recovers or asks for the active project and shows the Dashboard. It assumes the backend is running.

## `brain backlog-status` — backlog status report

```bash
brain backlog-status <backlog_path> [--json]
```

Computes the backlog status report (same calculation as the `backlog_status` generic script and `GET /backlog`): counts per Epic, LISTA/BLOQUEADA items, max-leverage chain, parse errors.

- `<backlog_path>`: path to the `02-backlog/` directory (required).
- `--json`: JSON output (`render_json_report`); without it, human-readable output (`format_human_report`).
- Exit code is always 0 under normal conditions (an empty backlog is valid and reports "no data").

Example:

```bash
brain backlog-status 02-backlog/
brain backlog-status 02-backlog/ --json
```

## `brain scribe resumir-backlog` — prose synthesis of the backlog (optional)

Optional prose synthesis layer over the `backlog-status` JSON, via Scribe (local Ollama). It reads the JSON from **stdin**:

```bash
brain backlog-status 02-backlog/ --json | brain scribe resumir-backlog
```

Exit codes:

| Code | Meaning |
|---|---|
| `0` | Success: prose summary printed. |
| `1` | Scribe/Ollama unavailable (`ScribeUnavailableError`) — explicit degradation, never blocks `backlog-status`. |
| `2` | The stdin is not a valid backlog JSON. |

## Backend entrypoint

`brain-api` (defined in `pyproject.toml` as `brain.api.main:main`) starts the FastAPI server:

```bash
brain-api            # port 8000
brain-api --host 127.0.0.1   # explicit override for development/local
```

Without `--host`, the host is resolved from the machine's network interface; if it fails, it raises an error — it never degrades to `0.0.0.0`.

## Quick reference

| Command | Description |
|---|---|
| `brain` | Starts the TUI. |
| `brain backlog-status <path> [--json]` | Backlog status report. |
| `brain scribe resumir-backlog` | Prose summary of the backlog JSON (via Scribe). |
| `brain-api` | Starts the API + web backend. |
