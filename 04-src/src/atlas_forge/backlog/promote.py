"""Promueve (propaga) el estado DONE hacia arriba en la jerarquia del backlog.

Regla determinista (la unica fuente de verdad de trazabilidad):

  1. Una User Story -> DONE  si tiene al menos una Task y TODAS sus Tasks estan DONE.
  2. Una Epic        -> DONE  si tiene al menos una User Story y TODAS sus US estan DONE.

Solo PROMUEVE (TO_DO/IN_PROGRESS/REVIEW -> DONE; para Epic, TO_DO). Nunca revierte ni toca estados
que no proceda promover. Idempotente: ejecutarlo dos veces no cambia nada.

Convencion: el campo `state` es el primero que aparece en el frontmatter YAML de
cada fichero. Solo se reescribe la linea `^state:` del frontmatter.

## Drift inverso (T-AF022-US13-04)

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
from datetime import datetime, timezone
from pathlib import Path

FRONTMATTER_RE = re.compile(r"^(---\s*\n.*?\n---)", re.S)
STATE_LINE_RE = re.compile(r"^state:\s*.*$", re.MULTILINE)
UPDATED_AT_RE = re.compile(r"^updated_at:\s*.*$", re.MULTILINE)


def upsert_updated_at(content: str, timestamp: str | None = None) -> str:
    """Inserta o actualiza la línea `updated_at:` del frontmatter de un
    fichero de backlog (T-AF036-US13-01) — centralizado aquí para que
    cualquier cambio de `state` (promoción automática, edición manual por
    la web o cambios del Dispatcher) actualice también el timestamp de la
    última transición.

    Si ya existe una línea `updated_at:` se reemplaza su valor; si no, se
    inserta justo después de la línea `state:` (el campo que se está
    cambiando). Devuelve el contenido resultante (no escribe en disco).

    `timestamp` por defecto es el instante actual en ISO-8601 UTC
    (`datetime.now(timezone.utc).isoformat()`); permitir pasarlo explícito
    hace los tests deterministas."""
    ts = timestamp or datetime.now(timezone.utc).isoformat()
    if UPDATED_AT_RE.search(content):
        return UPDATED_AT_RE.sub(f"updated_at: {ts}", content, count=1)
    state_match = STATE_LINE_RE.search(content)
    if state_match is None:
        return content
    insert_at = state_match.end() + 1
    return content[:insert_at] + f"updated_at: {ts}\n" + content[insert_at:]


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
    """Cambia el estado de un fichero de backlog, actualizando también el
    campo `updated_at` (T-AF036-US13-01): cualquier cambio de `state`
    (promoción automática, aprobación del Arquitecto o edición manual por
    la web) queda timestampado con ISO-8601 UTC en el frontmatter."""
    with open(path, encoding="utf-8") as f:
        content = f.read()
    updated, n = STATE_LINE_RE.subn(f"state: {new_state}", content, count=1)
    if n != 1:
        raise RuntimeError(f"No se pudo actualizar state en {path}")
    updated = upsert_updated_at(updated)
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
    for path in glob.glob(os.path.join(backlog_path, "epics", "AF-*.md")):
        meta = _read_meta(path)
        if "id" in meta:
            epics[meta["id"]] = (path, meta)
    return tasks_by_us, uss, epics


def _collect_with_ids(backlog_path: str) -> tuple[dict, dict, dict]:
    """Igual que `_collect`, pero conservando el `id` de cada Task junto a
    su estado (`tasks_by_us: {us_id: [(task_id, state), ...]}`) — la
    promocion normal solo necesita el estado para decidir si promociona,
    pero la deteccion de drift inverso (T-AF022-US13-04) necesita poder
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
    for path in glob.glob(os.path.join(backlog_path, "epics", "AF-*.md")):
        meta = _read_meta(path)
        if "id" in meta:
            epics[meta["id"]] = (path, meta)

    return tasks_by_us, uss, epics


def _us_should_promote(state: str, tasks: list[str]) -> bool:
    # AF-040: la US promueve a IN_REVIEW (no DONE) cuando todas sus Tasks
    # están DONE — la validación final del Arquitecto la lleva a DONE.
    return bool(tasks) and state not in ("DONE", "IN_REVIEW") and all(s == "DONE" for s in tasks)


