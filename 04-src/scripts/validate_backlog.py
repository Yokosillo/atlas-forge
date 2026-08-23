#!/usr/bin/env python3
"""CLI de validacion de formato de backlog contra `validate_backlog_file_v2`
(YAML frontmatter, AF-027) — dos modos:

## Modo staged (por defecto, T-AF022-US13-06)

Valida solo los ficheros de `02-backlog/{epics,user-stories,tasks}/*.md`
que estan STAGED en el commit actual (`git diff --cached --name-only`) —
no repasa el backlog completo en cada commit. Pensado para el pre-commit
hook (`install_git_hooks.sh`), como control tecnico independiente de
`promote_states.py --check` (reconciliacion de estado): uno valida
FORMATO, el otro valida COHERENCIA de estado entre padres e hijos —
ambos deben pasar, ninguno exime al otro.

Uso:
    python3 04-src/scripts/validate_backlog.py

## Modo lote (--batch, T-AF022-US13-07)

Valida TODOS los `.md` de un directorio arbitrario (no necesariamente
`02-backlog/` de un proyecto, ni dentro de un repositorio git) — pensado
para revisar de antemano un lote de migracion (backlog externo ya
convertido al esquema de Atlas Forge) antes de moverlo al repositorio
real. Reporte agregado legible (total / validos / invalidos con su error
exacto). Nunca escribe ni mueve nada — solo lectura y reporte.

Uso:
    python3 04-src/scripts/validate_backlog.py --batch /ruta/al/lote

Ambos modos reutilizan exactamente `validate_backlog_file_v2` (mismo
validador que usa el Arquitecto al generar backlog) — ninguna logica de
validacion propia duplicada aqui.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from atlas_forge.backlog.validator_v2 import ValidationResultV2, validate_backlog_file_v2

REPO_ROOT = Path(__file__).resolve().parents[2]

_BACKLOG_SUBDIRS = ("epics", "user-stories", "tasks")


def _staged_backlog_files() -> list[Path]:
    """Ficheros `.md` de `02-backlog/{epics,user-stories,tasks}/` staged
    en el commit actual (criterio 3 de T-AF022-US13-06: no repasar los
    ~400 ficheros existentes en cada commit sin necesidad)."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    staged = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line.endswith(".md"):
            continue
        parts = Path(line).parts
        if len(parts) >= 3 and parts[0] == "02-backlog" and parts[1] in _BACKLOG_SUBDIRS:
            staged.append(REPO_ROOT / line)
    return staged


def _report_results(results: list[tuple[Path, ValidationResultV2]]) -> bool:
    """Imprime el reporte agregado y devuelve True si todo es valido."""
    total = len(results)
    invalid = [(path, result) for path, result in results if not result.valid]
    valid_count = total - len(invalid)

    print(f"Ficheros revisados: {total}")
    print(f"Validos: {valid_count}")
    print(f"Invalidos: {len(invalid)}")

    if invalid:
        print("\nDetalle de ficheros invalidos:")
        for path, result in invalid:
            print(f"\n  {path}")
            for error in result.errors:
                print(f"    linea {error.line}: {error.message}")

    return len(invalid) == 0


def _run_staged() -> int:
    staged = _staged_backlog_files()
    if not staged:
        print("Sin ficheros de 02-backlog/ staged en este commit — nada que validar.")
        return 0

    results = [(path, validate_backlog_file_v2(path)) for path in staged]
    ok = _report_results(results)
    return 0 if ok else 1


def _run_batch(directory: Path) -> int:
    if not directory.is_dir():
        print(f"ERROR: '{directory}' no es un directorio.", file=sys.stderr)
        return 2

    files = sorted(directory.rglob("*.md"))
    if not files:
        print(f"Sin ficheros .md en '{directory}' — nada que validar.")
        return 0

    results = []
    for path in files:
        result = validate_backlog_file_v2(path)
        results.append((path, result))

    print(f"Lote de migración: {directory}")
    ok = _report_results(results)
    if ok:
        print("\nTodos los ficheros del lote cumplen el esquema de 02-backlog/README.md.")
    else:
        print(
            "\nCorrige los ficheros inválidos antes de mover el lote al repositorio real."
        )
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--batch",
        metavar="DIRECTORIO",
        type=Path,
        default=None,
        help="valida todos los .md de este directorio (modo lote, T-AF022-US13-07) "
             "en vez del modo staged por defecto (T-AF022-US13-06)",
    )
    args = parser.parse_args()

    if args.batch is not None:
        return _run_batch(args.batch)
    return _run_staged()


if __name__ == "__main__":
    sys.exit(main())
