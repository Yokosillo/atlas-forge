# Metodología de desarrollo de Factory Brain

## Objetivo

El objetivo de esta metodología es garantizar que el producto evolucione de forma ordenada, incremental y completamente trazable.

Toda implementación debe ser consecuencia de una decisión de producto previamente documentada.

---

# Principios

El producto se diseña antes de implementarse.

La documentación define el producto.

El backlog define el trabajo pendiente.

Las tareas definen el trabajo inmediato.

El código únicamente implementa tareas.

Los informes documentan el trabajo realizado.

---

# Jerarquía del proyecto

Todo desarrollo debe seguir esta secuencia.

```text
Visión
    ↓
Arquitectura
    ↓
Roadmap
    ↓
Backlog
    ↓
Epic
    ↓
User Story
    ↓
Task
    ↓
Implementación
    ↓
Validación
    ↓
Informe
```

Nunca debe invertirse este flujo.

---

# Documentación

La documentación describe qué es el producto.

No describe el estado del desarrollo.

No contiene tareas.

Debe mantenerse estable.

---

# Roadmap

Define la evolución prevista del producto.

Agrupa objetivos estratégicos.

No contiene detalles técnicos.

---

# Epic

Una Epic representa una capacidad importante del producto.

Una Epic agrupa varias User Stories relacionadas.

Una Epic puede declarar un **Alcance v1 (mínimo)** y un **Diferido a v2** cuando el incremento completo descrito en su objetivo es mayor de lo necesario para el primer resultado observable. Las User Stories de una Epic deben cubrir su alcance v1 antes de abordar lo diferido a v2.

---

# User Story

Una User Story describe una necesidad funcional.

Debe indicar:

- objetivo
- valor aportado
- criterios de aceptación

Una User Story puede generar varias Tasks.

---

# Descomposición del backlog

La jerarquía oficial es:

```text
Roadmap
    ↓
Epic
    ↓
User Story
    ↓
Task
```

No existe ningún nivel intermedio persistente entre Epic y User Story, ni entre User Story y Task. No se crean Capabilities, Features, Iniciativas ni ningún otro artefacto de planificación como nivel del backlog (la Epic FB-010 Capability Engine es una capacidad *del producto*, no un nivel de planificación del backlog).

Un análisis técnico puede identificar agrupaciones intermedias (componentes, bloques funcionales) para razonar sobre dependencias o alcance. Esas agrupaciones son herramientas temporales de análisis, no artefactos del backlog: nunca se guardan como ficheros propios ni se referencian como si fueran un nivel de la jerarquía. Al cerrar el análisis, toda decisión se materializa directamente como Epic, User Story o Task.

## Criterio de corte: User Story vs. Task

Una User Story representa un incremento funcional de valor **observable y verificable de forma independiente** — alguien (el desarrollador, un agente, otro componente del sistema) puede comprobar que existe una capacidad nueva que antes no existía, sin necesitar que se complete ningún otro trabajo simultáneo.

Una Task representa el trabajo técnico necesario para completar una User Story. No tiene valor observable por sí sola fuera del contexto de la Story a la que pertenece.

Prueba práctica: si al terminar una pieza de trabajo nadie puede comprobar una funcionalidad nueva — solo se ha tocado código, se ha preparado un dato, o se ha refactorizado una parte interna — esa pieza probablemente no era una User Story, sino una Task.

Los pasos internos de implementación (escribir un parser, definir un esquema, añadir una validación, refactorizar un módulo) se modelan siempre como Tasks. Nunca como User Stories, aunque individualmente representen trabajo sustancial.

### Ejemplo — Epic FB-001 · Workspace Management (alcance v1)

Un análisis de dependencias sobre el alcance v1 de FB-001 puede identificar piezas técnicas como: "recorrer el workspace en busca de `.git`", "excluir directorios internos", "guardar la ruta seleccionada en almacenamiento local", "recuperar la selección al arrancar". Ninguna de ellas es una User Story por separado: descubrir repos sin poder seleccionar uno no resuelve nada; seleccionar sin persistir obliga a repetir la selección en cada arranque; persistir sin descubrir no tiene qué persistir.

Esas piezas se agrupan en una única User Story: *"Abrir Factory Brain sobre el proyecto en el que se trabajó la última vez"*. Es verificable de forma independiente — el desarrollador abre Factory Brain y ve su proyecto ya seleccionado, sin pasos manuales — y no requiere que exista gestión de múltiples Workspaces, ni alta/baja de proyectos.

---

# Task

La Task es la unidad mínima de trabajo.

Toda implementación corresponde exactamente a una Task.

Cada Task debe incluir como mínimo:

- identificador único
- título
- descripción
- estado
- prioridad
- criterios de aceptación
- dependencias

Estados permitidos:

- TODO
- IN_PROGRESS
- REVIEW
- DONE

---

# Implementación

Antes de escribir código debe existir una Task.

Cada sesión de desarrollo implementa únicamente una Task.

Si una Task resulta demasiado grande, debe dividirse en varias.

---

# Validación

Al finalizar una Task deben ejecutarse las validaciones necesarias.

Una Task no puede marcarse como DONE sin cumplir todos sus criterios de aceptación.

---

# Informes

Cada sesión de trabajo debe generar un informe indicando:

- objetivo
- cambios realizados
- validaciones
- incidencias
- trabajo pendiente

Los informes proporcionan trazabilidad histórica.

No sustituyen a la documentación.

---

# Regla fundamental

Si durante una implementación aparece una decisión arquitectónica nueva, el desarrollo debe detenerse temporalmente.

La decisión debe documentarse.

Después debe actualizarse la documentación o el backlog.

Solo entonces debe continuar la implementación.

La arquitectura dirige el desarrollo.

El desarrollo nunca debe dirigir la arquitectura.
