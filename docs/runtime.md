# Runtime y Scribe

## Runtimes

Factory Brain no ejecuta modelos directamente: cada agente lanzado es una **instancia de runtime** ejecutándose en una **sesión tmux** del servidor dedicado `factory-brain` (`tmux/manager.py`). El prompt inicial se pasa como argumento en el propio comando de arranque (no se "escribe" después).

### Claude Code

```bash
claude --dangerously-skip-permissions <prompt>
```

- Comando: `claude`; args: `--dangerously-skip-permissions` (máxima autonomía).
- **Sin flag de modelo**: Claude Code no admite selección de modelo desde el arranque. El prompt se pasa como **argumento posicional**.
- Runtime type: `claude-code`.

### OpenCode

```bash
opencode --auto [--model provider/model] --prompt "<prompt>"
```

- Comando: `opencode`; args: `--auto` (autonomía, respetando reglas "deny" explícitas).
- **Soporta modelo**: si se pasa `model` (formato `provider/model`), se añade `--model <model>`.
- El prompt se pasa con `--prompt`.
- Runtime type: `opencode`.

### Codex

Planificado, **no implementado**. El catálogo de modelos lo contempla como runtime (`codex`) con entrada comentada en `models.yml`, pero `launch_agent` solo acepta `claude-code` y `opencode`.

## Gestión de modelos en caliente (OpenCode)

`brain/agent_model.py` lee/escribe el modelo activo de un agente OpenCode en ejecución interactuando con la barra de estado de la TUI del runtime:

- `get_active_model(agent_id)`: lee el patrón `"Build · …"` del pane. Devuelve `None` (sin lanzar excepción) para runtime no-OpenCode, sesión muerta o patrón no encontrado.
- `set_active_model(agent_id, model_name)`: flujo interactivo (Ctrl+P → Ctrl+X → navegar → Enter) verificando cada paso con capturas de pane. Devuelve `False` ante cualquier fallo, sin mutar el estado del agente.
- `get_available_models()` / `get_available_model_entries()`: leen el catálogo `.factory-brain/models.yml`.
- `resolve_runtime_for_model(model_id)`: mapea runtime de catálogo → tipo de lanzamiento real (`claude_code` → `claude-code`).

Expuestos en la API: `GET/PUT /agents/{id}/model`, `GET /agents/{id}/available-models`.

## Scribe

**Scribe** es una herramienta determinista local (no un agente conversacional) que resume/indexa documentación con un **modelo local vía Ollama**, sin gastar tokens de Claude Code/OpenCode.

- **Base URL**: `http://localhost:11434` (endpoint OpenAI-compatible `/v1/chat/completions`).
- **Modelo por defecto**: `qwen2.5-coder:14b`.
- **Catálogo cerrado de operaciones** (`brain/local_tools/scribe.py`):

| Operación | Uso |
|---|---|
| `summarize_document(text)` | Resume un documento largo. |
| `index_documents(texts)` | Índice temático de varios documentos (p. ej. acción "Indexar proyecto"). |
| `resumir_estado_backlog(resultado_json)` | Resumen en prosa del JSON de `brain backlog-status` (nunca relee el backlog). |
| `index_scripts(scripts)` | Descripción de una línea por script del catálogo. |

### Degradación explícita

Scribe es **siempre opcional, nunca una dependencia dura**:

- Si Ollama no responde (conexión rechazada, timeout, HTTP error), se lanza `ScribeUnavailableError` con el motivo concreto.
- **Dispatch de Job**: si Scribe se dispara pero no está disponible, se antepone una nota de degradación a la instrucción y el Job sigue su curso.
- **CLI `scribe resumir-backlog`**: exit code 1 con mensaje claro; nunca bloquea `backlog-status`.
- **Paso `scribe` de un plan**: la indisponibilidad es fallo duro del paso (Scribe es el mecanismo elegido, no un acelerador).
- **Acción `indexar`**: lanza `RuntimeError` si Scribe no está disponible.

### Disparo automático por el Dispatcher

`dispatch_job` decide si invocar a Scribe para **pre-procesar contexto** antes de enviar la tarea al agente (ahorro de tokens):

- **Por tamaño**: descripción > 4000 caracteres.
- **Por conteo**: ≥ 10 Jobs consecutivos sobre el mismo `(session_id, agent_id)`.

Si se dispara, el contexto enriquecido se añade a la instrucción en una sección delimitada (`--- Contexto pre-procesado por Scribe ---`); la descripción original del Job **nunca se muta** (el enriquecimiento es local al despacho). Tras un disparo exitoso se reinicia el contador consecutivo.
