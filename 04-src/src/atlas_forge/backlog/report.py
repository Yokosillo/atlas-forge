"""Informe estructurado del estado de `02-backlog/` (T-AF018-US02-02,
US-AF018-02 · "Estado del backlog: conteo, dependencias y siguiente foco,
sin gastar tokens de agente cognitivo").

Capa de presentación sobre el parser de T-AF018-US02-01: `build_backlog_report`
construye UN solo dict estructurado (serializable a JSON) con el conteo de
US/Task por estado agrupado por Epic, la lista de items TO_DO LISTA ordenada
por Prioridad, la lista de items TO_DO BLOQUEADA con su dependencia pendiente,
y la cadena de mayor apalancamiento.

Tanto el formateo legible (`format_human_report`) como la salida `--json`
(`render_json_report`) se derivan del MISMO dict, así que muestran siempre
las mismas cifras (criterios 1 y 2 de la Task). Este módulo es la única
fuente del cálculo: lo usa el comando `atlas_forge backlog-status` y la entrada
`backlog_status` del catálogo de scripts genéricos sin duplicar lógica de
invocación (criterio 3).

Orden de prioridad determinista: Crítica > Alta > Media > Baja > sin
prioridad, con desempate por identificador. La palabra clave es el primer
token del valor literal de `## Prioridad` (p. ej. `Alta.`, `Baja — ...`,
`Crítica — ...`)."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path

from atlas_forge.backlog.parser import (
    classify_todo_items,
    find_max_leverage_chain,
    load_backlog,
    calculate_unblock_degree,
    parse_frontmatter,
)
from atlas_forge.backlog.promote import derive_graph_consolidation
from atlas_forge.models.backlog import ITEM_KIND_EPIC, ITEM_KIND_TASK, ITEM_KIND_USER_STORY

BACKLOG_STATUS_NO_DATA_TEXT = "Sin datos: el backlog no tiene aún Epics/US/Tasks."

_PRIORITY_RANK = {"Crítica": 0, "Alta": 1, "Media": 2, "Baja": 3}
_PRIORITY_LABEL = {0: "Crítica", 1: "Alta", 2: "Media", 3: "Baja", 4: "Sin prioridad"}

_EPIC_PREFIX_PATTERN = re.compile(r"^(AF-\d{3,})")


def priority_rank(priority: str | None) -> int:
    """Rango ordenable de un valor de `## Prioridad` (0 = más prioritaria).

    La palabra clave es el primer token del valor literal sin punto final:
    `Alta.`/`Alta — ...` → 1, `Baja...` → 3. Valor ausente o desconocido → 4
    (al final). Determinista, sin heurística de modelo."""
    if not priority:
        return 4
    keyword = priority.strip().split(" ")[0].rstrip(".")
    return _PRIORITY_RANK.get(keyword, 4)


def _state_counts(items: list) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item.state] = counts.get(item.state, 0) + 1
    return counts


def _epic_label(epic: str | None) -> str:
    if epic is None:
        return "(sin epic)"
    return epic

def _epic_prefix(epic: str | None) -> str | None:
    if epic is None:
        return None
    match = _EPIC_PREFIX_PATTERN.match(epic.strip())
    return match.group(1) if match else None

def _epic_label_from_file(backlog_path: str | Path, epic_id: str) -> str:
    """Título legible de la Epic `epic_id` (p. ej. "Descubrimiento y
    Selección de Proyectos"), leído del campo `title` del frontmatter
    YAML de su fichero (T-AF018-US02-06) — mismo patrón que
    `_read_task_title` (`dispatcher/job_plan_builder.py`, tras
    `T-AF008-US04-07`), reutilizando `parse_frontmatter` en vez de una
    segunda implementación de parseo. No hace falta compatibilidad con
    el formato Markdown antiguo (primera línea `# AF-NNN · Título`,
    lógica previa a esta Task): confirmado que el backlog real de este
    proyecto no tiene ningún fichero de Epic pendiente de migrar a
    frontmatter (`AF-027`, 2026-08-06).

    Fallback a `epic_id` (nunca lanza) si el fichero no existe, no tiene
    frontmatter válido, o el campo `title` está vacío/ausente — mismo
    criterio de robustez que ya tenía la función."""
    epics_dir = Path(backlog_path) / "epics"
    epic_file = next(iter(sorted(epics_dir.glob(f"{epic_id}-*.md"))), None) if epics_dir.is_dir() else None
    if epic_file is None:
        return epic_id

    try:
        data = parse_frontmatter(epic_file.read_text(encoding="utf-8"))
    except ValueError:
        return epic_id

    title = data.get("title")
    return title.strip() if isinstance(title, str) and title.strip() else epic_id


def _summary(item) -> dict:
    return {
        "id": item.id,
        "kind": item.kind,
        "epic": item.epic,
        "priority": item.priority,
        "fase": item.fase,
        # T-AF036-US13-02: timestamp de la última transición (frontmatter),
        # `None` si el fichero no lo declara (retrocompatibilidad).
        "updated_at": item.updated_at,
    }


def _sorted_by_priority(items: list[dict]) -> list[dict]:
    return sorted(
        items,
        key=lambda entry: (priority_rank(entry["priority"]), entry["id"]),
    )


def reconcile_graph_state(graph):
    """Devuelve un `BacklogGraph` donde ninguna US/Epic aparece con un
    estado distinto de su derivacion determinista de sus hijos
    (T-AF022-US13-09): una US sin Tasks aparece como `NO_TASKS`, una US con
    Tasks aparece como su Task menos avanzada (o `IN_REVIEW` si todas estan
    `DONE`), y una Epic como `DONE` (todas sus US `DONE`) o `TO_DO`. Esto
    sustituye al ajuste grueso anterior (solo el drift inverso
    `DONE`+hijo reabierto -> `IN_PROGRESS`, T-AF022-US13-04/-05) por la
    derivacion completa en memoria.

    Nunca escribe en disco — reemplaza únicamente los `BacklogItem` en
    memoria del `BacklogGraph` ya cargado (frozen dataclass, se sustituye
    con `dataclasses.replace`, no se muta). Devuelve el grafo reconciliado y
    el conjunto de ids cuyo estado se ajustó."""
    changes = derive_graph_consolidation(graph)
    if not changes:
        return graph, frozenset()

    items = dict(graph.items)
    for item_id, new_state in changes.items():
        original = items.get(item_id)
        if original is not None:
            items[item_id] = replace(original, state=new_state)

    return type(graph)(items=items, errors=graph.errors), frozenset(changes.keys())


def build_backlog_report(backlog_path: str | Path) -> dict:
    """Informe estructurado del `02-backlog/` dado, en UN solo dict.

    Reusa `load_backlog`/`classify_todo_items`/`find_max_leverage_chain` de
    T-AF018-US02-01 (los mismos cálculos del parser, no una reimplementación).
    Nunca lanza por un backlog vacío o recién creado: en ese caso devuelve
    `empty=True` y listas/cuentas vacías (criterio 3 de la Task).

    T-AF022-US13-05: antes de calcular nada, se reconcilia el estado de
    cualquier US/Epic con drift inverso (DONE en disco, hijo reabierto) —
    el resto de esta función ve el grafo ya corregido, sin necesidad de
    tocar cada cálculo (`classify_todo_items`, conteos por Epic, etc.) por
    separado."""
    graph, drifted_ids = reconcile_graph_state(load_backlog(backlog_path))
    lista, bloqueada = classify_todo_items(graph)
    chain = find_max_leverage_chain(graph)

    epics_items = [item for item in graph.items.values() if item.kind == ITEM_KIND_EPIC]
    user_stories = [item for item in graph.items.values() if item.kind == ITEM_KIND_USER_STORY]
    tasks = [item for item in graph.items.values() if item.kind == ITEM_KIND_TASK]

    by_epic: dict[str, dict] = {}
    for item in graph.items.values():
        if item.kind == ITEM_KIND_EPIC:
            continue
        prefix = _epic_prefix(item.epic)
        label = prefix if prefix is not None else "(sin epic)"
        entry = by_epic.setdefault(
            label,
            {
                "epic": label,
                "epic_label": _epic_label_from_file(backlog_path, label) if prefix else "(sin epic)",
                "user_stories": {},
                "tasks": {},
                # T-AF036-US15-01: detalle de cada User Story de la Epic con
                # su `fase` (para que la vista "Por Fase" muestre solo las US
                # de la fase del grupo). Campo aditivo, no rompe consumidores.
                "user_stories_detail": [],
            },
        )
        if item.kind == ITEM_KIND_USER_STORY:
            entry["user_stories"][item.state] = entry["user_stories"].get(item.state, 0) + 1
            entry["user_stories_detail"].append(
                {"id": item.id, "fase": item.fase, "state": item.state}
            )
        else:
            entry["tasks"][item.state] = entry["tasks"].get(item.state, 0) + 1
    # T-AF036-US02-04: una Epic recién creada (sin US/Tasks todavía) debe
    # aparecer igualmente en el listado agrupado. El bucle de arriba solo
    # puebla `by_epic` desde los items hijos (US/Task), así que una Epic sin
    # hijos nunca generaba entrada — el criterio "la Epic aparece expandida
    # tras crearla" quedaba sin tarjeta que expandir (bug real reportado en
    # la Task). Se añaden aquí las Epics con hijos (ya presentes) y las sin
    # hijos (con conteos vacíos), nunca se duplican entradas.
    for epic_item in epics_items:
        if epic_item.id in by_epic:
            continue
        by_epic[epic_item.id] = {
            "epic": epic_item.id,
            "epic_label": _epic_label_from_file(backlog_path, epic_item.id),
            "user_stories": {},
            "tasks": {},
            "user_stories_detail": [],
        }
    epics_sorted = sorted(by_epic.values(), key=lambda e: e["epic"])

    for entry in epics_sorted:
        if entry["epic"] != "(sin epic)":
            entry["unblock_degree"] = calculate_unblock_degree(graph, entry["epic"])
            epic_item = graph.items.get(entry["epic"])
            # T-AF036-US15-06: la vista "Por Fase" agrupa las Epics por su
            # `version` (US-AF036-18: la Epic se versiona, no declara fase).
            # Se expone `version` por Epic (campo aditivo); `fase` se conserva
            # como legado para las Epics que aún la declaran.
            if epic_item is not None:
                if epic_item.version:
                    entry["version"] = epic_item.version
                if epic_item.fase:
                    entry["fase"] = epic_item.fase
        # T-AF036-US15-01: detalle de US ordenado por id (determinista).
        entry["user_stories_detail"] = sorted(
            entry.get("user_stories_detail", []), key=lambda us: us["id"]
        )

    items_bloqueada = []
    for item in bloqueada:
        blocking = [
            {
                "id": dependency_id,
                "state": (
                    graph.items[dependency_id].state
                    if dependency_id in graph.items
                    else None
                ),
            }
            for dependency_id in item.dependencies
            if dependency_id not in graph.items
            or graph.items[dependency_id].state != "DONE"
        ]
        items_bloqueada.append({**_summary(item), "blocking_dependencies": blocking})
    items_bloqueada.sort(key=lambda entry: entry["id"])

    errors = [
        {"id": error.item_id, "path": str(error.path), "reason": error.reason}
        for error in graph.errors
    ]

    result = {
        "backlog_path": str(Path(backlog_path)),
        # T-AF036-US02-04: `empty` es False con una sola Epic real (aunque
        # aún no tenga US/Tasks) — un backlog con una Epic recién creada no
        # es "vacío": el listado agrupado tiene una tarjeta que mostrar y
        # expandir. Un backlog sin ningún item (ni Epics ni US/Tasks) sigue
        # siendo `empty=True`, mismo criterio que antes para ese caso.
        "empty": len(epics_items) + len(user_stories) + len(tasks) == 0,
        "total": {
            "items": len(user_stories) + len(tasks),
            "epics": _state_counts(epics_items),
            "user_stories": _state_counts(user_stories),
            "tasks": _state_counts(tasks),
            "errors": len(errors),
        },
        "by_epic": epics_sorted,
        "items_lista": _sorted_by_priority([_summary(item) for item in lista]),
        "items_bloqueada": items_bloqueada,
        "max_leverage_chain": [_summary(item) for item in chain],
        "errors": errors,
    }
    # T-AF022-US13-05, criterio 3: campo nuevo solo si hay drift — un
    # backlog sin drift no cambia su respuesta respecto a antes de esta
    # Task. `total.user_stories`/`total.epics`/`by_epic` ya reflejan el
    # estado reconciliado (`state: IN_PROGRESS`, no `DONE` crudo del
    # fichero) porque se calculan sobre `graph` ya reconciliado arriba —
    # este campo es solo la lista explícita de qué ids tenían el fichero
    # en disco todavía en DONE, para no ocultarlo sin más.
    if drifted_ids:
        result["drift"] = sorted(drifted_ids)
    return result


def format_human_report(report: dict) -> str:
    """Salida legible del informe (mismas cifras que `render_json_report`,
    porque ambas se derivan del mismo dict)."""
    if report["empty"]:
        return BACKLOG_STATUS_NO_DATA_TEXT

    total = report["total"]
    lines = [f"Estado del backlog: {report['backlog_path']}"]

    lines.append(
        "Total: {items} items · {errors} errores de parseo".format(
            items=total["items"], errors=total["errors"]
        )
    )

    def format_kind(label: str, counts: dict[str, int]) -> str:
        if not counts:
            return f"{label}: 0"
        details = ", ".join(f"{state}={count}" for state, count in sorted(counts.items()))
        return f"{label}: {sum(counts.values())} ({details})"

    lines.append(f"  US:   {format_kind('US', total['user_stories'])}")
    lines.append(f"  Task: {format_kind('Task', total['tasks'])}")

    lines.append("\nPor Epic:")
    for epic in report["by_epic"]:
        lines.append(f"  {epic.get('epic_label', epic['epic'])}")
        if epic["user_stories"]:
            lines.append(f"    US:   {format_kind('US', epic['user_stories'])}")
        if epic["tasks"]:
            lines.append(f"    Task: {format_kind('Task', epic['tasks'])}")

    lines.append("\nItems TO_DO LISTA (ordenados por prioridad):")
    if report["items_lista"]:
        for entry in report["items_lista"]:
            label = _PRIORITY_LABEL[priority_rank(entry["priority"])]
            lines.append(f"  {label:<12} {entry['id']:<24} {_epic_label(entry['epic'])}")
    else:
        lines.append("  (ninguno)")

    lines.append("\nItems TO_DO BLOQUEADA (con dependencia pendiente):")
    if report["items_bloqueada"]:
        for entry in report["items_bloqueada"]:
            pending = ", ".join(
                dependency["id"]
                + (" " + dependency["state"] if dependency["state"] else " (no existe)")
                for dependency in entry["blocking_dependencies"]
            )
            lines.append(f"  {entry['id']:<24} ← espera a {pending}")
    else:
        lines.append("  (ninguna)")

    lines.append("\nCadena de mayor apalancamiento (próximo foco):")
    if report["max_leverage_chain"]:
        chain_ids = " → ".join(entry["id"] for entry in report["max_leverage_chain"])
        lines.append(f"  {chain_ids}")
    else:
        lines.append("  (ninguna: no hay item TO_DO que desbloquee a otros)")

    if report["errors"]:
        lines.append("\nErrores de parseo:")
        for error in report["errors"]:
            label = error["id"] or error["path"]
            lines.append(f"  {label}: {error['reason']}")

    return "\n".join(lines)


def render_json_report(report: dict) -> str:
    """Salida JSON estructurada (criterio 2): un dict parseable, no el texto
    formateado. Mismas cifras que `format_human_report`."""
    return json.dumps(report, ensure_ascii=False, indent=2)
