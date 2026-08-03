"""Comando `brain backlog-status <backlog_path>` (T-FB018-US02-02,
US-FB018-02 · "Estado del backlog: conteo, dependencias y siguiente foco,
sin gastar tokens de agente cognitivo").

Invoca `build_backlog_report` (que reusa `load_backlog`/
`classify_todo_items`/`find_max_leverage_chain` de T-FB018-US02-01) y
muestra la salida legible o, con `--json`, el mismo informe como dict
estructurado. Sin duplicar lógica de invocación: esta es la misma función
de cálculo que usa la entrada `backlog_status` del catálogo de scripts
genéricos.

El comando nunca falla por un backlog vacío o recién creado: `build_backlog_report`
devuelve `empty=True` y el texto legible reporta "sin datos" (criterio 3 de
la Task)."""

from __future__ import annotations

import argparse

from brain.backlog import build_backlog_report, format_human_report, render_json_report


def run_backlog_status(argv: list[str] | None = None) -> int:
    """Renderiza el informe del backlog y lo imprime por stdout.

    Devuelve el código de salida (0 siempre en condiciones normales: un
    backlog vacío/recién creado también es una salida válida, "sin datos")."""
    parser = argparse.ArgumentParser(
        prog="brain backlog-status",
        description="Estado del backlog: conteo, dependencias y siguiente foco.",
    )
    parser.add_argument(
        "backlog_path",
        help="directorio `02-backlog/` del proyecto a inspeccionar",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="salida estructurada JSON en lugar del texto legible",
    )
    args = parser.parse_args(argv)

    report = build_backlog_report(args.backlog_path)
    if args.json:
        print(render_json_report(report))
    else:
        print(format_human_report(report))
    return 0
