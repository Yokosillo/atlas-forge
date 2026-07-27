# Development Session

## Objetivo

La Development Session representa un entorno persistente de trabajo sobre un proyecto.

Su finalidad es evitar la recreación continua de agentes y conservar el contexto de trabajo entre tareas.

---

# Componentes

Una sesión de desarrollo incluye.

- proyecto activo
- agentes activos
- runtimes
- sesiones tmux
- contexto acumulado
- historial de trabajos
- configuración temporal

---

# Ciclo de vida

Creada

↓

Inicializada

↓

Agentes iniciados

↓

Esperando trabajo

↓

Ejecutando trabajo

↓

Esperando trabajo

↓

Finalizada

---

# Funcionamiento

El usuario inicia la sesión manualmente.

Factory Brain crea automáticamente los agentes configurados para el proyecto.

Los agentes permanecen activos hasta que el usuario finaliza la sesión.

Cada nuevo trabajo se ejecuta utilizando los mismos agentes y el mismo contexto acumulado.

---

# Objetivos

- reducir consumo de tokens
- mantener continuidad del razonamiento
- evitar reinicializaciones
- disminuir tiempos de espera
- centralizar el estado del desarrollo

