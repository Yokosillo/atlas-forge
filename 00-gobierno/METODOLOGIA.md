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

# Chequeo de reconciliación de estado

El backlog tiene un mecanismo automático de red de seguridad para garantizar
que el estado de US/Epic nunca quede desincronizado respecto a sus hijos
(criterio de la US-FB022-13). Se ejecuta en **cada `git commit`** como
pre-commit hook, no como pipeline de CI: este repositorio no tiene CI remoto
(sin `.github/`, sin `.gitlab-ci.yml`), así que el gancho se instala
localmente por fichero (ver más abajo).

## Quién lo ejecuta (determinista, sin LLM)

El encargado de ejecutarlo es `04-src/scripts/promote_states.py --check`
(Python determinista dentro del venv `04-src/.venv`), que implementa la regla
de trazabilidad definida en `brain/backlog/promote.py`:

1. Una User Story → `DONE` si tiene ≥1 Task y todas sus Tasks son `DONE`.
2. Una Epic → `DONE` si tiene ≥1 US y todas sus US son `DONE`.

Solo detecta drift: `--check` no escribe nada; `--apply` escribe las
promociones. Ambos son **deterministas e idempotentes** — no interviene ningún
agente LLM en la decisión, coherente con "automatización determinista primero".

## Cuándo se ejecuta

- **Pre-commit hook** (local, en cada commit): `promote_states.py --check`
  corre con `git commit` y **bloquea el commit** si hay drift (US/Epic con
  todos sus hijos `DONE` pero el padre no); es el único mecanismo de reporte
  en el proyecto (no hay pipeline de CI remoto) — siempre que el gancho esté
  instalado.
- **Síncrono en el pipeline** (`brain/dispatcher/job_plan_dispatch.py`):
  `_mark_story_tasks_done` invoca `promote_backlog` justo después de marcar
  `DONE` las Tasks de una Story — mismo instante, sin ventana de inconsistencia.

## Instalación

El hook se instala con:

```bash
bash 04-src/scripts/install_git_hooks.sh
```

que escribe `.git/hooks/pre-commit` (respaldando antes una versión previa en
`.git/hooks/pre-commit.bak`). Debe reinstalarse en cada clon del repositorio.

## Resolución de drift

El mensaje del hook indica la solución: salir de drift se hace con
`promote_states.py --apply`:

```bash
python3 04-src/scripts/promote_states.py --apply
git add 02-backlog/ && git commit
```

Como el chequeo es idempotente, ejecutar `--apply` sobre un backlog ya
consistente no cambia nada — por lo que se puede entrelazar con `--check`
sin miedo.

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

# Protocolo de reorientación de producto (análisis doble + reconstrucción de backlog)

Existe un modo de trabajo distinto del ciclo normal Task→Implementación, reservado para cuando el producto necesita un cambio de dirección de fondo (no una funcionalidad nueva, sino repensar cómo se organiza el trabajo existente). Se usó por primera vez el 2026-08-04/05 para reorientar Factory Brain hacia un pipeline Backlog-céntrico (resultado: `FB-022`, `FB-023`), y queda documentado aquí como opción reutilizable, no como excepción de una sola vez.

## Cuándo aplica

Cuando el usuario plantea una reorientación de producto de alcance amplio (afecta a varias Epics, cambia roles de agente, o redefine cómo se organiza el trabajo), no una Task o User Story puntual. Señal característica: la pregunta no es "¿cómo implemento X?" sino "¿deberíamos organizar esto de otra forma?".

## Los pasos

1. **Investigación de código en paralelo, no supuestos.** Antes de proponer nada, verificar con evidencia directa (grep, lectura de módulos) qué existe hoy y qué no — nunca asumir el estado del sistema por la documentación de intención. Puede delegarse en un agente Explore para no gastar el contexto principal en lecturas exhaustivas.

2. **Informe de arquitectura propio, redactado directamente (no delegado).** Quien conduce la reorientación (el asistente principal de la conversación) escribe un primer informe con: visión de destino descrita por el usuario, estado real pieza por pieza (verificado, no supuesto), decisiones razonadas explícitas sobre los puntos ambiguos que el usuario deja abiertos (no listar opciones sin más — dar una recomendación con su porqué), y tamaño relativo del trabajo. Se guarda en `07-informes/`.

3. **Auditoría independiente de un segundo agente, con encargo por escrito y persistente.** Se prepara un encargo detallado (rol, marco de producto, preguntas concretas obligatorias por área, método de verificación exigido, formato de entregable) y se guarda como fichero de gobierno reutilizable en `00-gobierno/` (no solo como prompt efímero) — mismo patrón que `ARQUITECTO.md`/`DEVELOPER.md`. El agente auditor recibe el informe de arquitectura como contexto obligatorio, para que su auditoría lo contraste en vez de partir de cero.

4. **El auditor no es un espejo — se le exige incisividad y evidencia verificable.** El encargo debe prohibir explícitamente hallazgos vacíos ("la UX podría mejorar" sin decir cómo) y exigir que cada afirmación sea reproducible por un tercero (cita de línea de código, captura real, comando ejecutado). Navegación/verificación real contra el sistema vivo, no solo lectura de código estático, cuando el objeto de auditoría lo permite.

5. **Crítica dura del resultado, con verificación cruzada — nunca aceptación automática.** Quien conduce la reorientación no da por bueno el informe del auditor solo porque termine con el marcador de cierre. Se verifican al menos algunas afirmaciones concretas contra el código real (no todas — una muestra representativa basta para calibrar confianza), y se exige corrección de lo que no pase esa verificación antes de darlo por definitivo. El agente auditor puede y debe recibir una segunda ronda con observaciones concretas, reutilizando su misma sesión (no repitiendo la investigación desde cero) si el runtime lo permite.

6. **Preguntas abiertas se resuelven con análisis explícito, no se dejan sin decidir.** Si durante el proceso surge una duda de arquitectura no resuelta por ninguno de los dos informes (p. ej. "¿deberíamos fusionar estos dos roles?"), se responde con el mismo rigor — ventajas/desventajas explícitas, no una opinión sin fundamento — y se documenta la decisión razonada en el informe antes de escribir el backlog.

7. **Reconstrucción del backlog combinando ambos informes, solo al final.** Nuevas Epics/User Stories/Tasks se escriben después de tener ambos informes (arquitectura + auditoría) y las preguntas abiertas resueltas — nunca antes, para no tener que reescribir el backlog dos veces. Cada Epic nueva debe citar su origen (qué informes la motivan) en su sección de Contexto.

## Nota operativa: si el segundo agente corre sobre OpenCode headless

Ver `00-gobierno/ARQUITECTO.md`, sección "Lanzar OpenCode para una tarea puntual sin supervisión" — el protocolo técnico de lanzamiento (evitar tmux, usar `opencode run --auto` o `opencode serve`, fragmentar escrituras largas, detectar cuelgues por inactividad de log) es prerrequisito operativo para que los pasos 3-5 de este protocolo funcionen de forma fiable sin intervención manual constante.

---

# Regla fundamental

Si durante una implementación aparece una decisión arquitectónica nueva, el desarrollo debe detenerse temporalmente.

La decisión debe documentarse.

Después debe actualizarse la documentación o el backlog.

Solo entonces debe continuar la implementación.

La arquitectura dirige el desarrollo.

El desarrollo nunca debe dirigir la arquitectura.
