"""Migración AF-040: renombra los estados del frontmatter YAML de los
ficheros de backlog al vocabulario canónico.

Mapeo por tipo (leído del propio frontmatter):
- Task:   TO_DO -> READY; EN_DESARROLLO -> TO_DEVELOP; REVIEW -> IN_REVIEW;
          FUERA_ROADMAP -> READY (la epic no admite OUT_OF_SCOPE en Task).
- User Story: NO_TASKS (queda); EN_DISEÑO -> TO_PLAN; TO_DO -> READY;
          REVIEW -> IN_REVIEW; FUERA_ROADMAP -> OUT_OF_SCOPE.
- Epic: sin cambios (fuera del contrato canónico Task/US).

Solo toca la línea `state:` del frontmatter (primera ocurrencia). No toca
menciones en el cuerpo del fichero.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

BACKLOG = Path(__file__).resolve().parents[2] / "02-backlog"

TASK_MAP = {
    "TO_DO": "READY",
    "EN_DESARROLLO": "TO_DEVELOP",
    "REVIEW": "IN_REVIEW",
    "FUERA_ROADMAP": "READY",
}
US_MAP = {
    "EN_DISEÑO": "TO_PLAN",
    "TO_DO": "READY",
    "REVIEW": "IN_REVIEW",
    "FUERA_ROADMAP": "OUT_OF_SCOPE",
}
# Los estados canónicos ya no se tocan (idempotente).
CANONICAL = {
    "READY", "TO_DEVELOP", "IN_PROGRESS", "IN_REVIEW", "DONE",
    "NO_TASKS", "TO_PLAN", "OUT_OF_SCOPE", "TO_DO", "FUERA_ROADMAP",
}


def _read_type(content: str) -> str | None:
    m = re.search(r"^type:\s*(\w+)\s*$", content, re.MULTILINE)
    return m.group(1) if m else None


def _state_line(content: str) -> str | None:
    m = re.search(r"^state:\s*(\S+)\s*$", content, re.MULTILINE)
    return m.group(1) if m else None


def migrate_dir(dir_name: str) -> tuple[int, int]:
    changed = 0
    skipped = 0
    for path in sorted((BACKLOG / dir_name).glob("*.md")):
        content = path.read_text(encoding="utf-8")
        item_type = _read_type(content)
        if item_type not in ("task", "user_story"):
            skipped += 1
            continue
        mapping = TASK_MAP if item_type == "task" else US_MAP
        state = _state_line(content)
        if state is None or state not in mapping:
            skipped += 1
            continue
        new_state = mapping[state]
        updated = re.sub(r"^state:\s*\S+\s*$", f"state: {new_state}", content, count=1, flags=re.MULTILINE)
        path.write_text(updated, encoding="utf-8")
        print(f"  {path.name}: {state} -> {new_state}")
        changed += 1
    return changed, skipped


def main() -> int:
    dry = "--dry" in sys.argv
    total_changed = 0
    for dir_name in ("tasks", "user-stories"):
        print(f"== {dir_name} ==")
        changed, skipped = migrate_dir(dir_name)
        total_changed += changed
        print(f"  cambiados: {changed}, sin cambio: {skipped}")
    print(f"\nTOTAL cambiados: {total_changed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
