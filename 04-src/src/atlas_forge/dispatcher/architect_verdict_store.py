"""Persistencia de la cola de veredictos del Arquitecto (T-AF022-US07-03).

El ciclo de veredicto de User Story (`run_architect_verdict_dispatch_cycle`
y `poll_inflight_architect_verdict_completions` en
`dispatch_queue_worker.py`) mantiene su estado en RAM del proceso
`atlas-forge-api`: qué User Stories están `IN_REVIEW` esperando veredicto y
cuál está "en vuelo" (el único veredicto en curso, porque el Arquitecto
nunca procesa más de uno a la vez). Ese estado intermedio se perdía ante un
reinicio del proceso.

Este módulo persiste ese estado en un fichero JSON dentro del `state_dir`
del proyecto, con el MISMO patrón de ruta que `architect_queue.py`
(`<project_root>/.claude/state/<project_name>/architect_verdict_queue.json`),
y proporciona la reconciliación contra el backlog real al arrancar
`atlas-forge-api`.

Formato persistido:

    {
      "pending":  ["US-AF022-10", "US-AF022-11"],   # orden FIFO de espera
      "inflight": "US-AF022-10" | null              # veredicto en curso
    }

## Reconciliación al arranque

Un veredicto "en vuelo" persistido de un proceso anterior NO puede
reanudarse tal cual: su Job y su fichero de reporte viven en RAM de ese
proceso ya muerto. Por eso, al restaurar, la US en vuelo que sigue `IN_REVIEW`
se devuelve al FRENTE de `pending`, para que el ciclo de despacho la vuelva
a revisar (criterio de aceptación 2: la US nunca queda bloqueada ni en un
estado incoherente). Las US ya `DONE` o que dejaron de estar `IN_REVIEW` se
descartan; las `IN_REVIEW` del backlog que faltaban en `pending` se añaden
en orden de id (criterio de aceptación 1: ninguna se pierde ante el
reinicio).

## Consumo

`DispatchQueueWorker.start()` llama a `reconcile_architect_verdict_queue` al
arrancar (restaurando y persistiendo el estado ya reconciliado), y el worker
re-persiste el estado en cada ciclo de polling tras despachar o completar un
veredicto (`_persist_verdict_state`), de modo que el fichero siempre refleja
el estado corriente de la cola.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from atlas_forge.dispatcher.architect_queue import _sanitize_project_dirname

_QUEUE_FILENAME = "architect_verdict_queue.json"

# Serializa las escrituras de este proceso para no intercalar bytes entre dos
# `json.dumps` concurrentes; la escritura es atómica (tmp + replace), así que
# dos procesos distintos no se pisan entre sí.
_write_lock = threading.Lock()


def architect_verdict_queue_path(
    project_root: Path | str, project_name: str
) -> Path:
    """Ruta del fichero persistente de la cola de veredictos de
    `project_name`, dentro de `<project_root>/.claude/state/<project_name>/`.

    `project_root` es la raíz del repositorio del proyecto (`Project.path`) —
    la cola vive DENTRO del propio proyecto gestionado, nunca en un directorio
    compartido entre proyectos (mismo criterio que `architect_queue_path`)."""
    dirname = _sanitize_project_dirname(project_name)
    return Path(project_root) / ".claude" / "state" / dirname / _QUEUE_FILENAME


def load_architect_verdict_queue(
    project_root: Path | str, project_name: str
) -> dict:
    """Lee el estado persistido de la cola de veredictos.

    Devuelve `{"pending": [...], "inflight": None}` (cola vacía) si el
    fichero no existe o es ilegible — una cola nunca escrita es un caso
    normal, no un error, y un fichero corrupto no debe impedir el arranque
    (se reconcilia desde el backlog, la fuente de verdad de las US
    `IN_REVIEW`)."""
    path = architect_verdict_queue_path(project_root, project_name)
    if not path.is_file():
        return {"pending": [], "inflight": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, ValueError):
        return {"pending": [], "inflight": None}

    pending = [s for s in data.get("pending", []) if isinstance(s, str)]
    inflight = data.get("inflight")
    if not isinstance(inflight, str) or not inflight:
        inflight = None
    return {"pending": pending, "inflight": inflight}


def save_architect_verdict_queue(
    project_root: Path | str,
    project_name: str,
    *,
    pending: list[str],
    inflight: str | None,
) -> Path:
    """Persiste el estado de la cola de veredictos a disco de forma atómica.

    Crea el directorio y el fichero si no existen. La escritura pasa por un
    fichero temporal (`*.tmp`) que luego se renombra (`replace`) sobre el
    definitivo, de modo que un lector concurrente nunca vea un JSON a medias.

    Devuelve la ruta del fichero escrito."""
    path = architect_verdict_queue_path(project_root, project_name)
    data = {"pending": list(pending), "inflight": inflight}
    body = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    with _write_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(body, encoding="utf-8")
        tmp.replace(path)
    return path


def reconcile_architect_verdict_queue(
    project_root: Path | str, project_name: str, backlog_dir: Path | str
) -> dict:
    """Restaura la cola persistida y la reconcilia con el backlog real.

    Es la operación que se invoca al arrancar `atlas-forge-api`: lee el
    estado de disco, lo cruza con las User Stories `IN_REVIEW` del backlog y
    devuelve un estado coherente que persiste de nuevo. Reglas:

    - Una US `IN_REVIEW` del backlog que no estaba en `pending` se añade (en
      orden de id) — criterio de aceptación 1: ninguna se pierde.
    - Una US en `pending` que ya no está `IN_REVIEW` (p. ej. ya `DONE`) se
      descarta.
    - La US "en vuelo" persistida que sigue `IN_REVIEW` se devuelve al frente
      de `pending` y deja de estar en vuelo (el Job no puede reanudarse tras
      un reinicio; la US vuelve a quedar pendiente de revisión) — criterio de
      aceptación 2.
    - El Arquitecto nunca tiene más de un veredicto en curso: el estado
      restaurado tiene como mucho una US en vuelo (ninguna tras el reinicio,
      porque la en vuelo pasa a pending)."""

    stored = load_architect_verdict_queue(project_root, project_name)

    from atlas_forge.backlog.parser import load_backlog

    graph = load_backlog(Path(backlog_dir))
    in_review = sorted(
        item.id
        for item in graph.items.values()
        if item.kind == "US" and item.state == "IN_REVIEW"
    )
    in_review_set = set(in_review)

    # pending: conserva el orden FIFO persistido para las que siguen vigentes.
    pending = [s for s in stored["pending"] if s in in_review_set]

    # Un veredicto en vuelo de un proceso anterior no puede reanudarse (su
    # Job/report viven en RAM): si la US sigue IN_REVIEW, vuelve a quedar
    # pendiente de revisión para que el ciclo la re-despache.
    inflight = stored["inflight"]
    if inflight is not None and inflight in in_review_set:
        pending = [inflight] + [s for s in pending if s != inflight]
    inflight = None

    # Cualquier US IN_REVIEW del backlog que no estuviera ya cubierta se
    # añade en orden de id (puede haberse promovido mientras el proceso
    # estaba caído).
    pending_set = set(pending)
    for sid in in_review:
        if sid not in pending_set:
            pending.append(sid)

    state = {"pending": pending, "inflight": inflight}
    save_architect_verdict_queue(
        project_root, project_name, pending=pending, inflight=inflight
    )
    return state