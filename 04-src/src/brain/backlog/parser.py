"""Parser determinista de `02-backlog/` y grafo de dependencias
(T-FB018-US02-01, US-FB018-02 · "Estado del backlog: conteo, dependencias
y siguiente foco, sin gastar tokens de agente cognitivo").

## Qué hace y qué no hace

Lee todos los ficheros de `02-backlog/user-stories/*.md` y
`02-backlog/tasks/*.md` de un proyecto, extrae estado y dependencias con
parseo de texto (regex sobre la convención ya usada en todo el backlog —
`## Estado` con el valor en la línea siguiente, `## Dependencias` con
referencias en negrita `**T-FBxxx-...**`/`**US-FBxxx-...**`), y construye el
grafo de dependencias entre US/Tasks. NO usa ningún modelo ni heurística
de juicio: solo lectura del estado ya parseado de cada fichero.

## Convención de `02-backlog/` que se parsea (verificada sobre el backlog
## real de este proyecto 006)

- El identificador es el prefijo del nombre del fichero: `T-FB018-US02-01`
  (Task) o `US-FB018-02` (User Story). No se re-deriva de ninguna línea del
  contenido.
- `## Estado` va en su propia línea; el valor es la primera línea no vacía
  siguiente (`DONE`, `TODO`, `IN_PROGRESS`, ...). Puede haber valor en la
  misma línea (`## Estado: DONE`) — se acepta el valor inline y se ignora.
- `## Dependencias` va en su propia línea; las dependencias son los
  identificadores dentro de los patrones en negrita de esa sección,
  `**T-FBxxx-...**`/`**US-FBxxx-...**`. Un mismo patrón negrita puede
  contener varios identificadores (`**T-FB001-US01-01**, **T-FB001-US01-02**`).
  La palabra `Ninguna.` en la sección se interpreta como sin dependencias.
- `## Prioridad` va en su propia línea; el valor es la primera línea no
  vacía siguiente (p. ej. `Alta.`, `Media.`, `Baja — ...`). Es un campo
  OPcional: un item sin `## Prioridad` se parsea con `priority=None` (un
  backlog recién creado puede tener items aún sin prioridad) — no es un
  error de parseo, a diferencia de `## Estado`/`## Dependencias`.
- Un fichero que no sigue esta convención (`## Estado` o `## Dependencias`
  ausente o mal formado) se reporta como `BacklogParseError` de ese fichero
  concreto (identificador + motivo) sin abortar el resto — criterio de
  aceptación 6 de la Story.
"""

from __future__ import annotations

import re
from pathlib import Path

from brain.models.backlog import (
    BacklogGraph,
    BacklogItem,
    BacklogParseError,
    ITEM_KIND_TASK,
    ITEM_KIND_USER_STORY,
)

_ITEM_ID_PATTERN = re.compile(r"^(T|US)-FB\d{3}(?:-US\d{2})?-\d{2}")
_BOLD_DEPENDENCY_PATTERN = re.compile(
    r"\*\*((?:T|US)-FB\d{3}(?:-US\d{2})?-\d{2})\*\*"
)

_ESTADO_HEADER_PATTERN = re.compile(r"^##\s*Estado\s*(?::\s*(.+))?$")
_DEPENDENCIAS_HEADER_PATTERN = re.compile(r"^##\s*Dependencias\s*$")
_PRIORIDAD_HEADER_PATTERN = re.compile(r"^##\s*Prioridad\s*(?::\s*(.+))?$")

_NONE_DEPENDENCIES_KEYWORDS = ("ninguna", "ninguno")


def _item_id_from_stem(stem: str) -> str | None:
    match = _ITEM_ID_PATTERN.match(stem)
    return match.group(0) if match else None


def _item_kind(item_id: str) -> str:
    return ITEM_KIND_USER_STORY if item_id.startswith("US-") else ITEM_KIND_TASK


