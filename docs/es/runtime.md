# Runtime y Scribe

## Runtimes

Atlas Forge no ejecuta modelos directamente: cada agente lanzado es una **instancia de runtime** ejecutándose en una **sesión de tmux** del servidor dedicado `atlas-forge` (`tmux/manager.py`). El prompt inicial se pasa como argumento en el propio comando de arranque (no se "escribe" después).

### Claude Code

```bash
claude --dangerously-skip-permissions [--model <model>] <prompt>
```

- Comando: `claude`; args: `--dangerously-skip-permissions` (autonomía máxima), más `--model <model>` cuando se elige un modelo al lanzar (alias cortos `sonnet`/`opus`/`haiku`, o un id de modelo completo).
- El prompt se pasa como **argumento posicional**.
- Tipo de runtime: `claude-code`.

### OpenCode

```bash
opencode --auto [--model provider/model] --prompt "<prompt>"
```

- Comando: `opencode`; args: `--auto` (autonomía, respetando reglas explícitas de "deny").
- `--model <model>` (formato `provider/model`) cuando se elige un modelo al lanzar.
- El prompt se pasa con `--prompt`.
- Tipo de runtime: `opencode`.

### Codex

```bash
codex -a never -s workspace-write [--model <model>] <prompt>
```

- Comando: `codex`; args: `-a never` (nunca pedir aprobación), `-s workspace-write` (sandbox acotado al workspace, no un bypass completo), más `--model <model>` cuando se elige al lanzar.
- El prompt se pasa como **argumento posicional**.
- Tipo de runtime: `codex`.

## Selección de modelo

Runtime y modelo se eligen **en el momento del lanzamiento**. No hay cambio de runtime en caliente para un agente vivo; el cambio de **modelo** en caliente solo está disponible para agentes OpenCode (`PUT /agents/{agent_id}/model`). `atlas_forge/agent_model.py` expone `get_active_model(agent_id)` (lee el modelo que reporta actualmente el pane del runtime, `None` para una sesión muerta o un patrón no reconocido) y `get_available_models()`/`get_available_model_entries()` (leen el catálogo `.atlas-forge/models.yml`). `resolve_runtime_for_model(model_id)` mapea una entrada del catálogo a su tipo de lanzamiento real.

Expuesto en la API: `GET /agents/{id}/model`, `GET /agents/{id}/available-models`.

## Scribe

**Scribe** es una herramienta local determinista (no un agente conversacional) que resume/indexa documentación con un **modelo local vía Ollama**, sin gastar tokens de Claude Code/OpenCode.

- **URL base**: `http://localhost:11434` (endpoint compatible OpenAI `/v1/chat/completions`).
- **Modelo por defecto**: `qwen2.5-coder:14b`.
- **Catálogo cerrado de operaciones** (`atlas_forge/local_tools/scribe.py`):

| Operación | Uso |
|---|---|
| `summarize_document(text)` | Resume un documento largo. |
| `index_documents(texts)` | Índice temático de varios documentos (p. ej. acción "Indexar proyecto"). |
| `resumir_estado_backlog(resultado_json)` | Resumen en prosa del JSON del script `backlog_status` (nunca vuelve a leer el backlog). |
| `index_scripts(scripts)` | Descripción de una línea por script del catálogo. |

### Degradación explícita

Scribe es **siempre opcional, nunca una dependencia dura**:

- Si Ollama no responde (conexión rechazada, timeout, error HTTP), se lanza un `ScribeUnavailableError` con el motivo concreto.
- **Despacho de Jobs**: si Scribe se dispara pero no está disponible, se antepone una nota de degradación a la instrucción y el Job continúa.
- **Script genérico `backlog_status` con prosa de Scribe**: el script sale con código 1 y un mensaje claro; Scribe nunca bloquea el informe en sí.
- **Acción `indexar`**: lanza `RuntimeError` si Scribe no está disponible.

### Disparo automático por el Dispatcher

`dispatch_job` decide si invocar a Scribe para **pre-procesar contexto** antes de enviar la tarea al agente (ahorro de tokens):

- **Por tamaño**: descripción > 4000 caracteres.
- **Por cantidad**: ≥ 10 Jobs consecutivos sobre el mismo `(session_id, agent_id)`.

Si se dispara, el contexto enriquecido se añade a la instrucción en una sección delimitada (`--- Contexto pre-procesado por Scribe ---`); la descripción original del Job **nunca se muta** (el enriquecimiento es local al despacho). Tras un disparo exitoso, el contador consecutivo se reinicia.