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

# Subdirectorios canónicos del backlog (mismo listado que el watcher).
_BACKLOG_SUBDIRS = ("epics", "user-stories", "tasks")

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


def _resolve_epic_label(graph, label: str, backlog_path: str | Path) -> str:
    """Resuelve el `epic_label` de un grupo `by_epic` (T-AF048-US03-02) desde
    el grafo YA EN MEMORIA: `graph.items[label].title` (la Epic ya la cargó
    `load_backlog`; leer el fichero de nuevo por cada grupo era innecesario —
    la Task T-AF048-US03-01 eliminó la evaluación eager y esta Task elimina la
    re-lectura en el caso canónico).

    Fallback: si la Epic está referenciada por sus hijo/os pero NO existe en
    `graph.items` o su `title` está vacío (caso legacy sin fichero/título),
    recurre a `_epic_label_from_file` (que lee el fichero real; si tampoco
    existe, devuelve el propio `epic_id`). Nunca lanza."""
    item = graph.items.get(label)
    if item is not None and getattr(item, "title", None):
        title = item.title.strip()
        if title:
            return title
    return _epic_label_from_file(backlog_path, label)


def _summary(item, in_flight: bool | None = None) -> dict:
    entry = {
        "id": item.id,
        "kind": item.kind,
        "epic": item.epic,
        # T-AF036-US21-02: título del item (`title:` del frontmatter), para
        # que el buscador del informe raíz coincida también por nombre (y no
        # solo por ID). Campo aditivo; `None` si no se declara.
        "title": item.title,
        "priority": item.priority,
        "fase": item.fase,
        # T-AF036-US25-02: `version` del item (Epics y User Stories), para
        # que el nuevo valor editado vía `PUT /backlog/{item_id}/version` se
        # refleje en `GET /backlog`. Campo aditivo; `None` si no lo declara.
        "version": item.version,
        # T-AF036-US13-02: timestamp de la última transición (frontmatter),
        # `None` si el fichero no lo declara (retrocompatibilidad).
        "updated_at": item.updated_at,
    }
    # T-AF022-US17-01: indicador de en vuelo/huérfana para items IN_PROGRESS
    # (`True` si tiene entrada `dispatched` en `dispatch_queue.json` con su
    # agente; `False` si está IN_PROGRESS sin entrada → huérfana). Campo
    # aditivo solo para IN_PROGRESS — el resto de items no llevan `in_flight`
    # y su shape no cambia.
    if item.state == "IN_PROGRESS" and in_flight is not None:
        entry["in_flight"] = in_flight
    return entry


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


def find_duplicate_ids_in_backlog(backlog_path: str | Path) -> list[dict]:
    """IDS duplicados en todo el `02-backlog/` (T-AF008-US18-01, criterio 4):
    recorre `epics/`/`user-stories/`/`tasks/` con el checker determinista
    `find_duplicate_ids_in_dir` y devuelve, por id, la lista de rutas (relativas
    al backlog) de los ficheros que lo declaran. Es el error consultable para
    auditar un backlog YA escrito: lo que el validador individual también
    detecta, ahora expuesto de forma agregada en el informe.

    Determinista (orden alfabético por id). Devuelve `[]` si no hay
    duplicados."""
    # Import perezoso: `validator_v2` tira de `core`→`workspace`→`generic_scripts`
    # →`report`; un import de módulo en la cabecera crea un ciclo de importación.
    from atlas_forge.backlog.validator_v2 import find_duplicate_ids_in_dir

    backlog_root = Path(backlog_path)
    duplicates: list[dict] = []
    for subdir in _BACKLOG_SUBDIRS:
        dir_dupes = find_duplicate_ids_in_dir(backlog_root / subdir)
        for file_id, paths in dir_dupes.items():
            duplicates.append({
                "id": file_id,
                "paths": sorted(str(p.relative_to(backlog_root)) for p in paths),
            })
    duplicates.sort(key=lambda entry: entry["id"])
    return duplicates


def _dispatched_task_ids_from_queue(backlog_path: str | Path) -> set[str]:
    """Conjunto de `task_id` con entrada `dispatched` en `dispatch_queue.json`
    del proyecto (T-AF022-US17-01) — la fuente persistida que permite decidir
    si un item `IN_PROGRESS` tiene un Job en vuelo legítimo o está huérfano.

    El registro `_inflight` del Dispatcher es en memoria y se pierde al
    reiniciar `atlas-forge-api`; la cola JSON sobrevive al reinicio, así que
    un `IN_PROGRESS` sin entrada `dispatched` tras un reinicio ES huérfano.
    Determinista y testable: `get_queue` devuelve `[]` si el fichero no
    existe (proyecto sin cola), sin lanzar.

    El backlog vive en `<root>/02-backlog`, así que el proyecto se deriva de
    `backlog_path.parent` (raíz + nombre)."""
    from atlas_forge.dispatcher.dispatch_queue import STATUS_DISPATCHED, get_queue

    backlog_root = Path(backlog_path)
    project_root = backlog_root.parent
    entries = get_queue(project_root, project_root.name)
    return {
        entry.task_id
        for entry in entries
        if getattr(entry, "status", None) == STATUS_DISPATCHED
    }


