# Backlog del producto

> **DOCUMENTO OBSOLETO.**
>
> Este documento contenía una versión preliminar del roadmap (orden de Epics y numeración) que ya no coincide con el backlog vigente.
>
> El roadmap y el listado de Epics oficiales se mantienen en `02-backlog/roadmap.md` y `02-backlog/epics/`. La metodología completa (jerarquía Epic→User Story→Task) está en `00-gobierno/METODOLOGIA.md`.
>
> Se conserva este fichero como referencia histórica de la visión inicial, pero no debe usarse para priorizar trabajo.

## Objetivo

El desarrollo de Factory Brain estará dirigido por un backlog funcional.

No se implementarán funcionalidades fuera del backlog.

Toda nueva capacidad deberá pertenecer a una Epic, una User Story y un conjunto de Tasks.

---

# Roadmap

La evolución prevista del producto será la siguiente.

FB-001 Workspace Management

↓

FB-002 Project Dashboard

↓

FB-003 Session Manager

↓

FB-004 Runtime Manager

↓

FB-005 Agent Manager

↓

FB-006 Context Engine

↓

FB-007 Knowledge Engine

↓

FB-008 Dispatcher

↓

FB-009 Development Tools

↓

FB-010 Plugin System

---

# FB-001 Workspace Management

Objetivo

Gestionar el workspace y descubrir automáticamente los proyectos.

## User Stories

US-001 Descubrir repositorios Git.

US-002 Seleccionar proyecto activo.

US-003 Persistir el proyecto seleccionado.

US-004 Mostrar información del proyecto.

Tasks principales

- Descubrimiento automático.
- Detección de Git.
- Exclusión de directorios internos.
- Persistencia.
- Actualización automática.

---

# FB-002 Project Dashboard

Objetivo

Convertir el Dashboard del proyecto en el centro de operaciones.

## User Stories

US-005 Dashboard principal.

US-006 Navegación entre pantallas.

US-007 Información del proyecto.

US-008 Estado del proyecto.

Tasks principales

- Menús.
- Widgets.
- Navegación.
- Atajos de teclado.

---

# FB-003 Session Manager

Objetivo

Administrar sesiones persistentes.

## User Stories

US-009 Detectar sesiones tmux.

US-010 Crear sesiones.

US-011 Reiniciar sesiones.

US-012 Adjuntarse a sesiones.

US-013 Monitorizar sesiones.

Tasks principales

- Integración con tmux.
- Asociación proyecto-sesión.
- Estado.
- Eventos.

---

# FB-004 Runtime Manager

Objetivo

Administrar los distintos runtimes de IA.

## User Stories

US-014 Registrar runtimes.

US-015 Configurar runtimes.

US-016 Seleccionar runtime para un agente.

US-017 Supervisar runtimes.

Runtimes iniciales

- Claude Code.
- Codex.
- OpenCode.

Tasks principales

- Configuración.
- Estado.
- Integración.
- Diagnóstico.

---

# FB-005 Agent Manager

Objetivo

Administrar agentes especializados.

## User Stories

US-018 Registrar agentes.

US-019 Configurar agentes.

US-020 Ejecutar agentes.

US-021 Supervisar agentes.

Agentes iniciales

- Developer.
- Critic.

Agentes futuros

- Architect.
- Tester.
- Reviewer.
- Security.
- Documentation.
- Research.

Tasks principales

- Configuración.
- Prompt.
- Runtime.
- Estado.
- Historial.

---

# FB-006 Context Engine

Objetivo

Construir automáticamente el contexto del proyecto.

## User Stories

US-022 Descubrir documentación.

US-023 Construir contexto.

US-024 Resumir información.

US-025 Actualizar contexto.

Tasks principales

- README.
- AGENTS.
- Backlog.
- Arquitectura.
- Código.

---

# FB-007 Knowledge Engine

Objetivo

Mantener una base de conocimiento indexada.

## User Stories

US-026 Indexar documentos.

US-027 Buscar información.

US-028 Actualización incremental.

US-029 Persistencia.

Tasks principales

- SQLite.
- Índices.
- Hashes.
- Reindexación.

---

# FB-008 Dispatcher

Objetivo

Coordinar el trabajo entre agentes.

## User Stories

US-030 Crear trabajos.

US-031 Ejecutar pipelines.

US-032 Coordinar agentes.

US-033 Registrar resultados.

Tasks principales

- Cola.
- Dependencias.
- Estados.
- Reintentos.

---

# FB-009 Development Tools

Objetivo

Integrar herramientas habituales de desarrollo.

## User Stories

US-034 Git.

US-035 Tests.

US-036 Build.

US-037 Calidad.

US-038 Logs.

Tasks principales

- Git.
- Pytest.
- Linters.
- Cobertura.
- Informes.

---

# FB-010 Plugin System

Objetivo

Permitir ampliar Factory Brain mediante plugins.

## User Stories

US-039 Registrar plugins.

US-040 Descubrir plugins.

US-041 Ejecutar plugins.

US-042 Configuración de plugins.

Tasks principales

- API.
- Registro.
- Descubrimiento.
- Ciclo de vida.

---

# Filosofía

Las funcionalidades deberán implementarse siguiendo el orden del backlog.

Cada Epic deberá completarse antes de iniciar la siguiente, salvo dependencias justificadas.

Cada User Story deberá poder desarrollarse, probarse y validarse de forma independiente.

El backlog constituye la referencia funcional del producto y deberá mantenerse sincronizado con la implementación.
