"""Tests de T-FB022-US13-02: promoción transitiva de estado US/Epic → DONE.

Usa `tmp_path` con una estructura sintética de `02-backlog/{epics,user-stories,
tasks}/` para tener control total sobre los escenarios (no depende del backlog
real del proyecto, que cambia constantemente).
"""
from __future__ import annotations

from pathlib import Path

from brain.backlog.promote import (
    check_backlog_promotion,
    detect_reopened_drift,
    promote_backlog,
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


def test_promocion_us_a_done_cuando_todas_las_tasks_estan_done(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    _epic(backlog, "FB-100", "TO_DO")
    _story(backlog, "US-FB100-01", "FB-100", "TO_DO")
    _task(backlog, "T-FB100-US01-01", "FB-100", "US-FB100-01", "DONE")
    _task(backlog, "T-FB100-US01-02", "FB-100", "US-FB100-01", "DONE")

    result = promote_backlog(backlog)

    assert result.promoted_user_stories == ["US-FB100-01"]
    assert _state_of(backlog / "user-stories" / "US-FB100-01.md") == "DONE"


def test_promocion_transitiva_epic_a_done(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    _epic(backlog, "FB-100", "TO_DO")
    _story(backlog, "US-FB100-01", "FB-100", "TO_DO")
    _task(backlog, "T-FB100-US01-01", "FB-100", "US-FB100-01", "DONE")

    result = promote_backlog(backlog)

    assert result.promoted_user_stories == ["US-FB100-01"]
    assert result.promoted_epics == ["FB-100"]
    assert _state_of(backlog / "epics" / "FB-100.md") == "DONE"


def test_no_promociona_con_hijo_pendiente(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    _epic(backlog, "FB-100", "TO_DO")
    _story(backlog, "US-FB100-01", "FB-100", "TO_DO")
    _task(backlog, "T-FB100-US01-01", "FB-100", "US-FB100-01", "DONE")
    _task(backlog, "T-FB100-US01-02", "FB-100", "US-FB100-01", "TO_DO")

    result = promote_backlog(backlog)

    assert result.promoted_user_stories == []
    assert result.promoted_epics == []
    assert _state_of(backlog / "user-stories" / "US-FB100-01.md") == "TO_DO"
    assert _state_of(backlog / "epics" / "FB-100.md") == "TO_DO"


def test_no_revierte_estado_ya_done(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    _epic(backlog, "FB-100", "DONE")
    _story(backlog, "US-FB100-01", "FB-100", "DONE")
    _story(backlog, "US-FB100-02", "FB-100", "TO_DO")
    _task(backlog, "T-FB100-US01-01", "FB-100", "US-FB100-01", "DONE")
    _task(backlog, "T-FB100-US02-01", "FB-100", "US-FB100-02", "TO_DO")

    result = promote_backlog(backlog)

    assert "US-FB100-01" not in result.promoted_user_stories
    assert result.promoted_epics == []
    assert _state_of(backlog / "epics" / "FB-100.md") == "DONE"


def test_idempotente(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    _epic(backlog, "FB-100", "TO_DO")
    _story(backlog, "US-FB100-01", "FB-100", "TO_DO")
    _task(backlog, "T-FB100-US01-01", "FB-100", "US-FB100-01", "DONE")

    first = promote_backlog(backlog)
    second = promote_backlog(backlog)

    assert first.has_drift
    assert not second.has_drift
    assert second.promoted_user_stories == []
    assert second.promoted_epics == []


def test_check_no_escribe_nada(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    _epic(backlog, "FB-100", "TO_DO")
    _story(backlog, "US-FB100-01", "FB-100", "TO_DO")
    _task(backlog, "T-FB100-US01-01", "FB-100", "US-FB100-01", "DONE")

    result = check_backlog_promotion(backlog)

    assert result.has_drift
    assert result.promoted_user_stories == ["US-FB100-01"]
    assert _state_of(backlog / "user-stories" / "US-FB100-01.md") == "TO_DO"


def test_mark_story_tasks_done_accepts_canonical_us_prefixed_story_id(
    tmp_path: Path,
) -> None:
    """T-FB022-US13-01B end-to-end: `_mark_story_tasks_done` recibe la forma
    canónica `US-FB100-01` (la que llega vía `plan.goal` tras un veredicto
    APROBADO), debe encontrar y marcar las Tasks reales `T-FB100-US01-*` a
    DONE y promover transitivamente la US y la Epic."""
    from brain.dispatcher.job_plan_dispatch import _mark_story_tasks_done

    backlog = tmp_path / "02-backlog"
    _epic(backlog, "FB-100", "TO_DO")
    _story(backlog, "US-FB100-01", "FB-100", "TO_DO")
    _task(backlog, "T-FB100-US01-01", "FB-100", "US-FB100-01", "TO_DO")
    _task(backlog, "T-FB100-US01-02", "FB-100", "US-FB100-01", "TO_DO")

    _mark_story_tasks_done("US-FB100-01", backlog_dir=backlog)

    assert _state_of(backlog / "tasks" / "T-FB100-US01-01.md") == "DONE"
    assert _state_of(backlog / "tasks" / "T-FB100-US01-02.md") == "DONE"
    assert _state_of(backlog / "user-stories" / "US-FB100-01.md") == "DONE"
    assert _state_of(backlog / "epics" / "FB-100.md") == "DONE"


def test_mark_story_tasks_done_also_accepts_normalized_story_id(tmp_path: Path) -> None:
    """El normalizador es idempotente: `FB100-US01` (la forma ya normalizada)
    debe producir el mismo resultado que `US-FB100-01`."""
    from brain.dispatcher.job_plan_dispatch import _mark_story_tasks_done

    backlog = tmp_path / "02-backlog"
    _epic(backlog, "FB-100", "TO_DO")
    _story(backlog, "US-FB100-01", "FB-100", "TO_DO")
    _task(backlog, "T-FB100-US01-01", "FB-100", "US-FB100-01", "TO_DO")

    _mark_story_tasks_done("FB100-US01", backlog_dir=backlog)

    assert _state_of(backlog / "tasks" / "T-FB100-US01-01.md") == "DONE"
    assert _state_of(backlog / "user-stories" / "US-FB100-01.md") == "DONE"


# ── T-FB022-US13-04: drift inverso (padre DONE con hijo reabierto) ─────────


def test_detect_reopened_drift_reports_us_done_with_task_reopened(
    tmp_path: Path,
) -> None:
    # Caso real encontrado en vivo 2026-08-16: el Arquitecto añadió una
    # Task nueva bajo una US ya DONE, sin reabrir la US.
    backlog = tmp_path / "02-backlog"
    _epic(backlog, "FB-100", "TO_DO")
    _story(backlog, "US-FB100-01", "FB-100", "DONE")
    _task(backlog, "T-FB100-US01-01", "FB-100", "US-FB100-01", "DONE")
    _task(backlog, "T-FB100-US01-02", "FB-100", "US-FB100-01", "TO_DO")

    result = detect_reopened_drift(backlog)

    assert result.has_drift
    assert len(result.items) == 1
    item = result.items[0]
    assert item.parent_id == "US-FB100-01"
    assert item.parent_kind == "user_story"
    assert item.reopened_children == (("T-FB100-US01-02", "TO_DO"),)


def test_detect_reopened_drift_reports_epic_done_with_us_reopened(
    tmp_path: Path,
) -> None:
    backlog = tmp_path / "02-backlog"
    _epic(backlog, "FB-100", "DONE")
    _story(backlog, "US-FB100-01", "FB-100", "DONE")
    _story(backlog, "US-FB100-02", "FB-100", "IN_PROGRESS")
    _task(backlog, "T-FB100-US01-01", "FB-100", "US-FB100-01", "DONE")
    _task(backlog, "T-FB100-US02-01", "FB-100", "US-FB100-02", "IN_PROGRESS")

    result = detect_reopened_drift(backlog)

    parent_ids = {item.parent_id for item in result.items}
    assert "FB-100" in parent_ids
    epic_item = next(item for item in result.items if item.parent_id == "FB-100")
    assert epic_item.parent_kind == "epic"
    assert epic_item.reopened_children == (("US-FB100-02", "IN_PROGRESS"),)


def test_detect_reopened_drift_empty_when_backlog_consistent(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    _epic(backlog, "FB-100", "DONE")
    _story(backlog, "US-FB100-01", "FB-100", "DONE")
    _task(backlog, "T-FB100-US01-01", "FB-100", "US-FB100-01", "DONE")

    result = detect_reopened_drift(backlog)

    assert not result.has_drift
    assert result.items == []


def test_detect_reopened_drift_ignores_us_not_marked_done(tmp_path: Path) -> None:
    # Una US en TODO/IN_PROGRESS/REVIEW con Tasks pendientes no es drift —
    # es el estado normal, no un padre completado prematuramente.
    backlog = tmp_path / "02-backlog"
    _epic(backlog, "FB-100", "TO_DO")
    _story(backlog, "US-FB100-01", "FB-100", "TO_DO")
    _task(backlog, "T-FB100-US01-01", "FB-100", "US-FB100-01", "TO_DO")

    result = detect_reopened_drift(backlog)

    assert not result.has_drift


def test_detect_reopened_drift_does_not_write_any_file(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    _epic(backlog, "FB-100", "TO_DO")
    _story(backlog, "US-FB100-01", "FB-100", "DONE")
    _task(backlog, "T-FB100-US01-01", "FB-100", "US-FB100-01", "TO_DO")

    detect_reopened_drift(backlog)

    # Detección, no corrección: el fichero en disco sigue igual que antes.
    assert _state_of(backlog / "user-stories" / "US-FB100-01.md") == "DONE"


def test_promotion_case_still_works_unchanged_alongside_reopened_drift(
    tmp_path: Path,
) -> None:
    # Criterio 4 de T-FB022-US13-04: el caso ya cubierto (promoción hacia
    # DONE) sigue funcionando sin cambios de comportamiento, incluso en un
    # backlog que también tiene drift inverso en otra rama.
    backlog = tmp_path / "02-backlog"
    _epic(backlog, "FB-100", "TO_DO")
    _story(backlog, "US-FB100-01", "FB-100", "TO_DO")
    _task(backlog, "T-FB100-US01-01", "FB-100", "US-FB100-01", "DONE")
    _story(backlog, "US-FB100-02", "FB-100", "DONE")
    _task(backlog, "T-FB100-US02-01", "FB-100", "US-FB100-02", "TO_DO")

    promotion = check_backlog_promotion(backlog)
    reopened = detect_reopened_drift(backlog)

    assert promotion.promoted_user_stories == ["US-FB100-01"]
    assert reopened.has_drift
    assert reopened.items[0].parent_id == "US-FB100-02"
