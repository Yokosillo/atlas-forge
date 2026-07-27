# Runtime Architecture

## Objetivo

Factory Brain no ejecuta modelos de lenguaje directamente.

Su función consiste en orquestar agentes de desarrollo que se ejecutan sobre distintos runtimes especializados.

Esta separación permite desacoplar la lógica del producto de los proveedores de inteligencia artificial.

---

# Arquitectura

Factory Brain

↓

Agente

↓

Runtime

↓

Modelo

↓

Proveedor

Cada nivel tiene una responsabilidad diferente.

---

# Factory Brain

Responsabilidades

- Gestionar proyectos.
- Gestionar agentes.
- Gestionar sesiones.
- Construir contexto.
- Coordinar tareas.
- Orquestar pipelines.

Factory Brain nunca invoca directamente un modelo de lenguaje.

---

# Agentes

Un agente representa un rol dentro del proceso de desarrollo.

Ejemplos

- Developer
- Critic
- Architect
- Tester
- Reviewer
- Security
- Documentation
- Research

Cada agente tendrá:

- identificador
- nombre
- rol
- runtime
- prompt
- proyecto
- sesión tmux
- estado
- configuración

---

# Runtime

El runtime es la aplicación que ejecuta el agente.

Factory Brain administrará los siguientes runtimes.

## Claude Code

Utilizado para tareas complejas de desarrollo.

Aprovecha la suscripción de Claude.

Factory Brain únicamente iniciará la sesión y enviará instrucciones.

---

## Codex

Runtime orientado al desarrollo utilizando Codex.

Factory Brain administrará su ciclo de vida igual que el resto de runtimes.

---

## OpenCode

Runtime configurable.

Permitirá utilizar distintos proveedores compatibles.

Ejemplos:

- Ollama local
- DeepSeek
- Z.ai
- GLM
- Moonshot
- Otros compatibles

La selección del modelo será responsabilidad de OpenCode.

---

# Modelos

Los modelos pertenecen al runtime.

No pertenecen a Factory Brain.

Ejemplos

Claude Code

↓

Claude

OpenCode

↓

Ollama

↓

Qwen

OpenCode

↓

DeepSeek

OpenCode

↓

GLM

Factory Brain no necesita conocer qué modelo concreto está utilizando un runtime.

Únicamente necesita conocer que el runtime está disponible.

---

# Sesiones

Cada agente se ejecutará dentro de una sesión persistente de tmux.

Ejemplo

Proyecto

↓

Developer

↓

tmux

↓

Claude Code

Proyecto

↓

Critic

↓

tmux

↓

Claude Code

Proyecto

↓

Architect

↓

tmux

↓

OpenCode

Cada sesión será independiente.

---

# Dispatcher

El Dispatcher será responsable de coordinar el trabajo.

Ejemplo

Developer

↓

Critic

↓

Developer

↓

Architect

↓

Developer

El Dispatcher decidirá qué agente debe ejecutarse en cada momento.

---

# Comunicación

Los agentes intercambiarán información mediante artefactos persistentes.

Ejemplos

- Markdown
- JSON
- Informes
- Resultados
- Archivos de contexto

Factory Brain será responsable de localizar dichos artefactos.

---

# Configuración

Cada runtime dispondrá de su propia configuración.

Ejemplo

- ejecutable
- argumentos
- variables de entorno
- directorio de trabajo
- tiempo máximo
- estrategia de recuperación

Factory Brain únicamente utilizará la interfaz pública del runtime.

---

# Objetivos

La arquitectura debe permitir:

- añadir nuevos runtimes
- incorporar nuevos proveedores
- sustituir modelos
- cambiar configuraciones
- ejecutar varios runtimes simultáneamente

Todo ello sin modificar el núcleo de Factory Brain.

---

# Sesiones persistentes

Cada runtime podrá permanecer activo durante largos periodos de tiempo.

Factory Brain evitará reiniciar un runtime entre trabajos salvo que sea estrictamente necesario.

Mantener sesiones persistentes permite conservar el contexto de trabajo, reducir el número de prompts enviados y disminuir el consumo de tokens.

