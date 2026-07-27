# Factory Brain

## Visión del producto

Factory Brain es el sistema operativo de una factoría de desarrollo software basada en inteligencia artificial.

No es un IDE.

No es un editor de código.

No es un asistente conversacional.

Es una plataforma de orquestación cuyo objetivo es coordinar proyectos, agentes, contexto, herramientas y procesos de desarrollo desde una única aplicación de terminal.

Factory Brain constituye el punto de entrada para cualquier tarea de desarrollo dentro de la factoría.

Toda la interacción con los proyectos deberá realizarse desde Factory Brain.

---

# Problema

Actualmente el desarrollo asistido por IA requiere utilizar múltiples herramientas independientes.

Es habitual mantener varias sesiones de Claude Code abiertas, lanzar procesos mediante tmux, utilizar OpenCode para determinados modelos, consultar documentación manualmente y cambiar continuamente entre proyectos.

Cada herramienta mantiene su propio estado.

El conocimiento del proyecto está disperso.

No existe un punto central que coordine los agentes, el contexto y las herramientas.

Como consecuencia:

- se pierde tiempo preparando el contexto
- se consumen más tokens de los necesarios
- es difícil reutilizar información entre agentes
- la coordinación entre herramientas es manual
- los proyectos no siguen un flujo homogéneo

Factory Brain nace para resolver este problema.

---

# Objetivos

Factory Brain debe convertirse en el sistema operativo de la factoría.

Debe permitir trabajar sobre cualquier proyecto desde una única interfaz.

Los objetivos principales son:

- descubrir automáticamente todos los repositorios Git del workspace
- gestionar múltiples proyectos
- construir automáticamente el contexto de cada proyecto
- coordinar múltiples agentes de IA
- administrar sesiones persistentes mediante tmux
- integrar distintas herramientas de desarrollo
- facilitar el intercambio de información entre agentes
- reducir el consumo de tokens
- automatizar tareas repetitivas
- proporcionar una experiencia de trabajo uniforme para todos los proyectos

---

# Alcance

Factory Brain no pertenece a un único proyecto.

Es un producto transversal.

Su responsabilidad es administrar todos los repositorios de la factoría independientemente del lenguaje, la tecnología o el dominio funcional.

El repositorio Git constituye la unidad principal de trabajo.

Todas las funcionalidades girarán alrededor del repositorio seleccionado.

---

# Principios

El diseño de Factory Brain seguirá los siguientes principios.

## Un único punto de entrada

El desarrollador iniciará Factory Brain al comenzar su sesión de trabajo.

Desde ese momento todas las operaciones deberán realizarse desde la aplicación.

---

## El repositorio es la unidad de trabajo

Factory Brain nunca trabajará sobre directorios arbitrarios.

El sistema descubrirá automáticamente los repositorios Git disponibles y permitirá seleccionar uno de ellos como proyecto activo.

Todas las acciones posteriores se ejecutarán sobre ese proyecto.

---

## Arquitectura modular

Cada funcionalidad deberá implementarse como un módulo independiente.

La incorporación de nuevas capacidades no deberá requerir modificaciones en el núcleo de la aplicación.

---

## Agentes especializados

Cada agente tendrá una responsabilidad concreta.

Ejemplos:

- Developer
- Critic
- Architect
- Tester
- Reviewer
- Documentation
- Security
- Research

Los agentes podrán colaborar entre sí para completar una misma tarea.

---

## Desacoplamiento entre agentes y runtimes

Factory Brain no ejecutará modelos de lenguaje directamente.

Los agentes se ejecutarán sobre distintos runtimes, como Claude Code, Codex u OpenCode.

Cada runtime utilizará los modelos configurados en su propio entorno.

Factory Brain únicamente administrará los agentes y coordinará su ejecución.

---

## Persistencia

El estado del sistema deberá mantenerse entre sesiones.

Factory Brain deberá recordar:

- proyectos
- agentes
- sesiones
- contexto
- índices
- configuración

---

## Automatización

Las tareas repetitivas deberán poder automatizarse.

Factory Brain actuará como orquestador de procesos, eliminando trabajo manual siempre que sea posible.

---

# Usuario objetivo

Factory Brain está orientado a desarrolladores que trabajan con múltiples proyectos y utilizan inteligencia artificial como parte habitual de su flujo de trabajo.

Especialmente aquellos que:

- mantienen varias sesiones simultáneas
- utilizan distintos proveedores de IA
- necesitan conservar contexto entre sesiones
- trabajan con arquitecturas complejas
- desean automatizar tareas de desarrollo

---

# Objetivo a largo plazo

Factory Brain debe evolucionar hasta convertirse en el centro operativo de toda la factoría de desarrollo.

El usuario no debería necesitar abandonar la aplicación para realizar tareas habituales de desarrollo, coordinación de agentes, gestión del conocimiento o administración de proyectos.

Toda nueva funcionalidad deberá contribuir a este objetivo.

---

# Filosofía de operación

Factory Brain no pretende sustituir al desarrollador.

El desarrollador continúa siendo el responsable de dirigir el proceso de desarrollo y de tomar las decisiones relevantes.

Factory Brain automatiza la ejecución del trabajo, no las decisiones sobre qué trabajo realizar.

El usuario decide cuándo comienza un trabajo y cuándo inicia uno nuevo.

Una vez iniciado un trabajo, Factory Brain coordina automáticamente los agentes necesarios hasta completar dicho trabajo.

Al finalizar, el sistema vuelve al estado de espera.

No se iniciará automáticamente un nuevo trabajo.

---

# Sesiones de desarrollo

El trabajo se organiza mediante sesiones de desarrollo.

Una sesión de desarrollo representa un periodo de trabajo sobre un proyecto.

Durante una sesión permanecen activos los agentes necesarios para el desarrollo.

Los agentes mantienen su contexto y su historial entre trabajos.

Una sesión puede contener múltiples trabajos consecutivos.

