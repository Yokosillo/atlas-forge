# Scripts

Atlas Forge cataloga y ejecuta scripts desde la interfaz, distinguiendo dos fuentes:

- **Genéricos**: catálogo fijo incluido con Atlas Forge, disponible en cualquier proyecto del workspace.
- **Específicos de proyecto**: declarados por el proyecto activo en `.atlas-forge/scripts.yml`.

Ambos se ejecutan sobre el proyecto activo con el mismo mecanismo (`run_subprocess`, timeout de 30s) y se exponen juntos en `GET /scripts`.

## Scripts genéricos

Catálogo fijo (`atlas_forge/workspace/generic_scripts.py`, 7 identificadores):

| id | Nombre | Qué hace |
|---|---|---|
| `commit` | Commit de cambios | `git commit -m <message>` (requiere el parámetro `message`). |
| `push` | Push al remoto | `git push`. |
| `changed_files` | Archivos modificados | `git diff --name-only`. |
| `diff_stat` | Resumen de cambios por archivo | `git diff --stat`. |
| `language_stats` | Desglose de lenguaje y líneas | `cloc --json --quiet` (muestra una pista de instalación si falta `cloc`). |
| `backlog_status` | Estado del backlog | Informe determinista del backlog del proyecto activo: conteo por Epic, ítems LISTA/BLOQUEADA, cadena de máximo apalancamiento. Python puro, sin LLM. |
| `run_tests` | Ejecuta los tests del proyecto | `pytest <project>/tests -v` (con fallback `python3 -m pytest`; error explícito si no hay runner o directorio de tests). |

Ejemplos:

```bash
# Consultar el estado del backlog (determinista, sin LLM)
curl -X POST http://<host>:8000/scripts/backlog_status/run

# Commit con un mensaje
curl -X POST http://<host>:8000/scripts/commit/run \
  -H "Content-Type: application/json" \
  -d '{"message": "feat: add X"}'

# Ejecutar la suite de tests del proyecto
curl -X POST http://<host>:8000/scripts/run_tests/run
```

## Scripts específicos de proyecto

Declarados en `.atlas-forge/scripts.yml` del proyecto activo:

```yaml
scripts:
  - id: deploy-web
    name: "Deploy web (restart + verification)"
    command: >-
      sudo systemctl restart atlas-forge-api.service && ...
    description: "..."
```

- Esquema: `scripts:` → lista de `{id, name, command, description?}`. `id`, `name` y `command` son obligatorios.
- Errores de manifest (YAML roto, campos faltantes) → `MalformedScriptManifestError`.
- Manifest ausente = catálogo específico de proyecto vacío (válido).
- Caché TTL 5s validada por `(mtime, size)`.

## API

- `GET /scripts` — catálogo combinado (primero genéricos, sin `command`; luego específicos de proyecto con `command`). Cada ítem tiene `origin: "generic" | "particular"` y `description`.
- `POST /scripts/{script_id}/run` — ejecuta (bloqueante). Cuerpo opcional `{"message": ...}` (solo `commit`). Devuelve `{success, exit_code, stdout, stderr, error_message, data, prose}`; para `backlog_status`, `data` es el informe y `prose` el resumen opcional de Scribe.

Los fallos de ejecución se devuelven **estructuralmente** dentro del resultado (nunca como error HTTP), excepto 404 sin proyecto activo.

## En las interfaces

- **Web**: pestaña "Scripts" con grupos Genéricos/Proyecto, descripción visible y comando oculto tras "▶ View command"; un campo de mensaje solo para `commit`.

## Relación con Scribe

`index_scripts(scripts)` (Scribe) genera una descripción de una línea por script del catálogo combinado, consultable por el Developer/Arquitecto sin gastar tokens del runtime principal. La operación existe en el catálogo cerrado de Scribe.