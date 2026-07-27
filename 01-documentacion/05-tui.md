# Terminal User Interface

## Objetivo

La Terminal User Interface constituye la interfaz principal de Factory Brain.

El usuario permanecerá dentro de la aplicación durante toda la sesión de trabajo.

No deberá ser necesario ejecutar comandos Bash para utilizar las funcionalidades habituales del sistema.

La aplicación deberá proporcionar una experiencia similar a herramientas como LazyGit, k9s o Lazydocker.

---

# Principios

La TUI deberá cumplir los siguientes principios.

- Navegación sencilla.
- Respuesta inmediata.
- Atajos de teclado consistentes.
- Estado visible.
- Información contextual.
- Operaciones no destructivas.

---

# Flujo principal

Inicio

↓

Workspace

↓

Selección de proyecto

↓

Dashboard

↓

Módulo

↓

Acción

↓

Dashboard

El Dashboard constituye el centro de navegación.

Todas las pantallas deberán permitir volver a él.

---

# Pantallas

## Workspace

Responsabilidades.

- Descubrir proyectos.
- Mostrar repositorios.
- Seleccionar proyecto.
- Cambiar proyecto activo.

---

## Dashboard

Responsabilidades.

- Información del proyecto.
- Estado general.
- Acceso a módulos.
- Acciones rápidas.

Desde esta pantalla el usuario accederá al resto de funcionalidades.

---

## Agentes

Responsabilidades.

- Listar agentes.
- Crear agentes.
- Configurar agentes.
- Cambiar runtime.
- Ver estado.
- Ver historial.

---

## Sesiones

Responsabilidades.

- Mostrar sesiones tmux.
- Crear sesiones.
- Reiniciar sesiones.
- Adjuntarse.
- Finalizar sesiones.

---

## Contexto

Responsabilidades.

- Construir contexto.
- Mostrar contexto.
- Actualizar resúmenes.
- Consultar documentación.

---

## Knowledge

Responsabilidades.

- Buscar documentos.
- Consultar índices.
- Mostrar relaciones.
- Reindexar.

---

## Git

Responsabilidades.

- Estado.
- Diff.
- Commit.
- Branch.
- Push.
- Pull.

---

## Runtime

Responsabilidades.

- Mostrar runtimes.
- Estado.
- Configuración.
- Diagnóstico.

---

## Dispatcher

Responsabilidades.

- Trabajos.
- Cola.
- Estado.
- Historial.
- Reintentos.

---

## Logs

Responsabilidades.

- Eventos.
- Errores.
- Diagnóstico.
- Auditoría.

---

# Widgets

La interfaz reutilizará widgets comunes.

Ejemplos.

- Tabla.
- Lista.
- Árbol.
- Panel.
- Inspector.
- Barra lateral.
- Barra de estado.
- Consola.
- Visor de documentos.

Los widgets deberán reutilizarse entre pantallas.

---

# Navegación

La navegación deberá ser consistente.

Ejemplos.

- Flechas.
- Enter.
- Escape.
- Tab.
- Backspace.

Cada pantalla podrá añadir atajos específicos.

---

# Estado

La aplicación mostrará permanentemente.

- Proyecto activo.
- Rama Git.
- Runtime activo.
- Agentes ejecutándose.
- Número de sesiones.
- Trabajos pendientes.

El usuario no deberá perder el contexto durante la navegación.

---

# Filosofía

La interfaz deberá minimizar el número de pasos necesarios para ejecutar una tarea.

Las acciones frecuentes deberán estar disponibles desde el Dashboard.

La incorporación de nuevas pantallas no deberá modificar el flujo principal de navegación.

---

# Inicio de la aplicación

El flujo principal será el siguiente.

Workspace

↓

Seleccionar proyecto

↓

Dashboard

↓

Iniciar sesión de desarrollo

↓

Inicialización automática de agentes

↓

Esperando trabajo

Una vez iniciada la sesión, el usuario podrá lanzar trabajos de desarrollo sin necesidad de reiniciar los agentes.

