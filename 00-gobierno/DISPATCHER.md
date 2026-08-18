# Dispatcher de Factory Brain

## Propósito

El Dispatcher es la capa de coordinación determinista que transforma estados del backlog y disponibilidad de agentes en Jobs concretos.

No decide producto mediante LLM.

## Responsabilidades

- detectar trabajo elegible;
- respetar dependencias;
- seleccionar agente libre;
- despachar;
- interpretar resultado estructurado;
- promover o devolver estados;
- encadenar el siguiente paso;
- evitar que el humano tenga que intermediar entre cada fase.

## Ciclos

El worker de cola coordina, como mínimo:

1. aterrizaje US→Tasks → Arquitecto;
2. implementación Task → Developer;
3. verificación Task → Tester;
4. veredicto User Story → Arquitecto.

## Cola de despacho

La cola de desarrollo se gestiona mediante:

`brain.dispatcher.dispatch_queue`

El mecanismo HTTP de referencia es:

`POST /backlog/{task_id}/enqueue`

Si no existe `brain-api`, puede utilizarse la función de dominio equivalente.

El worker hace polling periódico y despacha una Task elegible por ciclo.

Una Task no debe ser despachada si:

- no existe;
- está en un estado no elegible;
- una dependencia obligatoria no está `DONE`;
- no hay Developer libre.

## Job

`POST /jobs` representa un Job puntual.

Es apropiado para trabajos cortos donde esperar un resultado estructurado de forma síncrona sea razonable.

El trabajo real de una Task no debe depender de un timeout corto de `dispatch_job`.

## Auto-reporte de Job

El Job formal puede pedir al agente que escriba su resultado en:

`/tmp/factory-brain-job-<uuid>.txt`

y cierre con:

`___FACTORY_BRAIN_JOB_DONE___`

El backend vigila el fichero y obtiene el resultado.

No debe confundirse este mecanismo con la cola de cierre asíncrona de Tasks.

## Cola Developer→Arquitecto

La cola:

`<project_root>/.claude/state/<project_name>/architect_queue.jsonl`

es unidireccional:

```text
Developer → Arquitecto
```

No es una cola para asignar trabajo al Developer.

Cada cierre de Task debe registrar:

- `agente`;
- `task_id`;
- `informe`;
- `ts`.

El informe referencia la sección concreta de la Task.

## Aviso al Arquitecto

`architect_queue_watcher.sh` puede avisar mediante tmux cuando aparece una nueva entrada.

La cola es append-only.

El Arquitecto no debe asumir que una entrada desaparece cuando ha sido atendida.

## User Story REVIEW

Cuando todas las Tasks están `DONE`, el Dispatcher promueve la User Story a `REVIEW` y la asigna a un Arquitecto libre.

No se necesita una cola adicional para este veredicto.

## Rechazo del Tester

Si Tester devuelve `FALLO`:

```text
Task REVIEW
   ↓
Dispatcher
   ↓
Developer
   ↓
Task REVIEW
```

No se crea automáticamente otra Task para cada fallo.

## Rechazo del Arquitecto

Si la User Story carece de cobertura:

```text
US REVIEW
   ↓
Arquitecto crea Task
   ↓
Task EN_DESARROLLO
   ↓
Dispatcher
```

La Task pertenece a la misma User Story.

## Restricción de disponibilidad

Un Developer con una Task pendiente de revisión del Tester puede mantenerse reservado según la preferencia actual `developer_waits_for_tester_review`.

Esta es una decisión operativa, no una regla conceptual de backlog.

## Fallos del Dispatcher

Si el Dispatcher no puede determinar el siguiente paso de forma segura, debe registrar el fallo y no inventar una transición.

La prioridad es preservar trazabilidad y evitar estados falsos.
