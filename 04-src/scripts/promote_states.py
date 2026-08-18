#!/usr/bin/env python3
"""CLI fina sobre `brain.backlog.promote` para promover el estado del backlog.

Regla determinista (la unica fuente de verdad de trazabilidad), implementada
en `brain/backlog/promote.py`:

  1. Una User Story -> DONE  si tiene al menos una Task y TODAS sus Tasks estan DONE.
  2. Una Epic        -> DONE  si tiene al menos una User Story y TODAS sus US estan DONE.

Solo PROMUEVE (TO_DO/IN_PROGRESS/REVIEW -> DONE; para Epic, TODO). Nunca revierte. Idempotente.

Uso:
  python3 scripts/promote_states.py --check   # falla (exit != 0) si hay drift, sin tocar nada
  python3 scripts/promote_states.py --apply   # escribe los cambios de estado
"""
from __future__ import annotations

import argparse
import os
import sys

from brain.backlog.promote import (
    check_backlog_promotion,
    detect_reopened_drift,
    promote_backlog,
)

BACKLOG = os.path.join(os.path.dirname(__file__), "..", "..", "02-backlog")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--check", action="store_true", help="reportar drift; exit != 0 si existe"
    )
    group.add_argument("--apply", action="store_true", help="escribir cambios")
    args = parser.parse_args()

    if args.check:
        result = check_backlog_promotion(BACKLOG)
        print(f"US a promover -> DONE: {len(result.promoted_user_stories)}")
        for us_id in result.promoted_user_stories:
            print(f"  {us_id}  (-> DONE)")
        print(f"\nEpics a promover -> DONE: {len(result.promoted_epics)}")
        for epic_id in result.promoted_epics:
            print(f"  {epic_id}  (-> DONE)")

        # T-FB022-US13-04: caso inverso — padre DONE con un hijo reabierto.
        # Solo se detecta y reporta, nunca se corrige por --apply.
        reopened = detect_reopened_drift(BACKLOG)
        print(f"\nPadres DONE con hijo reabierto: {len(reopened.items)}")
        for item in reopened.items:
            children = ", ".join(f"{cid} ({cstate})" for cid, cstate in item.reopened_children)
            print(f"  {item.parent_id} (DONE) con hijo(s) reabierto(s): {children}")

        if result.has_drift or reopened.has_drift:
            if result.has_drift:
                print("\nDrift detectado: hay US/Epics con todos sus hijos DONE pero el padre no.")
            if reopened.has_drift:
                print(
                    "\nDrift inverso detectado: hay US/Epics DONE con un hijo reabierto "
                    "(TO_DO/IN_PROGRESS/REVIEW) — revisar manualmente si el padre debe "
                    "reabrirse; este chequeo no lo hace automáticamente."
                )
            return 1
        print("\nSin drift: todo consistente.")
        return 0

    result = promote_backlog(BACKLOG)
    print(
        f"Promovidas {len(result.promoted_user_stories)} US y "
        f"{len(result.promoted_epics)} Epics a DONE."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
