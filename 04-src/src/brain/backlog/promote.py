"""Promueve (propaga) el estado DONE hacia arriba en la jerarquia del backlog.

Regla determinista (la unica fuente de verdad de trazabilidad):

  1. Una User Story -> DONE  si tiene al menos una Task y TODAS sus Tasks estan DONE.
  2. Una Epic        -> DONE  si tiene al menos una User Story y TODAS sus US estan DONE.

Solo PROMUEVE (TO_DO/IN_PROGRESS/REVIEW -> DONE; para Epic, TO_DO). Nunca revierte ni toca estados
que no proceda promover. Idempotente: ejecutarlo dos veces no cambia nada.

Convencion: el campo `state` es el primero que aparece en el frontmatter YAML de
cada fichero. Solo se reescribe la linea `^state:` del frontmatter.

## Drift inverso (T-FB022-US13-04)

Ademas de la promocion, este modulo detecta (sin corregir) el caso
contrario: una US/Epic marcada `DONE` que tiene un hijo directo
(Task/US) en un estado no-DONE — caso real encontrado en vivo
2026-08-16 (una Task nueva anadida bajo una US ya `DONE`, sin que nadie
reabriera la US). Decision de diseno explicita: SOLO detectar, nunca
corregir automaticamente (revertir DONE -> TO_DO sin intervencion humana
tiene mas impacto que promocionar hacia DONE — un usuario pudo marcar
DONE deliberadamente por otro motivo). `detect_reopened_drift` reutiliza
la misma recoleccion (`_collect`) que la promocion, para que ambos
calculos nunca puedan divergir entre si."""
from __future__ import annotations

import glob
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

FRONTMATTER_RE = re.compile(r"^(---\s*\n.*?\n---)", re.S)
STATE_LINE_RE = re.compile(r"^state:\s*.*$", re.MULTILINE)


@dataclass
class PromotionResult:
    promoted_user_stories: list[str] = field(default_factory=list)
    promoted_epics: list[str] = field(default_factory=list)

    @property
    def has_drift(self) -> bool:
        return bool(self.promoted_user_stories or self.promoted_epics)


@dataclass(frozen=True)
class ReopenedDriftItem:
    """Un padre (US o Epic) marcado `DONE` con al menos un hijo directo
    reabierto. `parent_id`/`parent_kind` ("user_story"/"epic") identifican
    el padre; `reopened_children` es la lista de `(child_id, child_state)`
    de los hijos no-DONE encontrados (puede tener mas de uno)."""

    parent_id: str
    parent_kind: str
    reopened_children: tuple[tuple[str, str], ...]


@dataclass
class ReopenedDriftResult:
    items: list[ReopenedDriftItem] = field(default_factory=list)

    @property
    def has_drift(self) -> bool:
        return bool(self.items)


