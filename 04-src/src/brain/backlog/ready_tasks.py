"""Tasks listas para coger sin instrucción explícita (T-FB022-US14-01,
US-FB022-14 · "Un Developer idle autoconsulta el backlog cada 10 minutos y
coge Tasks listas sin esperar instrucción").

Una Task está lista si su `state` es `TO_DO` y todas sus `dependencies`
declaradas están `DONE` (una Task sin dependencias cuenta como lista de
inmediato). Una dependencia cuyo identificador no existe en el grafo NUNCA
cuenta como `DONE` — fail-safe explícito: si no se puede confirmar el
estado de una dependencia, la Task no se considera lista."""

from __future__ import annotations

from brain.backlog.report import priority_rank
from brain.models.backlog import BacklogGraph, BacklogItem, ITEM_KIND_TASK


def _dependencies_all_done(graph: BacklogGraph, item: BacklogItem) -> bool:
    for dependency_id in item.dependencies:
        dependency = graph.items.get(dependency_id)
        if dependency is None or dependency.state != "DONE":
            return False
    return True


def find_ready_tasks(graph: BacklogGraph) -> list[BacklogItem]:
    """Tasks (`kind == "T"`) en `TO_DO` cuyas `dependencies` están todas
    `DONE`, ordenadas por prioridad más alta primero y, en caso de empate,
    por identificador ascendente (mismo criterio de desempate que el
    criterio de aceptación 2 de `US-FB022-14`)."""
    ready = [
        item
        for item in graph.items.values()
        if item.kind == ITEM_KIND_TASK
        and item.state == "TO_DO"
        and _dependencies_all_done(graph, item)
    ]
    return sorted(ready, key=lambda item: (priority_rank(item.priority), item.id))
