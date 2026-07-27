# Dispatcher

## Objetivo

El Dispatcher constituye el orquestador central de Factory Brain.

Su responsabilidad consiste en coordinar la ejecución de trabajos dentro de una sesión de desarrollo.

El Dispatcher no implementa funcionalidades técnicas ni toma decisiones de desarrollo.

Su función es coordinar recursos, agentes y componentes de automatización.

---

# Principios

El Dispatcher deberá cumplir los siguientes principios.

- No realizar trabajo cognitivo.
- No modificar código.
- No generar documentación.
- No ejecutar razonamiento.
- Coordinar exclusivamente la ejecución.

---

# Responsabilidades

El Dispatcher será responsable de.

- iniciar un Job
- construir el Pipeline
- asignar Tasks
- seleccionar el ejecutor adecuado
- esperar resultados
- gestionar reintentos
- registrar eventos
- finalizar el Job

---

# Flujo general

Usuario

↓

Selecciona proyecto

↓

Inicia Development Session

↓

Selecciona Job

↓

Dispatcher

↓

Pipeline

↓

Tasks

↓

Resultados

↓

Job finalizado

↓

Esperando siguiente Job

---

# Job

Un Job representa una unidad de trabajo iniciada manualmente por el usuario.

Ejemplos.

- implementar User Story
- corregir Bug
- refactorizar módulo
- revisar arquitectura
- investigar incidencia

El Dispatcher nunca iniciará un Job automáticamente.

---

# Pipeline

Todo Job genera un Pipeline.

Ejemplo.

Developer

↓

Critic

↓

Developer

↓

Critic

↓

Finalizado

Cada Pipeline podrá definir sus propias reglas.

---

# Task

Cada Pipeline estará formado por Tasks.

Una Task deberá declarar.

- identificador
- capacidad requerida
- prioridad
- estado
- entrada
- salida

---

# Selección del ejecutor

El Dispatcher nunca seleccionará un modelo.

Seleccionará un ejecutor capaz de proporcionar la capacidad solicitada.

Ejemplo.

Capability

↓

code.review

↓

Ejecutores disponibles

Critic

Architect

Reviewer

↓

Seleccionar uno

---

# Prioridad de ejecución

Cuando existan varios ejecutores válidos, Factory Brain aplicará el siguiente orden.

Componentes deterministas.

↓

Modelos locales.

↓

Runtimes remotos.

↓

Modelos de alta capacidad.

Siempre se elegirá la alternativa de menor coste compatible con la calidad requerida.

---

# Espera

Cuando una Task finalice, el Dispatcher permanecerá bloqueado hasta recibir el resultado.

Nunca asumirá que una ejecución ha terminado correctamente.

---

# Reintentos

Cada Task podrá definir una política de reintentos.

Ejemplos.

- sin reintentos
- máximo tres intentos
- intervención manual

---

# Finalización

Cuando todas las Tasks del Pipeline hayan concluido, el Job pasará a estado Completed.

La Development Session permanecerá activa.

Los agentes continuarán ejecutándose.

El Dispatcher volverá al estado Waiting.

---

# Eventos

Toda acción relevante generará un evento.

Ejemplos.

- JobStarted
- AgentAssigned
- TaskCompleted
- PipelineCompleted
- JobCompleted
- RuntimeFailed

---

# Intervención humana

El usuario podrá cancelar un Job en cualquier momento.

El usuario podrá reiniciar un Pipeline.

El usuario podrá modificar el Pipeline antes de iniciarlo.

El Dispatcher nunca continuará automáticamente con un nuevo Job tras finalizar el anterior.

---

# Filosofía

El Dispatcher coordina el trabajo.

Los agentes realizan el razonamiento.

Los componentes deterministas ejecutan tareas mecánicas.

El desarrollador continúa siendo el responsable de dirigir el proceso de desarrollo.

