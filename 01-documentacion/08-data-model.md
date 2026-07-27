# Modelo de datos

## Objetivo

El modelo de datos define las entidades gestionadas por Factory Brain y las relaciones existentes entre ellas.

Todas las funcionalidades de la aplicación deberán construirse sobre este modelo.

---

# Principios

El modelo deberá cumplir los siguientes principios.

- Bajo acoplamiento.
- Alta cohesión.
- Persistencia.
- Extensibilidad.
- Independencia de la interfaz.
- Independencia del runtime.

---

# Workspace

Representa la factoría completa.

Contiene.

- proyectos
- configuración
- recursos compartidos
- índices

Un Workspace contiene múltiples proyectos.

---

# Project

Representa un repositorio Git.

Un proyecto contiene.

- documentación
- backlog
- código
- configuración
- sesiones de desarrollo

Un proyecto puede tener múltiples sesiones históricas.

Sólo una sesión podrá permanecer activa.

---

# Development Session

Representa una sesión persistente de trabajo.

Contiene.

- agentes
- runtimes
- trabajos
- contexto
- historial
- eventos

Una sesión pertenece a un único proyecto.

---

# Agent

Representa un rol especializado.

Ejemplos.

- Developer
- Critic
- Architect
- Tester

Un agente dispone de.

- prompt
- runtime
- capacidades
- estado
- sesión tmux

---

# Runtime

Representa un entorno de ejecución.

Ejemplos.

- Claude Code
- Codex
- OpenCode

Un runtime puede alojar múltiples agentes.

---

# Job

Representa una unidad de trabajo.

Ejemplos.

- User Story
- Bug
- Refactor
- Investigación

Todo Job pertenece a una sesión.

---

# Pipeline

Representa el flujo de ejecución de un Job.

Ejemplo.

Developer

↓

Critic

↓

Developer

↓

Finalizado

---

# Task

Representa una operación concreta.

Una Task solicita exactamente una capacidad.

---

# Capability

Representa una habilidad requerida.

Ejemplos.

code.write

architecture.review

summary.generate

tests.run

git.commit

context.build

---

# Artifact

Representa cualquier resultado generado.

Ejemplos.

Markdown

JSON

Código

Informe

Prompt

Resumen

---

# Automation Component

Representa un proceso determinista.

Ejemplos.

Indexer

Summarizer

Git Analyzer

Context Builder

Dependency Scanner

---

# Knowledge Index

Representa el conocimiento previamente construido por el sistema.

Incluye.

- índices
- embeddings
- resúmenes
- relaciones
- estadísticas

---

# Event

Representa un evento del sistema.

Ejemplos.

AgentStarted

JobCompleted

RuntimeFailed

PipelineFinished

---

# Relaciones

Workspace

↓

Project

↓

Development Session

↓

Job

↓

Pipeline

↓

Task

↓

Capability

↓

Agente o Automation Component

↓

Artifact

