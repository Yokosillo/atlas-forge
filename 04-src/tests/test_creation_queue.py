"""Tests de la cola persistente de peticiones de creación (T-AF036-US20-06,
US-AF036-20): `atlas_forge.dispatcher.creation_queue`.

Cubre los criterios de aceptación de la Task:
- `enqueue_creation_request` crea una entrada `pending` con `request_id` único.
- `pick_next_pending_creation_request` devuelve la más antigua `pending` (FIFO)
  y nunca una `in_flight`/`done`/`failed`.
- `mark_creation_in_flight` persiste el `report_file`; tras simular un reinicio,
  la entrada con report_file existente sigue `in_flight` y la que no tiene
  report_file vuelve a `pending` (reconciliación `reconcile_creation_requests`).
- `mark_creation_failed` guarda los motivos verbatim.

Deterministas, sin tmux, sobre `tmp_path` (misma ubicación de estado por
proyecto que la cola de despacho)."""
from __future__ import annotations

from pathlib import Path

import pytest

from atlas_forge.dispatcher.creation_queue import (
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_IN_FLIGHT,
    STATUS_PENDING,
    creation_requests_path,
    enqueue_creation_request,
    get_creation_requests,
    mark_creation_done,
    mark_creation_failed,
    mark_creation_in_flight,
    pick_next_pending_creation_request,
    reconcile_creation_requests,
)


def _requests(project_root: Path) -> list:
    return get_creation_requests(project_root, "proj")


def test_enqueue_creates_pending_entries_with_unique_ids(tmp_path: Path) -> None:
    """Criterio: `enqueue` crea una entrada `pending` con `request_id` único;
    el fichero JSON se crea en el estado del proyecto si no existía."""
    project = tmp_path / "rep"
    a = enqueue_creation_request(
        project, "proj", tipo="epic", description="Construir un pipeline nuevo",
        ts="2026-08-25T00:00:00+00:00",
    )
    b = enqueue_creation_request(
        project, "proj", tipo="us", description="Una historia",
        epic_id="AF-999", ts="2026-08-25T00:01:00+00:00",
    )

    assert a.request_id != b.request_id
    assert a.tipo == "epic" and a.status == STATUS_PENDING
    assert b.tipo == "us" and b.epic_id == "AF-999" and b.status == STATUS_PENDING
    # Persistido en el fichero del estado del proyecto.
    assert creation_requests_path(project, "proj").is_file()
    assert len(_requests(project)) == 2


def test_enqueue_rejects_unknown_tipo(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="tipo"):
        enqueue_creation_request(tmp_path, "proj", tipo="epica", description="d")


def test_pick_next_returns_oldest_pending_only(tmp_path: Path) -> None:
    """Criterio FIFO: `pick_next` devuelve la más antigua `pending`, nunca una
    `in_flight`/`done`/`failed`."""
    project = tmp_path / "rep"
    first = enqueue_creation_request(
        project, "proj", tipo="epic", description="Primera",
        ts="2026-08-25T00:00:00+00:00",
    )
    second = enqueue_creation_request(
        project, "proj", tipo="task", description="Segunda",
        us_id="US-AF999-01", ts="2026-08-25T00:01:00+00:00",
    )
    third = enqueue_creation_request(
        project, "proj", tipo="us", description="Tercera",
        ts="2026-08-25T00:02:00+00:00",
    )

    # FIFO: primero el más antiguo.
    assert pick_next_pending_creation_request(project, "proj").request_id == first.request_id
    # `pick` no muta el estado.
    assert pick_next_pending_creation_request(project, "proj").request_id == first.request_id

    # Marcar el primero in_flight y el segundo done: ya no son `pending`.
    mark_creation_in_flight(project, "proj", first.request_id, tmp_path / "r1.txt")
    mark_creation_done(project, "proj", second.request_id)
    assert pick_next_pending_creation_request(project, "proj").request_id == third.request_id

    # Marcar el tercero failed: sin pendientes, devuelve None.
    mark_creation_failed(project, "proj", third.request_id, ["la propuesta no valida"])
    assert pick_next_pending_creation_request(project, "proj") is None