def _read_meta(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        content = f.read()
    m = FRONTMATTER_RE.match(content)
    if not m:
        return {}
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip()
    return meta


def _set_state(path: str, new_state: str) -> None:
    with open(path, encoding="utf-8") as f:
        content = f.read()
    updated, n = STATE_LINE_RE.subn(f"state: {new_state}", content, count=1)
    if n != 1:
        raise RuntimeError(f"No se pudo actualizar state en {path}")
    with open(path, "w", encoding="utf-8") as f:
        f.write(updated)


def _collect(backlog_path: str) -> tuple[dict, dict, dict]:
    tasks_by_us: dict[str, list[str]] = {}
    for path in glob.glob(os.path.join(backlog_path, "tasks", "T-*.md")):
        meta = _read_meta(path)
        us = meta.get("user_story")
        if us:
            tasks_by_us.setdefault(us, []).append(meta.get("state", ""))

    uss: dict[str, tuple[str, dict]] = {}
    for path in glob.glob(os.path.join(backlog_path, "user-stories", "US-*.md")):
        meta = _read_meta(path)
        if "id" in meta:
            uss[meta["id"]] = (path, meta)

    epics: dict[str, tuple[str, dict]] = {}
    for path in glob.glob(os.path.join(backlog_path, "epics", "FB-*.md")):
        meta = _read_meta(path)
        if "id" in meta:
            epics[meta["id"]] = (path, meta)
    return tasks_by_us, uss, epics


def _collect_with_ids(backlog_path: str) -> tuple[dict, dict, dict]:
    """Igual que `_collect`, pero conservando el `id` de cada Task junto a
    su estado (`tasks_by_us: {us_id: [(task_id, state), ...]}`) — la
    promocion normal solo necesita el estado para decidir si promociona,
    pero la deteccion de drift inverso (T-FB022-US13-04) necesita poder
    nombrar el hijo concreto que esta reabierto."""
    tasks_by_us: dict[str, list[tuple[str, str]]] = {}
    for path in glob.glob(os.path.join(backlog_path, "tasks", "T-*.md")):
        meta = _read_meta(path)
        us = meta.get("user_story")
        if us:
            tasks_by_us.setdefault(us, []).append(
                (meta.get("id", os.path.basename(path)), meta.get("state", ""))
            )

    uss: dict[str, tuple[str, dict]] = {}
    for path in glob.glob(os.path.join(backlog_path, "user-stories", "US-*.md")):
        meta = _read_meta(path)
        if "id" in meta:
            uss[meta["id"]] = (path, meta)

    epics: dict[str, tuple[str, dict]] = {}
    for path in glob.glob(os.path.join(backlog_path, "epics", "FB-*.md")):
        meta = _read_meta(path)
        if "id" in meta:
            epics[meta["id"]] = (path, meta)

    return tasks_by_us, uss, epics


def _us_should_promote(state: str, tasks: list[str]) -> bool:
    return bool(tasks) and state != "DONE" and all(s == "DONE" for s in tasks)


def _epic_should_promote(state: str, us_states: list[str]) -> bool:
    return bool(us_states) and state != "DONE" and all(s == "DONE" for s in us_states)


def _plan(backlog_path: str) -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]:
    tasks_by_us, uss, epics = _collect(backlog_path)

    to_promote_us = []
    for us_id, (path, meta) in sorted(uss.items()):
        if _us_should_promote(meta.get("state"), tasks_by_us.get(us_id, [])):
            to_promote_us.append((us_id, path, meta.get("state")))

    us_final_state = {us_id: "DONE" for us_id, _, _ in to_promote_us}
    us_states_by_epic: dict[str, list[str]] = {}
    for us_id, (_, meta) in uss.items():
        epic = meta.get("epic")
        if epic:
            us_states_by_epic.setdefault(epic, []).append(
                us_final_state.get(us_id, meta.get("state"))
            )

    to_promote_epic = []
    for epic_id, (path, meta) in sorted(epics.items()):
        if _epic_should_promote(meta.get("state"), us_states_by_epic.get(epic_id, [])):
            to_promote_epic.append((epic_id, path, meta.get("state")))

    return to_promote_us, to_promote_epic


def check_backlog_promotion(backlog_path: str | Path) -> PromotionResult:
    """Reporta que US/Epics se promoverian, sin escribir nada."""
    to_promote_us, to_promote_epic = _plan(str(backlog_path))
    return PromotionResult(
        promoted_user_stories=[us_id for us_id, _, _ in to_promote_us],
        promoted_epics=[epic_id for epic_id, _, _ in to_promote_epic],
    )


def _reopened_drift_from_collections(
    tasks_by_us: dict[str, list[tuple[str, str]]],
    us_states: dict[str, str],
    us_epic: dict[str, str | None],
    epic_states: dict[str, str],
) -> ReopenedDriftResult:
    """Nucleo puro del calculo de drift inverso, sin I/O — reutilizado
    tanto desde disco (`detect_reopened_drift`, via `_collect_with_ids`)
    como desde un `BacklogGraph` ya cargado en memoria
    (`detect_reopened_drift_in_graph`, T-FB022-US13-05), para que ambos
    caminos nunca puedan divergir entre si.

    Limitacion conocida (alcance literal de T-FB022-US13-04, "hijo
    directo reabierto" — no cascada transitiva): el drift de una Epic se
    calcula sobre el `state` EN DISCO de cada US, no sobre su estado ya
    reconciliado. Una Epic DONE cuya unica US tambien DONE tiene a su vez
    una Task reabierta (drift de la US, no de la Epic directamente) NO
    se marca aqui como Epic con drift — solo se detecta cuando la propia
    Epic tiene una US en estado no-DONE en disco. Verificado explicitamente
    en `test_backlog_detail.py`."""
    items: list[ReopenedDriftItem] = []

    for us_id, state in sorted(us_states.items()):
        if state != "DONE":
            continue
        reopened = tuple(
            (task_id, task_state)
            for task_id, task_state in tasks_by_us.get(us_id, [])
            if task_state != "DONE"
        )
        if reopened:
            items.append(
                ReopenedDriftItem(
                    parent_id=us_id, parent_kind="user_story",
                    reopened_children=reopened,
                )
            )

    for epic_id, state in sorted(epic_states.items()):
        if state != "DONE":
            continue
        reopened_us = tuple(
            (us_id, us_states[us_id])
            for us_id, epic in us_epic.items()
            if epic == epic_id and us_states.get(us_id) != "DONE"
        )
        if reopened_us:
            items.append(
                ReopenedDriftItem(
                    parent_id=epic_id, parent_kind="epic",
                    reopened_children=reopened_us,
                )
            )

    return ReopenedDriftResult(items=items)


