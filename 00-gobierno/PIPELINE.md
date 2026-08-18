# Pipeline operativo de Factory Brain

## Objetivo

Coordinar el recorrido de una User Story desde su creación hasta su veredicto sin depender de intervención manual entre cada paso.

## Estados canónicos

### Task

Una Task tiene exactamente estos estados, en este orden:

```text
READY → TO_DEVELOP → IN_PROGRESS → IN_REVIEW → DONE
```

| Estado | Significado |
|---|---|
| `READY` | La Task ha sido creada y está completamente definida. Preparada para ser enviada al Dispatcher, pero todavía no ha sido enviada. |
| `TO_DEVELOP` | La Task ya ha sido enviada al Dispatcher y está en la cola de implementación. |
| `IN_PROGRESS` | La Task ha sido recibida por un Developer y está siendo desarrollada. |
| `IN_REVIEW` | El Developer ha terminado la implementación y la Task está siendo revisada por el Tester. Si el Tester la aprueba, pasa a `DONE`; si la rechaza, vuelve a `IN_PROGRESS` con el mismo Developer. |
| `DONE` | La Task ha sido implementada y validada correctamente. |

Una Task **no puede tener** `OUT_OF_SCOPE`. `OUT_OF_SCOPE` pertenece exclusivamente a las User Stories.

### User Story

Estados propios iniciales:

```text
NO_TASKS → TO_PLAN
```

| Estado | Significado |
|---|---|
| `NO_TASKS` | La US ha sido creada pero todavía no tiene Tasks. |
| `TO_PLAN` | La US está pendiente de que el Arquitecto la analice y la descomponga en Tasks. |

Cuando el Arquitecto termina la planificación y crea las Tasks, la US deja de tener un estado de planificación propio y pasa a **reflejar el estado de sus Tasks** (ver "Estado derivado de la US").

### Estados derivados de la US

Una vez que una US tiene Tasks, su estado se calcula **automáticamente** a partir del estado de sus Tasks: la US refleja siempre la **Task menos avanzada**.

Orden de prioridad de estados:

```text
READY < TO_DEVELOP < IN_PROGRESS < IN_REVIEW < DONE
```

Ejemplos:

```text
Task A → READY        Task A → DONE         Task A → DONE
Task B → READY        Task B → IN_PROGRESS  Task B → IN_REVIEW
Task C → READY        Task C → DONE         Task C → DONE
US → READY            US → IN_PROGRESS      US → IN_REVIEW
```

**Regla especial:** cuando **todas** las Tasks de una US están en `DONE`, la US pasa a `IN_REVIEW`, y en ese caso `IN_REVIEW` significa que la US completa está pendiente de **validación por el Arquitecto**. La US **no** pasa automáticamente a `DONE`.

### Validación final de la US

Cuando todas las Tasks están `DONE`, debe producirse automáticamente:

```text
ALL TASKS = DONE
        ↓
US → IN_REVIEW   (queda disponible para que el Arquitecto haga la validación final)
        ↓
Arquitecto revisa la US completa (incluido el resultado de sus Tasks)
        ↓
Validación satisfactoria
        ↓
US IN_REVIEW → US DONE
```

La transición a `DONE` de la US **requiere la validación del Arquitecto**.

### OUT_OF_SCOPE

`OUT_OF_SCOPE` es un estado **exclusivo de User Story**: una US puede pasar a `OUT_OF_SCOPE` cuando se determina que queda fuera del alcance o del roadmap del proyecto. Una Task nunca puede tener este estado.

### Flujo completo

```text
USER STORY
    │
    ▼
NO_TASKS
    │
    ▼
TO_PLAN
    │  Arquitecto crea Tasks
    ▼
Tasks creadas
    │
    ▼
US = Task menos avanzada
    │
    ├── READY
    ├── TO_DEVELOP
    ├── IN_PROGRESS
    ├── IN_REVIEW
    └── ALL TASKS DONE → US IN_REVIEW → validación Arquitecto → US DONE
```

### Reglas de transición

**Task:**

