# Runtime and Scribe

## Runtimes

Atlas Forge does not run models directly: each launched agent is a **runtime instance** running in a **tmux session** of the dedicated `atlas-forge` server (`tmux/manager.py`). The initial prompt is passed as an argument in the startup command itself (not "written" afterwards).

### Claude Code

```bash
claude --dangerously-skip-permissions [--model <model>] <prompt>
```

- Command: `claude`; args: `--dangerously-skip-permissions` (maximum autonomy), plus `--model <model>` when a model is chosen at launch (short aliases `sonnet`/`opus`/`haiku`, or a full model id).
- The prompt is passed as a **positional argument**.
- Runtime type: `claude-code`.

### OpenCode

```bash
opencode --auto [--model provider/model] --prompt "<prompt>"
```

- Command: `opencode`; args: `--auto` (autonomy, respecting explicit "deny" rules).
- `--model <model>` (format `provider/model`) when a model is chosen at launch.
- The prompt is passed with `--prompt`.
- Runtime type: `opencode`.

### Codex

```bash
codex -a never -s workspace-write [--model <model>] <prompt>
```

- Command: `codex`; args: `-a never` (never ask for approval), `-s workspace-write` (sandbox scoped to the workspace, not a full bypass), plus `--model <model>` when chosen at launch.
- The prompt is passed as a **positional argument**.
- Runtime type: `codex`.

## Model selection

Runtime and model are chosen **at launch time only**, for all three runtimes above — there is no on-the-fly model switch for a live agent. `atlas_forge/agent_model.py` exposes `get_active_model(agent_id)` (reads the model currently reported by the runtime's pane, `None` for a dead session or an unrecognized pattern) and `get_available_models()`/`get_available_model_entries()` (reads the `.atlas-forge/models.yml` catalog). `resolve_runtime_for_model(model_id)` maps a catalog entry to its real launch type.

Exposed in the API: `GET /agents/{id}/model`, `GET /agents/{id}/available-models`.

## Scribe

**Scribe** is a local deterministic tool (not a conversational agent) that summarizes/indexes documentation with a **local model via Ollama**, without spending Claude Code/OpenCode tokens.

- **Base URL**: `http://localhost:11434` (OpenAI-compatible `/v1/chat/completions` endpoint).
- **Default model**: `qwen2.5-coder:14b`.
- **Closed catalog of operations** (`atlas_forge/local_tools/scribe.py`):

| Operation | Use |
|---|---|
| `summarize_document(text)` | Summarizes a long document. |
| `index_documents(texts)` | Thematic index of several documents (e.g. "Index project" action). |
| `resumir_estado_backlog(resultado_json)` | Prose summary of the `backlog_status` script JSON (never re-reads the backlog). |
| `index_scripts(scripts)` | One-line description per script of the catalog. |

### Explicit degradation

Scribe is **always optional, never a hard dependency**:

- If Ollama does not respond (connection refused, timeout, HTTP error), a `ScribeUnavailableError` is raised with the concrete reason.
- **Job dispatch**: if Scribe triggers but is unavailable, a degradation note is prepended to the instruction and the Job continues.
- **`backlog_status` generic script with Scribe prose**: the script exits with code 1 and a clear message; Scribe never blocks the report itself.
- **`indexar` action**: raises `RuntimeError` if Scribe is unavailable.

### Automatic triggering by the Dispatcher

`dispatch_job` decides whether to invoke Scribe to **pre-process context** before sending the task to the agent (token saving):

- **By size**: description > 4000 characters.
- **By count**: ≥ 10 consecutive Jobs over the same `(session_id, agent_id)`.

If it triggers, the enriched context is added to the instruction in a delimited section (`--- Contexto pre-procesado por Scribe ---`); the original Job description **is never mutated** (the enrichment is local to the dispatch). After a successful trigger the consecutive counter resets.
