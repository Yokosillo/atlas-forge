# Automation Engine

## Objetivo

El Automation Engine es el subsistema responsable de ejecutar todas las tareas deterministas y de bajo coste dentro de Factory Brain.

Su finalidad es reducir el trabajo manual del desarrollador, minimizar el consumo de tokens y preparar el trabajo para los agentes cognitivos.

El Automation Engine constituye la primera capa de ejecución del sistema.

---

# Principios

- Automatizar todo proceso repetitivo.
- Priorizar algoritmos deterministas.
- Reutilizar resultados previamente calculados.
- Reducir llamadas a modelos de lenguaje.
- Preparar información antes de invocar agentes.

---

# Responsabilidades

El Automation Engine será responsable de.

- indexar proyectos
- analizar repositorios
- construir contexto
- generar resúmenes
- detectar cambios
- localizar documentación
- analizar dependencias
- generar estadísticas
- preparar prompts
- detectar artefactos relevantes

---

# Tipos de componentes

## Scripts deterministas

Implementados mediante software tradicional.

Ejemplos.

- Python
- Git
- ripgrep
- tree-sitter
- SQLite
- Watchdog

Estas tareas no requieren razonamiento.

---

## Modelos locales

Utilizados cuando una tarea requiere cierta capacidad de comprensión pero no justifica consumir un modelo remoto.

Ejemplos.

- resumen de documentos
- clasificación
- extracción de conceptos
- etiquetado
- agrupación
- generación de contexto
- búsqueda semántica

Los modelos locales tendrán prioridad sobre modelos remotos cuando la calidad obtenida sea suficiente.

---

# Caché

Todo resultado reutilizable deberá almacenarse.

Ejemplos.

- índices
- resúmenes
- embeddings
- hashes
- dependencias
- contexto preparado

El sistema evitará recalcular información que permanezca vigente.

---

# Disparadores

Los componentes podrán ejecutarse.

- manualmente
- al detectar cambios
- al iniciar una sesión
- antes de ejecutar un Job
- bajo demanda del Dispatcher

---

# Integración con el Dispatcher

El Dispatcher podrá solicitar capacidades al Automation Engine del mismo modo que a un agente.

Ejemplos.

context.build

↓

Automation Engine

summary.generate

↓

Automation Engine

knowledge.search

↓

Automation Engine

Solo cuando el Automation Engine no pueda resolver una tarea se recurrirá a un agente cognitivo.

---

# Objetivo estratégico

El Automation Engine deberá absorber el mayor porcentaje posible del trabajo mecánico de la factoría.

Los agentes de IA deberán concentrarse exclusivamente en tareas que requieran razonamiento, creatividad o juicio técnico.

