# Scripts

Factory Brain cataloga y ejecuta scripts desde la interfaz, distinguiendo dos fuentes:

- **Genéricos**: catálogo fijo que Factory Brain trae consigo, disponibles en cualquier proyecto del workspace.
- **Particulares**: declarados por el proyecto activo en `.factory-brain/scripts.yml`.

Ambos se ejecutan sobre el proyecto activo con el mismo mecanismo (`run_subprocess`, 30s timeout) y se exponen juntos en `GET /scripts`.

## Scripts genéricos

Catálogo fijo (`brain/workspace/generic_scripts.py`, 7 identificadores):

| id | Nombre | Qué hace |
|---|---|---|
| `commit` | Commit de cambios | `git commit -m <message>` (requiere parámetro `message`). |
| `push` | Push al remoto | `git push`. |
| `changed_files` | Ficheros modificados | `git diff --name-only`. |
| `diff_stat` | Resumen de cambios por fichero | `git diff --stat`. |
| `language_stats` | Desglose de lenguajes y líneas | `cloc --json --quiet` (se muestra pista de instalación si `cloc` falta). |
| `backlog_status` | Estado del backlog | Informe determinista del backlog del proyecto activo: conteo por Epic, items LISTA/BLOQUEADA, cadena de máximo apalancamiento. Puro Python, sin LLM. |
| `run_tests` | Ejecutar tests del proyecto | `pytest <proyecto>/tests -v` (con fallback `python3 -m pytest`; error explícito si no hay runner o directorio de tests). |

Ejemplos:

```bash
# Consultar el estado del backlog (determinista, sin LLM)
curl -X POST http://<host>:8000/scripts/backlog_status/run

# Commit con mensaje
curl -X POST http://<host>:8000/scripts/commit/run \
  -H "Content-Type: application/json" \
  -d '{"message": "feat: añade X"}'

# Ejecutar la suite de tests del proyecto
curl -X POST http://<host>:8000/scripts/run_tests/run
```

## Scripts particulares del proyecto

Declarados en `.factory-brain/scripts.yml` del proyecto activo:

```yaml
scripts:
  - id: deploy-web
    name: "Deploy web (reinicio + verificación)"
    command: >-
      sudo systemctl restart factory-brain-api.service && ...
    description: "..."
```

- Esquema: `scripts:` → lista de `{id, name, command, description?}`. `id`, `name` y `command` son obligatorios.
- Errores de manifiesto (YAML roto, campos faltantes) → `MalformedScriptManifestError`.
- Manifiesto ausente = catálogo particular vacío (válido).
- Caché TTL 5s validada por `(mtime, size)`.

El repositorio de Factory Brain declara el script particular `deploy-web` (reinicia el servicio systemd y verifica que `/ui/` responda en la IP Tailscale).

## API

- `GET /scripts` — catálogo combinado (genéricos primero, sin `command`; luego particulares con `command`). Cada item tiene `origin: "generic" | "particular"` y `description`.
- `POST /scripts/{script_id}/run` — ejecuta (bloqueante). Body opcional `{"message": ...}` (solo `commit`). Devuelve `{success, exit_code, stdout, stderr, error_message, data, prose}`; para `backlog_status`, `data` es el informe y `prose` el resumen opcional de Scribe.

Los fallos de ejecución se devuelven **estructuralmente** dentro del resultado (nunca como error HTTP), salvo 404 sin proyecto activo.

## En las interfaces

- **Web**: pestaña "Scripts" con grupos Genéricos/Proyecto, descripción visible y comando oculto tras "▶ Ver comando"; campo de mensaje solo para `commit`.
- **TUI**: pantalla Scripts con selector etiquetado `[Genérico]`/`[Proyecto]`.
- **App Android**: pantalla Scripts con el mismo catálogo.

## Relación con Scribe

`index_scripts(scripts)` (Scribe) genera una descripción de una línea por script del catálogo combinado, consultable por Developer/Arquitecto sin gastar tokens del runtime principal. La operación existe en el catálogo cerrado de Scribe.
