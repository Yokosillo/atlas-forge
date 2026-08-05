# Configuración

Los ficheros de configuración de Factory Brain son YAML/JSON legibles y editables a mano, sin tocar código Python ni redeploy.

## `.factory-brain/models.yml` — catálogo de modelos

Declara los modelos disponibles en el sistema: su **identificador real** (el que se pasa a `--model`), nombre visible y **runtime** asociado.

```yaml
# Catalogo de modelos disponibles en Factory Brain.
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

| Campo | Tipo | Descripción |
|---|---|---|
| `id` | string | Identificador real del modelo (se pasa a `--model`). Único. |
| `name` | string | Nombre visible en las interfaces. |
| `runtime` | string | Uno de `opencode`, `claude_code`, `codex`. |

Reglas de validación (`models_catalog.py`): runtime soportado, sin IDs duplicados, campos obligatorios; catálogo vacío o malformado → `MalformedModelCatalogError` con mensaje concreto. Los cambios se reflejan al recargar (caché TTL con validación de mtime/size); los errores de parseo no se cachean.

!!! note "Codex"
    El runtime `codex` está contemplado en el catálogo pero **no activo**: la entrada `openai/gpt-5` está comentada porque Codex queda fuera del alcance actual del roadmap. `launch_agent` solo acepta `claude-code` y `opencode` por ahora.

## `.factory-brain/scripts.yml` — scripts particulares del proyecto

Declara los scripts propios del proyecto activo (no genéricos). Ver [Scripts](scripts.md).

```yaml
scripts:
  - id: deploy-web
    name: "Deploy web (reinicio + verificación)"
    command: >-
      sudo systemctl restart factory-brain-api.service && ...
    description: >-
      Reinicia factory-brain-api.service y verifica que /ui/ responde
      en la IP Tailscale de esta máquina.
```

| Campo | Tipo | Obligatorio | Descripción |
|---|---|---|---|
| `id` | string | Sí | Identificador único. |
| `name` | string | Sí | Nombre visible. |
| `command` | string | Sí | Comando shell a ejecutar. |
| `description` | string | No | Descripción mostrada en las interfaces. |

## `model_preferences.json` — preferencias de modelos

Estado editable por el usuario, distinto del catálogo. Ubicación: `<state_dir>/model_preferences.json` (por defecto `~/.local/share/brain/`).

```json
{
  "enabled_model_ids": ["opencode-go/deepseek-v4-flash", "claude-code"],
  "default_model_by_role": {"developer": "opencode-go/deepseek-v4-flash"}
}
```

| Campo | Tipo | Semántica |
|---|---|---|
| `enabled_model_ids` | `list[string]` | Modelos habilitados. **Vacío = todos habilitados.** |
| `default_model_by_role` | `dict[string, string]` | Modelo por defecto por rol (`developer`, `critic`, `arquitecto`, `tester`). |

Se edita desde la pestaña **Modelos** de la web (`GET/PUT /models/preferences`). Si el fichero no existe, se usan los defaults (`enabled_model_ids: []`, `default_model_by_role: {}`).

## Estado persistido (`state_dir`)

| Fichero | Contenido |
|---|---|
| `active_project.json` | Proyecto activo seleccionado (persistido). |
| `model_preferences.json` | Preferencias de modelos (habilitados + defaults). |

`state_dir` por defecto: `$XDG_DATA_HOME/brain` o `~/.local/share/brain`.

## Variables de entorno

| Variable | Uso |
|---|---|
| `GOOGLE_CLOUD_PROJECT` | Contexto GCP del entorno de despliegue (no usado por el código de `brain`; vive en `.env` del proyecto). |
| `GOOGLE_CLOUD_LOCATION` | Idem. |

El paquete `brain` no define variables de entorno obligatorias: el host de la API se resuelve con `tailscale ip -4` (o `--host` explícito), y Scribe apunta a `http://localhost:11434` por defecto.

## Deployment (systemd)

`deploy/systemd/factory-brain-api.service` es la fuente de verdad del servicio:

- `After=network.target tailscaled.service` — espera a que exista la interfaz Tailscale.
- `User/Group=secure_ai_atlas` — no-root, mismo usuario operador.
- `WorkingDirectory=<workspace root>` — para que el proceso vea los repos reales.
- `ExecStart=.../04-src/.venv/bin/brain-api`.
- `Restart=on-failure` — un `systemctl stop` deliberado no se reinicia.

Instalación:

```bash
sudo cp deploy/systemd/factory-brain-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now factory-brain-api.service
```
