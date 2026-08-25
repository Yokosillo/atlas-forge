"""Migración T-AF036-US24-01 (US-AF036-24): las User Stories pasan de
`fase` a `version`, asignando `0.9.2` a lo no asignado.

Decisión de producto (2026-08-21): "todo es version, tanto para US como
para epic". Hoy las User Stories usan `fase` (conjunto
`Fase 0.9/0.9.1/0.9.2`) y las Epics ya usan `version`. Este script migra
SOLO las User Stories (las Epics ya versionan y no se tocan, US-AF036-18):

- `fase: Fase 0.9`   → `version: 0.9`
- `fase: Fase 0.9.1` → `version: 0.9.1`
- `fase: Fase 0.9.2` → `version: 0.9.2`
- `fase: null` o `fase: SIN_ASIGNAR` → `version: 0.9.2`

La `version` derivada de la `fase` es la autoritativa: si la US ya
declaraba una `version`, se reemplaza (un solo campo `version` por US).
Tras migrar, la US ya no tiene campo `fase`. Actualiza `updated_at` de
cada US migrada (reusando `upsert_updated_at` de
`atlas_forge.backlog.promote`).

Idempotente: tras una ejecución ya no quedan `fase` en User Stories, la
segunda no cambia nada.

Uso:
    python -m scripts.migrate_af036_us24_01_fase_a_version [--dry] [--path <backlog>]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from atlas_forge.backlog.promote import upsert_updated_at

BACKLOG = Path(__file__).resolve().parents[2] / "02-backlog"

# Línea `fase:` de una User Story (captura el valor).
_FASE_LINE_RE = re.compile(r"^fase:\s*(.*)$", re.MULTILINE)

# `fase` → `version`. `null`/`SIN_ASIGNAR` (sin fase) → `0.9.2` (default).
_FASE_TO_VERSION = {
    "Fase 0.9": "0.9",
    "Fase 0.9.1": "0.9.1",
    "Fase 0.9.2": "0.9.2",
    "SIN_ASIGNAR": "0.9.2",
    "null": "0.9.2",
}


def _current_fase(content: str) -> str | None:
    m = _FASE_LINE_RE.search(content)
    return m.group(1).strip() if m else None


def _rewrite_migrated_frontmatter(content: str, version: str) -> str | None:
    """Reescribe el frontmatter de una User Story dejando EXACTAMENTE una
    línea `version: <version>` y NINGUNA `fase:` (T-AF036-US24-06).

    En vez de dos sustituciones regex dependientes del orden/cantidad de
    líneas (que podían dejar un `fase:` residual cuando el `version:`
    preexistente no coincidía con el patrón, o dos líneas `version:`), se
    reconstruye el bloque frontmatter línea a línea: se descartan TODAS las
    líneas que empiecen por `version:` o `fase:` y se inserta UNA línea
    `version: <version>` en la posición de la primera descartada (o antes
    del `---` de cierre). El resto del fichero (cuerpo) queda intacto.

    Devuelve el contenido reescrito, o `None` si el fichero no tiene un
    frontmatter YAML reconocible (`---...---`)."""
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        return None
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return None

    removed_index: int | None = None
    kept: list[str] = []
    for i, line in enumerate(lines[:end]):
        stripped = line.strip()
        if stripped.startswith("version:") or stripped.startswith("fase:"):
            if removed_index is None:
                removed_index = i
            continue
        kept.append(line)
    if removed_index is None:
        removed_index = end

    kept.insert(removed_index, f"version: {version}")
    return "\n".join(kept + lines[end:])


def migrate_user_stories(backlog_path: str | Path, dry: bool = False) -> tuple[int, int]:
    """Migra las User Stories de `fase` a `version`.

    Devuelve `(changed, skipped)`. `changed` = US reescritas; `skipped` =
    US sin `fase`, sin `fase` en el mapeo (legacy fuera de las tres
    versiones), o ya migradas. Con `dry=True` no escribe nada (solo
    cuenta e imprime). NO toca Epics.

    Por cada US migrada se reconstruye el frontmatter con
    `_rewrite_migrated_frontmatter` (T-AF036-US24-06): queda exactamente
    UNA línea `version:` y NINGUNA `fase:` — sin importar el orden de los
    campos ni cuántas/privilegiadas líneas hubiera. Idempotente: tras una
    ejecución ya no quedan `fase` en User Stories, la segunda no cambia
    nada."""
    us_dir = Path(backlog_path) / "user-stories"
    changed = 0
    skipped = 0
    if not us_dir.is_dir():
        return changed, skipped

    for path in sorted(us_dir.glob("*.md")):
        content = path.read_text(encoding="utf-8")
        fase = _current_fase(content)
        if fase is None:
            skipped += 1
            continue
        version = _FASE_TO_VERSION.get(fase)
        if version is None:
            # `fase` fuera del conjunto de migración (p. ej. un 0.x legacy
            # no cubierto): no se toca — idempotente y no corrompe.
            skipped += 1
            continue

        # Reconstruye el frontmatter: la `version` derivada de la `fase` es
        # la autoritativa (reemplaza cualquier `version` preexistente) y el
        # `fase:` se ELIMINA siempre (T-AF036-US24-06).
        updated = _rewrite_migrated_frontmatter(content, version)
        if updated is None:
            skipped += 1
            continue
        updated = upsert_updated_at(updated)
        if updated == content:
            skipped += 1
            continue
        if not dry:
            path.write_text(updated, encoding="utf-8")
        print(f"  {path.name}: fase={fase} -> version={version}")
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

    print(
        f"\nTOTAL: {us_changed} User Stories migradas{' (dry-run)' if dry else ''}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())