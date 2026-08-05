# Empezar

Guía de instalación, configuración y primeras ejecuciones de Factory Brain.

## Requisitos

- **Python ≥ 3.10**
- **tmux** (los runtimes se ejecutan en sesiones tmux; el socket por defecto es `factory-brain`)
- Un **runtime de IA** instalado y disponible en el PATH:
  - **OpenCode** (CLI `opencode`) — soporta selección de modelo.
  - **Claude Code** (CLI `claude`) — sin flag de modelo.
- **Opcional — Ollama** en `http://localhost:11434` para **Scribe** (modelo local, p. ej. `qwen2.5-coder:14b`). Scribe es un ahorro de tokens opcional: todo funciona sin él, degradando explícitamente.
- **Opcional — Tailscale** si quieres acceso remoto desde la app Android.

!!! note "Proveedores LLM"
    Factory Brain no ejecuta modelos directamente: delega en runtimes externos. El catálogo de modelos (`.factory-brain/models.yml`) declara los modelos disponibles por runtime. Codex figura en el catálogo como entrada futura (comentada) — no está soportado como runtime todavía.

## Instalación

```bash
cd 04-src
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

Esto instala el paquete `brain` y los entrypoints `brain` y `brain-api`.

## Ejecución

Factory Brain opera como **un único proceso de verdad** (`brain-api`) que expone la API y sirve la interfaz web. Todos los clientes (web, TUI, app) se conectan a él.

### 1. Arrancar el backend

```bash
brain-api
```

- Escucha en el puerto **8000**.
- El host se resuelve dinámicamente como la **IP Tailscale** de la máquina (`tailscale ip -4`); nunca en `0.0.0.0` (el perímetro de seguridad es la red Tailscale, no hay autenticación propia).
- Al arrancar, recupera el proyecto activo persistido y arranca su sesión de desarrollo (si existe). Si no hay proyecto, la API responde 404 en `/project` y `/session` hasta que selecciones uno.

### 2. Abrir la interfaz web

Navega a `http://<tailscale-ip>:8000/ui/` (o `http://127.0.0.1:8000/ui/` en local).

En el primer arranque la web te guía: verifica conectividad → elige tu primer proyecto → entra en la vista operativa. Desde ahí puedes lanzar agentes, crear Jobs, pedir planes, ejecutar scripts, consultar el backlog y lanzar acciones transversales.

### 3. (Alternativa) Usar la TUI

```bash
brain
```

La TUI (Textual) también es un cliente de la API: comprueba conectividad, elige o recupera proyecto y ofrece las pantallas Workspace, Dashboard, Agentes, Jobs, Plan, Scripts y Backlog. Asume que `brain-api` ya está corriendo (p. ej. vía systemd).

### 4. (Alternativa) Instalar como servicio systemd

```bash
sudo cp deploy/systemd/factory-brain-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now factory-brain-api.service
```

El servicio arranca `brain-api` como usuario no-root, espera a que la interfaz Tailscale exista y se reinicia solo ante crash (un `systemctl stop` deliberado no se reinicia).

## Probar

```bash
cd 04-src
pytest
```

Suite completa (más de 600 tests). Para ver solo los tests sin tocar red/tmux, los tests usan `TestClient` en memoria y sockets tmux propios; la suite no requiere un runtime real ni Ollama para pasar.

## Verificación rápida

```bash
curl http://<tailscale-ip>:8000/health
# {"status": "ok", "session_id": null}  →  hasta que elijas proyecto
curl http://127.0.0.1:8000/projects    # lista repos Git descubiertos
```

## Dónde vive el estado

| Dato | Ubicación |
|---|---|
| Proyecto activo | `<state_dir>/active_project.json` |
| Preferencias de modelos | `<state_dir>/model_preferences.json` |
| Estado de sesión/agentes/Jobs | En memoria del proceso `brain-api` (no persistido a disco) |
| Sesiones tmux | Servidor tmux `factory-brain` |

`state_dir` por defecto: `$XDG_DATA_HOME/brain` o `~/.local/share/brain`.

!!! warning "Estado en memoria"
    Sesiones, agentes y Jobs viven en memoria del proceso. Un reinicio de `brain-api` deja de nuevo la sesión en blanco (el proyecto activo sí se recupera de disco). La persistencia de sesión tras reinicio es una User Story planificada, no implementada.

## Siguientes pasos

- Lee [Conceptos](concepts.md) para entender el modelo de dominio.
- Sigue la [guía de la interfaz web](interfaces-web.md) para tu primera tarea real.
