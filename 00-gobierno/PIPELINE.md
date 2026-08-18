# Pipeline operativo de Factory Brain

## Objetivo

Coordinar el recorrido de una User Story desde su creación hasta su veredicto sin depender de intervención manual entre cada paso.

## Estados canónicos

### User Story

```text
NO_TASKS
   ↓ Progresar
EN_DISEÑO
   ↓ Arquitecto crea Tasks
TO_DO
   ↓ Progresar
EN_DESARROLLO
   ↓ todas las Tasks DONE
REVIEW
   ↓ veredicto Arquitecto
DONE
```

`NO_TASKS`, `EN_DISEÑO`, `TO_DO`, `EN_DESARROLLO`, `REVIEW` y `DONE` son estados de User Story.

### Task

El flujo operativo canónico es:

```text
TO_DO → EN_DESARROLLO → REVIEW → DONE
                          ↓
                     EN_DESARROLLO
```

La vuelta a `EN_DESARROLLO` ocurre cuando Tester rechaza la implementación y el Dispatcher devuelve la Task al Developer.

`FUERA_ROADMAP` es un estado administrativo permitido para trabajo aplazado.

`IN_PROGRESS` no debe coexistir como segundo significado de `EN_DESARROLLO`. Si el código actual todavía acepta `IN_PROGRESS`, debe tratarse como compatibilidad técnica pendiente de convergencia, no como un estado semántico adicional.

## Progresar

La Web expone un único verbo "Progresar" para una User Story.

- `NO_TASKS` → `EN_DISEÑO`.
- `TO_DO` → `EN_DESARROLLO`.

No se crean dos acciones equivalentes con nombres diferentes.

## Aterrizaje US→Tasks

Cuando una User Story está en `EN_DISEÑO`, el Dispatcher asigna el aterrizaje al Arquitecto.

El aterrizaje es determinista desde el punto de vista de orquestación y no debe convertirse en un Job de implementación.

Cuando existe al menos una Task válida, la User Story pasa a `TO_DO`.

El Developer no crea Tasks por iniciativa propia para suplir una User Story sin aterrizar.

## Desarrollo

Cuando la User Story entra en `EN_DESARROLLO`, sus Tasks elegibles se encolan.

El Dispatcher solo debe despachar Tasks cuyas dependencias estén satisfechas y cuyo estado permita desarrollo.

## REVIEW de Task

El Tester verifica únicamente la Task y sus criterios.

### Éxito

```text
REVIEW → DONE
```

### Fallo

```text
REVIEW → EN_DESARROLLO → REVIEW
```

La corrección vuelve al mismo Developer cuando está disponible. No se crea una Task de corrección separada para cada fallo del Tester.

Si el Developer ya no está disponible, la Task puede volver a `TO_DO` con el hallazgo persistido.

## REVIEW de User Story

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
REVIEW → DONE
```

### Rechazo por cobertura

El Arquitecto crea una Task adicional en la misma User Story. La nueva Task puede entrar directamente en `EN_DESARROLLO` para que el Dispatcher la atienda.

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