def test_mark_in_flight_and_reconcile_after_restart(tmp_path: Path) -> None:
    """Criterio 3: `mark_in_flight` persiste el `report_file`. Tras simular un
    reinicio (`reconcile_creation_requests`):
    - la entrada con report_file EXISTENTE sigue `in_flight` (Job legítimo);
    - la entrada sin report_file (o cuyo fichero ya no existe) vuelve a `pending`."""
    project = tmp_path / "rep"
    live = enqueue_creation_request(
        project, "proj", tipo="epic", description="En vuelo",
        ts="2026-08-25T00:00:00+00:00",
    )
    orphan = enqueue_creation_request(
        project, "proj", tipo="us", description="Huérfana",
        ts="2026-08-25T00:01:00+00:00",
    )
    missing = enqueue_creation_request(
        project, "proj", tipo="task", description="Sin ruta",
        ts="2026-08-25T00:02:00+00:00",
    )

    # El report_file del Job en vuelo EXISTE en disco (el Arquitecto sigue
    # escribiendo su informe) → legítimo.
    live_report = tmp_path / "report-live.txt"
    live_report.write_text("escribiendo…", encoding="utf-8")
    mark_creation_in_flight(project, "proj", live.request_id, live_report)
    # report_file persiste pero el fichero YA NO existe (huérfana real).
    mark_creation_in_flight(project, "proj", orphan.request_id, tmp_path / "report-borrado.txt")
    # Sin report_file (nunca se registró la ruta).
    mark_creation_in_flight(project, "proj", missing.request_id, "no-importa")  # noqa

    # Forzar el caso "sin report_file persistido": scribe directo del field.
    from atlas_forge.dispatcher.creation_queue import _read_all
    entries = _read_all(creation_requests_path(project, "proj"))
    for e in entries:
        if e.request_id == missing.request_id:
            e.report_file = None
    from atlas_forge.dispatcher.creation_queue import _write_all
    _write_all(creation_requests_path(project, "proj"), entries)

    # Simular reinicio → reconciliar.
    reconciled = reconcile_creation_requests(project, "proj")

    assert "live" not in reconciled  # el legítimo NO se toca
    assert orphan.request_id in reconciled
    assert missing.request_id in reconciled

    by_id = {e.request_id: e for e in _requests(project)}
    assert by_id[live.request_id].status == STATUS_IN_FLIGHT
    assert by_id[orphan.request_id].status == STATUS_PENDING
    assert by_id[missing.request_id].status == STATUS_PENDING


def test_reconcile_registers_in_reconciliation_log(tmp_path: Path) -> None:
    """T-AF022-US18-03, criterio 3: cada petición reconciliada (in_flight sin
    report_file → pending) se registra en `reconciliation_log.jsonl` con su
    motivo."""
    from atlas_forge.core.reconciliation_log import reconciliation_log_path

    project = tmp_path / "rep"
    orphan = enqueue_creation_request(
        project, "proj", tipo="us", description="Huérfana",
        ts="2026-08-25T00:00:00+00:00",
    )
    mark_creation_in_flight(project, "proj", orphan.request_id, tmp_path / "report-borrado.txt")

    reconcile_creation_requests(project, "proj")

    log_text = reconciliation_log_path(project, "proj").read_text(encoding="utf-8")
    assert orphan.request_id in log_text
    assert "creation_request_reconciled" in log_text
    assert "in_flight" in log_text
    assert "report_file" in log_text
    assert "pending" in log_text


def test_mark_failed_guarda_motivos_verbatim(tmp_path: Path) -> None:
    """Criterio 4: `mark_failed` guarda los motivos verbatim."""
    project = tmp_path / "rep"
    req = enqueue_creation_request(
        project, "proj", tipo="task", description="Crear endpoint",
        ts="2026-08-25T00:00:00+00:00",
    )
    motivos = [
        "El identificador 'T-AF999-01' no tiene formato válido.",
        "La fase 'Fase 0.1' no pertenece al conjunto cerrado 0.9/0.9.1/0.9.2.",
    ]
    mark_creation_failed(project, "proj", req.request_id, motivos)

    entry = next(e for e in _requests(project) if e.request_id == req.request_id)
    assert entry.status == STATUS_FAILED
    assert entry.errors == motivos  # verbatim


def test_empty_queue_is_best_effort(tmp_path: Path) -> None:
    """Sin fichero: `pick`, `get_creation_requests` y `reconcile` no lanzan."""
    empty = tmp_path / "nada"
    assert pick_next_pending_creation_request(empty, "proj") is None
    assert get_creation_requests(empty, "proj") == []
    assert reconcile_creation_requests(empty, "proj") == []
