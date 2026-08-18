# Roles y responsabilidades de Factory Brain

## Modelo

Factory Brain no utiliza un rol Critic separado. La función de planificación y veredicto corresponde al Arquitecto.

UX y Auditor-OSS son roles especializados que se invocan sobre encargos concretos; no forman parte del ciclo Task→Implementación→Veredicto.

## Matriz

| Rol | Hace | No hace |
|---|---|---|
| Humano | Decide producto, prioridad y excepciones | No delega decisiones críticas implícitas |
| Arquitecto | Genera backlog, aterriza US→Tasks, emite veredictos, conversa sobre backlog | No implementa código |
| Developer | Implementa Tasks | No crea Tasks por iniciativa propia |
| Tester | Verifica criterios y genera pruebas para huecos reales | No modifica producto ni backlog |
| UX | Diseña flujos Web nuevos | No implementa ni audita pantallas existentes |
| Auditor-OSS | Audita imagen pública y Web existente | No implementa ni diseña flujos completos |
| Documentador | Mantiene documentación pública | No inventa funcionalidades |
| Dispatcher | Despacha y encadena estados | No decide producto mediante LLM |
| Operador | Opera runtime | No cambia producto como solución operativa |

## Regla de independencia

La persona/agente que implementa no debe ser quien certifique el cumplimiento de su propia implementación.

El Developer produce evidencia. El Tester verifica Task. El Arquitecto verifica la cobertura de la User Story y la coherencia de conjunto.

## Regla de autoridad

El rol no puede ampliar su responsabilidad porque detecte algo que podría hacer otro rol.

Debe comunicar el hallazgo por el canal definido.

## Regla de especialización

Los documentos de rol pueden añadir restricciones y procedimientos, pero no pueden redefinir:

- la jerarquía del backlog;
- el significado de los estados;
- el contrato de pruebas;
- la dirección de las colas;
- las responsabilidades de otros roles.
