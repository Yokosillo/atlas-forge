"""Promueve (propaga) el estado DONE hacia arriba en la jerarquia del backlog.

Regla determinista (la unica fuente de verdad de trazabilidad):

  1. Una User Story -> DONE  si tiene al menos una Task y TODAS sus Tasks estan DONE.
  2. Una Epic        -> DONE  si tiene al menos una User Story y TODAS sus US estan DONE.

Solo PROMUEVE (TODO/IN_PROGRESS/REVIEW -> DONE). Nunca revierte ni toca estados
que no proceda promover. Idempotente: ejecutarlo dos veces no cambia nada.

Convencion: el campo `state` es el primero que aparece en el frontmatter YAML de
cada fichero. Solo se reescribe la linea `^state:` del frontmatter.
"""
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