def _epic_should_promote(state: str, us_states: list[str]) -> bool:
    return bool(us_states) and state != "DONE" and all(s == "DONE" for s in us_states)


def _plan(backlog_path: str) -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]:
    tasks_by_us, uss, epics = _collect(backlog_path)

    to_promote_us = []
    for us_id, (path, meta) in sorted(uss.items()):
        if _us_should_promote(meta.get("state"), tasks_by_us.get(us_id, [])):
            to_promote_us.append((us_id, path, meta.get("state")))

    us_final_state = {us_id: "IN_REVIEW" for us_id, _, _ in to_promote_us}
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
    (`detect_reopened_drift_in_graph`, T-AF022-US13-05), para que ambos
    caminos nunca puedan divergir entre si.

    Limitacion conocida (alcance literal de T-AF022-US13-04, "hijo
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
    `BacklogGraph` ya cargado en memoria (T-AF022-US13-05, `GET /backlog`)."""
    tasks_by_us, uss, epics = _collect_with_ids(str(backlog_path))

    us_states = {us_id: meta.get("state", "") for us_id, (_, meta) in uss.items()}
    us_epic = {us_id: meta.get("epic") for us_id, (_, meta) in uss.items()}
    epic_states = {epic_id: meta.get("state", "") for epic_id, (_, meta) in epics.items()}

    return _reopened_drift_from_collections(tasks_by_us, us_states, us_epic, epic_states)


def detect_reopened_drift_in_graph(graph) -> ReopenedDriftResult:
    """Igual que `detect_reopened_drift`, pero sobre un `BacklogGraph` ya
    cargado en memoria (T-AF022-US13-05: reutilizado por
    `build_backlog_report`/`build_item_detail`/`build_epic_detail` para
    que `GET /backlog` nunca sirva un padre DONE con un hijo pendiente,
    sin releer disco por su cuenta — el grafo ya se carga completo para
    construir esos informes de todas formas).

    Import perezoso de `ITEM_KIND_*` para evitar un ciclo de import entre
    `atlas_forge.models.backlog` y este modulo (que hoy no depende de
    `models.backlog` en absoluto, solo trabaja con dicts sobre disco)."""
    from atlas_forge.models.backlog import ITEM_KIND_EPIC, ITEM_KIND_TASK, ITEM_KIND_USER_STORY

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

    AF-040: las User Story se promueven a `IN_REVIEW` (validación final del
    Arquitecto pendiente), nunca a `DONE` directamente; las Epics solo a
    `DONE` cuando todas sus US están `DONE`. Solo promueve (nunca revierte).
    Idempotente: una segunda ejecucion sobre el resultado de la primera no
    produce mas cambios.
    """
    to_promote_us, to_promote_epic = _plan(str(backlog_path))

    for _, path, _ in to_promote_us:
        _set_state(path, "IN_REVIEW")
    for _, path, _ in to_promote_epic:
        _set_state(path, "DONE")

    return PromotionResult(
        promoted_user_stories=[us_id for us_id, _, _ in to_promote_us],
        promoted_epics=[epic_id for epic_id, _, _ in to_promote_epic],
    )


# ── Consolidación bidireccional (T-AF022-US13-09) ─────────────────────────
# El estado de una User Story es SIEMPRE la derivación determinista de sus
# Tasks: `NO_TASKS` si no tiene ninguna, si no el estado de su Task menos
# avanzada. `consolidate_states` aplica esa derivación en AMBOS sentidos
# (promover, reabrir y fijar `NO_TASKS`) en una sola pasada idempotente;
# `check_consolidation` detecta TODO el drift de derivación.

# Estados de US que la consolidación NO toca (propiedad del pipeline o
# terminales): una US en `TO_PLAN` se está planificando (puede tener 0
# Tasks, no se le impone `NO_TASKS` mientras tanto); `OUT_OF_SCOPE` es
# terminal exclusivo de User Story.
_US_CONSOLIDATION_SKIP = frozenset({"TO_PLAN", "OUT_OF_SCOPE"})
# Epics: `FUERA_ROADMAP` y `OUT_OF_SCOPE` son terminales deliberados.
_EPIC_CONSOLIDATION_SKIP = frozenset({"FUERA_ROADMAP", "OUT_OF_SCOPE"})


def _derive_user_story_state_safe(task_states: list[str]) -> str | None:
    """`derive_user_story_state` (única fuente de verdad, AF-040) tolerante
    a estados de Task no canónicos: ante la duda devuelve `None` (el
    llamador deja el estado tal cual) en vez de abortar la consolidación."""
    from atlas_forge.core.state_machines import derive_user_story_state

    try:
        return derive_user_story_state(task_states)
    except ValueError:
        return None


def derive_us_target_state(current_state: str, task_states: list[str]) -> str:
    """Estado derivado (bidireccional) que debe tener una User Story según
    su estado actual y el de sus Tasks (T-AF022-US13-09):

    - `TO_PLAN`/`OUT_OF_SCOPE`: se respetan (transitorio/terminal), sin
      cambio (criterio 6: una US en `TO_PLAN` con 0 Tasks no se revierte a
      `NO_TASKS`).
    - `DONE`: con 0 Tasks -> `NO_TASKS` (criterio 1); todas sus Tasks
      `DONE` -> se mantiene `DONE` (ya validada por el Arquitecto); con
      alguna reabierta -> la Task menos avanzada (reabrir).
    - Resto: `NO_TASKS` si 0 Tasks; si no, el estado de la Task menos
      avanzada (`IN_REVIEW` si todas `DONE`, pendiente de validación)."""
    if current_state in _US_CONSOLIDATION_SKIP:
        return current_state
    derived = _derive_user_story_state_safe(task_states)
    if derived is None:
        return current_state
    if current_state == "DONE":
        if not task_states:
            return "NO_TASKS"
        if all(s == "DONE" for s in task_states):
            return "DONE"
        return derived
    return derived


def derive_epic_target_state(current_state: str, us_states: list[str]) -> str:
    """Estado derivado de una Epic: `DONE` si todas sus US están `DONE`; si
    no, `TO_DO` (criterio 3). Se respetan `FUERA_ROADMAP`/`OUT_OF_SCOPE`.
    Sin US, se deja tal cual (no se puede derivar)."""
    if current_state in _EPIC_CONSOLIDATION_SKIP:
        return current_state
    if not us_states:
        return current_state
    if all(s == "DONE" for s in us_states):
        return "DONE"
    return "TO_DO"


def _consolidation_plan(backlog_path: str) -> list[tuple[str, str, str, str]]:
    """Plan de consolidación bidireccional (T-AF022-US13-09): lista de
    `(id, path, new_state, kind)` — US/Epic cuyo estado en disco difiere de
    su estado derivado (incluido `NO_TASKS` y el más retrasado), sin
    escribir nada. Idempotente: sobre un backlog ya consolidado devuelve
    `[]`."""
    tasks_by_us, uss, epics = _collect_with_ids(backlog_path)

    changes: list[tuple[str, str, str, str]] = []
    us_final: dict[str, str] = {}
    for us_id, (path, meta) in sorted(uss.items()):
        task_states = [state for _, state in tasks_by_us.get(us_id, [])]
        target = derive_us_target_state(meta.get("state", ""), task_states)
        us_final[us_id] = target
        if target != meta.get("state", ""):
            changes.append((us_id, path, target, "user_story"))

    us_states_by_epic: dict[str, list[str]] = {}
    for us_id, (_, meta) in uss.items():
        epic = meta.get("epic")
        if epic:
            us_states_by_epic.setdefault(epic, []).append(us_final[us_id])

    for epic_id, (path, meta) in sorted(epics.items()):
        target = derive_epic_target_state(
            meta.get("state", ""), us_states_by_epic.get(epic_id, [])
        )
        if target != meta.get("state", ""):
            changes.append((epic_id, path, target, "epic"))

    return changes


def check_consolidation(backlog_path: str | Path) -> list[tuple[str, str, str, str]]:
    """Detecta TODO el drift de derivación (T-AF022-US13-09) — promoción,
    reapertura y `NO_TASKS`/más retrasado — sin escribir nada. Devuelve el
    mismo plan que `consolidate_states` aplicaría."""
    return _consolidation_plan(str(backlog_path))


def consolidate_states(backlog_path: str | Path) -> list[tuple[str, str, str, str]]:
    """Consolida el estado del backlog en AMBOS sentidos (T-AF022-US13-09):
    escribe en disco el estado derivado de cada US/Epic que difiere del
    actual — promover, reabrir y fijar `NO_TASKS` — en una sola pasada
    idempotente. Respeta los estados transitorios/terminales
    (`TO_PLAN`/`OUT_OF_SCOPE`/`FUERA_ROADMAP` y la US `DONE` válida).

    Devuelve la lista de `(id, path, new_state, kind)` aplicados."""
    changes = _consolidation_plan(str(backlog_path))
    for _id, path, new_state, _kind in changes:
        _set_state(path, new_state)
    return changes


def derive_graph_consolidation(graph) -> dict[str, str]:
    """Nucleo puro de la consolidacion sobre un `BacklogGraph` ya cargado
    (T-AF022-US13-09): devuelve `{item_id: estado_derivado}` para cada
    US/Epic cuyo estado en memoria difiere de su estado derivado (incluido
    `NO_TASKS` y el mas retrasado). Sin I/O — reutilizado por la
    reconciliacion de lectura (`report.reconcile_graph_state`) y por el
    detalle (`detail.py`) para que `GET /backlog`/`GET /backlog/{id}` nunca
    sirvan una US desactualizada aunque el fichero en disco no se haya
    consolidado."""
    from atlas_forge.models.backlog import ITEM_KIND_EPIC, ITEM_KIND_TASK, ITEM_KIND_USER_STORY

    tasks_by_us: dict[str, list[str]] = {}
    us_states: dict[str, str] = {}
    us_epic: dict[str, str | None] = {}
    epic_states: dict[str, str] = {}
    for item in graph.items.values():
        if item.kind == ITEM_KIND_TASK:
            if item.user_story:
                tasks_by_us.setdefault(item.user_story, []).append(item.state)
        elif item.kind == ITEM_KIND_USER_STORY:
            us_states[item.id] = item.state
            us_epic[item.id] = item.epic
        elif item.kind == ITEM_KIND_EPIC:
            epic_states[item.id] = item.state

    us_final: dict[str, str] = {}
    changes: dict[str, str] = {}
    for us_id, state in us_states.items():
        target = derive_us_target_state(state, tasks_by_us.get(us_id, []))
        us_final[us_id] = target
        if target != state:
            changes[us_id] = target

    us_by_epic: dict[str, list[str]] = {}
    for us_id, epic in us_epic.items():
        if epic:
            us_by_epic.setdefault(epic, []).append(us_final[us_id])
    for epic_id, state in epic_states.items():
        target = derive_epic_target_state(state, us_by_epic.get(epic_id, []))
        if target != state:
            changes[epic_id] = target
    return changes


def _reopen_target_us(task_states: list[str]) -> str | None:
    """Estado objetivo de una User Story reabierta a partir del estado de sus
    Tasks (T-AF022-US13-08): el estado de la Task más retrasada según el orden
    canónico de progreso (READY < TO_DEVELOP < IN_PROGRESS < IN_REVIEW < DONE).

    Reglas del padre:
    - Nunca devuelve `NO_TASKS` por esta vía (una US no se marca `NO_TASKS`
      por reapertura — si no tiene Tasks reabre a `READY`).
    - Si todas las Tasks están `DONE` devuelve `None` (el padre no se reabre).
    - Devuelve el estado de la Task menos avanzada (más retrasada) si hay
      alguna no-DONE. Reutiliza `derive_user_story_state` (única fuente de
      verdad del orden de progreso, AF-040) en vez de re-declarar el orden."""
    from atlas_forge.core.state_machines import derive_user_story_state

    if not task_states:
        return "READY"
    if all(s == "DONE" for s in task_states):
        return None
    derived = _derive_user_story_state_safe(task_states)
    # `derived` es el estado de la Task menos avanzada (o `IN_REVIEW` si
    # todas DONE, ya descartado arriba); nunca `NO_TASKS` con Tasks.
    return derived if derived is not None else "READY"


def _reopen_target_epic(us_states: list[str]) -> str | None:
    """Estado objetivo de una Epic reabierta a partir del estado de sus User
    Stories (T-AF022-US13-08): si todas las US están `DONE` la Epic no se
    reabre (`None`); si alguna US no está `DONE` (incluida una US
    `NO_TASKS`/`TO_PLAN`/`READY` o excluida `OUT_OF_SCOPE`) la Epic reabre a
    `TO_DO` (su estado menos avanzado)."""
    if not us_states:
        return None
    if all(s == "DONE" for s in us_states):
        return None
    return "TO_DO"


def reopen_backlog(backlog_path: str | Path) -> ReopenedDriftResult:
    """Reapertura determinista del padre al estado del hijo más retrasado
    (T-AF022-US13-08) — el sentido inverso de la promoción: además de
    promover un padre a `DONE` cuando todos sus hijos están `DONE` (ya
    existente), un padre `DONE` con un hijo directo que deja de estar `DONE`
    se reabre al estado del hijo más retrasado. Escribe los cambios en disco.

    Reglas (simétricas a la promoción):
    - User Story: reabre al estado de su Task más retrasada (nunca
      `NO_TASKS`; sin Tasks reabre a `READY`; todas las Tasks `DONE` -> no se
      toca).
    - Epic: reabre a `TO_DO` si alguna de sus User Stories no está `DONE`.

    Devuelve el resultado con los padres reabiertos (trazabilidad/logging).
    Es idempotente: ejecutarlo sobre un backlog ya consistente no cambia nada.
    """
    tasks_by_us, uss, epics = _collect_with_ids(str(backlog_path))

    items: list[ReopenedDriftItem] = []

    # Primera pasada: calcular el estado final de cada User Story reabierta
    # (en memoria) y aplicar los cambios — se usa después para la Epic
    # (cascada transitiva en una sola pasada idempotente).
    us_final: dict[str, str] = {}
    for us_id, (path, meta) in sorted(uss.items()):
        if meta.get("state") != "DONE":
            us_final[us_id] = meta.get("state", "")
            continue
        task_states = [s for _, s in tasks_by_us.get(us_id, [])]
        target = _reopen_target_us(task_states)
        if target is None:
            us_final[us_id] = "DONE"
            continue
        _set_state(path, target)
        us_final[us_id] = target
        items.append(
            ReopenedDriftItem(
                parent_id=us_id,
                parent_kind="user_story",
                reopened_children=tuple(
                    (cid, s) for cid, s in tasks_by_us.get(us_id, []) if s != "DONE"
                ),
            )
        )

    # Segunda pasada: las Epic usan el estado derivado de sus US (tras la
    # reapertura) para que una US reabierta reabra también su Epic en el
    # mismo ciclo.
    us_states_by_epic: dict[str, list[str]] = {}
    for us_id, (_, meta) in uss.items():
        epic = meta.get("epic")
        if epic:
            us_states_by_epic.setdefault(epic, []).append(
                us_final.get(us_id, meta.get("state", ""))
            )

    for epic_id, (path, meta) in sorted(epics.items()):
        if meta.get("state") != "DONE":
            continue
        us_states = us_states_by_epic.get(epic_id, [])
        target = _reopen_target_epic(us_states)
        if target is None:
            continue
        _set_state(path, target)
        items.append(
            ReopenedDriftItem(
                parent_id=epic_id,
                parent_kind="epic",
                reopened_children=tuple(
                    (us_id, us_final.get(us_id, uss[us_id][1].get("state", "")))
                    for us_id, _ in uss.items()
                    if uss[us_id][1].get("epic") == epic_id
                    and us_final.get(us_id, uss[us_id][1].get("state", "")) != "DONE"
                ),
            )
        )

    return ReopenedDriftResult(items=items)
