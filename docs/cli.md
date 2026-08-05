# CLI

El entrypoint `brain` (`04-src/src/brain/cli/main.py`) arranca la TUI por defecto y expone dos subcomandos. Los comandos CLI sueltos para lanzar agentes se retiraron en T-FB002-US02-05: esa funcionalidad vive en la pantalla Agentes de la TUI unificada.

## `brain` — arranca la TUI

```bash
brain
```

Sin subcomando, arranca la aplicación Textual. Comprueba conectividad contra `brain-api` (`http://127.0.0.1:8000` por defecto), recupera o pide el proyecto activo y muestra el Dashboard. Asume que el backend está corriendo.

## `brain backlog-status` — informe de estado del backlog

```bash
brain backlog-status <backlog_path> [--json]
```

Calcula el informe de estado del backlog (mismo cálculo que el script genérico `backlog_status` y que `GET /backlog`): conteos por Epic, items LISTA/BLOQUEADA, cadena de máximo apalancamiento, errores de parseo.

- `<backlog_path>`: ruta al directorio `02-backlog/` (obligatorio).
- `--json`: salida JSON (`render_json_report`); sin él, salida legible (`format_human_report`).
- Exit code siempre 0 en condiciones normales (un backlog vacío es válido y reporta "sin datos").

Ejemplo:

```bash
brain backlog-status 02-backlog/
brain backlog-status 02-backlog/ --json
```

## `brain scribe resumir-backlog` — síntesis en prosa del backlog (opcional)

Capa opcional de síntesis en prosa sobre el JSON de `backlog-status`, vía Scribe (Ollama local). Lee el JSON de **stdin**:

```bash
brain backlog-status 02-backlog/ --json | brain scribe resumir-backlog
```

Exit codes:

| Código | Significado |
|---|---|
| `0` | Éxito: resumen en prosa impreso. |
| `1` | Scribe/Ollama no disponible (`ScribeUnavailableError`) — degradación explícita, nunca bloquea `backlog-status`. |
| `2` | El stdin no es un JSON de backlog válido. |

## Entrypoint del backend

`brain-api` (definido en `pyproject.toml` como `brain.api.main:main`) arranca el servidor FastAPI:

```bash
brain-api            # host resuelto como IP Tailscale, puerto 8000
brain-api --host 127.0.0.1   # override explícito para desarrollo/local
```

Sin `--host`, `resolve_tailscale_host()` ejecuta `tailscale ip -4` (timeout 5s); si falla, levanta error — nunca degrada a `0.0.0.0`.

## Referencia rápida

| Comando | Descripción |
|---|---|
| `brain` | Arranca la TUI. |
| `brain backlog-status <path> [--json]` | Informe de estado del backlog. |
| `brain scribe resumir-backlog` | Resumen en prosa del JSON del backlog (vía Scribe). |
| `brain-api` | Arranca el backend API + web. |
