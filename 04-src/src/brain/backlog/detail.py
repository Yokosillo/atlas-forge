"""Detalle de un item concreto del backlog (`T-FB020-US01-01`,
US-FB020-01 · "Ver el estado del backlog: Epics, User Stories y su
detalle").

A diferencia de `parser.py` (que solo guarda `id/kind/epic/state/
dependencies/priority/path` de cada item, sin su contenido), este módulo
lee el fichero Markdown de UN item ya localizado en el grafo y extrae sus
secciones convencionales (`## Objetivo`/`## Historia`, `## Criterios de
aceptación`) con el mismo parseo de texto simple por encabezados `##` que
ya usa `parser.py` — ningún modelo, ninguna heurística de juicio.

Las Epics NO son nodos de `BacklogGraph` (`load_backlog` solo recorre
`user-stories/` y `tasks/`) — viven en `02-backlog/epics/FB-xxx-*.md` y se
identifican por el prefijo `FB-xxx` de su nombre de fichero. La etiqueta
`item.epic` de cada `BacklogItem` es el texto libre tras `**Epic:**` (p.
ej. `"FB-020 · Gestión de Backlog (alcance v1)"`) — distintas Tasks/US de
la MISMA Epic real pueden traer sufijos distintos (verificado sobre el
backlog real de este proyecto: `FB-008` aparece con 8 variantes de
sufijo). Por eso el desglose de una Epic agrupa por el prefijo `FB-xxx`
del label, no por el string completo (a diferencia de `by_epic` en
`report.py`, que sí agrupa por label completo — ese cálculo no se toca
aquí, es el de otro endpoint)."""

from __future__ import annotations

import re
from pathlib import Path

from brain.backlog.promote import detect_reopened_drift_in_graph
from brain.models.backlog import BacklogGraph, ITEM_KIND_TASK, ITEM_KIND_USER_STORY

_EPIC_ID_PATTERN = re.compile(r"^FB-\d{3,}$")
_EPIC_LABEL_PREFIX_PATTERN = re.compile(r"^(FB-\d{3,})")

_SECTION_HEADER_PATTERN = re.compile(r"^##\s*(.+?)\s*$")


def _read_section(text: str, header_name: str) -> str | None:
    """Contenido de la sección `## {header_name}` de `text` (hasta el
    siguiente encabezado — `#` O `##` — o el final del fichero), o `None`
    si no está presente — mismo criterio que `_read_priority` de
    `parser.py` (campo opcional, ausencia no es un error). Comparación
    insensible a mayúsculas para tolerar variantes ya presentes en el
    backlog real (`## objetivo` no existe hoy, pero el criterio de
    robustez es el mismo que el resto del parser: parseo de texto simple,
    sin exigir formato exacto de más de lo necesario).

    Corta también en `#` (H1), no solo en `##`: las Epics reales de
    `02-backlog/epics/*.md` mezclan niveles de encabezado — `## Objetivo`
    va seguido de secciones en `#` (`# Contexto`, `# Alcance`, ...), NO en
    `##` (bug real encontrado por el Crítico en la primera verificación de
    esta Task — sin este corte, `_read_section` arrastraba Contexto/
    Alcance/Diferido a v2 enteros dentro de "Objetivo", hasta el primer
    `##` que apareciera por casualidad varias secciones más abajo). Las
    Tasks/User Stories no tienen ningún `#` interno más allá del título
    (verificado sobre las 184 existentes), así que este corte no cambia su
    comportamiento. `T-FB018-US02-05` normalizará los encabezados de las
    Epics a `##` — cuando eso ocurra, este corte en `#` seguirá siendo
    válido (más laxo de lo necesario, no un problema).

    Un separador `---` (regla horizontal Markdown) al final de la sección
    se descarta — las 21 Epics reales lo usan para separar visualmente el
    Objetivo del resto del fichero (`FB-020-gestion-de-backlog.md` entre
    otras); sin este recorte quedaría colgando al final del contenido
    devuelto pese a no ser texto real de la sección."""
    lines = text.splitlines()
    target = header_name.strip().lower()
    for index, line in enumerate(lines):
        match = _SECTION_HEADER_PATTERN.match(line.strip())
        if match is None or match.group(1).strip().lower() != target:
            continue
        section_lines = []
        for following in lines[index + 1 :]:
            if re.match(r"^#{1,2}\s*", following):
                break
            section_lines.append(following)
        while section_lines and section_lines[-1].strip() in ("", "---"):
            section_lines.pop()
        content = "\n".join(section_lines).strip()
        return content or None
    return None


