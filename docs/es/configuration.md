# Configuración

Los ficheros de configuración de Atlas Forge son YAML/JSON legibles por humanos y editables a mano, sin tocar código Python ni re-desplegar.

## `.atlas-forge/models.yml` — catálogo de modelos

Declara los modelos disponibles en el sistema: su **identificador real** (el que se pasa a `--model`), nombre visible y **runtime** asociado.

```yaml
# Catálogo de modelos disponibles en Atlas Forge.
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

Los tres runtimes (`opencode`, `claude_code`, `codex`) están soportados por `launch_agent`. El catálogo real del proyecto declara modelos de los tres.

## `.atlas-forge/scripts.yml` — scripts específicos de proyecto

Declara los scripts propios del proyecto activo (no los genéricos). Ver [Scripts](scripts.md).

```yaml
scripts:
  - id: deploy-web
    name: "Deploy web (restart + verification)"
    command: >-
      sudo systemctl restart atlas-forge-api.service && ...
    description: >-
      Reinicia atlas-forge-api.service y verifica que /ui/ responde.
```

| Campo | Tipo | Obligatorio | Descripción |
|---|---|---|---|
| `id` | string | Sí | Identificador único. |
| `name` | string | Sí | Nombre visible. |
| `command` | string | Sí | Comando shell a ejecutar. |
| `description` | string | No | Descripción mostrada en las interfaces. |

## `model_preferences.json` — preferencias de modelo

Estado editable por el usuario, distinto del catálogo. Ubicación: `<state_dir>/model_preferences.json` (por defecto `~/.local/share/atlas_forge/`).

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

## `.atlas-forge/version.yml` — esquema de versiones

Declara el esquema de versiones de entrega del producto. Cada User Story del backlog declara a qué versión pertenece (`version:` en su frontmatter).

```yaml
current_closed: null
open: "0.9"
future:
  - "0.9.1"
  - "0.9.2"
```

| Campo | Semántica |
|---|---|
| `current_closed` | Última versión cerrada y entregada (`null` si no se ha cerrado ninguna). |
| `open` | Versión abierta en desarrollo (a la que se asigna trabajo nuevo). |
| `future` | Versiones posteriores planificadas, en orden. |

Se actualiza con `04-src/scripts/close_version.py` cuando se cierra una versión.

## Estado persistido (`state_dir`)

| Fichero | Contenido |
|---|---|
| `active_project.json` | Proyecto activo seleccionado (persistido). |
| `model_preferences.json` | Preferencias de modelo (habilitados + valores por defecto). |
| `version.yml` | Esquema de versiones (ver arriba). |

`state_dir` por defecto es `$XDG_DATA_HOME/atlas_forge` o `~/.local/share/atlas_forge`.

## Preferencias del sistema (`GET/PUT /system/preferences`)

Preferencias de configuración a nivel de sistema, persistidas independientemente de cualquier proyecto:

| Clave | Tipo | Default | Descripción |
|---|---|---|---|
| `max_simultaneous_developers` | int | `3` | Límite de Developers simultáneos. |
| `difficulty_model_map` | dict | `Baja:1, Media:2, Alta:4, Crítica:5` | Mapa dificultad→tier de modelo para la asignación por dificultad. |
| `developer_waits_for_tester_review` | bool | `true` | Un Developer no coge Task nueva mientras su Task anterior está en `IN_REVIEW` del Tester. |
| `autonomous_config` | dict | `enabled: false` | Escalado autónomo: límites por rol (`developer`, `tester`), tasks por agente y máximo total. |
| `backlog_multiple_expansion` | `"single"` \| `"multi"` | `"single"` | Expansión de epis en el listado del backlog. |
| `tui_enabled` | bool | `false` | (Legacy, sin interfaz terminal activa.) |
| `auto_reenqueue_orphaned` | bool | `false` | Re-encolar automáticamente tasks huérfanas. |

## Despliegue (systemd)

`deploy/systemd/atlas-forge-api.service` es la fuente de verdad del servicio:

- Ejecuta `atlas-forge-api` como usuario operador no root.
- `WorkingDirectory=<raíz del workspace>` — para que el proceso vea los repos reales.
- `ExecStart=.../04-src/.venv/bin/atlas-forge-api`.
- `Restart=on-failure` — un `systemctl stop` deliberado no se reinicia.

Instalación:

```bash
sudo cp deploy/systemd/atlas-forge-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now atlas-forge-api.service
```