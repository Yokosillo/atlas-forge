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

**Estados reales del modelo `Agent` (`brain/models/agent.py`, campo `status`), verificados contra el backend en marcha:**

- `idle` — vivo, sin trabajo en curso, listo para recibir un Job.
- `working` — vivo, procesando un Job (`dispatch_job` lo transiciona a `working` antes de enviar la instrucción y siempre de vuelta a `idle` al terminar, éxito o fallo).
- `stopped` — detenido explícitamente (`stop_agent`) o descartado al cambiar de proyecto.
- `unavailable` — el rol existe en el registro pero no tiene runtime lanzado.

Un agente `stopped`/`unavailable` no conserva contexto de conversación al relanzarse — es una sesión tmux nueva. Solo un agente reutilizado en caliente (mismo rol, ya `idle`/`working`, `register_agent_with_reuse`) conserva su sesión y su historial.

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

# Agentes registrados hoy

**Nota de vigencia:** el Critic descrito en versiones anteriores de este documento se fusionó con el rol Arquitecto (ver `00-gobierno/old/CRITICO.md`, conservado como registro histórico de un rol ya descontinuado — no describe ningún comportamiento vigente). El rol único de revisión hoy es Arquitecto, no Critic.

Solo dos roles tienen función de registro real en el backend hoy (`register_role(RoleConfig(...))`, `04-src/src/brain/agents/*.py`) — cualquier otro rol mencionado más abajo ("Agentes previstos") no es lanzable todavía, aunque pueda aparecer listado en la interfaz con "Lanzar" deshabilitado (`US-FB024-11`).

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

Único rol multi-instancia (varios Developer simultáneos en la misma sesión, límite configurable — `system_preferences`/`MAX_SIMULTANEOUS_DEVELOPERS`, `US-FB024-12`). El resto de roles son de instancia única por sesión.

---

## Arquitecto

Responsabilidad.

Triple función: aterrizar backlog (generar Epic/User Story/Task a partir de necesidades descritas por el humano), emitir veredicto sobre el trabajo del Developer, y conversar sobre backlog ya existente sin modificarlo. Rol de gobierno completo en `00-gobierno/ARQUITECTO.md`.

Capacidades.

- generar backlog con formato estándar, validado por un módulo determinista antes de presentarse
- revisar el trabajo del Developer y decidir APROBADO / APROBADO_CON_OBSERVACIONES / RECHAZADO
- razonar sobre Epics/User Stories existentes sin generar ni modificar artefactos

No implementa código de producto — cualquier corrección que detecte se traduce en una Task nueva o en el siguiente prompt para el Developer, nunca en un parche escrito por el propio Arquitecto.

---

# Agentes previstos (no registrados todavía)

Factory Brain deberá permitir incorporar nuevos agentes sin modificar la arquitectura.

Ejemplos.

- Tester
- Auditor-OSS
- UX
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

**Identidad del proyecto activo (hueco detectado 2026-08-14, ver `T-FB005-US01-07`):** el agente arranca con su `cwd` real ya en el proyecto correcto, pero el rol base no menciona explícitamente el nombre del proyecto en el propio texto del prompt — el agente no debería tener que inferirlo con `pwd`/`git remote`. `T-FB005-US01-07` corrige esto añadiendo el nombre del proyecto activo de forma explícita al prompt inicial, mismo principio que el resto de esta sección.

---

## Rol base vs. gobierno específico de proyecto (corrección arquitectónica, ver T-FB005-US01-05)

Se detectó un hueco real que contradecía el principio anterior: el prompt inicial de cada rol (entonces Critic/Developer; Critic hoy fusionado en Arquitecto, ver "Agentes registrados hoy") delegaba en el propio agente la decisión de "si existen ficheros de gobierno en este proyecto, léelos" — es decir, el agente tenía que descubrir y construir su propio contexto de gobierno, no Factory Brain. Además, ese contexto (jerarquía Epic→Story→Task, protocolo de reporte) variaba según si el proyecto activo tenía o no su propia carpeta `00-gobierno/`, haciendo que el mismo rol se comportara de forma distinta según el proyecto sin que eso fuera una decisión consciente.

Corrección: el rol de cada agente (Arquitecto, Developer, y cualquier rol futuro) se define en dos capas, ambas construidas por Factory Brain, nunca por decisión del propio agente:

1. **Rol base**, en el propio código de `brain` (`agents/arquitecto.py`, `agents/developer.py`): responsabilidad y límites del rol (qué hace, qué NO hace) más un protocolo de reporte genérico (cómo comunica éxito/fallo de su trabajo) — completo y autosuficiente, válido para cualquier proyecto sobre el que Factory Brain opere, sin depender de que exista ningún fichero externo.
2. **Gobierno específico del proyecto**, capa adicional: si el proyecto activo declara su propia convención (`00-gobierno/<rol>.md` + `00-gobierno/METODOLOGIA.md`, mismo patrón ya usado en PROD-006/PROD-005), se añade como instrucción explícita para que el agente la lea — pero el rol base ya es funcional sin ella. Un proyecto sin esa convención (como PROD-004) no degrada el comportamiento del agente, solo carece de la capa adicional.

