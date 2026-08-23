"""Watcher de `02-backlog/` (T-AF022-US13-09): detección de cambios fuera
del pipeline por polling simple de mtime (mismo patrón que
`atlas_forge/agents/models_catalog.py`) y consolidación in-process en ambos
sentidos cuando hay cambios.

El pipeline ya deja los estados consistentes cuando escribe; un cambio
manual (edición, herramienta externa, otro agente) puede dejarlos
desalineados. Como la consolidación es determinista e idempotente, no hace
falta distinguir el autor: tras un cambio del pipeline es un no-op, tras un
cambio manual corrige. El único coste a evitar es consolidar sin necesidad
en cada tick, por eso se escanean las marcas `(mtime_ns, size)` y solo se
consolida si cambió algo.

No crea hilo ni proceso propio: se invoca desde un ciclo de "mejor
esfuerzo" (el polling del Dispatcher) o manualmente.
"""

from __future__ import annotations

from pathlib import Path

from atlas_forge.backlog.promote import consolidate_states

_SUBDIRS = ("epics", "user-stories", "tasks")


def scan_backlog_marks(backlog_path: str | Path) -> dict[str, tuple[int, int]]:
    """Marcas `(st_mtime_ns, st_size)` de cada fichero `*.md` de
    `epics/`/`user-stories/`/`tasks/`. Coste: unos ms sobre ~400 ficheros."""
    marks: dict[str, tuple[int, int]] = {}
    root = Path(backlog_path)
    for subdir in _SUBDIRS:
        directory = root / subdir
        if not directory.is_dir():
            continue
        for path in directory.glob("*.md"):
            try:
                st = path.stat()
                marks[str(path)] = (st.st_mtime_ns, st.st_size)
            except OSError:
                continue
    return marks


def consolidate_if_changed(
    backlog_path: str | Path, previous_marks: dict[str, tuple[int, int]] | None
) -> tuple[dict[str, tuple[int, int]], bool, list]:
    """Consolida `backlog_path` en ambos sentidos SOLO si sus marcas de
    mtime/size cambiaron respecto a `previous_marks`.

    Devuelve `(nuevas_marks, changed, applied)`:
    - `nuevas_marks`: las marcas del tick actual (para el siguiente tick).
    - `changed`: `True` si hubo algún cambio de marcas.
    - `applied`: la lista de `(id, path, new_state, kind)` aplicada por la
      consolidación (`[]` si no hubo cambios o no hizo falta consolidar).

    `previous_marks=None` (primer tick) siempre consolida (no hay línea
    base). Es idempotente: si el disco ya estaba consistente, `applied`
    queda vacío aunque `changed` sea `True`."""
    current = scan_backlog_marks(backlog_path)
    if previous_marks is not None and current == previous_marks:
        return current, False, []
    applied = consolidate_states(backlog_path)
    # Re-escanea TRAS consolidar: el siguiente tick compara contra el estado
    # post-consolidación, de modo que un tick sin cambios reales es no-op
    # (sin esto, la propia escritura de la consolidación marcaría "cambió").
    return scan_backlog_marks(backlog_path), True, applied
