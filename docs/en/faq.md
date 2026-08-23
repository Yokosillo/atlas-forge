# FAQ and troubleshooting

## Frequently asked questions

### Is Atlas Forge an IDE or an agent framework?

No. It is a **coordination** platform. Agents execute with their own runtimes (Claude Code, OpenCode) and models; Atlas Forge decides who does what, when, and keeps context alive.

### What runtimes does it support?

Claude Code and OpenCode (launched in tmux sessions). **Codex is not supported yet** — it appears in the model catalog as a commented-out entry (future). See [Runtime and Scribe](runtime.md).

### Do I need Ollama?

No. Scribe (Ollama) is **optional**: it is a token saver for reads/summaries. Without Ollama everything keeps working, degrading explicitly (notes in Jobs, exit code 1 in the summary CLI, hard failure only on the `indexar` action that explicitly uses Scribe).

### How do I select an agent's model?

When launching an agent you choose role + model from the catalog (`GET /agents/options`). Only OpenCode supports a model. In hot, you can change the model of a launched OpenCode agent (`PUT /agents/{agent_id}/model`). Preferences (enabled + default per role) are managed in the Models tab / `models.yml`.

### Where is the state stored?

Active project and model preferences in `~/.local/share/atlas_forge/`. Session, agents and Jobs **in the memory of the `atlas-forge-api` process** — lost when the backend restarts. See [Configuration](configuration.md).

### Is there a plugin system or MCP?

**No.** The Plugin System (AF-011) is planned but not implemented. Any new integration is done by code in `04-src/`.

### Why is the backlog the center of the product?

Since Phase 0.9 (2026-08-05) the product is **backlog-centric**: all work is deployed from the backlog (Epic → US → Task → Implement) with buttons, not by writing Markdown by hand or talking to each agent separately. See [Backlog and pipeline](backlog.md).

## Troubleshooting

### The backend does not start

If `atlas-forge-api` without `--host` cannot resolve the machine's network interface, it raises an error with the reason. Solutions:
- Verify that the network interface is up.
- For development/local: `atlas-forge-api --host 127.0.0.1`.

### The web does not connect ("No connection to the backend")

- Confirm `atlas-forge-api` is running (`systemctl status atlas-forge-api` or `curl http://<host>:8000/health`).
- Access via the correct IP/URL: the web is served at `/ui/` of the same process, same-origin (no CORS).

### An agent appears as `unavailable`

Liveness is lazy: if the runtime's tmux session died without you asking, the agent transitions to `unavailable` when queried. Relaunch the agent (a `stopped`/`unavailable` agent is not reused; it is replaced).

### A Job never finishes (timeout)

`POST /jobs` is blocking and reporting is cooperative (the agent writes a file with a marker). If the agent does not follow the reporting instruction, the Job fails by timeout (`JobReportTimeoutError`) after 30s by default. Options:
- Cancel the Job (`POST /jobs/{job_id}/cancel`).
- Stop the agent (`POST /agents/{id}/stop`) if it is stuck.
- Query the agent's pane (`GET /agents/{id}/pane`) to see what it is doing.

### A Task never gets picked up

Confirm its `state` is `TO_DEVELOP` (not `READY`) — the Dispatcher only picks up eligible states, and a `READY` Task waits to be queued as `TO_DEVELOP`. Also confirm a Developer is `idle` and its dependencies are all `DONE`.

### Scribe is not available

- Confirm Ollama is running: `curl http://localhost:11434` and `ollama list` (the `qwen2.5-coder:14b` model must exist).
- The rest of the system works without Scribe; only the `indexar` action fails explicitly.

### I want to change an agent's model

Model (and runtime) are chosen at launch — stop the agent and relaunch it with the model you want. There is no on-the-fly model switch for a live agent.

### The project's scripts do not appear

- The manifest must be in `.atlas-forge/scripts.yml` of the **active project** (not the Atlas Forge repository).
- Manifest errors → `MalformedScriptManifestError` when querying `GET /scripts`.
- The TTL cache is 5s; wait or query again.

### Questions about the backlog

- Canonical state lives in `02-backlog/` (Epics, User Stories, Tasks). `07-informes/` contains only closing reports, not the current version of an Epic.
- If `GET /backlog/{item_id}` returns 404 with a parse reason, the file does not comply with the schema (see `02-backlog/README.md`).
