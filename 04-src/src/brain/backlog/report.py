"""Informe estructurado del estado de `02-backlog/` (T-FB018-US02-02,
US-FB018-02 · "Estado del backlog: conteo, dependencias y siguiente foco,
sin gastar tokens de agente cognitivo").

Capa de presentación sobre el parser de T-FB018-US02-01: `build_backlog_report`
construye UN solo dict estructurado (serializable a JSON) con el conteo de
US/Task por estado agrupado por Epic, la lista de items TODO LISTA ordenada
por Prioridad, la lista de items TODO BLOQUEADA con su dependencia pendiente,
y la cadena de mayor apalancamiento.

Tanto el formateo legible (`format_human_report`) como la salida `--json`
(`render_json_report`) se derivan del MISMO dict, así que muestran siempre
las mismas cifras (criterios 1 y 2 de la Task). Este módulo es la única
fuente del cálculo: lo usa el comando `brain backlog-status` y la entrada
`backlog_status` del catálogo de scripts genéricos sin duplicar lógica de
invocación (criterio 3).

Orden de prioridad determinista: Crítica > Alta > Media > Baja > sin
prioridad, con desempate por identificador. La palabra clave es el primer
token del valor literal de `## Prioridad` (p. ej. `Alta.`, `Baja — ...`,
`Crítica — ...`)."""

from __future__ import annotations

import json
from pathlib import Path

from brain.backlog.parser import (
    classify_todo_items,
    find_max_leverage_chain,
    load_backlog,
)
from brain.models.backlog import ITEM_KIND_USER_STORY

BACKLOG_STATUS_NO_DATA_TEXT = "Sin datos: el backlog no tiene aún US/Tasks."

_PRIORITY_RANK = {"Crítica": 0, "Alta": 1, "Media": 2, "Baja": 3}
_PRIORITY_LABEL = {0: "Crítica", 1: "Alta", 2: "Media", 3: "Baja", 4: "Sin prioridad"}


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
    return epic if epic is not None else "(sin epic)"


def _summary(item) -> dict:
    return {
        "id": item.id,
        "kind": item.kind,
        "epic": item.epic,
        "priority": item.priority,
    }


def _sorted_by_priority(items: list[dict]) -> list[dict]:
    return sorted(
        items,
        key=lambda entry: (priority_rank(entry["priority"]), entry["id"]),
    )


def build_backlog_report(backlog_path: str | Path) -> dict:
    """Informe estructurado del `02-backlog/` dado, en UN solo dict.

    Reusa `load_backlog`/`classify_todo_items`/`find_max_leverage_chain` de
    T-FB018-US02-01 (los mismos cálculos del parser, no una reimplementación).
    Nunca lanza por un backlog vacío o recién creado: en ese caso devuelve
    `empty=True` y listas/cuentas vacías (criterio 3 de la Task)."""
    graph = load_backlog(backlog_path)
    lista, bloqueada = classify_todo_items(graph)
    chain = find_max_leverage_chain(graph)

    user_stories = [item for item in graph.items.values() if item.kind == ITEM_KIND_USER_STORY]
    tasks = [item for item in graph.items.values() if item.kind != ITEM_KIND_USER_STORY]

    by_epic: dict[str, dict] = {}
    for item in graph.items.values():
        label = _epic_label(item.epic)
        entry = by_epic.setdefault(label, {"epic": label, "user_stories": {}, "tasks": {}})
        target = entry["user_stories"] if item.kind == ITEM_KIND_USER_STORY else entry["tasks"]
        target[item.state] = target.get(item.state, 0) + 1
    epics = sorted(by_epic.values(), key=lambda entry: entry["epic"])

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

    return {
        "backlog_path": str(Path(backlog_path)),
        "empty": len(graph.items) == 0,
        "total": {
            "items": len(graph.items),
            "user_stories": _state_counts(user_stories),
            "tasks": _state_counts(tasks),
            "errors": len(errors),
        },
        "by_epic": epics,
        "items_lista": _sorted_by_priority([_summary(item) for item in lista]),
        "items_bloqueada": items_bloqueada,
        "max_leverage_chain": [_summary(item) for item in chain],
        "errors": errors,
    }


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
        lines.append(f"  {epic['epic']}")
        if epic["user_stories"]:
            lines.append(f"    US:   {format_kind('US', epic['user_stories'])}")
        if epic["tasks"]:
            lines.append(f"    Task: {format_kind('Task', epic['tasks'])}")

    lines.append("\nItems TODO LISTA (ordenados por prioridad):")
    if report["items_lista"]:
        for entry in report["items_lista"]:
            label = _PRIORITY_LABEL[priority_rank(entry["priority"])]
            lines.append(f"  {label:<12} {entry['id']:<24} {_epic_label(entry['epic'])}")
    else:
        lines.append("  (ninguno)")

    lines.append("\nItems TODO BLOQUEADA (con dependencia pendiente):")
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
        lines.append("  (ninguna: no hay item TODO que desbloquee a otros)")

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
