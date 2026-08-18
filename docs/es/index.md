# Factory Brain

**Coordinación de desarrollo de software asistido por IA desde una única plataforma.**

Factory Brain es el sistema operativo de una fábrica de desarrollo basada en IA. Coordina proyectos, agentes, runtimes, Jobs y pipelines de trabajo, manteniendo vivo el contexto operativo a lo largo de todo el ciclo de desarrollo.

No es un IDE. No es un framework de agentes. No sustituye la toma de decisiones del desarrollador: coordina *quién* hace *qué* y *cuándo*, y los agentes ejecutan con sus propios runtimes y modelos.

## Cómo funciona en 30 segundos

1. **Descubre** los repositorios Git de tu workspace automáticamente.
2. **Selecciona** un proyecto activo (una única sesión de desarrollo por proyecto).
3. **Usa el backlog como panel de control**: el trabajo se despliega desde el backlog (Epic → User Story → Task → Implementar) con un único botón "Progresar" por User Story, no escribiendo Markdown a mano ni hablando con cada agente por separado.
4. **Ejecuta el pipeline**: el Arquitecto aterriza Epics en User Stories y Tasks; un Dispatcher en segundo plano asigna luego cada Task a un Developer libre, cada Task cerrada a un Tester libre para su verificación, y cada Story completamente terminada a un Arquitecto libre para un veredicto final — automáticamente, sin re-despacho manual por paso.
5. **Envía Jobs aislados** a un agente específico cuando necesitas trabajo puntual fuera del pipeline guiado por estados, y **encadena** resultados (Developer → Arquitecto); también puedes **cancelar** trabajo en curso.
6. **Automatiza lo repetitivo** con scripts deterministas (commit, push, tests, estado del backlog) y delega lecturas/resúmenes en **Scribe**, un modelo local (Ollama) que no consume tokens de tus runtimes remotos.

Todo se opera desde una única API HTTP/WebSocket; la **interfaz web** es el cliente principal.

## Qué problema resuelve

Desarrollar con IA hoy requiere mantener varias sesiones de Claude Code abiertas, lanzar procesos con tmux, usar OpenCode para ciertos modelos, cambiar entre proyectos y reconstruir el contexto a mano en cada tarea. Cada herramienta guarda su propio estado; el conocimiento queda disperso; se pierde tiempo y se consumen más tokens de los necesarios.

Factory Brain centraliza ese flujo: el proyecto activo, la sesión viva, los agentes lanzados, el historial de Jobs, los scripts y el estado del backlog viven en un único proceso (`brain-api`) al que se conecta cualquier interfaz.

## Qué es realmente Factory Brain

Factory Brain es una **capa de coordinación entre el trabajo definido y los agentes que lo ejecutan**. Su propia declaración de visión es la definición más clara disponible: *"Factory Brain automatiza la ejecución del trabajo, no las decisiones sobre qué trabajo hacer."*

El concepto central no es el backlog ni los propios agentes — es la **sesión de desarrollo persistente**: agentes que sobreviven entre jobs, cargando contexto acumulado, coordinados por un dispatcher, ejecutándose sobre runtimes intercambiables. El backlog (Epic → User Story → Task) es el *lenguaje* usado para describir el trabajo; Jobs y pipelines son el *mecanismo* usado para ejecutarlo.

**En qué se diferencia de una herramienta tradicional de gestión de proyectos:** Jira describe trabajo para que lo hagan humanos. Aquí el backlog es *ejecutable* — una Task puede pasar de un archivo Markdown a código verificado y testeado sin que un humano escriba una sola línea, actualizando el propio backlog al cerrarse.

**En qué se diferencia de un agente de codificación:** Claude Code hace el trabajo pero no sabe qué trabajo existe, no persiste entre sesiones por sí solo, no se coordina con otros agentes y no valida su propia salida. Factory Brain es la capa que necesita un agente de codificación para convertirse en una *fábrica* en lugar de una herramienta.

### Dónde encaja

- **No compite con Jira/Linear** — y no debería intentarlo. Su modelo de backlog de archivos Markdown más validador es funcional, pero es la parte menos diferenciada del producto.
- **No compite con Claude Code / Codex / OpenCode** — los consume como runtimes, que es exactamente la relación correcta.
- Su vecino real más cercano es la categoría emergente de **orquestadores de agentes de codificación** (Factory.ai, el agente de codificación de GitHub Copilot, GitLab Duo). La diferencia observable: esos son de un único proveedor/runtime; Factory Brain es agnóstico al runtime por diseño, y añade una capa de veredicto/validación (el ciclo Developer → Arquitecto) que esas herramientas no tratan como concepto de primera clase.
- Puntos de integración naturales: aguas arriba con herramientas de gestión de trabajo (importando issues), aguas abajo con runtimes. Hoy no hay integración aguas arriba — el backlog completo es nativo del sistema.

