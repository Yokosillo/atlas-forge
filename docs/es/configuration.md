# Configuración

Los ficheros de configuración de Factory Brain son YAML/JSON legibles por humanos y editables a mano, sin tocar código Python ni re-desplegar.

## `.factory-brain/models.yml` — catálogo de modelos

Declara los modelos disponibles en el sistema: su **identificador real** (el que se pasa a `--model`), nombre visible y **runtime** asociado.

```yaml
# Catálogo de modelos disponibles en Factory Brain.
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

Reglas de validación (`models_catalog.py`): runtime soportado, sin IDs duplicados, campos obligatorios; un catálogo vacío o malformado → `MalformedModelCatalogError` con un mensaje concreto. Los cambios se reflejan al recargar (caché TTL validada por mtime/size); los errores de parseo no se cachean.

!!! note "Codex"
    El runtime `codex` se considera en el catálogo pero **no está activo**: la entrada `openai/gpt-5` está comentada porque Codex está fuera del alcance del roadmap actual. `launch_agent` solo acepta `claude-code` y `opencode` por ahora.

## `.factory-brain/scripts.yml` — scripts específicos de proyecto

Declara los scripts propios del proyecto activo (no los genéricos). Ver [Scripts](scripts.md).

```yaml
scripts:
  - id: deploy-web
    name: "Deploy web (restart + verification)"
    command: >-
      sudo systemctl restart factory-brain-api.service && ...
    description: >-
      Reinicia factory-brain-api.service y verifica que /ui/ responde.
```

| Campo | Tipo | Obligatorio | Descripción |
|---|---|---|---|
| `id` | string | Sí | Identificador único. |
| `name` | string | Sí | Nombre visible. |
| `command` | string | Sí | Comando shell a ejecutar. |
| `description` | string | No | Descripción mostrada en las interfaces. |

## `model_preferences.json` — preferencias de modelo

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
| `default_model_by_role` | `dict[string, string]` | Modelo por defecto por rol (`developer`, `arquitecto`, `tester`, `ux`, `auditor_oss`, `documentador`). |

Se edita desde la pestaña **Models** de la web (`GET/PUT /models/preferences`). Si el fichero no existe, se usan los valores por defecto (`enabled_model_ids: []`, `default_model_by_role: {}`).

## Estado persistido (`state_dir`)

| Fichero | Contenido |
|---|---|
| `active_project.json` | Proyecto activo seleccionado (persistido). |
| `model_preferences.json` | Preferencias de modelo (habilitados + valores por defecto). |

`state_dir` por defecto es `$XDG_DATA_HOME/brain` o `~/.local/share/brain`.

## Despliegue (systemd)

`deploy/systemd/factory-brain-api.service` es la fuente de verdad del servicio:

- Ejecuta `brain-api` como usuario operador no root.
- `WorkingDirectory=<raíz del workspace>` — para que el proceso vea los repos reales.
- `ExecStart=.../04-src/.venv/bin/brain-api`.
- `Restart=on-failure` — un `systemctl stop` deliberado no se reinicia.

Instalación:

```bash
sudo cp deploy/systemd/factory-brain-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now factory-brain-api.service
```