# Configuration

Factory Brain's configuration files are human-readable YAML/JSON editable by hand, without touching Python code or redeploying.

## `.factory-brain/models.yml` — model catalog

Declares the models available in the system: their **real identifier** (the one passed to `--model`), visible name and associated **runtime**.

```yaml
# Catalog of models available in Factory Brain.
models:
  - id: opencode-go/deepseek-v4-flash
    name: "DeepSeek V4 Flash"
    runtime: opencode

  - id: opencode-go/deepseek-v4-pro
    name: "DeepSeek V4 Pro"
    runtime: opencode

  - id: opencode-go/glm-5.2
    name: "GLM 5.2"
    runtime: opencode

  - id: opencode-go/kimi-k3
    name: "Kimi K3"
    runtime: opencode

  - id: claude-code
    name: "Claude Code"
    runtime: claude_code
```

| Field | Type | Description |
|---|---|---|
| `id` | string | Real identifier of the model (passed to `--model`). Unique. |
| `name` | string | Name visible in the interfaces. |
| `runtime` | string | One of `opencode`, `claude_code`, `codex`. |

Validation rules (`models_catalog.py`): supported runtime, no duplicate IDs, mandatory fields; an empty or malformed catalog → `MalformedModelCatalogError` with a concrete message. Changes are reflected on reload (TTL cache validated by mtime/size); parse errors are not cached.

!!! note "Codex"
    The `codex` runtime is considered in the catalog but **not active**: the `openai/gpt-5` entry is commented out because Codex is outside the current roadmap scope. `launch_agent` only accepts `claude-code` and `opencode` for now.

## `.factory-brain/scripts.yml` — project-specific scripts

Declares the active project's own scripts (not generics). See [Scripts](scripts.md).

```yaml
scripts:
  - id: deploy-web
    name: "Deploy web (restart + verification)"
    command: >-
      sudo systemctl restart factory-brain-api.service && ...
    description: >-
      Restarts factory-brain-api.service and verifies that /ui/ responds.
```

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | string | Yes | Unique identifier. |
| `name` | string | Yes | Visible name. |
| `command` | string | Yes | Shell command to run. |
| `description` | string | No | Description shown in the interfaces. |

## `model_preferences.json` — model preferences

User-editable state, distinct from the catalog. Location: `<state_dir>/model_preferences.json` (default `~/.local/share/brain/`).

```json
{
  "enabled_model_ids": ["opencode-go/deepseek-v4-flash", "claude-code"],
  "default_model_by_role": {"developer": "opencode-go/deepseek-v4-flash"}
}
```

| Field | Type | Semantics |
|---|---|---|
| `enabled_model_ids` | `list[string]` | Enabled models. **Empty = all enabled.** |
| `default_model_by_role` | `dict[string, string]` | Default model per role (`developer`, `arquitecto`, `tester`, `ux`, `auditor_oss`, `documentador`). |

It is edited from the **Models** tab of the web (`GET/PUT /models/preferences`). If the file does not exist, the defaults are used (`enabled_model_ids: []`, `default_model_by_role: {}`).

## Persisted state (`state_dir`)

| File | Content |
|---|---|
| `active_project.json` | Selected active project (persisted). |
| `model_preferences.json` | Model preferences (enabled + defaults). |

`state_dir` defaults to `$XDG_DATA_HOME/brain` or `~/.local/share/brain`.

## Deployment (systemd)

`deploy/systemd/factory-brain-api.service` is the source of truth for the service:

- Runs `brain-api` as a non-root operator user.
- `WorkingDirectory=<workspace root>` — so the process sees the real repos.
- `ExecStart=.../04-src/.venv/bin/brain-api`.
- `Restart=on-failure` — a deliberate `systemctl stop` is not restarted.

Installation:

```bash
sudo cp deploy/systemd/factory-brain-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now factory-brain-api.service
```
