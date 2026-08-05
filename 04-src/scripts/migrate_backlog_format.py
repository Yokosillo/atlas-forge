#!/usr/bin/env python3
"""Migrate backlog files to the standard format defined by T-FB018-US02-05.

Deterministic and idempotent: running twice produces identical output.

Rules:
1. Epic files: promote # X → ## X for all H1 headers except title line.
   Add ## Estado section with a valid closed-set value.
   Clean FB-003 criterion ## Estado collision, FB-015 DESCARTADA.

2. US/Task files: normalize **Epic:** → FB-NNN (ID only).
   Normalize **User Story:** → US-FBNNN-nn (ID only).
   Clean ## Estado variant values (SUPERADA, DONE(...) etc.) → closed set + note.

Usage:
    cd 04-src && .venv/bin/python scripts/migrate_backlog_format.py ../02-backlog/
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_EPIC_STATES: dict[str, str] = {
    "FB-001": "DONE", "FB-002": "DONE", "FB-003": "DONE",
    "FB-004": "DONE", "FB-005": "DONE", "FB-006": "TODO",
    "FB-007": "TODO", "FB-008": "DONE", "FB-009": "TODO",
    "FB-010": "TODO", "FB-011": "TODO", "FB-012": "TODO",
    "FB-013": "TODO", "FB-014": "DONE", "FB-015": "DONE",
    "FB-016": "DONE", "FB-017": "DONE", "FB-018": "DONE",
    "FB-019": "DONE", "FB-020": "DONE", "FB-021": "DONE",
}

_EPIC_STATE_NOTES: dict[str, str] = {
    "FB-015": "DESCARTADA (en principio). Decision de producto de 2026-08-02.",
}

_EPIC_ID_RE = re.compile(r"^(FB-\d{3,})")
_H1_RE = re.compile(r"^# +(.+)$")
_H2_RE = re.compile(r"^## +(.+)$")
_ESTADO_H2_RE = re.compile(r"^##\s*Estado\s*(?::\s*(.+))?$")

_EPIC_FIELD_RE = re.compile(r"^(\*\*Epic:\*\*\s*)\**(.+?)\**$")
_US_FIELD_RE = re.compile(r"^(\*\*User Story:\*\*\s*)\**(.+?)\**$")
_US_ID_RE = re.compile(r"^(US-FB\d{3,}-\d{2})")

_CLOSED_STATES = {"TODO", "IN_PROGRESS", "REVIEW", "DONE"}
_VARIANT_MAP: dict[str, str] = {
    "superada": "DONE", "sustituida": "DONE", "descartada": "DONE",
    "done": "DONE", "todo": "TODO",
    "in_progress": "IN_PROGRESS", "review": "REVIEW",
}


def _normalize_epic_field(line: str) -> str | None:
    """Return normalized **Epic:** line (FB-NNN only) or None if no change."""
    m = _EPIC_FIELD_RE.match(line.strip())
    if not m:
        return None
    prefix, value = m.group(1), m.group(2).strip()
    id_m = _EPIC_ID_RE.match(value)
    if not id_m:
        return None
    new_line = f"{prefix}{id_m.group(1)}"
    stripped = line.strip()
    if new_line == stripped:
        return None
    indent = len(line) - len(stripped)
    return " " * indent + new_line


def _normalize_us_field(line: str) -> str | None:
    """Return normalized **User Story:** line (US-ID only) or None if no change."""
    m = _US_FIELD_RE.match(line.strip())
    if not m:
        return None
    prefix, value = m.group(1), m.group(2).strip()
    id_m = _US_ID_RE.match(value)
    if not id_m:
        return None
    new_line = f"{prefix}{id_m.group(1)}"
    stripped = line.strip()
    if new_line == stripped:
        return None
    indent = len(line) - len(stripped)
    return " " * indent + new_line


def _clean_estado_value_line(line: str) -> str | None:
    """Return cleaned estado value or None if no change needed."""
    stripped = line.strip()
    if stripped in _CLOSED_STATES:
        return None
    if _H2_RE.match(stripped) or _H1_RE.match(stripped):
        return None
    first_token = stripped.split(" ")[0].rstrip(".")
    if first_token in _CLOSED_STATES:
        return None  # Already clean (may have # comment after)
    key = first_token.lower()
    clean = _VARIANT_MAP.get(key)
    if clean is None:
        return None
    indent = len(line) - len(stripped)
    new_line = " " * indent + clean
    if stripped != clean:
        new_line += f"  # {stripped}"
    return new_line


# -- Epic ----------------------------------------------------------------

def _migrate_epic(path: Path) -> tuple[str, str, int]:
    """Migrate one epic file."""
    filename = path.name
    ep_m = _EPIC_ID_RE.match(filename)
    epic_id = ep_m.group(1) if ep_m else None
    original = path.read_text(encoding="utf-8")
    changes = 0

    # Pre-pass: FB-003 rename criterion ## Estado -> ## Estado de la sesion
    # so that has_estado tracking does not pick it up as a status field.
    pre_lines = original.splitlines()
    if epic_id == "FB-003":
        pre_lines = list(pre_lines)
        for idx in range(len(pre_lines)):
            stripped = pre_lines[idx].strip()
            if _ESTADO_H2_RE.match(stripped):
                after = "\n".join(pre_lines[idx+1:idx+6])
                if "Debe ser posible" in after and "consultar el estado actual" in after:
                    pre_lines[idx] = pre_lines[idx].replace("## Estado", "## Estado de la sesion")
                    changes += 1

    lines = pre_lines
    new_lines: list[str] = []
    has_estado = False

    for idx, line in enumerate(lines):
        stripped = line.lstrip()
        if idx == 0:
            new_lines.append(line)
            continue
        if not has_estado and _ESTADO_H2_RE.match(stripped):
            has_estado = True
        h1m = _H1_RE.match(stripped)
        if h1m and not _H2_RE.match(stripped):
            indent = len(line) - len(stripped)
            new_lines.append(" " * indent + "## " + h1m.group(1))
            changes += 1
        else:
            new_lines.append(line)

    text = "\n".join(new_lines)

    # Ensure ## Estado section exists
    if epic_id is not None and not has_estado:
        estado = _EPIC_STATES.get(epic_id, "TODO")
        note = _EPIC_STATE_NOTES.get(epic_id, "")
        estado_line = f"## Estado\n\n{estado}"
        if note:
            estado_line += f"  # {note}"
        text = text.rstrip() + "\n\n" + estado_line + "\n"
        changes += 1

    # FB-015: clean DESCARTA state value
    if epic_id == "FB-015":
        lines_out = text.splitlines()
        new_lines_out: list[str] = []
        in_estado_section = False
        found_value = False
        for line in lines_out:
            stripped = line.strip()
            if _ESTADO_H2_RE.match(stripped):
                in_estado_section = True
                new_lines_out.append(line)
                continue
            if in_estado_section and not found_value:
                if stripped == "":
                    new_lines_out.append(line)
                    continue
                if _H2_RE.match(stripped) or _H1_RE.match(stripped):
                    new_lines_out.append(line)
                    in_estado_section = False
                    continue
                # Value line
                if "descartada" in stripped.lower() or "DESCARTADA" in stripped:
                    indent = len(line) - len(stripped)
                    note = (
                        "  # DESCARTADA (en principio) — decision de producto"
                        " de 2026-08-02 — la necesidad real quedo resuelta"
                        " por FB-016/FB-017 (ver nota al inicio del fichero)"
                    )
                    new_lines_out.append(" " * indent + "DONE" + note)
                    changes += 1
                    found_value = True
                    continue
                new_lines_out.append(line)
                found_value = True
                continue
            new_lines_out.append(line)
        text = "\n".join(new_lines_out)

    return original, text, changes


# -- US/Task -------------------------------------------------------------

def _migrate_item(path: Path) -> tuple[str, str, int]:
    """Migrate one US or Task file."""
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines()
    new_lines: list[str] = []
    changes = 0

    # Scan for Estado value to clean
    estado_value_idx: int | None = None
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not _ESTADO_H2_RE.match(stripped):
            continue
        for vi in range(idx + 1, len(lines)):
            vs = lines[vi].strip()
            if vs == "":
                continue
            if _H2_RE.match(vs) or _H1_RE.match(vs):
                break
            if vs not in _CLOSED_STATES:
                estado_value_idx = vi
            break
        break

    for idx, line in enumerate(lines):
        stripped = line.strip()

        # Normalize **Epic:** field
        normalized = _normalize_epic_field(line)
        if normalized is not None:
            new_lines.append(normalized)
            changes += 1
            continue

        # Normalize **User Story:** field
        normalized = _normalize_us_field(line)
        if normalized is not None:
            new_lines.append(normalized)
            changes += 1
            continue

        # Clean Estado variant value
        if idx == estado_value_idx:
            cleaned = _clean_estado_value_line(line)
            if cleaned is not None:
                new_lines.append(cleaned)
                changes += 1
                continue

        new_lines.append(line)

    return original, "\n".join(new_lines), changes


# -- Main ----------------------------------------------------------------

def migrate_backlog(backlog_path: str, dry_run: bool = False) -> int:
    root = Path(backlog_path)
    total_files, total_changes = 0, 0
    label = "DRY RUN" if dry_run else "modified"

    for subdir, migrator in [("epics", _migrate_epic),
                               ("user-stories", _migrate_item),
                               ("tasks", _migrate_item)]:
        d = root / subdir
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.md")):
            orig, migrated, changes = migrator(f)
            if orig != migrated:
                total_changes += changes
                if dry_run:
                    print(f"[DRY RUN] {label}: {f.relative_to(root.parent)} ({changes})")
                else:
                    f.write_text(migrated, encoding="utf-8")
                    print(f"  {label}: {f.relative_to(root.parent)} ({changes})")
            total_files += 1

    print(f"\nProcessed {total_files} files, {total_changes} changes applied.")
    return total_files


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <path-to-02-backlog/> [--dry-run]", file=sys.stderr)
        sys.exit(1)
    _bp = sys.argv[1]
    _dry = "--dry-run" in sys.argv
    if _dry:
        print(f"Dry run on: {_bp}\n")
    migrate_backlog(_bp, dry_run=_dry)
    if _dry:
        print("\nDry run complete — no files were modified.")
