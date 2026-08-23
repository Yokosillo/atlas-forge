#!/usr/bin/env python3
"""Cierre de version de Atlas Forge (T-AF024-US23-01).

Cierra la version abierta actual: comprueba que toda User Story asignada a esa
version (`version: <v>` en su frontmatter) este en `state: DONE`, y si es asi
avanza el esquema de `.atlas-forge/version.yml`:

  current_closed -> la version cerrada
  open           -> la primera de `future`
  future         -> la siguiente (open_old + 2, open_old + 3)

Solo CIERRA (never revierte) y es idempotente: si ya se cerro, no hace nada.

Uso:
  python3 scripts/close_version.py --check   # reporta sin tocar nada; exit != 0 si hay US sin DONE
  python3 scripts/close_version.py --apply   # valida y escribe el nuevo esquema de versiones
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(os.path.dirname(__file__)).resolve().parents[1]
BACKLOG = REPO_ROOT / "02-backlog" / "user-stories"
VERSION_FILE = REPO_ROOT / ".atlas-forge" / "version.yml"

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


def _load_version_scheme() -> dict:
    if not VERSION_FILE.exists():
        print(f"ERROR: no existe el esquema de versiones en {VERSION_FILE}", file=sys.stderr)
        sys.exit(1)
    with open(VERSION_FILE, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not data.get("open") or not data.get("future"):
        print(f"ERROR: esquema de versiones incompleto en {VERSION_FILE}", file=sys.stderr)
        sys.exit(1)
    return data


def _us_entries() -> list[tuple[str, str, str]]:
    """(id, state, version) de cada User Story del backlog."""
    entries = []
    for path in sorted(BACKLOG.glob("US-*.md")):
        text = path.read_text(encoding="utf-8")
        m = _FRONTMATTER_RE.match(text)
        if not m:
            continue
        fm = yaml.safe_load(m.group(1)) or {}
        entries.append(
            (str(fm.get("id", path.stem)), str(fm.get("state", "")), str(fm.get("version", "")))
        )
    return entries


def _check_version(version: str) -> list[str]:
    """Devuelve la lista de US asignadas a `version` que no estan DONE."""
    not_done = []
    for us_id, state, us_version in _us_entries():
        if us_version == version and state != "DONE":
            not_done.append(f"{us_id} (state={state})")
    return not_done


def _next_versions(version: str, count: int) -> list[str]:
    """Siguientes `count` versiones tras `version` (p. ej. "0.9.1" -> ["0.9.2", "0.9.3"])."""
    parts = str(version).split(".")
    major = int(parts[0])
    minor = int(parts[1]) if len(parts) > 1 else 0
    patch = int(parts[2]) if len(parts) > 2 else 0
    return [f"{major}.{minor}.{patch + i + 1}" for i in range(count)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--check", action="store_true", help="reportar sin tocar nada; exit != 0 si hay US sin DONE"
    )
    group.add_argument("--apply", action="store_true", help="validar y escribir el nuevo esquema")
    args = parser.parse_args()

    scheme = _load_version_scheme()
    closing = scheme["open"]
    future = list(scheme["future"])
    if not future:
        print(f"ERROR: no hay versiones futuras planificadas para cerrar '{closing}'.", file=sys.stderr)
        return 1

    not_done = _check_version(closing)
    print(f"Version a cerrar: {closing} (abierta actual)")
    print(f"US asignadas a {closing} no-DONE: {len(not_done)}")
    for entry in not_done:
        print(f"  {entry}")

    if not_done:
        print(
            f"\nNo se puede cerrar {closing}: hay US no-DONE asignadas. "
            "Reasignalas a una version posterior o marcalas DONE antes de cerrar.",
            file=sys.stderr,
        )
        return 1

    new_open = future[0]
    new_future = _next_versions(new_open, 2)
    if args.check:
        print(f"\nEsquema resultante si se cierra {closing}:")
        print(f"  current_closed: {closing}")
        print(f"  open:           {new_open}")
        print(f"  future:         {new_future}")
        return 0

    scheme["current_closed"] = closing
    scheme["open"] = new_open
    scheme["future"] = new_future
    with open(VERSION_FILE, "w", encoding="utf-8") as fh:
        yaml.safe_dump(scheme, fh, allow_unicode=True, sort_keys=False, default_flow_style=False)
    print(f"\nVersion {closing} cerrada. Esquema actualizado en {VERSION_FILE}.")
    print(f"  current_closed: {closing}")
    print(f"  open:           {new_open}")
    print(f"  future:         {new_future}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
