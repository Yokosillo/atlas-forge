"""Parser determinista de `02-backlog/` y grafo de dependencias
(T-FB018-US02-01, US-FB018-02, FB-027).

Lee todos los ficheros de `02-backlog/epics/*.md`,
`02-backlog/user-stories/*.md` y `02-backlog/tasks/*.md` de un proyecto,
extrae estado y dependencias del YAML frontmatter (formato FB-027), y
construye el grafo de dependencias entre US/Tasks. Ningun modelo, ninguna
heuristica de juicio: solo lectura del estado ya declarado en cada fichero.

## Formato esperado (FB-027)

Cada fichero `.md` empieza con un bloque YAML frontmatter entre `---`:

```yaml
---
id: T-FB022-US05-02
type: task
title: ...
state: DONE
dependencies: [T-FB022-US05-01, US-FB022-06]
priority: Critica
epic: FB-022
user_story: US-FB022-05
---
```

El identificador canonico se toma del prefijo del nombre del fichero
(convencion de `02-backlog/`), no del campo `id` del frontmatter.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from brain.models.backlog import (
    BacklogGraph,
    BacklogItem,
    BacklogParseError,
    ITEM_KIND_EPIC,
    ITEM_KIND_TASK,
    ITEM_KIND_USER_STORY,
)

_ITEM_ID_PATTERN = re.compile(r"^(T|US)-FB\d{3,}(?:-US\d{2}[A-Z]?)?-\d{2}[A-Z]?")
_EPIC_ID_PATTERN = re.compile(r"^(FB-\d{3,})")


def _item_id_from_stem(stem: str) -> str | None:
    match = _ITEM_ID_PATTERN.match(stem)
    if match:
        return match.group(0)
    match = _EPIC_ID_PATTERN.match(stem)
    return match.group(1) if match else None


def _item_kind(item_id: str) -> str:
    if item_id.startswith("US-"):
        return ITEM_KIND_USER_STORY
    if item_id.startswith("FB-"):
        return ITEM_KIND_EPIC
    return ITEM_KIND_TASK


def parse_frontmatter(text: str) -> dict:
    """Extrae y parsea el bloque YAML frontmatter del contenido.

    Publica (T-FB008-US04-05) para que otros modulos que necesiten leer
    un campo suelto del frontmatter de un fichero de Task (p. ej.
    `job_plan_builder.py`, que trabaja con rutas de fichero sueltas via
    glob, no con un `BacklogGraph` cargado) reutilicen este parseo en vez
    de reimplementar un segundo parser YAML.

    Raises ValueError si el frontmatter esta ausente o es invalido.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("el fichero no empieza con frontmatter YAML (`---`)")

    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break

    if end_idx is None:
        raise ValueError("frontmatter YAML no cerrado (falta `---` de cierre)")

    yaml_text = "\n".join(lines[1:end_idx])
    if not yaml_text.strip():
        raise ValueError("frontmatter YAML vacio")

    data = yaml.safe_load(yaml_text)
    if not isinstance(data, dict):
        raise ValueError(f"el frontmatter no es un diccionario YAML (tipo: {type(data).__name__})")

    return data


