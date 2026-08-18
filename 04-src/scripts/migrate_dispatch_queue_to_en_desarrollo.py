#!/usr/bin/env python3
"""CLI fina sobre `brain.dispatcher.dispatch_queue.migrate_queued_entries_to_state`
(T-FB008-US14-01, criterio de aceptación de migración).

Antes de esta Task, "lista para desarrollo" solo vivía en
`dispatch_queue.json` (entradas `status: "queued"`) — el `state` real del
fichero de la Task seguía en `TODO`. Este script pone al día esos
ficheros a `state: EN_DESARROLLO`, sin tocar el propio JSON (sigue existiendo
como registro auxiliar de orden/auditoría).

Uso:
  python3 scripts/migrate_dispatch_queue_to_en_desarrollo.py --project-root . --project-name <nombre>
"""
from __future__ import annotations

import argparse
import os

from brain.dispatcher.dispatch_queue import migrate_queued_entries_to_state

_DEFAULT_PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root", default=_DEFAULT_PROJECT_ROOT,
        help="Raíz del repositorio del proyecto (por defecto, la raíz de este mismo repo).",
    )
    parser.add_argument(
        "--project-name", required=True,
        help="Nombre del proyecto (mismo criterio de saneo que dispatch_queue_path).",
    )
    args = parser.parse_args()

    backlog_dir = os.path.join(args.project_root, "02-backlog")
    migrated = migrate_queued_entries_to_state(
        args.project_root, args.project_name, backlog_dir
    )

    if not migrated:
        print("Nada que migrar: sin entradas 'queued' en dispatch_queue.json con state todavía en TODO.")
        return 0

    print(f"Migradas {len(migrated)} Task(s) a state: EN_DESARROLLO:")
    for task_id in migrated:
        print(f"  {task_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
