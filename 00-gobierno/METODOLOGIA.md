# Metodología de desarrollo de Factory Brain

## Propósito

Factory Brain es una factoría de software gobernada por backlog. El sistema separa decisiones de producto, diseño, implementación, verificación y operación para mantener trazabilidad y evitar que un agente convierta una decisión implícita en código.

Esta es la capa de **invariantes**. Los detalles del pipeline, del Dispatcher, de los validadores y de cada rol están en documentos especializados.

## Principios fundamentales

1. El producto se diseña antes de implementarse.
2. La documentación define el producto; no es un registro de ejecución.
3. El roadmap expresa evolución estratégica.
4. El backlog define el trabajo pendiente.
5. La Task es la unidad mínima de implementación.
6. El código implementa Tasks, no necesidades ambiguas.
7. La validación aporta evidencia de cumplimiento.
8. Los informes proporcionan trazabilidad histórica.
9. La automatización determinista debe preceder a una decisión LLM cuando ambas pueden resolverla.
10. Un agente no certifica su propio trabajo.
11. Una decisión arquitectónica nueva no se resuelve accidentalmente dentro de una implementación.
12. El estado del sistema debe derivarse y comprobarse de forma determinista cuando sea posible.

## Cadena conceptual

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
Pruebas / Validación
  ↓
Informe
```

La cadena no significa que cada agente deba ejecutar todos los pasos. Significa que cada implementación debe poder remontarse a una decisión y a una Task.

## Separación de responsabilidades

- Humano: intención de producto, prioridades y decisiones que requieran autoridad de producto.
- Arquitecto: modelado del backlog, aterrizaje US→Tasks, veredicto de conjunto y decisiones arquitectónicas.
- Developer: implementación de Tasks.
- Tester: verificación objetiva de criterios y pruebas adicionales cuando exista un hueco real.
- UX: especificación de flujos Web nuevos antes de su implementación.
- Auditor-OSS: auditoría transversal de producto público y de la Web existente.
- Documentador: documentación pública basada en evidencia.
- Dispatcher: coordinación determinista del flujo.
- Operador: disponibilidad y operación del runtime.

## Regla de implementación

Toda modificación de código debe estar asociada a una única Task.

Si la Task es demasiado grande para una implementación controlable, debe dividirse antes de programar.

No se amplía el alcance de una Task porque durante la implementación aparezca una mejora conveniente. El hallazgo se documenta y se devuelve al Arquitecto.

## Decisiones arquitectónicas

Si aparece una decisión que cambia estructura, responsabilidades, contratos, estados, persistencia, seguridad o comportamiento transversal:

1. detener la parte de implementación afectada;
2. documentar la cuestión;
3. resolverla mediante el Arquitecto o el protocolo de reorientación cuando corresponda;
4. actualizar arquitectura/backlog;
5. continuar solo cuando la nueva decisión sea explícita.

La arquitectura dirige el desarrollo. El desarrollo no redefine silenciosamente la arquitectura.

## Informes

El informe no sustituye a la documentación del producto.

Para Tasks, el patrón vigente es un informe acumulativo por User Story:

`07-informes/<story_id>/<story_id>.md`

Cada Task cerrada añade una sección propia. La entrada de la cola del Arquitecto apunta a esa sección.

## Qué NO pertenece a esta metodología

No contiene:

- nombres concretos de funciones Python;
- comandos de operación;
- estado puntual del repositorio;
- cifras históricas;
- instrucciones específicas de tmux;
- procedimientos de reinicio;
- detalles de una ejecución concreta.

Esos datos pertenecen a documentos especializados.