def detect_reopened_drift(backlog_path: str | Path) -> ReopenedDriftResult:
    """Detecta (sin corregir) el drift inverso al de promocion: una
    US/Epic con `state: DONE` que tiene al menos un hijo directo (Task
    para una US; User Story para una Epic) en un estado no-DONE, leyendo
    `backlog_path` de disco (uso desde CLI/pre-commit hook).

    Solo lectura — no escribe nada, no forma parte de `--apply`. Ver
    `detect_reopened_drift_in_graph` para la variante que opera sobre un
    `BacklogGraph` ya cargado en memoria (T-FB022-US13-05, `GET /backlog`)."""
    tasks_by_us, uss, epics = _collect_with_ids(str(backlog_path))

    us_states = {us_id: meta.get("state", "") for us_id, (_, meta) in uss.items()}
    us_epic = {us_id: meta.get("epic") for us_id, (_, meta) in uss.items()}
    epic_states = {epic_id: meta.get("state", "") for epic_id, (_, meta) in epics.items()}

    return _reopened_drift_from_collections(tasks_by_us, us_states, us_epic, epic_states)


def detect_reopened_drift_in_graph(graph) -> ReopenedDriftResult:
    """Igual que `detect_reopened_drift`, pero sobre un `BacklogGraph` ya
    cargado en memoria (T-FB022-US13-05: reutilizado por
    `build_backlog_report`/`build_item_detail`/`build_epic_detail` para
    que `GET /backlog` nunca sirva un padre DONE con un hijo pendiente,
    sin releer disco por su cuenta — el grafo ya se carga completo para
    construir esos informes de todas formas).

    Import perezoso de `ITEM_KIND_*` para evitar un ciclo de import entre
    `brain.models.backlog` y este modulo (que hoy no depende de
    `models.backlog` en absoluto, solo trabaja con dicts sobre disco)."""
    from brain.models.backlog import ITEM_KIND_EPIC, ITEM_KIND_TASK, ITEM_KIND_USER_STORY

    tasks_by_us: dict[str, list[tuple[str, str]]] = {}
    us_states: dict[str, str] = {}
    us_epic: dict[str, str | None] = {}
    epic_states: dict[str, str] = {}

    for item in graph.items.values():
        if item.kind == ITEM_KIND_TASK:
            if item.user_story:
                tasks_by_us.setdefault(item.user_story, []).append((item.id, item.state))
        elif item.kind == ITEM_KIND_USER_STORY:
            us_states[item.id] = item.state
            us_epic[item.id] = item.epic
        elif item.kind == ITEM_KIND_EPIC:
            epic_states[item.id] = item.state

    return _reopened_drift_from_collections(tasks_by_us, us_states, us_epic, epic_states)


def promote_backlog(backlog_path: str | Path) -> PromotionResult:
    """Promueve US/Epics con todos sus hijos DONE, escribiendo el nuevo estado.

    Solo promueve (nunca revierte). Idempotente: una segunda ejecucion
    sobre el resultado de la primera no produce mas cambios.
    """
    to_promote_us, to_promote_epic = _plan(str(backlog_path))

    for _, path, _ in to_promote_us:
        _set_state(path, "DONE")
    for _, path, _ in to_promote_epic:
        _set_state(path, "DONE")

    return PromotionResult(
        promoted_user_stories=[us_id for us_id, _, _ in to_promote_us],
        promoted_epics=[epic_id for epic_id, _, _ in to_promote_epic],
    )