def _read_epic(text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("**Epic:"):
            value = stripped.removeprefix("**Epic:").strip()
            value = value.removeprefix("**").strip()
            value = value.rstrip("*").strip()
            return value or None
    return None


def _read_state(text: str, path: Path, item_id: str | None) -> str:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = _ESTADO_HEADER_PATTERN.match(line.strip())
        if match is None:
            continue
        if match.group(1) is not None and match.group(1).strip():
            return match.group(1).strip()
        for following in lines[index + 1 :]:
            stripped = following.strip()
            if not stripped:
                continue
            if re.match(r"^##\s*", following):
                break
            return stripped
        break
    raise BacklogParseError(
        path=path,
        item_id=item_id,
        reason="sección `## Estado` ausente o sin valor",
    )


def _read_dependencies(text: str, path: Path, item_id: str | None) -> tuple[str, ...]:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if _DEPENDENCIAS_HEADER_PATTERN.match(line.strip()) is None:
            continue
        section_lines = []
        for following in lines[index + 1 :]:
            if re.match(r"^##\s*", following):
                break
            section_lines.append(following)
        section = "\n".join(section_lines)
        if not any(stripped for stripped in (ln.strip() for ln in section_lines)):
            return ()
        if any(
            keyword in section.lower()
            for keyword in _NONE_DEPENDENCIES_KEYWORDS
        ):
            return ()
        dependencies = tuple(
            dict.fromkeys(_BOLD_DEPENDENCY_PATTERN.findall(section))
        )
        return dependencies
    raise BacklogParseError(
        path=path,
        item_id=item_id,
        reason="sección `## Dependencias` ausente",
    )


def _read_priority(text: str) -> str | None:
    """Valor literal de la sección `## Prioridad` (primera línea no vacía
    siguiente, aceptando también `## Prioridad: <valor>` inline), o `None`
    si el fichero no la declara. A diferencia de `## Estado`/
    `## Dependencias`, la ausencia NO es un error de parseo (campo opcional,
    ver docstring del módulo)."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = _PRIORIDAD_HEADER_PATTERN.match(line.strip())
        if match is None:
            continue
        if match.group(1) is not None and match.group(1).strip():
            return match.group(1).strip()
        for following in lines[index + 1 :]:
            stripped = following.strip()
            if not stripped:
                continue
            if re.match(r"^##\s*", following):
                break
            return stripped
        break
    return None


def parse_backlog_item(path: Path) -> BacklogItem:
    """Lee un fichero `.md` de `02-backlog/` y lo convierte en un
    `BacklogItem`.

    El identificador se toma del prefijo del nombre del fichero (convención
    de `02-backlog/`). Lanza `BacklogParseError` si el fichero no sigue la
    convención de `## Estado` o `## Dependencias`; NUNCA devuelve un item a
    medias ni propaga el fallo a otros ficheros (quien lo llame decide si
    aborta o reporta por separado)."""
    if not path.is_file():
        raise BacklogParseError(
            path=path,
            item_id=None,
            reason="no es un fichero",
        )
    text = path.read_text(encoding="utf-8")
    item_id = _item_id_from_stem(path.stem)
    if item_id is None:
        raise BacklogParseError(
            path=path,
            item_id=None,
            reason="el nombre del fichero no sigue el patrón de identificador",
        )
    state = _read_state(text, path, item_id)
    dependencies = _read_dependencies(text, path, item_id)
    return BacklogItem(
        id=item_id,
        kind=_item_kind(item_id),
        epic=_read_epic(text),
        state=state,
        dependencies=dependencies,
        priority=_read_priority(text),
        path=path,
    )


def load_backlog(backlog_path: Path) -> BacklogGraph:
    """Lee todo un `02-backlog/`: los ficheros de `user-stories/` y
    `tasks/`, parsea cada uno y construye el grafo (nodo por item, arista
    por dependencia declarada).

    Un fichero mal formado se reporta como `BacklogParseError` en
    `graph.errors` SIN interrumpir el parseo del resto (criterio de
    aceptación 6 de US-FB018-02) — el grafo se construye con los ficheros
    válidos y los errores se acumulan por separado. `backlog_path` debe ser
    el directorio `02-backlog/` (con subdirectorios `user-stories/` y
    `tasks/`)."""
    backlog_path = Path(backlog_path)
    items: dict[str, BacklogItem] = {}
    errors: list[BacklogParseError] = []

    for subdir in ("user-stories", "tasks"):
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


def _dependency_state_blocks(graph: BacklogGraph, item: BacklogItem) -> bool:
    """True si al menos una dependencia declarada de `item` sigue en un
    estado que no es `DONE` (o no existe en el grafo). Se usa en
    `classify_todo_items` — solo lectura del estado ya parseado, sin
    heurística de modelo."""
    for dependency_id in item.dependencies:
        dependency = graph.items.get(dependency_id)
        if dependency is None or dependency.state != "DONE":
            return True
    return False


def classify_todo_items(
    graph: BacklogGraph,
) -> tuple[list[BacklogItem], list[BacklogItem]]:
    """Separa los items en estado `TODO` en dos listas:

    - LISTA: todas las dependencias declaradas están `DONE` (o no tiene
      ninguna) — listo para empezar.
    - BLOQUEADA: al menos una dependencia sigue en un estado no-`DONE`.

    Solo lectura del estado ya parseado de cada dependencia — sin heurística
    de modelo, según T-FB018-US02-01. El orden de ambas listas es
    determinista (por identificador, como aparecen en el backlog)."""
    todos = sorted(
        (item for item in graph.items.values() if item.state == "TODO"),
        key=lambda item: item.id,
    )
    lista = [item for item in todos if not _dependency_state_blocks(graph, item)]
    bloqueada = [item for item in todos if _dependency_state_blocks(graph, item)]
    return lista, bloqueada


def _cascade_for_item(graph: BacklogGraph, root: BacklogItem) -> list[str]:
    """Items `TODO`-BLOQUEADOS que la finalización de `root` desbloquearía
    en cascada, recorriendo el grafo hasta punto fijo.

    Simula `root` como `DONE` y repite: un item `TODO`-BLOQUEADO se
    desbloquea cuando TODAS sus dependencias declaradas están `DONE` (o ya
    desbloqueadas en esta cascada); los items que ya estaban LISTOS (todas
    sus dependencias `DONE`) no se cuentan como "desbloqueados" por `root`
    — ya lo estaban, y no propagan la cascada porque no se han completado.
    Orden determinista por identificador. NUNCA incluye `root` mismo."""
    completed = {
        item.id for item in graph.items.values() if item.state == "DONE"
    } | {root.id}

    unlocked: set[str] = set()
    changed = True
    while changed:
        changed = False
        for item in graph.items.values():
            if (
                item.state != "TODO"
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


def find_max_leverage_chain(graph: BacklogGraph) -> list[BacklogItem]:
    """Identifica la Task/US en `TODO` cuya finalización desbloquea más
    Tasks BLOQUEADAS en cascada, y devuelve la cadena
    `[raíz] + [items desbloqueados en cascada]`.

    Para cada item `TODO` se simula su finalización y se cuentan los items
    `TODO`-BLOQUEADOS que quedan desbloqueados por el recorrido del grafo
    hasta punto fijo (recorrido del grafo, no juicio de un modelo —
    criterio T-FB018-US02-01). En caso de empate se elige el identificador
    menor (decisión determinista documentada). Si no hay ningún item `TODO`
    cuyo cierre desbloquee algo, devuelve `[]`."""
    todos = [
        item for item in graph.items.values() if item.state == "TODO"
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
