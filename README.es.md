# Factory Brain

**Coordinación de desarrollo de software asistido por IA desde una única plataforma.**

Factory Brain orquesta proyectos, agentes, runtimes, Jobs y pipelines de desarrollo sin sustituir la capacidad de decisión del desarrollador. No es un IDE, no es un framework de agentes: es la capa de coordinación que mantiene vivo el contexto entre agentes, evita el trabajo manual repetitivo y minimiza el consumo de tokens de los modelos remotos.

## Qué resuelve

Desarrollar con IA hoy requiere mantener varias sesiones de Claude Code abiertas, lanzar procesos con tmux, usar OpenCode para ciertos modelos, cambiar entre proyectos y perder tiempo reconstruyendo el contexto en cada tarea. Cada herramienta guarda su propio estado y el conocimiento acaba disperso.

Factory Brain centraliza ese flujo:

- **Descubre** los repositorios Git de tu workspace automáticamente.
- **Coordina** agentes especializados (Developer, Arquitecto y otros roles de gobernanza) sobre runtimes reales (Claude Code, OpenCode) en sesiones de tmux persistentes.
- **Envía Jobs** a los agentes y **encadena** resultados (Developer → Arquitecto).
- **Propone y ejecuta** planes de trabajo con una única aprobación humana.
- **Automatiza lo repetitivo** con scripts deterministas antes de gastar tokens en un modelo.
- **Delega lecturas/resúmenes en un modelo local** (Scribe + Ollama) para reducir el consumo de tokens remotos.
- **Expone todo** a través de una única API HTTP/WebSocket consumida por la interfaz web.

## Qué es realmente Factory Brain

Factory Brain es una **capa de coordinación entre el trabajo definido y los agentes que lo ejecutan** — no otro gestor de proyectos, y no otro agente de codificación. El backlog (Epic → User Story → Task) es el lenguaje usado para describir el trabajo; la sesión de desarrollo persistente, los Jobs y los pipelines son el mecanismo usado para ejecutarlo y verificarlo.

- **vs. Jira/Linear**: esos describen trabajo para que lo hagan humanos. Aquí el backlog es *ejecutable* — una Task puede pasar de un archivo Markdown a código verificado y testeado sin que un humano escriba una línea.
- **vs. Claude Code/Codex/OpenCode**: esos ejecutan trabajo pero no saben qué trabajo existe, no persisten entre sesiones y no validan su propia salida. Factory Brain es la capa que convierte un agente de codificación en una fábrica.
- **Lo genuinamente diferencial**: el ciclo de verificación adversarial (Developer implementa → Arquitecto re-verifica de forma independiente con evidencia real → veredicto estructurado) y la "automatización determinista primero" como disciplina operativa real, no un eslogan.

Ver [Qué es realmente Factory Brain](docs/es/index.md#qu-es-realmente-factory-brain) en la documentación completa para el panorama completo, incluido el posicionamiento de mercado.

## Qué lo diferencia

- **Coordinación sobre ejecución**: Factory Brain decide *quién hace qué y cuándo*; los agentes ejecutan con sus propios runtimes y modelos.
- **Automatización determinista primero**: scripts → automatizaciones → modelo local → modelo remoto, en ese orden de prioridad.
- **Contexto persistente**: los agentes no se destruyen cuando termina un Job; la sesión y su historial permanecen vivos.
- **Un único proceso de verdad** (`brain-api`) con un único cliente (la interfaz web).

## Estado actual

Factory Brain ha completado las Fases 0.1–0.4 y la mayor parte de la Fase 1.0 del roadmap: Workspace, Sesión, Runtime, Agentes, Dispatcher (Jobs/planes/cancelación), Scribe, API backend, scripts genéricos, gestión de backlog, interfaz web, pipeline centrado en el backlog (rol Arquitecto, generadores Epic→US→Task, veredictos, formato de backlog estructurado), sesiones multi-proyecto simultáneas, reconciliación de agentes al reiniciar el backend, log de agente en vivo en la web y mejoras de UX web. Context Engine, Knowledge Engine, Capability Engine, Plugin System y Automation Engine permanecen en el backlog sin implementar.

Ver el [roadmap completo](docs/es/roadmap.md) y el [estado por Epic](docs/es/roadmap.md#estado-por-epic) para más detalle.

## Inicio rápido

Requisitos: Python ≥ 3.10, `tmux`, un runtime de IA (Claude Code u OpenCode), y opcionalmente Ollama para Scribe.

```bash
cd 04-src
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

## Ejecución

El backend (único proceso de verdad, expone API + interfaz web):

```bash
brain-api
```

La interfaz web se sirve desde el propio backend en `http://<tailscale-ip>:8000/ui/`. En un sistema `systemd` se instala como servicio:

```bash
sudo cp deploy/systemd/factory-brain-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now factory-brain-api.service
```

## Pruebas

```bash
cd 04-src
pytest
```

## Documentación

La documentación pública vive en [`/docs`](docs/es/index.md) y está lista para publicarse con [MkDocs](https://www.mkdocs.org/) o GitHub Pages:

- [Primeros pasos](docs/es/getting-started.md)
- [Arquitectura](docs/es/architecture.md)
- [Conceptos](docs/es/concepts.md)
- [Configuración](docs/es/configuration.md)
- [API](docs/es/api.md)
- [Interfaces: web](docs/es/interfaces-web.md)
- [Agentes](docs/es/agents.md)
- [Runtime y Scribe](docs/es/runtime.md)
- [Jobs y planes](docs/es/jobs.md)
- [Scripts](docs/es/scripts.md)
- [Backlog y pipeline centrado en el backlog](docs/es/backlog.md)
- [Roadmap](docs/es/roadmap.md)
- [FAQ y resolución de problemas](docs/es/faq.md)
- [Desarrollo](docs/es/development.md)

La documentación está disponible en [español](docs/es/index.md) e [inglés](docs/en/index.md).

## Licencia

Decisión pendiente — ver [roadmap](docs/es/roadmap.md) y el backlog del proyecto.