### Qué es genuinamente diferencial (con evidencia real, no solo intención de diseño)

- **El ciclo de verificación adversarial**: Developer implementa → Arquitecto verifica de forma independiente (re-ejecutando tests, leyendo el código real, reproduciendo el resultado en vivo) → veredicto estructurado. Este ciclo ha atrapado bugs reales que el propio Developer no vio. Ninguno de los productos anteriores tiene esto como mecanismo central.
- **"Determinista primero"**: validadores de formato, promoción de estados, hooks de pre-commit — el sistema gasta llamadas LLM solo donde aportan valor. Es una disciplina operativa real verificada en el uso diario, no un eslogan.

## Principios de diseño

| Principio | Qué significa |
|---|---|
| **Coordinación sobre ejecución** | Factory Brain coordina; los agentes ejecutan con sus propios runtimes y modelos. El sistema no genera código directamente. |
| **Automatización determinista primero** | Scripts deterministas → automatizaciones locales → modelo local (Ollama) → modelo remoto. Nunca un LLM para algo que un script puede hacer. |
| **Contexto persistente** | La sesión mantiene el proyecto, agentes, runtimes, historial y contexto. Los agentes no se destruyen cuando termina un Job. |
| **Pipeline centrado en el backlog** | El backlog es el panel de control central: todo el trabajo se despliega desde él, no desde comandos manuales dispersos. |
| **Arquitectura basada en capacidades** *(en backlog)* | El Dispatcher pide capacidades, no modelos específicos. El Capability Engine (FB-010) está planificado, no implementado. |
| **Un proceso, un cliente** | La web consume la API; el dominio no pertenece a ningún cliente. |

## Estado del proyecto

Consulta el [roadmap](roadmap.md) para más detalle.

- **Fases 0.1 a 0.4: completas.** Workspace, Sesión, Runtime (Claude Code, OpenCode, Codex), Agentes, Jobs aislados (encadenamiento, cancelación), Scribe, API backend, scripts genéricos, gestión de backlog e interfaz web.
- **Fase 1.0 (pipeline centrado en backlog): en curso.** Roles de Arquitecto y Tester, generadores Epic→US→Task, el pipeline guiado por estados Developer→Tester→Arquitecto, formato de backlog estructurado, acciones transversales (FB-025), análisis de hilos paralelizables (FB-026), sesiones multi-proyecto simultáneas, reconciliación de agentes al reiniciar el backend y log de agente en vivo en la web están implementados y en producción.
- **Planificado, no implementado:** Context Engine (FB-006), Knowledge Engine (FB-007), Capability Engine (FB-010), Plugin System (FB-011), Automation Engine (FB-009/012), Config Management (FB-013), detección automática de agentes atascados (FB-023), barra de control persistente para agentes críticos (FB-028). **No existe sistema de plugins ni MCP.**

## Primeros pasos

- [Primeros pasos](getting-started.md) — requisitos, instalación, ejecución y pruebas.
- [Conceptos](concepts.md) — proyecto, sesión, agente, Job.
- [Arquitectura](architecture.md) — diseño del sistema con diagramas.

## Documentación

| Sección | Contenido |
|---|---|
| [Interfaz web](interfaces-web.md) | La interfaz principal: Backlog, Agentes, Arquitecto, Scripts, Acciones, Configuración. |
| [API](api.md) | Referencia completa REST + WebSocket. |
| [Agentes](agents.md) | Roles, lanzamiento, ciclo de vida, gobernanza. |
| [Runtime y Scribe](runtime.md) | Claude Code, OpenCode, Codex, tmux, Scribe/Ollama. |
| [Jobs y el pipeline de trabajo](jobs.md) | Ciclo de vida de los Jobs, encadenamiento, el pipeline de backlog guiado por estados. |
| [Scripts](scripts.md) | Scripts genéricos y específicos de proyecto. |
| [Backlog y pipeline](backlog.md) | Gestión del backlog, validador, generadores Epic→US→Task. |
| [Configuración](configuration.md) | `models.yml`, `scripts.yml`, preferencias de modelos. |
| [Roadmap](roadmap.md) | Fases, estado por Epic, backlog hold. |
| [FAQ y resolución de problemas](faq.md) | Preguntas frecuentes y resolución de problemas. |
| [Desarrollo](development.md) | Guía para nuevos desarrolladores. |

## Repositorio

- Código: [`04-src/`](https://github.com/factoria-software/factory-brain/tree/main/04-src) — el paquete Python `brain`.
- Backlog canónico: [`02-backlog/`](https://github.com/factoria-software/factory-brain/tree/main/02-backlog).