def _drifted_ids(graph: BacklogGraph) -> frozenset[str]:
    """Ids de US/Epic con drift inverso (T-FB022-US13-04: `state: DONE`
    en disco con un hijo directo reabierto) presentes en `graph`.

    T-FB022-US13-05: `build_item_detail`/`build_epic_detail` la invocan
    para que `GET /backlog/{item_id}` nunca sirva un padre DONE con un
    hijo pendiente sin decirlo explícitamente — pasada extra sobre datos
    ya en memoria (el grafo ya está cargado por el llamador), sin releer
    disco ni escribir nada."""
    drift = detect_reopened_drift_in_graph(graph)
    return frozenset(item.parent_id for item in drift.items)


def is_epic_item_id(item_id: str) -> bool:
    """True si `item_id` tiene la forma `FB-xxx` (identificador de Epic,
    p. ej. `FB-020`) en vez de `T-FBxxx-...`/`US-FBxxx-...` (Task/User
    Story, nodos reales de `BacklogGraph`)."""
    return _EPIC_ID_PATTERN.match(item_id) is not None


def _epic_prefix(epic_label: str | None) -> str | None:
    if epic_label is None:
        return None
    match = _EPIC_LABEL_PREFIX_PATTERN.match(epic_label.strip())
    return match.group(1) if match else None


def build_epic_detail(backlog_path: str | Path, graph: BacklogGraph, epic_id: str) -> dict | None:
    """Detalle de la Epic `epic_id` (p. ej. `FB-020`): su objetivo (leído
    de `02-backlog/epics/{epic_id}-*.md`, sección `## Objetivo`) y el
    desglose de sus User Stories con estado — `None` si no existe ningún
    fichero de Epic con ese prefijo NI ninguna US/Task la declara (ni
    fichero de Epic ni items la referencian → la Epic no existe en este
    backlog, 404 en la capa HTTP).

    T-FB022-US13-05: si la propia Epic o alguna de sus User Stories
    listadas tiene drift inverso (`state: DONE` en disco con un hijo
    reabierto), el `state` mostrado aquí es el reconciliado
    (`IN_PROGRESS`), con `drift: true` explícito — nunca el `DONE` crudo
    sin matiz."""
    epics_dir = Path(backlog_path) / "epics"
    epic_file = next(iter(sorted(epics_dir.glob(f"{epic_id}-*.md"))), None) if epics_dir.is_dir() else None

    objetivo: str | None = None
    fase: str | None = None
    parse_warning: str | None = None
    if epic_file is not None:
        text = epic_file.read_text(encoding="utf-8")
        objetivo = _read_section(text, "Objetivo")
        fase = _read_section(text, "Fase")
        if objetivo is None:
            parse_warning = "sección `## Objetivo` ausente o vacía en el fichero de la Epic"
    else:
        parse_warning = (
            f"no existe ningún fichero de Epic '{epic_id}-*.md' en "
            "`02-backlog/epics/` — Epic referenciada solo por sus US/Tasks"
        )

    user_stories = sorted(
        (
            item
            for item in graph.items.values()
            if item.kind == ITEM_KIND_USER_STORY and _epic_prefix(item.epic) == epic_id
        ),
        key=lambda item: item.id,
    )

    if epic_file is None and not user_stories:
        return None

    drifted_ids = _drifted_ids(graph)

    # T-FB036-US01-09: número de Tasks de cada User Story, contado sobre
    # el mismo `graph` ya cargado (sin llamada adicional al backend) —
    # se cruza por el campo real `item.user_story` de cada Task (el
    # valor del `user_story:` del frontmatter YAML, `T-FB008-US04-05`),
    # NUNCA por prefijo del propio id de la Task: confirmado en
    # `T-FB036-US01-04`/`T-FB008-US10-01` que esa convención de nombre
    # de fichero no es universal en el backlog real (hay Tasks reales
    # cuyo id no coincide con su `user_story` verdadero).
    task_counts: dict[str, int] = {}
    for item in graph.items.values():
        if item.kind == ITEM_KIND_TASK and item.user_story is not None:
            task_counts[item.user_story] = task_counts.get(item.user_story, 0) + 1

    result: dict = {
        "id": epic_id,
        "kind": "epic",
        "objetivo": objetivo,
        "fase": fase,
        "user_stories": [
            {
                "id": item.id,
                "state": "IN_PROGRESS" if item.id in drifted_ids else item.state,
                "priority": item.priority,
                "task_count": task_counts.get(item.id, 0),
                **({"drift": True} if item.id in drifted_ids else {}),
            }
            for item in user_stories
        ],
    }
    if parse_warning is not None:
        result["parse_warning"] = parse_warning
    if epic_id in drifted_ids:
        result["state"] = "IN_PROGRESS"
        result["drift"] = True
    return result


