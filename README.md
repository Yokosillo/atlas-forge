# Factory Brain

**Coordinación de desarrollo software asistido por IA desde una única plataforma.**

Factory Brain orquesta proyectos, agentes, runtimes, Jobs y pipelines de desarrollo sin sustituir la capacidad de decisión del desarrollador. No es un IDE, no es un framework de agentes: es la capa de coordinación que mantiene vivo el contexto entre agentes, evita el trabajo manual repetitivo y minimiza el consumo de tokens de los modelos remotos.

## Qué resuelve

Desarrollar con IA hoy exige mantener varias sesiones de Claude Code, lanzar procesos en tmux, usar OpenCode para otros modelos, cambiar entre proyectos y perder tiempo reconstruyendo contexto en cada tarea. Cada herramienta mantiene su propio estado y el conocimiento queda disperso.

Factory Brain centraliza ese flujo:

- **Descubre** automáticamente los repositorios Git de tu workspace.
- **Coordina** agentes especializados (Developer, Critic, Director, Arquitecto) sobre runtimes reales (Claude Code, OpenCode) en sesiones tmux persistentes.
- **Envía Jobs** a los agentes y **encadena** resultados (Developer → Critic/Arquitecto).
- **Propone y ejecuta planes** de trabajo con una única aprobación humana.
- **Automatiza lo repetitivo** con scripts deterministas antes de gastar tokens en un modelo.
- **Delega lecturas/resúmenes en un modelo local** (Scribe + Ollama) para reducir el consumo de tokens remotos.
- **Expone todo** a través de una API HTTP/WebSocket única consumida por la interfaz web, la TUI y la app Android.

## Qué la diferencia

- **Coordinación frente a ejecución**: Factory Brain decide *quién hace qué y cuándo*; los agentes ejecutan con sus propios runtimes y modelos.
- **Automatización determinista primero**: scripts → automatizaciones → modelo local → modelo remoto, en ese orden de prioridad.
- **Contexto persistente**: los agentes no se destruyen al terminar un Job; la sesión y su historial permanecen vivos.
- **Un solo proceso de verdad** (`brain-api`) con tres clientes paralelos (web, TUI, Android).

## Estado actual

Factory Brain ha completado las Fases 0.1–0.4 y el grueso de la Fase 1.0 del roadmap: Workspace, Sesión, Runtime, Agentes, Dispatcher (Jobs/planes/cancelación), Scribe, API backend, app Android, scripts genéricos, TUI, gestión de backlog, interfaz web, pipeline backlog-céntrico (roles Director/Arquitecto, generadores Epic→US→Task, veredictos) y mejoras de UX web. Context Engine, Knowledge Engine, Capability Engine, Plugin System y Automation Engine siguen en backlog sin implementar.

Consulta el [roadmap completo](docs/roadmap.md) y el [estado por Epic](docs/roadmap.md#estado-por-epic) para el detalle.

## Instalación rápida

Requisitos: Python ≥ 3.10, `tmux`, un runtime de IA (Claude Code o OpenCode), y opcionalmente Ollama para Scribe.

```bash
cd 04-src
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

## Ejecución

El backend (proceso único de verdad, expone API + interfaz web):

```bash
brain-api
```

La TUI (cliente de la API):

```bash
brain
```

La interfaz web se sirve desde el propio backend en `http://<tailscale-ip>:8000/ui/`. Con un sistema con `systemd`, se instala como servicio:

```bash
sudo cp deploy/systemd/factory-brain-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now factory-brain-api.service
```

## Probar

```bash
cd 04-src
pytest
```

## Documentación

La documentación pública vive en [`/docs`](docs/index.md) y está preparada para publicarse con [MkDocs](https://www.mkdocs.org/) o GitHub Pages:

- [Empezar](docs/getting-started.md)
- [Arquitectura](docs/architecture.md)
- [Conceptos](docs/concepts.md)
- [CLI](docs/cli.md)
- [Configuración](docs/configuration.md)
- [API](docs/api.md)
- [Interfaces: web · TUI · Android](docs/interfaces-web.md)
- [Agentes](docs/agents.md)
- [Runtime y Scribe](docs/runtime.md)
- [Jobs y planes](docs/jobs.md)
- [Scripts](docs/scripts.md)
- [Backlog y pipeline backlog-céntrico](docs/backlog.md)
- [Roadmap](docs/roadmap.md)
- [FAQ y troubleshooting](docs/faq.md)
- [Desarrollo](docs/development.md)

## Licencia

Pendiente de decisión — ver [roadmap](docs/roadmap.md) y el backlog del proyecto.
