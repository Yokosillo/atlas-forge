# Arquitectura

## Objetivo

Factory Brain debe desarrollarse como una aplicación modular, extensible y mantenible.

La arquitectura debe permitir incorporar nuevas funcionalidades durante años sin necesidad de reestructurar el proyecto.

El desacoplamiento entre componentes es un requisito fundamental.

---

# Tipo de aplicación

Factory Brain nació como una aplicación TUI (Terminal User Interface) y ese sigue siendo su cliente de referencia, pero el dominio (agentes, sesiones, Jobs, Dispatcher) no pertenece a la TUI ni a ningún cliente concreto — vive detrás de una API propia (`brain/api/`, FastAPI) que cualquier interfaz puede consumir.

No es una colección de scripts.

No es una utilidad de línea de comandos.

No es un conjunto de comandos Bash.

La TUI debe comportarse como herramientas profesionales como:

- LazyGit
- k9s
- Lazydocker
- btop

La CLI únicamente servirá para arrancar la aplicación o ejecutar procesos automáticos.

Dentro de la TUI, toda la interacción del usuario se realiza desde ahí — no hay comandos sueltos.

---

# Clientes

Factory Brain expone su dominio a través de una única API HTTP/WebSocket (`brain/api/`), de la que penden todos sus clientes. Ningún cliente accede al dominio de otra forma que no sea esa API — incluida la propia TUI, que es cliente HTTP como cualquier otro, no un caso especial con acceso directo.

Clientes existentes o previstos:

- **TUI** (`brain/tui/`, Textual) — cliente de referencia, primero en recibir cada capacidad nueva.
- **App Android** (`10-android/`, Kotlin/Compose) — control remoto vía Tailscale, misma API que la TUI.
- **Interfaz web** (futura, sin Epic todavía) — mismo principio: cliente HTTP sobre la API existente, sin necesitar dominio nuevo ni acceso directo a `brain/agents`, `brain/dispatcher`, `brain/core`, etc.

Un cliente nuevo no debe requerir cambios en el dominio, solo en la capa de Presentación de ese cliente y, si acaso, un endpoint nuevo en `brain/api/` que envuelva capacidad de dominio ya existente. Las excepciones documentadas donde la TUI importa dominio directamente (catálogo estático de `brain/agents/agent_options`, configuración de disco local vía `brain/workspace`) son eso — excepciones acotadas y verificadas por test (`04-src/tests/test_module_boundaries.py`), no el patrón a seguir por clientes nuevos. Un cliente sin proceso local (como una interfaz web) no tiene ni siquiera esa opción: depende de la API en su totalidad.

---

# Workspace

Factory Brain trabaja sobre un único Workspace.

Ejemplo:

factoria-software/

Dentro del Workspace existen múltiples repositorios Git.

El sistema descubrirá automáticamente dichos repositorios.

El repositorio Git constituye la unidad principal de trabajo.

---

# Flujo de navegación

La aplicación seguirá el siguiente flujo principal.

Inicio

↓

Descubrir repositorios

↓

Seleccionar proyecto

↓

Dashboard del proyecto

↓

Seleccionar módulo

↓

Ejecutar funcionalidad

El usuario deberá poder volver siempre al Dashboard del proyecto sin abandonar la aplicación.

---

# Organización del código

La estructura del proyecto será la siguiente.

PROD-006-factory-brain/

├──00-gobierno
├──01-documentacion
├──02-backlog
├──03-conocimiento
├──04-src
│   ├──src
│   │   └──brain
│   │       ├──agents
│   │       ├──api
│   │       ├──cli
│   │       ├──context
│   │       ├──core
│   │       ├──dispatcher
│   │       ├──git
│   │       ├──indexer
│   │       ├──knowledge
│   │       ├──local_tools
│   │       ├──models
│   │       ├──plugins
│   │       ├──runtime
│   │       ├──search
│   │       ├──storage
│   │       ├──tmux
│   │       ├──tui
│   │       │   └──screens
│   │       └──workspace
│   └──tests
├──05-database
├──06-runtime
├──07-informes
├──08-logs
├──09-cache
└──10-android

---

# Capas de la aplicación

La aplicación se dividirá en cuatro capas principales.

## Presentación

Hoy implementada mediante Textual (TUI) y Kotlin/Compose (app Android); en el futuro, cualquier framework web sobre el mismo contrato HTTP/WebSocket de `brain/api/`.

Responsable de la navegación y la interacción con el usuario.

No contendrá lógica de negocio, en ningún cliente — esta regla no es específica de la TUI, aplica igual a la app Android y a cualquier interfaz futura (web incluida). Un cliente nuevo se apoya en `brain/api/`, nunca reimplementa ni bypassa el dominio.

---

## Aplicación

Coordina las operaciones solicitadas desde la interfaz.

Implementa los casos de uso.

Orquesta los distintos componentes.

---

## Dominio

Implementa las reglas de negocio.

Gestiona proyectos, agentes, sesiones, contexto y conocimiento.

Debe ser independiente de la interfaz.

---

## Infraestructura

Gestiona el acceso a Git, SQLite, tmux, sistema de archivos y runtimes externos.

---

# Módulos

Cada módulo deberá ser independiente.

Los módulos previstos son:

- Workspace
- Projects
- Context
- Knowledge
- Search
- Git
- Agents
- Runtime
- Dispatcher
- Sessions
- Indexer
- Plugins
- Configuration

Cada módulo expondrá una interfaz clara y evitará dependencias innecesarias con el resto.

---

# Persistencia

Toda la información persistente deberá almacenarse fuera del código fuente.

Se utilizarán directorios específicos para:

- bases de datos
- logs
- cache
- runtime

No se almacenará información temporal dentro del código.

---

# Extensibilidad

Factory Brain debe permitir incorporar nuevos módulos sin modificar el núcleo.

También deberá permitir añadir nuevos agentes, nuevos runtimes y nuevas herramientas mediante una arquitectura basada en componentes.

---

# Calidad

Las implementaciones deberán cumplir los siguientes principios:

- Bajo acoplamiento.
- Alta cohesión.
- Responsabilidad única.
- Separación entre interfaz y lógica de negocio.
- Código reutilizable.
- Cambios incrementales.
- Arquitectura orientada a largo plazo.

Las decisiones de diseño deberán priorizar siempre la mantenibilidad frente a soluciones rápidas.

---

# Modelo de ejecución

La arquitectura distingue dos conceptos fundamentales.

Sesión de desarrollo.

Representa un entorno persistente de trabajo sobre un proyecto.

Trabajo.

Representa una unidad concreta de desarrollo, como una User Story o una tarea del backlog.

Los trabajos se ejecutan dentro de una sesión de desarrollo.

La sesión permanece activa tras finalizar cada trabajo.

