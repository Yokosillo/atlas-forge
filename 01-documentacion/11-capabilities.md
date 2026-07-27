# Capabilities

## Objetivo

Las Capabilities representan las capacidades funcionales que pueden proporcionar los distintos componentes de Factory Brain.

Una Capability describe qué trabajo puede realizar un componente, sin indicar cómo se implementa.

Esta abstracción desacopla el Dispatcher de los agentes, de los runtimes y de las herramientas concretas.

---

# Principios

Las Capabilities deberán ser.

- independientes del runtime
- independientes del modelo
- independientes del lenguaje
- reutilizables
- componibles
- observables

El Dispatcher únicamente conocerá Capabilities.

Nunca conocerá modelos concretos.

---

# Proveedores

Una misma Capability podrá estar implementada por distintos proveedores.

Ejemplo.

Capability

code.review

↓

Critic

↓

Claude Code

o

↓

Critic

↓

OpenCode

o

↓

Reviewer

↓

Codex

El Dispatcher seleccionará el proveedor más adecuado según disponibilidad, coste y configuración.

---

# Tipos de Capabilities

## Desarrollo

- code.write
- code.refactor
- code.review
- code.explain
- code.debug

---

## Arquitectura

- architecture.review
- architecture.design
- dependency.analysis

---

## Documentación

- documentation.write
- documentation.review
- documentation.search
- documentation.summarize

---

## Contexto

- context.build
- context.refresh
- context.compress

---

## Conocimiento

- knowledge.index
- knowledge.search
- knowledge.refresh

---

## Git

- git.status
- git.diff
- git.commit.prepare
- git.branch.create

---

## Testing

- tests.run
- tests.analyze
- coverage.generate

---

## Automatización

- summary.generate
- prompt.build
- repository.scan
- change.detect
- artifact.generate

---

## Runtime

- runtime.start
- runtime.stop
- runtime.restart

---

## tmux

- tmux.create
- tmux.attach
- tmux.stop

---

# Registro

Factory Brain mantendrá un catálogo de Capabilities disponibles.

Cada proveedor registrará automáticamente las capacidades que puede ejecutar.

---

# Selección

Cuando el Dispatcher necesite una Capability.

1. Buscará proveedores compatibles.

2. Eliminará los no disponibles.

3. Aplicará la política de selección.

4. Ejecutará el proveedor elegido.

---

# Políticas

La selección podrá considerar.

- coste
- velocidad
- calidad
- disponibilidad
- preferencias del usuario
- proyecto
- estado del runtime

---

# Objetivo estratégico

Las Capabilities constituyen el contrato común entre todos los componentes del sistema.

Gracias a esta abstracción será posible incorporar nuevos agentes, nuevos runtimes y nuevos motores de automatización sin modificar el Dispatcher.

