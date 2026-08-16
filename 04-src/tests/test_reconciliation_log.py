"""Tests de T-FB037-US02-01: log persistente del resultado de
`reconcile_session_agents` (`brain.core.reconciliation_log`) — mismo
patrón que `test_architect_queue.py` (misma ubicación `.claude/state/`,
mismo JSONL append-only)."""

import json
from pathlib import Path

from brain.core.reconciliation_log import (
    append_reconciliation_log,
    reconciliation_log_path,
)


def test_append_creates_the_file_and_directory_if_they_do_not_exist(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "some-project"

    path = append_reconciliation_log(
        project_root,
        "some-project",
        total_sessions=2,
        recognized=2,
        reconciled=["Developer-1"],
        ignored=[],
    )

    assert path.is_file()
    assert path == project_root / ".claude" / "state" / "some-project" / "reconciliation_log.jsonl"


def test_each_line_is_a_standalone_valid_json_object_not_a_single_array(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "proj"

    append_reconciliation_log(
        project_root, "proj", total_sessions=1, recognized=1,
        reconciled=["Developer-1"], ignored=[], ts="2026-08-16T10:00:00+00:00",
    )
    append_reconciliation_log(
        project_root, "proj", total_sessions=3, recognized=1,
        reconciled=[], ignored=[
            {"session_name": "una-sesion-ajena", "reason": "nombre_no_reconocido"},
            {"session_name": "developer-1-proj", "reason": "ya_reconciliada"},
        ],
        ts="2026-08-16T10:05:00+00:00",
    )

    path = reconciliation_log_path(project_root, "proj")
    lines = path.read_text(encoding="utf-8").splitlines()

    assert len(lines) == 2
    for line in lines:
        # Cada linea es un objeto JSON completo por si misma (JSONL) — un
        # unico array englobando todo el fichero fallaria aqui.
        parsed = json.loads(line)
        assert isinstance(parsed, dict)

    first = json.loads(lines[0])
    assert first == {
        "ts": "2026-08-16T10:00:00+00:00",
        "total_sessions": 1,
        "recognized": 1,
        "reconciled_count": 1,
        "reconciled": ["Developer-1"],
        "ignored_count": 0,
        "ignored": [],
    }

    second = json.loads(lines[1])
    assert second["total_sessions"] == 3
    assert second["recognized"] == 1
    assert second["reconciled_count"] == 0
    assert second["ignored_count"] == 2
    # Criterio de aceptación 2 de US-FB037-02: distingue explícitamente
    # ignoradas de reenganchadas, con motivo — cada entrada de `ignored`
    # trae su propio `reason`, no un conteo agregado sin detalle.
    reasons = {entry["reason"] for entry in second["ignored"]}
    assert reasons == {"nombre_no_reconocido", "ya_reconciliada"}


def test_sanitizes_project_name_for_the_directory_same_as_architect_queue(
    tmp_path: Path,
) -> None:
    """Mismo criterio de saneo que `architect_queue_path` — un nombre de
    proyecto con espacios/mayúsculas produce el mismo directorio que
    `sanitize_session_name_part` calcularía para la sesión tmux del
    Arquitecto de ese proyecto, para que ambos logs vivan juntos."""
    from brain.dispatcher.architect_queue import architect_queue_path

    project_root = tmp_path / "Mi Proyecto Real"

    reconciliation_path = reconciliation_log_path(project_root, "Mi Proyecto Real")
    queue_path = architect_queue_path(project_root, "Mi Proyecto Real")

    assert reconciliation_path.parent == queue_path.parent


def test_append_is_safe_under_concurrent_writes(tmp_path: Path) -> None:
    """Mismo criterio de concurrencia que `architect_queue` — múltiples
    hilos escribiendo a la vez nunca producen una línea JSON mezclada."""
    import threading

    project_root = tmp_path / "proj-concurrente"
    errors = []

    def _write(i: int) -> None:
        try:
            append_reconciliation_log(
                project_root, "proj-concurrente", total_sessions=1, recognized=1,
                reconciled=[f"Developer-{i}"], ignored=[],
            )
        except Exception as error:  # pragma: no cover - solo si algo va mal
            errors.append(error)

    threads = [threading.Thread(target=_write, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    path = reconciliation_log_path(project_root, "proj-concurrente")
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 20
    for line in lines:
        parsed = json.loads(line)
        assert isinstance(parsed, dict)
