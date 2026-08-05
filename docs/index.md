# Factory Brain

**Coordinación de desarrollo software asistido por IA desde una única plataforma.**

Factory Brain es el sistema operativo de una factoría de desarrollo basada en inteligencia artificial. Coordina proyectos, agentes, runtimes, Jobs y pipelines de trabajo, manteniendo el contexto operativo durante todo el ciclo de desarrollo.

No es un IDE. No es un framework de agentes. No sustituye la capacidad de decisión del desarrollador: coordina *quién* hace *qué* y *cuándo*, y los agentes ejecutan con sus propios runtimes y modelos.

## Cómo funciona en 30 segundos

1. **Descubre** los repositorios Git de tu workspace automáticamente.
2. **Elige** un proyecto activo (una sola sesión de desarrollo por proyecto).
3. **Lanza agentes** con rol + runtime + modelo: Developer, Critic, Director, Arquitecto, sobre Claude Code u OpenCode, en sesiones tmux persistentes.
4. **Envía Jobs** a un agente, **encadena** resultados (Developer → Critic/Arquitecto) y **cancela** trabajo en curso.
5. Pide un **plan** al Arquitecto para una User Story, **apruébalo una vez** y el sistema despacha y encadena los pasos automáticamente.
6. **Automatiza lo repetitivo** con scripts deterministas (commit, push, tests, estado del backlog) y delega lecturas/resúmenes en **Scribe**, un modelo local (Ollama) que no consume tokens de tus runtimes remotos.

Todo se opera desde **tres clientes** que consumen una única API HTTP/WebSocket: la **interfaz web** (recomendada, interfaz principal desde 2026-08-04), la **TUI** de terminal y la **app Android** remota vía Tailscale.

## Qué problema resuelve

Desarrollar con IA hoy exige mantener varias sesiones de Claude Code abiertas, lanzar procesos con tmux, usar OpenCode para determinados modelos, cambiar entre proyectos y reconstruir contexto a mano en cada tarea. Cada herramienta mantiene su propio estado; el conocimiento queda disperso; se pierde tiempo y se consumen más tokens de los necesarios.

Factory Brain centraliza ese flujo: el proyecto activo, la sesión viva, los agentes lanzados, el historial de Jobs, los planes, los scripts y el estado del backlog viven en un único proceso (`brain-api`) al que cualquier interfaz se conecta.

## Principios de diseño

| Principio | En qué se concreta |
|---|---|
| **Coordinación frente a ejecución** | Factory Brain coordina; los agentes ejecutan con sus runtimes y modelos. El sistema no genera código directamente. |
| **Automatización determinista primero** | Scripts deterministas → automatizaciones locales → modelo local (Ollama) → modelo remoto. Nunca un LLM para lo que un script puede hacer. |
| **Persistencia de contexto** | La sesión mantiene proyecto, agentes, runtimes, historial y contexto. Los agentes no se destruyen al terminar un Job. |
| **Arquitectura basada en capacidades** *(en backlog)* | El Dispatcher pide capacidades, no modelos concretos. El Capability Engine (FB-010) está planificado, no implementado. |
| **Un proceso, tres clientes** | Web, TUI y Android consumen la misma API; el dominio no pertenece a ningún cliente. |

## Estado del proyecto

Ver el [roadmap](roadmap.md) para el detalle completo.

- **Fases 0.1 a 0.4: completadas.** Workspace, Sesión, Runtime (Claude Code y OpenCode), Agentes, Dispatcher manual (Jobs, encadenado, planes, cancelación), Scribe, API backend, app Android, scripts genéricos, TUI, gestión de backlog e interfaz web.
- **Fase 1.0 (pipeline backlog-céntrico): en curso.** Roles Director/Arquitecto y generadores Epic→US→Task están implementados (Tasks DONE); los ficheros de Epic aún no se han actualizado a `DONE` (discrepancia de metadatos del backlog señalada en el [roadmap](roadmap.md#estado-por-epic)).
- **Planificado, no implementado:** Context Engine (FB-006), Knowledge Engine (FB-007), Capability Engine (FB-010), Plugin System (FB-011), Automation Engine (FB-009/012), Config Management (FB-013), supervisión de ciclo de vida (FB-023), análisis de hilos (FB-026). **No hay sistema de plugins ni MCP todavía.**

## Empezar

- [Empezar](getting-started.md) — requisitos, instalación, ejecución y pruebas.
- [Conceptos](concepts.md) — proyecto, sesión, agente, Job, plan.
- [Arquitectura](architecture.md) — diseño del sistema con diagramas.

## Documentación

| Sección | Contenido |
|---|---|
| [Interfaz web](interfaces-web.md) | La interfaz principal: Roles, Plan, Scripts, Backlog, Modelos, Acciones. |
| [TUI](interfaces-tui.md) | Cliente de terminal (Textual). |
| [App Android](interfaces-android.md) | Cliente remoto vía Tailscale. |
| [API](api.md) | Referencia completa REST + WebSocket. |
| [Agentes](agents.md) | Roles, lanzamiento, ciclo de vida, gobernanza. |
| [Runtime y Scribe](runtime.md) | Claude Code, OpenCode, tmux, Scribe/Ollama. |
| [Jobs y planes](jobs.md) | Ciclo de un Job, encadenado, planes del Arquitecto. |
| [Scripts](scripts.md) | Scripts genéricos y particulares del proyecto. |
| [Backlog y pipeline](backlog.md) | Gestión del backlog, validador, generadores Epic→US→Task. |
| [Configuración](configuration.md) | `models.yml`, `scripts.yml`, preferencias de modelos. |
| [CLI](cli.md) | Comandos de la CLI `brain`. |
| [Roadmap](roadmap.md) | Fases, estado por Epic, backlog en espera. |
| [FAQ y troubleshooting](faq.md) | Preguntas frecuentes y resolución de problemas. |
| [Desarrollo](development.md) | Guía para nuevos desarrolladores. |

## Repositorio

- Código: [`04-src/`](https://github.com/factoria-software/factory-brain/tree/main/04-src) — paquete Python `brain`.
- Backlog canónico: [`02-backlog/`](https://github.com/factoria-software/factory-brain/tree/main/02-backlog).
- Documentación interna del proyecto: [`01-documentacion/`](https://github.com/factoria-software/factory-brain/tree/main/01-documentacion) (puede estar desactualizada; los `/docs` de este sitio son la fuente pública).