def _read_epic(text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("**Epic:"):
            value = stripped.removeprefix("**Epic:").strip()
            value = value.removeprefix("**").strip()
            value = value.rstrip("*").strip()
            return value or None
    return None


def _parse_legacy_format(text: str, path: Path, item_id: str) -> BacklogItem:
    """Fallback: parsea el formato Markdown antiguo (pre-FB-027) para
    compatibilidad con tests y ficheros que no se hayan migrado."""
    _ESTADO_HEADER = re.compile(r"^##\s*Estado\s*(?::\s*(.+))?$")
    _DEPENDENCIAS_HEADER = re.compile(r"^##\s*Dependencias\s*$")
    _PRIORIDAD_HEADER = re.compile(r"^##\s*Prioridad\s*(?::\s*(.+))?$")
    _FASE_HEADER = re.compile(r"^##\s*Fase\s*(?::\s*(.+))?$")
    _BOLD_DEP_RE = re.compile(
        r"\*\*((?:T|US)-FB\d{3,}(?:-US\d{2}[A-Z]?)?-\d{2}[A-Z]?|FB-\d{3,})\*\*"
    )

    lines = text.splitlines()

    state = None
    for idx, line in enumerate(lines):
        m = _ESTADO_HEADER.match(line.strip())
        if m is None:
            continue
        if m.group(1) and m.group(1).strip():
            state = m.group(1).strip().split("  #", 1)[0].strip()
        else:
            for following in lines[idx + 1:]:
                stripped = following.strip()
                if not stripped:
                    continue
                if re.match(r"^##\s*", following):
                    break
                state = stripped.split("  #", 1)[0].strip()
                break
        break

    if state is None:
        raise BacklogParseError(path=path, item_id=item_id, reason="## Estado ausente")

    dependencies = ()
    for idx, line in enumerate(lines):
        if not _DEPENDENCIAS_HEADER.match(line.strip()):
            continue
        section_lines = []
        for following in lines[idx + 1:]:
            if re.match(r"^##\s*", following):
                break
            section_lines.append(following)
        section = "\n".join(section_lines)
        if any(kw in section.lower() for kw in ("ninguna", "ninguno")):
            dependencies = ()
        else:
            dependencies = tuple(dict.fromkeys(_BOLD_DEP_RE.findall(section)))
        break

    priority = None
    for idx, line in enumerate(lines):
        m = _PRIORIDAD_HEADER.match(line.strip())
        if m is None:
            continue
        if m.group(1) and m.group(1).strip():
            priority = m.group(1).strip()
        else:
            for following in lines[idx + 1:]:
                stripped = following.strip()
                if not stripped:
                    continue
                if re.match(r"^##\s*", following):
                    break
                priority = stripped
                break
        break

    fase = None
    for idx, line in enumerate(lines):
        m = _FASE_HEADER.match(line.strip())
        if m is None:
            continue
        if m.group(1) and m.group(1).strip():
            fase = m.group(1).strip()
        else:
            for following in lines[idx + 1:]:
                stripped = following.strip()
                if not stripped:
                    continue
                if re.match(r"^##\s*", following):
                    break
                fase = stripped
                break
        break

    epic_val = _read_epic(text)

    return BacklogItem(
        id=item_id,
        kind=_item_kind(item_id),
        epic=epic_val,
        state=state,
        dependencies=dependencies,
        priority=priority,
        difficulty=None,
        fase=fase,
        path=path,
    )


def parse_backlog_item(path: Path) -> BacklogItem:
    """Lee un fichero `.md` de `02-backlog/` y lo convierte en un
    `BacklogItem`.

    El identificador se toma del prefijo del nombre del fichero. Los campos
    se leen del YAML frontmatter (formato FB-027), con fallback al formato
    Markdown antiguo (pre-FB-027) si el frontmatter no esta presente.
    """
    if not path.is_file():
        raise BacklogParseError(path=path, item_id=None, reason="no es un fichero")
    text = path.read_text(encoding="utf-8")
    item_id = _item_id_from_stem(path.stem)
    if item_id is None:
        raise BacklogParseError(path=path, item_id=None,
                                reason="el nombre del fichero no sigue el patron de identificador")

    if text.startswith("---"):
        try:
            data = parse_frontmatter(text)
        except ValueError as e:
            raise BacklogParseError(path=path, item_id=item_id, reason=str(e)) from e

        state = data.get("state")
        if state is None or not isinstance(state, str):
            raise BacklogParseError(path=path, item_id=item_id,
                                    reason="campo 'state' ausente en el frontmatter YAML")

        dependencies_raw = data.get("dependencies")
        if dependencies_raw is None:
            raise BacklogParseError(path=path, item_id=item_id,
                                    reason="campo 'dependencies' ausente en el frontmatter YAML")
        if not isinstance(dependencies_raw, list):
            raise BacklogParseError(path=path, item_id=item_id,
                                    reason="campo 'dependencies' no es una lista en el frontmatter YAML")
        dependencies = tuple(dict.fromkeys(d for d in dependencies_raw if isinstance(d, str)))

        epic = data.get("epic")
        if epic is not None and not isinstance(epic, str):
            epic = None

        priority = data.get("priority")
        if priority is not None and not isinstance(priority, str):
            priority = None

        difficulty = data.get("difficulty")
        if difficulty is not None and not isinstance(difficulty, str):
            difficulty = None

        fase = data.get("fase")
        if fase is not None and not isinstance(fase, str):
            fase = None

        user_story = data.get("user_story")
        if user_story is not None and not isinstance(user_story, str):
            user_story = None

        return BacklogItem(id=item_id, kind=_item_kind(item_id), epic=epic,
                           state=state, dependencies=dependencies,
                           priority=priority, difficulty=difficulty, fase=fase, path=path,
                           user_story=user_story)

    return _parse_legacy_format(text, path, item_id)


def load_backlog(backlog_path: Path) -> BacklogGraph:
    """Lee todo un `02-backlog/`: los ficheros de `epics/`, `user-stories/`
    y `tasks/`, parsea cada uno y construye el grafo (nodo por item, arista
    por dependencia declarada).

    Un fichero mal formado se reporta como `BacklogParseError` en
    `graph.errors` SIN interrumpir el parseo del resto (criterio de
    aceptacion 6 de US-FB018-02) — el grafo se construye con los ficheros
    validos y los errores se acumulan por separado. `backlog_path` debe ser
    el directorio `02-backlog/` (con subdirectorios `epics/`,
    `user-stories/` y `tasks/`)."""
    backlog_path = Path(backlog_path)
    items: dict[str, BacklogItem] = {}
    errors: list[BacklogParseError] = []

    for subdir in ("epics", "user-stories", "tasks"):
        directory = backlog_path / subdir
        if not directory.is_dir():
            continue
        for file_path in sorted(directory.glob("*.md")):
            try:
                item = parse_backlog_item(file_path)
            except BacklogParseError as error:
                errors.append(error)
                continue
            items[item.id] = item

    return BacklogGraph(
        items=items,
        errors=tuple(sorted(errors, key=lambda e: str(e.path))),
    )


# Bug corregido (2026-08-17, encontrado end-to-end vía el panel "Próximo
# foco" tras crear una User Story real): `classify_todo_items` y
# `find_max_leverage_chain` solo reconocían `state == "TO_DO"` como
# "pendiente de empezar, puede bloquear o estar bloqueada" — con el
# rediseño de estados (T-FB008-US15-01/-02) una User Story recién creada
# nace en `NO_TASKS` (esperando desgranarse en Tasks) o `EN_DISEÑO`
# (esperando al Arquitecto), ninguno de los dos `TO_DO`, así que quedaba
# invisible para ambos cálculos aunque otra Task dependiera de ella —
# mismo criterio ya aplicado en el resto del código (`EN_DESARROLLO`
# tratado como "todavía no empezado" en `_mark_story_tasks_done`, etc.):
# cualquier estado que no sea `DONE` participa como "pendiente".
# 2026-08-18, unificación de grafía (T-FB040-US01-01): `TO_DO` es la
# grafía única de los tres tipos; `TODO` ya no existe en el backlog.
_PENDING_STATES = frozenset({"TO_DO", "NO_TASKS", "EN_DISEÑO"})


def _dependency_state_blocks(graph: BacklogGraph, item: BacklogItem) -> bool:
    """True si al menos una dependencia declarada de `item` sigue en un
    estado que no es `DONE` (o no existe en el grafo)."""
    for dependency_id in item.dependencies:
        dependency = graph.items.get(dependency_id)
        if dependency is None or dependency.state != "DONE":
            return True
    return False


def classify_todo_items(
    graph: BacklogGraph,
) -> tuple[list[BacklogItem], list[BacklogItem]]:
    """Separa los items en estado `TO_DO` en dos listas:

    - LISTA: todas las dependencias declaradas estan `DONE` (o no tiene
      ninguna) — listo para empezar.
    - BLOQUEADA: al menos una dependencia sigue en un estado no-`DONE`.
    """
    todos = sorted(
        (item for item in graph.items.values()
         if item.state in _PENDING_STATES and item.kind != ITEM_KIND_EPIC),
        key=lambda item: item.id,
    )
    lista = [item for item in todos if not _dependency_state_blocks(graph, item)]
    bloqueada = [item for item in todos if _dependency_state_blocks(graph, item)]
    return lista, bloqueada


def _cascade_for_item(graph: BacklogGraph, root: BacklogItem) -> list[str]:
    """Items pendientes-BLOQUEADOS (`_PENDING_STATES`) que la finalizacion
    de `root` desbloquearia en cascada, recorriendo el grafo hasta punto
    fijo."""
    completed = {
        item.id for item in graph.items.values() if item.state == "DONE"
    } | {root.id}

    unlocked: set[str] = set()
    changed = True
    while changed:
        changed = False
        for item in graph.items.values():
            if (
                item.state not in _PENDING_STATES
                or item.id in completed
                or item.id in unlocked
            ):
                continue
            if _dependency_state_blocks(graph, item) and all(
                dependency_id in completed or dependency_id in unlocked
                for dependency_id in item.dependencies
            ):
                unlocked.add(item.id)
                completed.add(item.id)
                changed = True
    return sorted(unlocked - {root.id})


def _epic_items(graph: "BacklogGraph", epic_prefix: str) -> list["BacklogItem"]:
    """Items (US y Tasks) que pertenecen a la Epic identificada por
    `epic_prefix` (p. ej. `FB-020`), resueltos contra el `BacklogGraph`."""
    prefix_pattern = re.compile(r"^" + re.escape(epic_prefix))
    return sorted(
        (
            item
            for item in graph.items.values()
            if item.kind != ITEM_KIND_EPIC and item.epic is not None
            and prefix_pattern.match(item.epic.strip())
        ),
        key=lambda item: item.id,
    )


def _all_transitive_deps(graph: "BacklogGraph", item_id: str, visited: set | None = None) -> set[str]:
    """Recopila transitivamente todos los identificadores de dependencia
    de `item_id` cuyo estado NO es `DONE`."""
    if visited is None:
        visited = set()
    if item_id in visited:
        return visited
    visited.add(item_id)
    item = graph.items.get(item_id)
    if item is None:
        return visited
    for dep_id in item.dependencies:
        dep = graph.items.get(dep_id)
        if dep is not None and dep.state != "DONE":
            _all_transitive_deps(graph, dep_id, visited)
    return visited


def calculate_unblock_degree(graph: "BacklogGraph", epic_prefix: str) -> float:
    """Grado de desbloqueo de una Epic (porcentaje 0.0-1.0)."""
    items = _epic_items(graph, epic_prefix)
    if not items:
        return 1.0

    unblocked = 0
    for item in items:
        blocking_deps = _dependency_state_blocks(graph, item)
        if not blocking_deps:
            unblocked += 1

    return unblocked / len(items)


def find_max_leverage_chain(graph: BacklogGraph) -> list[BacklogItem]:
    """Identifica la Task/US pendiente (`_PENDING_STATES`) cuya
    finalizacion desbloquea mas Tasks BLOQUEADAS en cascada."""
    todos = [
        item for item in graph.items.values() if item.state in _PENDING_STATES
    ]

    best_chain: list[BacklogItem] = []
    best_leverage = 0
    for item in sorted(todos, key=lambda candidate: candidate.id):
        unlocked_ids = _cascade_for_item(graph, item)
        if len(unlocked_ids) > best_leverage:
            best_leverage = len(unlocked_ids)
            best_chain = [item] + [
                graph.items[unlocked_id] for unlocked_id in unlocked_ids
            ]
    return best_chain
