# Primeros pasos

Instalación, configuración y primeras ejecuciones de Atlas Forge.

## Requisitos

- **Python ≥ 3.10**
- **tmux** (los runtimes se ejecutan en sesiones de tmux; el socket por defecto es `atlas-forge`)
- Un **runtime de IA** instalado y disponible en el PATH (al menos uno):
  - **OpenCode** (CLI `opencode`) — soporta selección de modelo.
  - **Claude Code** (CLI `claude`) — sin flag de modelo.
  - **Codex** (CLI `codex`) — soporta selección de modelo.
- **Opcional — Ollama** en `http://localhost:11434` para **Scribe** (modelo local, p. ej. `qwen2.5-coder:14b`). Scribe es un ahorrador de tokens opcional: todo funciona sin él, degradándose explícitamente.
- **Opcional — acceso remoto** si quieres llegar al backend desde un dispositivo móvil.

!!! note "Proveedores de LLM"
    Atlas Forge no ejecuta modelos directamente: delega en runtimes externos. El catálogo de modelos (`.atlas-forge/models.yml`) declara los modelos disponibles por runtime. Los tres runtimes — OpenCode, Claude Code y Codex — se soportan.

## Instalación

```bash
cd 04-src
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

Esto instala el paquete `atlas_forge` y los entrypoints `atlas_forge` y `atlas-forge-api`.

## Ejecución

Atlas Forge opera como **un único proceso de verdad** (`atlas-forge-api`) que expone la API y sirve la interfaz web. Todos los clientes (la web) se conectan a él.

### 1. Inicia el backend

```bash
atlas-forge-api
```

- Escucha en el puerto **8000**.
- Al arrancar recupera el proyecto activo persistido e inicia su sesión de desarrollo (si la hay). Si no hay proyecto, la API responde 404 en `/project` y `/session` hasta que selecciones uno.

### 2. Abre la interfaz web

Navega a `http://<host>:8000/ui/` (o `http://127.0.0.1:8000/ui/` en local).

En el primer arranque la web te guía: verifica la conectividad → elige tu primer proyecto → entra en la vista operativa. Desde ahí puedes lanzar agentes, conducir el pipeline del backlog con "Progresar", despachar Jobs aislados, ejecutar scripts y disparar acciones transversales.

### 3. (Alternativa) Instalar como servicio systemd

```bash
sudo cp deploy/systemd/atlas-forge-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now atlas-forge-api.service
```

El servicio ejecuta `atlas-forge-api` como usuario no root y se reinicia a sí mismo en caso de crash (un `systemctl stop` deliberado no se reinicia).

## Pruebas

```bash
cd 04-src
pytest
```

Suite completa (más de 600 tests). Para ejecutar los tests sin tocar la red/tmux, los tests usan un `TestClient` en memoria y sus propios sockets de tmux; la suite no requiere un runtime real ni Ollama para pasar.

## Verificación rápida

```bash
curl http://127.0.0.1:8000/health
# {"status": "ok", "session_id": null}  →  hasta que selecciones un proyecto
curl http://127.0.0.1:8000/projects    # lista los repos Git descubiertos
```

## Dónde vive el estado

| Dato | Ubicación |
|---|---|
| Proyecto activo | `<state_dir>/active_project.json` |
| Preferencias de modelo | `<state_dir>/model_preferences.json` |
| Estado de sesión/agentes/Jobs | En la memoria del proceso `atlas-forge-api` (no persistido en disco) |
| Sesiones de tmux | Servidor tmux `atlas-forge` |

`state_dir` por defecto es `$XDG_DATA_HOME/atlas_forge` o `~/.local/share/atlas_forge`.

!!! warning "Estado en memoria"
    Sesiones, agentes y Jobs viven en la memoria del proceso. Reiniciar `atlas-forge-api` deja la sesión en blanco de nuevo (el proyecto activo se recupera del disco). La persistencia de la sesión entre reinicios es una User Story planificada, no implementada.

## Siguientes pasos

- Lee [Conceptos](concepts.md) para entender el modelo de dominio.
- Sigue la [guía de la interfaz web](interfaces-web.md) para tu primera tarea real.