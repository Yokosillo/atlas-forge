# Agentes

## Objetivo

Los agentes constituyen la unidad fundamental de trabajo de Factory Brain.

Un agente representa un rol especializado dentro del proceso de desarrollo de software.

Los agentes no son modelos de lenguaje.

Los agentes tampoco son procesos del sistema operativo.

Un agente es una combinación de:

- Rol
- Prompt
- Runtime
- Sesión
- Contexto
- Estado

---

# Principios

Todos los agentes deberán cumplir los siguientes principios.

- Especialización.
- Responsabilidad única.
- Persistencia.
- Independencia.
- Reutilización.
- Colaboración.

Cada agente deberá tener un propósito claramente definido.

---

# Ciclo de vida

Todo agente atravesará el siguiente ciclo.

Creado

↓

Configurado

↓

Inicializado

↓

Disponible

↓

Ejecutándose

↓

Esperando

↓

Finalizado

↓

Archivado

Un agente podrá volver a activarse sin perder su historial.

---

# Configuración

Cada agente dispondrá de una configuración persistente.

Campos mínimos.

- id
- nombre
- rol
- runtime
- proyecto
- prompt
- tmux_session
- estado
- prioridad
- configuración específica

---

# Agentes iniciales

## Developer

Responsabilidad.

Implementar funcionalidades.

Capacidades.

- escribir código
- modificar documentación
- crear tests
- refactorizar
- generar propuestas

No valida su propio trabajo.

---

## Critic

Responsabilidad.

Revisar el trabajo realizado por otros agentes.

Capacidades.

- revisión técnica
- búsqueda de defectos
- validación funcional
- validación arquitectónica
- identificación de riesgos

No implementa funcionalidades.

---

# Agentes previstos

Factory Brain deberá permitir incorporar nuevos agentes sin modificar la arquitectura.

Ejemplos.

- Architect
- Tester
- Reviewer
- Security
- Documentation
- Research
- Performance
- DevOps
- Product Manager

---

# Contexto

Antes de ejecutar una tarea, el agente recibirá un contexto construido automáticamente.

El contexto podrá incluir.

- documentación
- backlog
- código
- historial
- resultados anteriores
- informes
- decisiones arquitectónicas

El agente nunca deberá construir manualmente su propio contexto.

---

## Rol base vs. gobierno específico de proyecto (corrección arquitectónica, ver T-FB005-US01-05)

Se detectó un hueco real que contradecía el principio anterior: el prompt inicial de Critic/Developer delegaba en el propio agente la decisión de "si existen ficheros de gobierno en este proyecto, léelos" — es decir, el agente tenía que descubrir y construir su propio contexto de gobierno, no Factory Brain. Además, ese contexto (jerarquía Epic→Story→Task, protocolo de reporte) variaba según si el proyecto activo tenía o no su propia carpeta `00-gobierno/`, haciendo que el mismo rol se comportara de forma distinta según el proyecto sin que eso fuera una decisión consciente.

Corrección: el rol de cada agente (Critic, Developer) se define en dos capas, ambas construidas por Factory Brain, nunca por decisión del propio agente:

1. **Rol base**, en el propio código de `brain` (`agents/critic.py`, `agents/developer.py`): responsabilidad y límites del rol (qué hace, qué NO hace) más un protocolo de reporte genérico (cómo comunica éxito/fallo de su trabajo) — completo y autosuficiente, válido para cualquier proyecto sobre el que Factory Brain opere, sin depender de que exista ningún fichero externo.
2. **Gobierno específico del proyecto**, capa adicional: si el proyecto activo declara su propia convención (`00-gobierno/<rol>.md` + `00-gobierno/METODOLOGIA.md`, mismo patrón ya usado en PROD-006/PROD-005), se añade como instrucción explícita para que el agente la lea — pero el rol base ya es funcional sin ella. Un proyecto sin esa convención (como PROD-004) no degrada el comportamiento del agente, solo carece de la capa adicional.

Factory Brain sigue siendo quien decide y construye ambas capas antes de arrancar el agente — el agente nunca decide por sí mismo qué leer, solo ejecuta la instrucción ya construida.

---

# Comunicación

Los agentes no se comunicarán directamente.

Toda la comunicación se realizará mediante artefactos persistentes.

Ejemplos.

- Markdown
- JSON
- YAML
- Informes
- Resultados de ejecución

El Dispatcher será el encargado de coordinar el intercambio de información.

---

# Estado

Cada agente tendrá un estado observable.

Estados iniciales.

- Idle
- Running
- Waiting
- Blocked
- Failed
- Completed

La interfaz mostrará siempre el estado actual.

---

# Sesiones

Cada agente se ejecutará dentro de una sesión independiente de tmux.

Una sesión contendrá exactamente una instancia del runtime correspondiente.

Factory Brain administrará el ciclo de vida de dichas sesiones.

---

# Independencia

Los agentes no deberán conocer la existencia de otros agentes.

Cada uno recibirá únicamente el contexto necesario para ejecutar su tarea.

La coordinación será responsabilidad exclusiva del Dispatcher.

---

# Objetivo

El diseño deberá permitir ejecutar simultáneamente múltiples agentes especializados sobre distintos proyectos y distintos runtimes manteniendo un modelo homogéneo de operación.

---

# Persistencia

Los agentes son persistentes.

Un agente no se crea para ejecutar una única tarea.

El agente permanece activo durante toda la sesión de desarrollo.

El historial de conversación y el contexto acumulado forman parte del estado del agente.

Factory Brain reutilizará la misma sesión siempre que sea posible para reducir el consumo de tokens y mantener la continuidad del razonamiento.

