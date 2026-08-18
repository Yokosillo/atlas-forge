# Protocolo de reorientación de producto

## Cuándo se utiliza

Cuando el usuario plantea un cambio de dirección que afecta a varias Epics, roles, arquitectura o forma de organizar el trabajo.

No se utiliza para una funcionalidad normal que puede modelarse directamente como User Story/Task.

## Fases

### 1. Investigación

Verificar el sistema real mediante código, ejecución o herramientas. No asumir que la documentación de intención refleja el runtime.

### 2. Informe arquitectónico

El responsable de conducir la reorientación redacta:

- visión de destino;
- estado actual verificado;
- decisiones recomendadas;
- ambigüedades;
- tamaño relativo del cambio;
- riesgos.

### 3. Auditoría independiente

Un segundo agente recibe el informe como contexto y lo contrasta.

El encargo debe exigir evidencia reproducible y prohibir hallazgos vagos.

### 4. Verificación cruzada

El responsable verifica una muestra representativa de las afirmaciones del auditor contra el sistema real.

No se acepta el informe únicamente porque tenga un marcador de cierre.

### 5. Resolución de preguntas

Las dudas de arquitectura se resuelven antes de escribir el backlog.

Debe quedar una decisión razonada, no una lista indefinida de opciones.

### 6. Reconstrucción del backlog

Solo después de disponer de arquitectura + auditoría + decisiones abiertas resueltas se generan Epics, User Stories y Tasks.

Cada Epic nueva debe indicar en su contexto qué informe o decisión la origina.

## Auditoría incisiva

Un hallazgo válido debe poder reproducirse.

Debe incluir, cuando proceda:

- fichero/línea;
- comando;
- comportamiento observado;
- captura o evidencia de navegador;
- condición concreta.

"Podría mejorarse" no es suficiente.

## OpenCode headless

Si se necesita ejecutar un segundo agente sin supervisión, usar el mecanismo headless del runtime disponible y evitar TUI/tmux cuando la operación no lo necesite.

El protocolo técnico exacto debe mantenerse en la documentación operativa del runtime, no aquí.

## Resultado

El protocolo termina cuando:

1. existe una visión de destino;
2. el estado actual ha sido verificado;
3. existe auditoría independiente;
4. las discrepancias se han resuelto;
5. el backlog nuevo refleja las decisiones.
