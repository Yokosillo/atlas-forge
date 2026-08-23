"""T-AF022-US13-09: estado de User Story derivado de sus Tasks (NO_TASKS /
más retrasada) con reconciliación bidireccional.

Cubre: derivación pura (US/Epic), `consolidate_states` bidireccional e
idempotente, `check_consolidation` (drift de derivación), la reconciliación
de lectura (`reconcile_graph_state`/`build_item_detail` — el estado derivado
se ve sin `--apply`) y el respeto de los estados transitorios/terminales.
"""

from __future__ import annotations

from pathlib import Path

from atlas_forge.backlog.promote import (
    check_consolidation,
    consolidate_states,
    derive_epic_target_state,
    derive_us_target_state,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _epic(backlog: Path, epic_id: str, state: str) -> None:
    _write(
        backlog / "epics" / f"{epic_id}.md",
        f"---\nid: {epic_id}\ntype: epic\ntitle: {epic_id}\nstate: {state}\n"
        "dependencies: []\n---\n\n## Objetivo\n\nTest.\n",
    )


def _story(backlog: Path, us_id: str, epic_id: str, state: str) -> None:
    _write(
        backlog / "user-stories" / f"{us_id}.md",
        f"---\nid: {us_id}\ntype: user_story\ntitle: {us_id}\nstate: {state}\n"
        f"dependencies: []\nepic: {epic_id}\n---\n\n## Historia\n\nTest.\n",
    )


def _task(backlog: Path, task_id: str, epic_id: str, us_id: str, state: str) -> None:
    _write(
        backlog / "tasks" / f"{task_id}.md",
        f"---\nid: {task_id}\ntype: task\ntitle: {task_id}\nstate: {state}\n"
        f"dependencies: []\nepic: {epic_id}\nuser_story: {us_id}\n---\n\n"
        "## Objetivo\n\nTest.\n",
    )


def _state_of(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("state:"):
            return line.split(":", 1)[1].strip()
    raise AssertionError(f"no state field in {path}")


# ── derivación pura (criterios 1, 2, 3) ───────────────────────────────────


def test_derive_us_target_state_no_tasks() -> None:
    assert derive_us_target_state("READY", []) == "NO_TASKS"
    assert derive_us_target_state("DONE", []) == "NO_TASKS"


def test_derive_us_target_state_least_advanced_task() -> None:
    assert derive_us_target_state("READY", ["DONE", "READY"]) == "READY"
    assert derive_us_target_state("READY", ["DONE", "TO_DEVELOP"]) == "TO_DEVELOP"
    assert derive_us_target_state("READY", ["DONE", "IN_PROGRESS"]) == "IN_PROGRESS"
    assert derive_us_target_state("READY", ["DONE", "IN_REVIEW"]) == "IN_REVIEW"
    assert derive_us_target_state("READY", ["DONE", "DONE"]) == "IN_REVIEW"


def test_derive_us_target_state_done_validated_and_reopened() -> None:
    # DONE válida (todas sus Tasks DONE) se mantiene.
    assert derive_us_target_state("DONE", ["DONE", "DONE"]) == "DONE"
    # DONE con una Task reabierta vuelve a la menos avanzada.
    assert derive_us_target_state("DONE", ["DONE", "READY"]) == "READY"


def test_derive_us_target_state_respects_transients() -> None:
    assert derive_us_target_state("TO_PLAN", []) == "TO_PLAN"
    assert derive_us_target_state("OUT_OF_SCOPE", []) == "OUT_OF_SCOPE"


def test_derive_epic_target_state() -> None:
    assert derive_epic_target_state("READY", ["DONE", "DONE"]) == "DONE"
    assert derive_epic_target_state("DONE", ["DONE", "READY"]) == "TO_DO"
    assert derive_epic_target_state("READY", []) == "READY"
    assert derive_epic_target_state("FUERA_ROADMAP", ["READY"]) == "FUERA_ROADMAP"


# ── consolidate_states bidireccional e idempotente (criterios 1-4) ───────


def test_consolidate_states_no_tasks_us_to_no_tasks(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    _epic(backlog, "AF-100", "READY")
    _story(backlog, "US-AF100-01", "AF-100", "READY")

    applied = consolidate_states(backlog)

    assert ("US-AF100-01", _path(backlog, "US-AF100-01"), "NO_TASKS", "user_story") in applied
    assert _state_of(backlog / "user-stories" / "US-AF100-01.md") == "NO_TASKS"


def test_consolidate_states_mixed_tasks(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    _epic(backlog, "AF-100", "READY")
    _story(backlog, "US-AF100-01", "AF-100", "READY")
    _task(backlog, "T-AF100-US01-01", "AF-100", "US-AF100-01", "DONE")
    _task(backlog, "T-AF100-US01-02", "AF-100", "US-AF100-01", "READY")

    consolidate_states(backlog)

    assert _state_of(backlog / "user-stories" / "US-AF100-01.md") == "READY"


def test_consolidate_states_all_done_to_in_review(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    _epic(backlog, "AF-100", "READY")
    _story(backlog, "US-AF100-01", "AF-100", "READY")
    _task(backlog, "T-AF100-US01-01", "AF-100", "US-AF100-01", "DONE")
    _task(backlog, "T-AF100-US01-02", "AF-100", "US-AF100-01", "DONE")

    consolidate_states(backlog)

    assert _state_of(backlog / "user-stories" / "US-AF100-01.md") == "IN_REVIEW"


def test_consolidate_states_epic_done_with_all_us_done(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    _epic(backlog, "AF-100", "READY")
    _story(backlog, "US-AF100-01", "AF-100", "DONE")
    _task(backlog, "T-AF100-US01-01", "AF-100", "US-AF100-01", "DONE")

    consolidate_states(backlog)

    assert _state_of(backlog / "epics" / "AF-100.md") == "DONE"


def test_consolidate_states_epic_to_todo_when_us_not_done(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    _epic(backlog, "AF-100", "DONE")
    _story(backlog, "US-AF100-01", "AF-100", "DONE")
    _task(backlog, "T-AF100-US01-01", "AF-100", "US-AF100-01", "DONE")
    _story(backlog, "US-AF100-02", "AF-100", "READY")

    consolidate_states(backlog)

    assert _state_of(backlog / "epics" / "AF-100.md") == "TO_DO"


def test_consolidate_states_is_idempotent_and_check_clean(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    _epic(backlog, "AF-100", "READY")
    _story(backlog, "US-AF100-01", "AF-100", "DONE")
    _task(backlog, "T-AF100-US01-01", "AF-100", "US-AF100-01", "READY")

    first = consolidate_states(backlog)
    assert first, "la primera pasada debe aplicar cambios"
    # Idempotente: la segunda no produce cambios (criterio 4).
    assert consolidate_states(backlog) == []
    # Tras consolidar, --check no reporta drift (criterio 4).
    assert check_consolidation(backlog) == []


def test_consolidate_states_respects_transients(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    _epic(backlog, "AF-100", "READY")
    # US en TO_PLAN (planificación) con 0 Tasks no se revierte a NO_TASKS.
    _story(backlog, "US-AF100-01", "AF-100", "TO_PLAN")
    # US OUT_OF_SCOPE no se toca.
    _story(backlog, "US-AF100-02", "AF-100", "OUT_OF_SCOPE")

    applied = consolidate_states(backlog)

    assert _state_of(backlog / "user-stories" / "US-AF100-01.md") == "TO_PLAN"
    assert _state_of(backlog / "user-stories" / "US-AF100-02.md") == "OUT_OF_SCOPE"


# ── reconciliación de lectura (criterio 5): estado derivado SIN --apply ──


def test_read_reconciliation_reflects_derived_state_without_apply(tmp_path: Path) -> None:
    from atlas_forge.backlog.detail import build_item_detail
    from atlas_forge.backlog.parser import load_backlog
    from atlas_forge.backlog.report import build_backlog_report, reconcile_graph_state

    backlog = tmp_path / "02-backlog"
    _epic(backlog, "AF-100", "READY")
    _story(backlog, "US-AF100-01", "AF-100", "DONE")  # en disco DONE
    _task(backlog, "T-AF100-US01-01", "AF-100", "US-AF100-01", "READY")  # reabierta

    # GET /backlog/{id}: build_item_detail sirve el estado derivado (READY),
    # no el DONE crudo del disco, sin necesidad de --apply.
    graph = load_backlog(backlog)
    detail = build_item_detail(graph, "US-AF100-01")
    assert detail is not None
    assert detail["state"] == "READY"
    assert detail["drift"] is True

    # GET /backlog: el informe reconcilia en memoria (la US no cuenta como DONE).
    report = build_backlog_report(backlog)
    assert report["total"]["user_stories"].get("DONE", 0) == 0
    assert report["total"]["user_stories"]["READY"] == 1


def _path(backlog: Path, us_id: str) -> str:
    return str(backlog / "user-stories" / f"{us_id}.md")


# ── watcher de 02-backlog/ (criterio 7) ──────────────────────────────────


def test_watcher_no_change_is_noop(tmp_path: Path) -> None:
    from atlas_forge.backlog.watcher import consolidate_if_changed, scan_backlog_marks

    backlog = tmp_path / "02-backlog"
    _epic(backlog, "AF-100", "READY")
    _story(backlog, "US-AF100-01", "AF-100", "DONE")
    _task(backlog, "T-AF100-US01-01", "AF-100", "US-AF100-01", "READY")

    # Primer tick consolida (no hay línea base) y deja el disco consistente.
    marks, changed, applied = consolidate_if_changed(backlog, None)
    assert changed is True
    assert applied
    assert _state_of(backlog / "user-stories" / "US-AF100-01.md") == "READY"

    # Segundo tick sin cambios: no-op, no escribe nada.
    marks2, changed2, applied2 = consolidate_if_changed(backlog, marks)
    assert changed2 is False
    assert applied2 == []


def test_watcher_manual_change_triggers_consolidation(tmp_path: Path) -> None:
    from atlas_forge.backlog.watcher import consolidate_if_changed, scan_backlog_marks

    backlog = tmp_path / "02-backlog"
    _epic(backlog, "AF-100", "READY")
    _story(backlog, "US-AF100-01", "AF-100", "DONE")
    _task(backlog, "T-AF100-US01-01", "AF-100", "US-AF100-01", "DONE")

    marks, _c, _a = consolidate_if_changed(backlog, None)  # queda consistente
    assert _state_of(backlog / "user-stories" / "US-AF100-01.md") == "DONE"

    # Cambio manual fuera del pipeline: se reabre una Task.
    _task(backlog, "T-AF100-US01-01", "AF-100", "US-AF100-01", "READY")

    marks2, changed, applied = consolidate_if_changed(backlog, marks)
    assert changed is True
    assert applied
    # El siguiente tick consolida la US al estado derivado en disco.
    assert _state_of(backlog / "user-stories" / "US-AF100-01.md") == "READY"

    # Tick sin cambios posterior: no-op.
    _c3, changed3, applied3 = consolidate_if_changed(backlog, marks2)
    assert changed3 is False
    assert applied3 == []


def test_worker_run_consolidation_once_consolidates_manual_change(tmp_path: Path) -> None:
    """Criterio 7: el tick del worker (`run_consolidation_once`) consolida
    en disco un cambio manual de una Task en el siguiente tick, y un tick
    sin cambios es no-op."""
    from atlas_forge.core.session_lifecycle import activate
    from atlas_forge.dispatcher.dispatch_queue_worker import DispatchQueueWorker
    from atlas_forge.models import DevelopmentSession

    backlog_root = tmp_path
    backlog = backlog_root / "02-backlog"
    _epic(backlog, "AF-100", "READY")
    _story(backlog, "US-AF100-01", "AF-100", "DONE")
    _task(backlog, "T-AF100-US01-01", "AF-100", "US-AF100-01", "DONE")

    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    worker = DispatchQueueWorker(backlog_root, "proj", session)

    # Primer tick (sin línea base): la US DONE con Task DONE se mantiene
    # DONE, y la Epic READY con su US DONE se promueve a DONE.
    changed, applied = worker.run_consolidation_once()
    assert applied  # la Epic AF-100 -> DONE
    assert _state_of(backlog / "user-stories" / "US-AF100-01.md") == "DONE"
    assert _state_of(backlog / "epics" / "AF-100.md") == "DONE"

    # Tick sin cambios: no-op.
    changed, applied = worker.run_consolidation_once()
    assert changed is False
    assert applied == []

    # Cambio manual fuera del pipeline: se reabre una Task.
    _task(backlog, "T-AF100-US01-01", "AF-100", "US-AF100-01", "READY")

    # Siguiente tick del worker: consolida la US al estado derivado (READY).
    changed, applied = worker.run_consolidation_once()
    assert changed is True
    assert applied
    assert _state_of(backlog / "user-stories" / "US-AF100-01.md") == "READY"
