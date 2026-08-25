"""Cola persistente de peticiones de creación de Epic/US/Task desde
descripción en lenguaje natural (T-AF036-US20-06, US-AF036-20).

El mecanismo que hace que una petición ("el humano describe; el Arquitecto
estructura") quede `pending` hasta que el Arquitecto esté libre para
procesarla — "despachada cuando corresponda" — con recuperación tras
reinicio. Mismo patrón que `dispatch_queue.py`:

- Fichero JSON mutable por proyecto en
  `<project_root>/.claude/state/<proyecto>/creation_requests.json`.
- Api de dominio: `enqueue_creation_request`, `pick_next_pending_creation_request`
  (FIFO por `created_at`), `mark_creation_in_flight`, `mark_creation_done`,
  `mark_creation_failed`, `get_creation_requests` y la reconciliación de
  arranque `reconcile_creation_requests` (mismo patrón que
  `reconcile_dispatch_queue_entries`).
- Idempotente y de mejor esfuerzo: no lanza si el fichero no existe (se
  crea al primer `enqueue`); escritura completa del fichero bajo un
  `threading.Lock`, mismo criterio que la cola de despacho.

Estados de cada entrada: `pending` → `in_flight` → `done` | `failed`.
Una entrada `in_flight` persiste su `report_file` (ruta del Job en vuelo,
T-AF008-US10-05): al reiniciar, si el fichero sigue existiendo el Job está
legítimamente en vuelo (no se toca); si no existe (o nunca se registró)
vuelve a `pending`.
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from atlas_forge.runtime.generic import sanitize_session_name_part

_QUEUE_FILENAME = "creation_requests.json"

STATUS_PENDING = "pending"
STATUS_IN_FLIGHT = "in_flight"
STATUS_DONE = "done"
STATUS_FAILED = "failed"

_VALID_TYPES = {"epic", "us", "task"}

_write_lock = threading.Lock()


@dataclass
class CreationRequest:
    """Una petición de creación de Epic/US/Task (US-AF036-20).

    `request_id` es único (UUID hex). `tipo` ∈ {epic, us, task};
    `epic_id`/`us_id` son el contexto padre (opcional). `description` es la
    descripción libre del usuario. `status` ∈ {pending, in_flight, done,
    failed}. `report_file` persiste la ruta del Job en vuelo del Arquitecto
    (T-AF008-US10-05) para recuperar huérfanas tras reinicio. `result`/
    `errors` guardan los motivos verbatim del cierre. `created_at`/
    `dispatched_at` marcan encolado y despacho."""

    request_id: str
    tipo: str
    description: str
    status: str
    created_at: str
    epic_id: str | None = None
    us_id: str | None = None
    report_file: str | None = None
    dispatched_at: str | None = None
    result: str | None = None
    errors: list[str] = field(default_factory=list)


def creation_requests_path(project_root: Path | str, project_name: str) -> Path:
    """Ruta del fichero de cola de peticiones de creación de `project_name`,
    dentro de `<project_root>/.claude/state/<project_name>/creation_requests.json`
    — misma raíz de estado por proyecto que `dispatch_queue_path`, misma
    sanitización del nombre."""
    dirname = sanitize_session_name_part(project_name)
    return Path(project_root) / ".claude" / "state" / dirname / _QUEUE_FILENAME


def _read_all(path: Path) -> list[CreationRequest]:
    if not path.is_file():
        return []
    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        return []
    data = json.loads(raw)
    return [CreationRequest(**entry) for entry in data]


def _write_all(path: Path, entries: list[CreationRequest]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps([asdict(entry) for entry in entries], ensure_ascii=False, indent=2)
    path.write_text(payload, encoding="utf-8")


def enqueue_creation_request(
    project_root: Path | str,
    project_name: str,
    *,
    tipo: str,
    description: str,
    epic_id: str | None = None,
    us_id: str | None = None,
    request_id: str | None = None,
    ts: str | None = None,
) -> CreationRequest:
    """Añade una petición de creación `pending` a la cola (US-AF036-20,
    criterio 4). `tipo` ∈ {epic, us, task}; `epic_id`/`us_id` son el contexto
    padre opcional. Devuelve la entrada creada con su `request_id` único
    (UUID hex si no se pasa). Mejor esfuerzo: crea el fichero si no existe."""
    if tipo not in _VALID_TYPES:
        raise ValueError(
            f"tipo de petición de creación inválido '{tipo}' — debe ser "
            f"uno de: {', '.join(sorted(_VALID_TYPES))}."
        )
    path = creation_requests_path(project_root, project_name)
    entry = CreationRequest(
        request_id=request_id or uuid.uuid4().hex,
        tipo=tipo,
        description=description,
        status=STATUS_PENDING,
        created_at=ts if ts is not None else datetime.now(timezone.utc).isoformat(),
        epic_id=epic_id,
        us_id=us_id,
    )
    with _write_lock:
        entries = _read_all(path)
        entries.append(entry)
        _write_all(path, entries)
    return entry


def _pick_next_pending(entries: list[CreationRequest]) -> CreationRequest | None:
    pending = [e for e in entries if e.status == STATUS_PENDING]
    if not pending:
        return None
    # FIFO por `created_at`; desempate determinista por `request_id`.
    return sorted(pending, key=lambda e: (e.created_at, e.request_id))[0]


def pick_next_pending_creation_request(
    project_root: Path | str, project_name: str
) -> CreationRequest | None:
    """Devuelve la petición `pending` más antigua (FIFO por `created_at`)
    sin cambiar su estado — nunca una `in_flight`/`done`/`failed`. `None` si
    no hay ninguna pendiente. Solo lectura (no muta el fichero)."""
    path = creation_requests_path(project_root, project_name)
    with _write_lock:
        entries = _read_all(path)
        picked = _pick_next_pending(entries)
    return picked


def mark_creation_in_flight(
    project_root: Path | str,
    project_name: str,
    request_id: str,
    report_file: Path | str,
    *,
    ts: str | None = None,
) -> None:
    """Transiciona la petición `request_id` de `pending` a `in_flight` y
    persiste la ruta del `report_file` del Job en vuelo del Arquitecto
    (T-AF008-US10-05). Mejor esfuerzo: no lanza si `request_id` no existe."""
    path = creation_requests_path(project_root, project_name)
    with _write_lock:
        entries = _read_all(path)
        for entry in entries:
            if entry.request_id == request_id and entry.status == STATUS_PENDING:
                entry.status = STATUS_IN_FLIGHT
                entry.report_file = str(report_file)
                entry.dispatched_at = ts if ts is not None else datetime.now(timezone.utc).isoformat()
        _write_all(path, entries)


def mark_creation_done(
    project_root: Path | str,
    project_name: str,
    request_id: str,
    result: str | None = None,
) -> None:
    """Transiciona la petición `request_id` a `done` (el Arquitecto escribió
    la entidad y pasó la validación). Mejor esfuerzo."""
    path = creation_requests_path(project_root, project_name)
    with _write_lock:
        entries = _read_all(path)
        for entry in entries:
            if entry.request_id == request_id:
                entry.status = STATUS_DONE
                entry.result = result
        _write_all(path, entries)


def mark_creation_pending(
    project_root: Path | str,
    project_name: str,
    request_id: str,
) -> None:
    """T-AF036-US20-08: devuelve la petición `request_id` a `pending` tras un
    timeout de su Job (se reintenta sola en el siguiente ciclo de despacho —
    el humano no tiene que re-encolarla). Limpia la ruta del reporte del Job
    perdido. Mejor esfuerzo."""
    path = creation_requests_path(project_root, project_name)
    with _write_lock:
        entries = _read_all(path)
        for entry in entries:
            if entry.request_id == request_id and entry.status == STATUS_IN_FLIGHT:
                entry.status = STATUS_PENDING
                entry.report_file = None
                entry.dispatched_at = None
        _write_all(path, entries)


def mark_creation_failed(
    project_root: Path | str,
    project_name: str,
    request_id: str,
    errors: list[str],
) -> None:
    """Transiciona la petición `request_id` a `failed` guardando los motivos
    verbatim (la propuesta del Arquitecto no superó la validación/autoauditoría
    o el Job falló). Mejor esfuerzo."""
    path = creation_requests_path(project_root, project_name)
    with _write_lock:
        entries = _read_all(path)
        for entry in entries:
            if entry.request_id == request_id:
                entry.status = STATUS_FAILED
                entry.errors = list(errors)
        _write_all(path, entries)


def get_creation_requests(
    project_root: Path | str, project_name: str
) -> list[CreationRequest]:
    """Todas las peticiones de creación (cualquier estado), en el orden en
    que se añadieron — para el endpoint web de la cola. Solo lectura; no
    lanza si el fichero no existe (devuelve `[]`)."""
    path = creation_requests_path(project_root, project_name)
    with _write_lock:
        return _read_all(path)


def reconcile_creation_requests(
    project_root: Path | str,
    project_name: str,
) -> list[str]:
    """T-AF036-US20-06 + T-AF022-US18-03 (criterios 1/2, mismo patrón que
    `reconcile_dispatch_queue_entries`): al arrancar (o en el ciclo periódico
    del worker), una entrada `in_flight` cuyo `report_file` ya no existe (o
    nunca se registró) es una huérfana real — el Job del Arquitecto se perdió
    con el reinicio/timeout/agente caído — y vuelve a `pending` (re-encolable
    en el siguiente ciclo de `run_creation_dispatch_cycle`). Si el
    `report_file` todavía existe, el Job sigue legítimamente en vuelo y NO se
    toca.

    Cada petición reconciliada se registra en `reconciliation_log.jsonl`
    (motivo `creation_request_reconciled`, petición, estado previo → nuevo,
    timestamp) — T-AF022-US18-03.

    Devuelve la lista de `request_id` reconciliados. Mejor esfuerzo: devuelve
    `[]` sin lanzar si no hay cola."""
    from atlas_forge.core.reconciliation_log import (
        append_creation_request_reconciliation,
    )

    path = creation_requests_path(project_root, project_name)
    reconciled: list[str] = []
    with _write_lock:
        entries = _read_all(path)
        changed = False
        for entry in entries:
            if entry.status != STATUS_IN_FLIGHT:
                continue
            if not entry.report_file:
                entry.status = STATUS_PENDING
                changed = True
                reconciled.append(entry.request_id)
                append_creation_request_reconciliation(
                    project_root, project_name,
                    request_id=entry.request_id,
                    previous_status=STATUS_IN_FLIGHT,
                    reason="sin report_file persistido",
                )
                continue
            if not Path(entry.report_file).is_file():
                entry.status = STATUS_PENDING
                changed = True
                reconciled.append(entry.request_id)
                append_creation_request_reconciliation(
                    project_root, project_name,
                    request_id=entry.request_id,
                    previous_status=STATUS_IN_FLIGHT,
                    reason="report_file ya no existe (Job perdido)",
                )
        if changed:
            _write_all(path, entries)
    return reconciled
