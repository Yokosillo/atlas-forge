# Workspace

## Objetivo

El Workspace constituye el ámbito de trabajo de Factory Brain.

Representa la factoría de desarrollo completa y contiene todos los proyectos gestionados por la aplicación.

El Workspace es el punto de entrada para cualquier operación realizada por Factory Brain.

---

# Conceptos

## Workspace

El Workspace es un directorio raíz que agrupa todos los repositorios de la factoría.

Ejemplo.

factoria-software/

Dentro del Workspace pueden existir proyectos, documentación compartida, herramientas y otros recursos comunes.

---

## Proyecto

Un proyecto corresponde a un repositorio Git.

El repositorio constituye la unidad mínima de trabajo.

Factory Brain nunca trabajará directamente sobre directorios que no sean repositorios.

---

## Proyecto activo

En cada momento existirá un único proyecto activo.

Todas las operaciones se ejecutarán sobre dicho proyecto salvo que el usuario indique explícitamente otro.

El proyecto activo permanecerá seleccionado entre sesiones.

---

# Descubrimiento

Factory Brain descubrirá automáticamente todos los repositorios Git presentes dentro del Workspace.

El descubrimiento será recursivo.

No será necesario registrar manualmente los proyectos.

---

# Información del proyecto

Cada proyecto deberá disponer, como mínimo, de la siguiente información.

- nombre
- ruta
- rama activa
- estado Git
- fecha de última modificación
- número de agentes activos
- número de sesiones
- runtime asociado
- documentación disponible

La información deberá actualizarse automáticamente.

---

# Selección

El primer paso tras iniciar Factory Brain será seleccionar un proyecto.

Una vez seleccionado se accederá al Dashboard correspondiente.

El usuario podrá cambiar de proyecto en cualquier momento.

---

# Contexto

Cada proyecto dispondrá de un contexto independiente.

El contexto incluirá información como.

- documentación
- backlog
- conocimiento
- configuración
- historial
- resúmenes
- índices

La información de un proyecto nunca deberá mezclarse con la de otro.

---

# Recursos compartidos

El Workspace podrá contener recursos comunes accesibles por todos los proyectos.

Ejemplos.

- plantillas
- documentación corporativa
- agentes compartidos
- plugins
- herramientas
- scripts

Estos recursos no pertenecerán a un proyecto concreto.

---

# Organización

Factory Brain no impondrá una estructura rígida para los proyectos.

Únicamente requerirá que cada proyecto sea un repositorio Git válido.

No obstante, podrá reconocer estructuras conocidas para ofrecer funcionalidades adicionales.

---

# Escalabilidad

La arquitectura deberá soportar decenas o cientos de proyectos dentro del mismo Workspace.

El descubrimiento y la indexación deberán ser incrementales para minimizar el tiempo de carga.

---

# Persistencia

Factory Brain almacenará información del Workspace.

Como mínimo.

- último proyecto activo
- proyectos conocidos
- configuración
- preferencias
- índices
- estado de sincronización

---

# Filosofía

El Workspace representa la factoría completa.

Los proyectos son unidades independientes dentro de dicha factoría.

Factory Brain debe ofrecer una experiencia homogénea independientemente del número de proyectos existentes o de las tecnologías utilizadas por cada uno.

---

# Sesión de desarrollo

Cada proyecto podrá tener una única sesión de desarrollo activa.

La sesión agrupa todos los recursos utilizados durante el trabajo.

Incluye.

- agentes
- runtimes
- sesiones tmux
- contexto
- historial
- trabajos ejecutados

El usuario podrá iniciar y finalizar la sesión manualmente desde Factory Brain.