Factory Brain sigue siendo quien decide y construye ambas capas antes de arrancar el agente — el agente nunca decide por sí mismo qué leer, solo ejecuta la instrucción ya construida.

---

# Comunicación

Los agentes no se comunican directamente entre sí.

Toda la comunicación se realiza mediante artefactos persistentes (Markdown, JSON, informes, resultados de ejecución) y el mecanismo de despacho de Jobs, coordinado siempre por Brain — nunca los agentes negociando entre ellos.

## Despacho de un Job (humano o Arquitecto, mismo mecanismo)

`POST /jobs` es idéntico sin importar quién lo origina — el humano desde la interfaz, o el Arquitecto por su cuenta (vía Plan o conversacionalmente). El modelo `Job` no distingue emisor.

La instrucción se teclea en la sesión tmux del agente destino, pidiéndole explícitamente que escriba su resultado en un fichero temporal con un marcador de fin (`auto-reporte cooperativo`, `dispatch_job`, `brain/dispatcher/job_dispatch.py`) — no se trata la sesión como una shell con prompt, ni se usa `capture-pane`. El backend hace polling de ese fichero (timeout 30s por defecto, verificado sin excepción en ningún caller, incluido el flujo de Plan). `POST /jobs` es bloqueante: la petición no responde hasta que el Job termina.

## Aviso de cierre de Task hacia el Arquitecto (cola, ver `FB-030`)

Distinto del despacho de un Job: para que el Arquitecto se entere de que el Developer cerró una Task sin depender de un timeout corto ni de un mecanismo con destino fijo hardcodeado, cada proyecto tiene su propia cola de fichero append-only (`.claude/state/<proyecto>/architect_queue.jsonl`). El Developer anota ahí su cierre (Task, ruta del informe) sin bloquear. Un watcher (`inotify` sobre el directorio de la cola) calcula el nombre de sesión tmux del Arquitecto de ESE proyecto por convención de nombre normalizado (ver "Sesiones", más abajo) y le envía un aviso simple por `tmux send-keys` — sin volcar el contenido, sin fichero de suscripción. El Arquitecto además revisa su propia cola cada 10 minutos como respaldo.

Sustituye, para este caso, el mecanismo legado `watch_worker.sh` (destino de aviso hardcodeado a una única sesión fija, sin noción de proyecto).

---

# Estado

Cada agente tiene un estado observable (ver estados reales en "Ciclo de vida", arriba). La interfaz muestra siempre el estado actual.

---

# Sesiones

Cada agente se ejecuta dentro de una sesión tmux independiente, sobre un socket propio de Factory Brain (`factory-brain`, aislado del socket tmux por defecto del sistema para no interferir con sesiones que el usuario tenga abiertas fuera de la aplicación).

Una sesión tmux contiene exactamente una instancia del runtime correspondiente (Claude Code u OpenCode).

## Nombre de sesión normalizado (ver `FB-030`)

El nombre de la sesión tmux se calcula de forma determinista por rol y proyecto (`session_name_for`, `brain/runtime/generic.py`): `<rol>-<proyecto>` para roles de instancia única (p. ej. `arquitecto-PROD-006-factory-brain`), `<rol>-N-<proyecto>` para Developer (multi-instancia). No es un identificador opaco (UUID) — es reconocible de un vistazo y calculable sin coordinación en tiempo de ejecución, lo que permite dos capacidades adicionales:

- que el watcher de la cola de cierre (ver "Comunicación") sepa a qué sesión avisar sin fichero de suscripción;
- que Brain reconcilie agentes vivos al arrancar (ver "Reconciliación al arrancar", más abajo).

## Sesiones de proyecto simultáneas (ver `FB-029`)

Factory Brain mantiene una `DevelopmentSession` viva por proyecto (no una única sesión global) — trabajar en un proyecto no destruye los agentes de otro. La interfaz opera siempre sobre "el proyecto con foco"; cambiar el foco no detiene ningún agente del proyecto que lo pierde. Como máximo una sesión viva por proyecto.

## Reconciliación al arrancar (ver `FB-031`)

El registro de agentes vive en memoria del proceso `brain-api` — un reinicio del proceso lo pierde, aunque las sesiones tmux reales sigan vivas (caso real reproducido el 2026-08-14: un reinicio operativo del backend dejó `GET /agents` vacío mientras 8 sesiones tmux reales, incluida la del propio Arquitecto en curso, seguían respondiendo). Al arrancar, Brain lista las sesiones reales del socket tmux, reconoce las que siguen el patrón de nombre normalizado del proyecto activo, y las reengancha a su registro en estado `idle` — sin relanzar el runtime, sin perder la sesión tmux ya viva. No se reconcilia el estado `working`/el resultado de un Job en curso en el momento del reinicio.

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