def _build_in_progress_items(
    tasks: list,
    user_stories: list,
    dispatched_task_ids: set[str],
) -> list[dict]:
    """Resúmenes (`_summary`) de los items `IN_PROGRESS` (Task y US derivada)
    con su indicador `in_flight` (T-AF022-US17-01), ordenados por id.

    - Task: `in_flight` = su `task_id` tiene entrada `dispatched` en la cola.
    - US: la cola es por Task, así que una US `IN_PROGRESS` derivada se
      considera `in_flight` si alguna de sus Tasks lo está."""
    in_flight_by_id: dict[str, bool] = {
        task.id: task.id in dispatched_task_ids
        for task in tasks
        if task.state == "IN_PROGRESS"
    }
    for us in user_stories:
        if us.state != "IN_PROGRESS":
            continue
        us_tasks = [task for task in tasks if task.user_story == us.id]
        in_flight_by_id[us.id] = any(
            task.id in dispatched_task_ids for task in us_tasks
        )

    items = [
        item
        for item in list(tasks) + list(user_stories)
        if item.state == "IN_PROGRESS"
    ]
    items.sort(key=lambda item: item.id)
    return [
        _summary(item, in_flight=in_flight_by_id[item.id])
        for item in items
    ]


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
        # T-AF048-US03-01 (bug de evaluación eager): `setdefault(label, {...})`
        # evalúa sus argumentos SIEMPRE aunque la clave ya exista — por eso
        # `_epic_label_from_file` se ejecutaba 844 veces (una por hijo) para
        # construir solo 51 grupos (0.70 ms × 844 ≈ 0.59 s). Con el chequeo
        # explícito la etiqueta (lectura de fichero) solo se resuelve cuando
        # se CREA un grupo nuevo.
        if label not in by_epic:
            # T-AF048-US03-02: `epic_label` se resuelve desde `graph.items`
            # (sin re-leer el fichero de Epic en el caso canónico);
            # `_epic_label_from_file` queda solo como fallback.
            by_epic[label] = {
                "epic": label,
                "epic_label": _resolve_epic_label(graph, label, backlog_path) if prefix else "(sin epic)",
                "user_stories": {},
                "tasks": {},
                # T-AF036-US15-01: detalle de cada User Story de la Epic con
                # su `fase` (para que la vista "Por Fase" muestre solo las US
                # de la fase del grupo). Campo aditivo, no rompe consumidores.
                "user_stories_detail": [],
            }
        entry = by_epic[label]
        if item.kind == ITEM_KIND_USER_STORY:
            entry["user_stories"][item.state] = entry["user_stories"].get(item.state, 0) + 1
            entry["user_stories_detail"].append(
                {"id": item.id, "fase": item.fase, "state": item.state, "version": item.version}
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
            # T-AF048-US03-02: resolución desde graph.items (title) con
            # fallback a _epic_label_from_file, coherente con el bucle de
            # hijos de arriba.
            "epic_label": _resolve_epic_label(graph, epic_item.id, backlog_path),
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

    # T-AF008-US18-01, criterio 4: ids duplicados en el backlog ya escrito,
    # como error consultable (solo se añade el campo si hay duplicados, igual
    # que `drift` — un backlog limpio no cambia su respuesta respecto a antes).
    duplicate_ids = find_duplicate_ids_in_backlog(backlog_path)

    # T-AF022-US17-01: indicador de en vuelo/huérfana para items IN_PROGRESS,
    # cruzando con las entradas `dispatched` de `dispatch_queue.json` (la
    # fuente persistida, no el registro `_inflight` en memoria).
    items_in_progress = _build_in_progress_items(
        tasks, user_stories, _dispatched_task_ids_from_queue(backlog_path)
    )

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
        "items_in_progress": items_in_progress,
        "max_leverage_chain": [_summary(item) for item in chain],
        "errors": errors,
    }
    if duplicate_ids:
        result["duplicate_ids"] = duplicate_ids
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

    # T-AF022-US17-01: items IN_PROGRESS con su indicador de en vuelo/huérfana
    # (cruzado con dispatch_queue.json) — para detectar atascos que nunca se
    # resolverán solos.
    lines.append("\nItems IN_PROGRESS (en vuelo / huérfanas):")
    if report["items_in_progress"]:
        for entry in report["items_in_progress"]:
            state_label = "en vuelo" if entry["in_flight"] else "HUÉRFANA"
            lines.append(f"  {entry['id']:<28} [{state_label}]")
    else:
        lines.append("  (ninguno)")

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

    if report.get("duplicate_ids"):
        lines.append("\nIDs duplicados:")
        for entry in report["duplicate_ids"]:
            lines.append(f"  {entry['id']}: {', '.join(entry['paths'])}")

    return "\n".join(lines)


def render_json_report(report: dict) -> str:
    """Salida JSON estructurada (criterio 2): un dict parseable, no el texto
    formateado. Mismas cifras que `format_human_report`."""
    return json.dumps(report, ensure_ascii=False, indent=2)
