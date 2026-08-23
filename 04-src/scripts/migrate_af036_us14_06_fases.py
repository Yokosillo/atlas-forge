"""Migración T-AF036-US14-06 + T-AF036-US18-03: limpia las fases
persistidas del backlog.

- User Stories (T-AF036-US14-06): reescribe la `fase` 0.x inválida a
  `Fase 0.9` (el conjunto cerrado de T-AF036-US14-05 rechaza 0.1..0.8).
- Epics (T-AF036-US18-03): la Epic se versiona, ya no lleva `fase` — se
  sustituye el campo `fase:` del frontmatter por `version: 0.9` (default de
  la migración, coherente con `create_epic` de US-AF036-18). Si la Epic ya
  tuviera un campo `version`, no se pisa (solo se retira la `fase`).

No toca User Stories ya en `Fase 0.9`/`Fase 0.9.1`/`Fase 0.9.2`,
`SIN_ASIGNAR`, `null` o sin campo `fase`. Actualiza `updated_at` de cada
item migrado (reusando `upsert_updated_at` de `atlas_forge.backlog.promote`).

Idempotente: tras una ejecución ya no quedan fases pendientes, la segunda
no cambia nada.

Uso:
    python -m scripts.migrate_af036_us14_06_fases [--dry] [--path <backlog>]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from atlas_forge.backlog.fases import VALID_FASES
from atlas_forge.backlog.promote import upsert_updated_at

BACKLOG = Path(__file__).resolve().parents[2] / "02-backlog"

# `fase: Fase 0.x...` en el frontmatter — solo se migra si el valor NO es
# una de las fases válidas del conjunto cerrado ({0.9, 0.9.1, 0.9.2}).
_FASE_LINE_RE = re.compile(r"^fase:\s*(Fase\s+0\.\S+)\s*$", re.MULTILINE)

# Cualquier línea `fase:` de una Epic (la Epic no debe llevar fase) y su
# `version:` (para no pisar una version ya declarada). `.*$` cubre valores
# con espacios ("Fase 0.1") y los marcadores SIN_ASIGNAR/null.
_EPIC_FASE_LINE_RE = re.compile(r"^fase:\s*.*$", re.MULTILINE)
_VERSION_LINE_RE = re.compile(r"^version:\s*\S+\s*$", re.MULTILINE)

# Sin fase: `SIN_ASIGNAR`/`null`/ausente — no se migra (en User Stories).
_NO_FASE = frozenset({"SIN_ASIGNAR", "null"})


def _current_fase(content: str) -> str | None:
    m = _FASE_LINE_RE.search(content)
    return m.group(1) if m else None


def migrate_user_stories(backlog_path: str | Path, dry: bool = False) -> tuple[int, int]:
    """Migra las User Stories con `fase` 0.x a `Fase 0.9`.

    Devuelve `(changed, skipped)`. `changed` = items reescritos; `skipped` =
    items que no tocó (fase válida, SIN_ASIGNAR/null/ausente, o ya migrado).
    Con `dry=True` no escribe nada (solo cuenta e imprime)."""
    us_dir = Path(backlog_path) / "user-stories"
    changed = 0
    skipped = 0
    if not us_dir.is_dir():
        return changed, skipped

    for path in sorted(us_dir.glob("*.md")):
        content = path.read_text(encoding="utf-8")
        fase = _current_fase(content)
        if fase is None or fase in _NO_FASE:
            skipped += 1
            continue
        # `fase` es `Fase 0.x` — si ya es válida (0.9/0.9.1/0.9.2) o no es
        # un 0.x no se toca (idempotente y acotado a 0.x).
        if fase in VALID_FASES:
            skipped += 1
            continue

        updated = _FASE_LINE_RE.sub("fase: Fase 0.9", content, count=1)
        updated = upsert_updated_at(updated)
        if updated == content:
            skipped += 1
            continue
        if not dry:
            path.write_text(updated, encoding="utf-8")
        print(f"  {path.name}: {fase} -> Fase 0.9")
        changed += 1
    return changed, skipped


def migrate_epics(backlog_path: str | Path, dry: bool = False) -> tuple[int, int]:
    """T-AF036-US18-03: sustituye la `fase` persistida de las Epics por
    `version: 0.9` (default de la migración). Si la Epic ya tiene `version`,
    no se pisa — solo se retira la `fase`. NO toca User Stories.

    Devuelve `(changed, skipped)`. `changed` = Epics reescritas; `skipped` =
    Epics sin `fase` o ya migradas. Con `dry=True` no escribe nada."""
    epics_dir = Path(backlog_path) / "epics"
    changed = 0
    skipped = 0
    if not epics_dir.is_dir():
        return changed, skipped

    for path in sorted(epics_dir.glob("*.md")):
        content = path.read_text(encoding="utf-8")
        if _EPIC_FASE_LINE_RE.search(content) is None:
            skipped += 1
            continue
        if _VERSION_LINE_RE.search(content):
            # La Epic ya declara `version`: no se pisa — solo se retira la
            # `fase` residual.
            updated = _EPIC_FASE_LINE_RE.sub("", content, count=1)
        else:
            updated = _EPIC_FASE_LINE_RE.sub("version: 0.9", content, count=1)
        updated = upsert_updated_at(updated)
        if updated == content:
            skipped += 1
            continue
        if not dry:
            path.write_text(updated, encoding="utf-8")
        print(f"  {path.name}: fase -> version: 0.9")
        changed += 1
    return changed, skipped


def main() -> int:
    dry = "--dry" in sys.argv
    backlog_path = BACKLOG
    if "--path" in sys.argv:
        idx = sys.argv.index("--path")
        if idx + 1 < len(sys.argv):
            backlog_path = Path(sys.argv[idx + 1])

    print(f"== {backlog_path / 'user-stories'} ==")
    us_changed, us_skipped = migrate_user_stories(backlog_path, dry=dry)
    print(f"  migradas: {us_changed}, sin cambio: {us_skipped}")

    print(f"== {backlog_path / 'epics'} ==")
    ep_changed, ep_skipped = migrate_epics(backlog_path, dry=dry)
    print(f"  migradas: {ep_changed}, sin cambio: {ep_skipped}")

    print(
        f"\nTOTAL: {us_changed} User Stories + {ep_changed} Epics "
        f"migradas{' (dry-run)' if dry else ''}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())