def build_item_detail(graph: BacklogGraph, item_id: str) -> dict | None:
    """Detalle de una Task/User Story ya cargada en `graph` — `None` si
    `item_id` no existe en el grafo (404 en la capa HTTP).

    Lee el fichero de `item.path` y extrae `## Objetivo`/`## Historia`
    (lo que declare el fichero — las Tasks usan `## Objetivo`, las User
    Stories `## Historia`, convención ya verificada sobre el backlog real)
    y `## Criterios de aceptación`. Si ninguna de las dos variantes de
    objetivo está presente, o falta `## Criterios de aceptación`, el resto
    del contenido disponible se devuelve igualmente junto con
    `parse_warning` explícito (criterio 4 de la Task: nunca falla el
    endpoint entero por una sección mal formada).

    Para una User Story, incluye además sus Tasks (id + estado) derivadas
    de `graph.items` filtrando por el campo `user_story` de cada Task
    (T-FB008-US04-05: `dependencies` nunca fue la relación Task→US real —
    ninguna Task del proyecto declaró jamás su propia US ahí, esa relación
    vive en `user_story:` del frontmatter — no requiere releer ningún
    fichero adicional, ya viene resuelto en el grafo).

    T-FB022-US13-05: si `item_id` es una User Story con drift inverso
    (`state: DONE` en disco con una Task hija reabierta), `state` se
    reconcilia a `IN_PROGRESS` y se añade `drift: true` — nunca se sirve
    el `DONE` crudo del fichero sin ese matiz."""
    item = graph.items.get(item_id)
    if item is None:
        return None

    text = item.path.read_text(encoding="utf-8")
    objetivo = _read_section(text, "Objetivo")
    if objetivo is None:
        objetivo = _read_section(text, "Historia")
    criterios = _read_section(text, "Criterios de aceptación")

    warnings = []
    if objetivo is None:
        warnings.append("sección `## Objetivo`/`## Historia` ausente o vacía")
    if criterios is None:
        warnings.append("sección `## Criterios de aceptación` ausente o vacía")

    drifted_ids = _drifted_ids(graph) if item.kind == ITEM_KIND_USER_STORY else frozenset()
    is_drifted = item_id in drifted_ids

    result: dict = {
        "id": item.id,
        "kind": item.kind,
        "epic": item.epic,
        "state": "IN_PROGRESS" if is_drifted else item.state,
        "priority": item.priority,
        # T-FB008-US11-02: dificultad estimada de la Task (`Crítica`/
        # `Alta`/`Media`/`Baja`, `T-FB008-US11-01`) — `None` para una User
        # Story (el campo no existe en su esquema, nunca se asigna ahí) o
        # para una Task todavía no puntuada, mismo criterio que `priority`.
        "difficulty": item.difficulty,
        "fase": item.fase,
        "dependencies": [
            {
                "id": dep_id,
                "state": graph.items[dep_id].state if dep_id in graph.items else None,
            }
            for dep_id in item.dependencies
        ],
        "objetivo": objetivo,
        "criterios_aceptacion": criterios,
    }
    if is_drifted:
        result["drift"] = True

    if item.kind == ITEM_KIND_USER_STORY:
        tasks = sorted(
            (
                other
                for other in graph.items.values()
                if other.kind != ITEM_KIND_USER_STORY and other.user_story == item_id
            ),
            key=lambda other: other.id,
        )
        result["tasks"] = [{"id": task.id, "state": task.state, "priority": task.priority} for task in tasks]

    if warnings:
        result["parse_warning"] = "; ".join(warnings)

    return result
