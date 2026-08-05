# Runtime and Scribe

## Runtimes

Factory Brain does not run models directly: each launched agent is a **runtime instance** running in a **tmux session** of the dedicated `factory-brain` server (`tmux/manager.py`). The initial prompt is passed as an argument in the startup command itself (not "written" afterwards).

### Claude Code

```bash
claude --dangerously-skip-permissions <prompt>
```

- Command: `claude`; args: `--dangerously-skip-permissions` (maximum autonomy).
- **No model flag**: Claude Code does not support model selection at launch. The prompt is passed as a **positional argument**.
- Runtime type: `claude-code`.

### OpenCode

```bash
opencode --auto [--model provider/model] --prompt "<prompt>"
```

- Command: `opencode`; args: `--auto` (autonomy, respecting explicit "deny" rules).
- **Supports model**: if `model` is passed (format `provider/model`), `--model <model>` is added.
- The prompt is passed with `--prompt`.
- Runtime type: `opencode`.

### Codex

Planned, **not implemented**. The model catalog considers it as a runtime (`codex`) with a commented-out entry in `models.yml`, but `launch_agent` only accepts `claude-code` and `opencode`.

## Hot model management (OpenCode)

`brain/agent_model.py` reads/writes the active model of a running OpenCode agent by interacting with the status bar of the runtime's TUI:

- `get_active_model(agent_id)`: reads the `"Build · …"` pattern from the pane. Returns `None` (without raising) for non-OpenCode runtimes, dead sessions or an unmatched pattern.
- `set_active_model(agent_id, model_name)`: interactive flow (Ctrl+P → Ctrl+X → navigate → Enter) verifying each step with pane captures. Returns `False` on any failure, without mutating the agent's state.
- `get_available_models()` / `get_available_model_entries()`: read the `.factory-brain/models.yml` catalog.
- `resolve_runtime_for_model(model_id)`: maps catalog runtime → real launch type (`claude_code` → `claude-code`).

Exposed in the API: `GET/PUT /agents/{id}/model`, `GET /agents/{id}/available-models`.

## Scribe

**Scribe** is a local deterministic tool (not a conversational agent) that summarizes/indexes documentation with a **local model via Ollama**, without spending Claude Code/OpenCode tokens.

- **Base URL**: `http://localhost:11434` (OpenAI-compatible `/v1/chat/completions` endpoint).
- **Default model**: `qwen2.5-coder:14b`.
- **Closed catalog of operations** (`brain/local_tools/scribe.py`):

| Operation | Use |
|---|---|
| `summarize_document(text)` | Summarizes a long document. |
| `index_documents(texts)` | Thematic index of several documents (e.g. "Index project" action). |
| `resumir_estado_backlog(resultado_json)` | Prose summary of the `brain backlog-status` JSON (never re-reads the backlog). |
| `index_scripts(scripts)` | One-line description per script of the catalog. |

### Explicit degradation

Scribe is **always optional, never a hard dependency**:

- If Ollama does not respond (connection refused, timeout, HTTP error), a `ScribeUnavailableError` is raised with the concrete reason.
- **Job dispatch**: if Scribe triggers but is unavailable, a degradation note is prepended to the instruction and the Job continues.
- **CLI `scribe resumir-backlog`**: exit code 1 with a clear message; never blocks `backlog-status`.
- **`scribe` step of a plan**: unavailability is a hard failure of the step (Scribe is the chosen mechanism, not an accelerator).
- **`indexar` action**: raises `RuntimeError` if Scribe is unavailable.

### Automatic triggering by the Dispatcher

`dispatch_job` decides whether to invoke Scribe to **pre-process context** before sending the task to the agent (token saving):

- **By size**: description > 4000 characters.
- **By count**: ≥ 10 consecutive Jobs over the same `(session_id, agent_id)`.

If it triggers, the enriched context is added to the instruction in a delimited section (`--- Contexto pre-procesado por Scribe ---`); the original Job description **is never mutated** (the enrichment is local to the dispatch). After a successful trigger the consecutive counter resets.
