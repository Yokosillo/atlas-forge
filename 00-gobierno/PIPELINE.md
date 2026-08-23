# Pipeline operativo de Atlas Forge

## Objetivo

Coordinar el recorrido de una User Story desde su creación hasta su veredicto sin depender de intervención manual entre cada paso.

## Estados canónicos

El vocabulario canónico (AF-040) vive en `04-src/src/atlas_forge/core/state_machines.py` (única fuente de verdad, con `can_transition` y `derive_user_story_state`); este documento lo describe, no lo define.

### User Story

```text
NO_TASKS
   ↓ Progresar
TO_PLAN
   ↓ Arquitecto crea Tasks
READY            (derivado: Task menos avanzada en READY)
   ↓ Progresar
TO_DEVELOP       (derivado)
   ↓ todas las Tasks DONE
IN_REVIEW        (derivado + validación final del Arquitecto)
   ↓ veredicto Arquitecto
DONE
```

`NO_TASKS`, `TO_PLAN`, `READY`, `TO_DEVELOP`, `IN_PROGRESS`, `IN_REVIEW`, `DONE` y `OUT_OF_SCOPE` son estados de User Story. `OUT_OF_SCOPE` es exclusivo de User Story.

### Task

El flujo operativo canónico es:

```text
READY → TO_DEVELOP → IN_PROGRESS → IN_REVIEW → DONE
                                     ↓
                                IN_PROGRESS
```

La vuelta a `IN_PROGRESS` ocurre cuando el Tester rechaza la implementación y el Dispatcher devuelve la Task al Developer (el ciclo normal la re-envía a `IN_REVIEW` al completarse de nuevo).

Las Tasks **nunca** pueden estar en `OUT_OF_SCOPE` (es exclusivo de User Story). `TO_DEVELOP → READY` (desencolar) es la única otra salida del avance lineal justificada por el pipeline.

## Progresar

La Web expone un único verbo "Progresar" para una User Story.

- `NO_TASKS` → `TO_PLAN`.
- `READY` → `TO_DEVELOP`.

No se crean dos acciones equivalentes con nombres diferentes.

## Aterrizaje US→Tasks

Cuando una User Story está en `TO_PLAN`, el Dispatcher asigna el aterrizaje al Arquitecto.

El aterrizaje es determinista desde el punto de vista de orquestación y no debe convertirse en un Job de implementación.

Cuando existe al menos una Task válida, la User Story pasa a `READY` (su estado derivado).

El Developer no crea Tasks por iniciativa propia para suplir una User Story sin aterrizar.

## Desarrollo

Cuando la User Story está en `TO_DEVELOP` (derivado), sus Tasks elegibles se encolan.

El Dispatcher solo debe despachar Tasks cuyas dependencias estén satisfechas y cuyo estado permita desarrollo.

## IN_REVIEW de Task

El Tester verifica únicamente la Task y sus criterios.

### Éxito

```text
IN_REVIEW → DONE
```

### Fallo

```text
IN_REVIEW → IN_PROGRESS → IN_REVIEW
```

La corrección vuelve al mismo Developer cuando está disponible. No se crea una Task de corrección separada para cada fallo del Tester.

Si el Developer ya no está disponible, la Task puede volver a `READY` con el hallazgo persistido.

## IN_REVIEW de User Story

Solo se activa cuando todas las Tasks de la Story están `DONE` (derivado automático: `derive_user_story_state` devuelve `IN_REVIEW`).

El Arquitecto revisa:

- cobertura de la necesidad;
- correspondencia entre código y necesidad;
- criterios de la User Story;
- coherencia con la Epic;
- fuera de alcance;
- deuda o huecos relevantes.

No repite mecánicamente la verificación funcional de cada Task.

### Aprobación

```text
IN_REVIEW → DONE
```

Solo la validación final del Arquitecto lleva la User Story a `DONE`; la promoción automática (`promote_backlog`) la deja en `IN_REVIEW`, nunca en `DONE`.

### Rechazo por cobertura

El Arquitecto crea una Task adicional en la misma User Story. La nueva Task puede entrar directamente en `TO_DEVELOP` para que el Dispatcher la atienda.

No se crea una User Story nueva para completar una User Story que ya existe.

## Job aislado

Existe además un camino puntual:

`POST /jobs`

El humano puede enviar trabajo directamente a un agente concreto.

Un Job aislado no sustituye la trazabilidad de una Task cuando el trabajo realmente pertenece al backlog.

## Regla de coordinación

El Dispatcher coordina el ciclo completo:

```text
US→Tasks → Arquitecto
Task implementación → Developer
Task verificación → Tester
US veredicto → Arquitecto
```

No se utiliza una cola paralela para sustituir la responsabilidad del Dispatcher.

## Estado padre/hijo

El estado de una User Story es una **función determinista** de sus Tasks (`derive_user_story_state` en `state_machines.py`): `NO_TASKS` si no tiene Tasks; si no, el estado de su Task **menos avanzada** (orden `READY` < `TO_DEVELOP` < `IN_PROGRESS` < `IN_REVIEW` < `DONE`); si la menos avanzada está `DONE` (todas lo están) → `IN_REVIEW` (validación final pendiente).

El pipeline solo transita estados respetando esta invariante: cada transición de estado de una Task actualiza el estado de su User Story en ambos sentidos (avanzar y retrasar), nunca deja una US desactualizada respecto a sus Tasks. `TO_PLAN` (con 0 Tasks) y el `IN_REVIEW` de User Story (con todas sus Tasks `DONE`) son estados transitorios que fija el propio pipeline.

Una Epic solo puede considerarse `DONE` cuando tiene al menos una User Story y todas están `DONE`; con una User Story pendiente se reabre al estado más retrasado de sus User Stories.

La comprobación y consolidación se realizan de forma determinista según `VALIDACION.md`.