```text
READY → TO_DEVELOP
TO_DEVELOP → IN_PROGRESS
IN_PROGRESS → IN_REVIEW
IN_REVIEW → DONE | IN_PROGRESS
```

No debe existir ninguna transición directa que salte fases sin una razón explícita del pipeline.

**User Story:**

```text
NO_TASKS → TO_PLAN
TO_PLAN → (derivado de sus Tasks: READY | TO_DEVELOP | IN_PROGRESS | IN_REVIEW)
```

Las transiciones posteriores a `TO_PLAN` son **derivadas automáticamente** de sus Tasks, no transiciones manuales de la US. Cuando todas las Tasks estén `DONE`: `US → IN_REVIEW`; después de la validación del Arquitecto: `IN_REVIEW → DONE`. Además, cualquier US aplicable puede pasar a `OUT_OF_SCOPE` según las reglas de negocio existentes.

### Regla fundamental

**No** se implementan `READY`, `TO_DEVELOP`, `IN_PROGRESS` ni `IN_REVIEW` de una US como estados operativos independientes: **son estados derivados**. La fuente de verdad del estado operativo es el conjunto de Tasks asociadas a la US. La única excepción es el `IN_REVIEW` final de la US cuando todas sus Tasks están `DONE`, porque en ese momento la revisión ya no corresponde al Tester sino al Arquitecto.

## Progresar

La Web expone un único verbo "Progresar" para una User Story.

- `NO_TASKS` → `TO_PLAN`.

No se crean dos acciones equivalentes con nombres diferentes.

## Aterrizaje US→Tasks

Cuando una User Story está en `TO_PLAN`, el Dispatcher asigna el aterrizaje al Arquitecto.

El aterrizaje es determinista desde el punto de vista de orquestación y no debe convertirse en un Job de implementación.

Cuando existe al menos una Task válida, la User Story deja de tener estado de planificación propio y pasa a reflejar el estado de sus Tasks.

El Developer no crea Tasks por iniciativa propia para suplir una User Story sin aterrizar.

## Desarrollo

Cuando la User Story entra en desarrollo (sus Tasks empiezan a encolarse), sus Tasks elegibles se encolan.

El Dispatcher solo debe despachar Tasks cuyas dependencias estén satisfechas y cuyo estado permita desarrollo (`TO_DEVELOP`).

## IN_REVIEW de Task

El Tester verifica únicamente la Task y sus criterios.

### Éxito

```text
IN_REVIEW → DONE
```

### Fallo

```text
IN_REVIEW → IN_PROGRESS
```

La corrección vuelve al mismo Developer cuando está disponible (la Task pasa de nuevo a `IN_PROGRESS`). No se crea una Task de corrección separada para cada fallo del Tester.

Si el Developer ya no está disponible, la Task puede volver a `READY` con el hallazgo persistido.

## IN_REVIEW de User Story

Solo se activa cuando todas las Tasks de la Story están `DONE`.

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

### Rechazo por cobertura

El Arquitecto crea una Task adicional en la misma User Story. La nueva Task puede entrar directamente en desarrollo para que el Dispatcher la atienda.

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

El estado de una User Story es una **función determinista** de sus Tasks (ver `VALIDACION.md`): `NO_TASKS` si no tiene Tasks, si no el estado de su Task más retrasada (orden `TO_DO` < `EN_DESARROLLO` < `REVIEW` < `DONE`; `IN_PROGRESS` ≡ `EN_DESARROLLO`, `FUERA_ROADMAP` ≡ `TO_DO`).

El pipeline solo transita estados respetando esta invariante: cada transición de estado de una Task actualiza el estado de su User Story en ambos sentidos (avanzar y retrasar), nunca deja una US desactualizada respecto a sus Tasks. `EN_DISEÑO` (con 0 Tasks) y el `REVIEW` de User Story (con todas sus Tasks `DONE`) son estados transitorios que fija el propio pipeline.

Una Epic solo puede considerarse `DONE` cuando tiene al menos una User Story y todas están `DONE`; con una User Story pendiente se reabre al estado más retrasado de sus User Stories.

La comprobación y consolidación se realizan de forma determinista según `VALIDACION.md`.
