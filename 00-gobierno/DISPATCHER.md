# Dispatcher de Atlas Forge

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

`atlas_forge.dispatcher.dispatch_queue`

El mecanismo HTTP de referencia es:

`POST /backlog/{task_id}/enqueue`

Si no existe `atlas-forge-api`, puede utilizarse la función de dominio equivalente.

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

`/tmp/atlas-forge-job-<uuid>.txt`

y cierre con:

`___ATLAS_FORGE_JOB_DONE___`

El backend vigila el fichero y obtiene el resultado.

No debe confundirse este mecanismo con la cola de cierre asíncrona de Tasks.

## Canal Developer→Arquitecto

El canal Developer→Arquitecto es el ciclo de veredicto del Dispatcher
(`dispatch_queue_worker.run_architect_verdict_dispatch_cycle`, T-AF008-US14-02):

1. El cierre de un Job de Developer (marcador `___ATLAS_FORGE_JOB_DONE___`)
   persiste su informe en `07-informes/<story_id>/<job_id>.md`.
2. Cuando TODAS las Tasks de una User Story están `DONE`,
   `trigger_architect_verdict` marca la US en `REVIEW`.
3. En el ciclo de polling, si hay una US en `REVIEW` y un Arquitecto
   `idle`, el Dispatcher despacha un Job de veredicto al Arquitecto
   (`dispatch_architect_verdict`). El Arquitecto devuelve su decisión como
   resultado del Job (`job.result`, formato `ESTADO:`/`JUSTIFICACIÓN:`/
   `SIGUIENTE_PROMPT_PARA_WORKER:`); `_process_verdict_result` la procesa y
   promueve la US (o crea una Task de cobertura) según el estado.

No es un canal para asignar trabajo al Developer.

El mecanismo legado `architect_queue.jsonl` + `architect_queue_watcher.sh`
está deprecado y no debe utilizarse.

## User Story IN_REVIEW

Cuando todas las Tasks están `DONE`, el Dispatcher promueve la User Story a `IN_REVIEW` y la asigna a un Arquitecto libre.

No se necesita una cola adicional para este veredicto.

## Rechazo del Tester

Si Tester devuelve `FALLO`:

```text
Task IN_REVIEW
   ↓
Dispatcher
   ↓
Developer
   ↓
Task IN_REVIEW
```

No se crea automáticamente otra Task para cada fallo.

## Rechazo del Arquitecto

Si la User Story carece de cobertura:

```text
US IN_REVIEW
   ↓
Arquitecto crea Task
   ↓
Task TO_DEVELOP
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
