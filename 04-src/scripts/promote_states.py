#!/usr/bin/env python3
"""CLI fina sobre `atlas_forge.backlog.promote` para consolidar el estado del
backlog en ambos sentidos (T-AF022-US13-09).

El estado de una User Story es SIEMPRE la derivacion determinista de sus
Tasks: `NO_TASKS` si no tiene ninguna, si no el estado de su Task menos
avanzada; una Epic es `DONE` si todas sus US estan `DONE`, si no `TO_DO`.
Esta regla (la unica fuente de verdad de trazabilidad) vive en
`atlas_forge/backlog/promote.py` (`consolidate_states`/`check_consolidation`).

La consolidacion es BIDIRECCIONAL e idempotente: en una sola pasada
promueve, reabre y fija `NO_TASKS`/el estado mas retrasado. (Antes de
T-AF022-US13-09 el `--apply` solo promovia hacia delante y nunca
revertia; eso deja de ser cierto.)

Uso:
  python3 scripts/promote_states.py --check   # reporta drift; exit != 0 si existe, sin tocar nada
  python3 scripts/promote_states.py --apply   # consolida los estados derivados en disco
"""
from __future__ import annotations

import argparse
import os
import sys

from atlas_forge.backlog.promote import check_consolidation, consolidate_states

BACKLOG = os.path.join(os.path.dirname(__file__), "..", "..", "02-backlog")

_KIND_LABEL = {"user_story": "US", "epic": "Epic"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--check", action="store_true", help="reportar drift; exit != 0 si existe"
    )
    group.add_argument("--apply", action="store_true", help="escribir los estados derivados")
    args = parser.parse_args()

    if args.check:
        drift = check_consolidation(BACKLOG)
        print(f"Drift de derivacion: {len(drift)} item(s) desalineado(s).")
        for item_id, _path, new_state, kind in drift:
            print(f"  {_KIND_LABEL.get(kind, kind)} {item_id}  (-> {new_state})")
        if drift:
            print("\nDrift detectado: ejecuta --apply para consolidar.")
            return 1
        print("\nSin drift: todo consistente.")
        return 0

    applied = consolidate_states(BACKLOG)
    print(f"Consolidadas {len(applied)} transiciones de estado derivado.")
    for item_id, _path, new_state, kind in applied:
        print(f"  {_KIND_LABEL.get(kind, kind)} {item_id}  (-> {new_state})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
