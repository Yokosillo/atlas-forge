# Primeros pasos

Instalación, configuración y primeras ejecuciones de Factory Brain.

## Requisitos

- **Python ≥ 3.10**
- **tmux** (los runtimes se ejecutan en sesiones de tmux; el socket por defecto es `factory-brain`)
- Un **runtime de IA** instalado y disponible en el PATH:
  - **OpenCode** (CLI `opencode`) — soporta selección de modelo.
  - **Claude Code** (CLI `claude`) — sin flag de modelo.
- **Opcional — Ollama** en `http://localhost:11434` para **Scribe** (modelo local, p. ej. `qwen2.5-coder:14b`). Scribe es un ahorrador de tokens opcional: todo funciona sin él, degradándose explícitamente.
- **Opcional — acceso remoto** si quieres llegar al backend desde un dispositivo móvil.

!!! note "Proveedores de LLM"
    Factory Brain no ejecuta modelos directamente: delega en runtimes externos. El catálogo de modelos (`.factory-brain/models.yml`) declara los modelos disponibles por runtime. Codex aparece en el catálogo como entrada futura (comentada) — todavía no se soporta como runtime.

## Instalación

```bash
cd 04-src
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

Esto instala el paquete `brain` y los entrypoints `brain` y `brain-api`.

## Ejecución

Factory Brain opera como **un único proceso de verdad** (`brain-api`) que expone la API y sirve la interfaz web. Todos los clientes (la web) se conectan a él.

### 1. Inicia el backend

```bash
brain-api
```

- Escucha en el puerto **8000**.
- Al arrancar recupera el proyecto activo persistido e inicia su sesión de desarrollo (si la hay). Si no hay proyecto, la API responde 404 en `/project` y `/session` hasta que selecciones uno.

### 2. Abre la interfaz web

Navega a `http://<host>:8000/ui/` (o `http://127.0.0.1:8000/ui/` en local).

En el primer arranque la web te guía: verifica la conectividad → elige tu primer proyecto → entra en la vista operativa. Desde ahí puedes lanzar agentes, conducir el pipeline del backlog con "Progresar", despachar Jobs aislados, ejecutar scripts y disparar acciones transversales.

### 3. (Alternativa) Instalar como servicio systemd

```bash
sudo cp deploy/systemd/factory-brain-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now factory-brain-api.service
```

El servicio ejecuta `brain-api` como usuario no root y se reinicia a sí mismo en caso de crash (un `systemctl stop` deliberado no se reinicia).

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
| Estado de sesión/agentes/Jobs | En la memoria del proceso `brain-api` (no persistido en disco) |
| Sesiones de tmux | Servidor tmux `factory-brain` |

`state_dir` por defecto es `$XDG_DATA_HOME/brain` o `~/.local/share/brain`.

!!! warning "Estado en memoria"
    Sesiones, agentes y Jobs viven en la memoria del proceso. Reiniciar `brain-api` deja la sesión en blanco de nuevo (el proyecto activo se recupera del disco). La persistencia de la sesión entre reinicios es una User Story planificada, no implementada.

## Siguientes pasos

- Lee [Conceptos](concepts.md) para entender el modelo de dominio.
- Sigue la [guía de la interfaz web](interfaces-web.md) para tu primera tarea real.