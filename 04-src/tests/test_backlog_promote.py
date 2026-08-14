"""Tests de T-FB022-US13-02: promoción transitiva de estado US/Epic → DONE.

Usa `tmp_path` con una estructura sintética de `02-backlog/{epics,user-stories,
tasks}/` para tener control total sobre los escenarios (no depende del backlog
real del proyecto, que cambia constantemente).
"""
from __future__ import annotations

from pathlib import Path

from brain.backlog.promote import check_backlog_promotion, promote_backlog


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
    _epic(backlog, "FB-100", "TODO")
    _story(backlog, "US-FB100-01", "FB-100", "TODO")
    _task(backlog, "T-FB100-US01-01", "FB-100", "US-FB100-01", "DONE")
    _task(backlog, "T-FB100-US01-02", "FB-100", "US-FB100-01", "DONE")

    result = promote_backlog(backlog)

    assert result.promoted_user_stories == ["US-FB100-01"]
    assert _state_of(backlog / "user-stories" / "US-FB100-01.md") == "DONE"


def test_promocion_transitiva_epic_a_done(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    _epic(backlog, "FB-100", "TODO")
    _story(backlog, "US-FB100-01", "FB-100", "TODO")
    _task(backlog, "T-FB100-US01-01", "FB-100", "US-FB100-01", "DONE")

    result = promote_backlog(backlog)

    assert result.promoted_user_stories == ["US-FB100-01"]
    assert result.promoted_epics == ["FB-100"]
    assert _state_of(backlog / "epics" / "FB-100.md") == "DONE"


def test_no_promociona_con_hijo_pendiente(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    _epic(backlog, "FB-100", "TODO")
    _story(backlog, "US-FB100-01", "FB-100", "TODO")
    _task(backlog, "T-FB100-US01-01", "FB-100", "US-FB100-01", "DONE")
    _task(backlog, "T-FB100-US01-02", "FB-100", "US-FB100-01", "TODO")

    result = promote_backlog(backlog)

    assert result.promoted_user_stories == []
    assert result.promoted_epics == []
    assert _state_of(backlog / "user-stories" / "US-FB100-01.md") == "TODO"
    assert _state_of(backlog / "epics" / "FB-100.md") == "TODO"


def test_no_revierte_estado_ya_done(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    _epic(backlog, "FB-100", "DONE")
    _story(backlog, "US-FB100-01", "FB-100", "DONE")
    _story(backlog, "US-FB100-02", "FB-100", "TODO")
    _task(backlog, "T-FB100-US01-01", "FB-100", "US-FB100-01", "DONE")
    _task(backlog, "T-FB100-US02-01", "FB-100", "US-FB100-02", "TODO")

    result = promote_backlog(backlog)

    assert "US-FB100-01" not in result.promoted_user_stories
    assert result.promoted_epics == []
    assert _state_of(backlog / "epics" / "FB-100.md") == "DONE"


def test_idempotente(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    _epic(backlog, "FB-100", "TODO")
    _story(backlog, "US-FB100-01", "FB-100", "TODO")
    _task(backlog, "T-FB100-US01-01", "FB-100", "US-FB100-01", "DONE")

    first = promote_backlog(backlog)
    second = promote_backlog(backlog)

    assert first.has_drift
    assert not second.has_drift
    assert second.promoted_user_stories == []
    assert second.promoted_epics == []


def test_check_no_escribe_nada(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    _epic(backlog, "FB-100", "TODO")
    _story(backlog, "US-FB100-01", "FB-100", "TODO")
    _task(backlog, "T-FB100-US01-01", "FB-100", "US-FB100-01", "DONE")

    result = check_backlog_promotion(backlog)

    assert result.has_drift
    assert result.promoted_user_stories == ["US-FB100-01"]
    assert _state_of(backlog / "user-stories" / "US-FB100-01.md") == "TODO"


def test_mark_story_tasks_done_accepts_canonical_us_prefixed_story_id(
    tmp_path: Path,
) -> None:
    """T-FB022-US13-01B end-to-end: `_mark_story_tasks_done` recibe la forma
    canónica `US-FB100-01` (la que llega vía `plan.goal` tras un veredicto
    APROBADO), debe encontrar y marcar las Tasks reales `T-FB100-US01-*` a
    DONE y promover transitivamente la US y la Epic."""
    from brain.dispatcher.job_plan_dispatch import _mark_story_tasks_done

    backlog = tmp_path / "02-backlog"
    _epic(backlog, "FB-100", "TODO")
    _story(backlog, "US-FB100-01", "FB-100", "TODO")
    _task(backlog, "T-FB100-US01-01", "FB-100", "US-FB100-01", "TODO")
    _task(backlog, "T-FB100-US01-02", "FB-100", "US-FB100-01", "TODO")

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
    _epic(backlog, "FB-100", "TODO")
    _story(backlog, "US-FB100-01", "FB-100", "TODO")
    _task(backlog, "T-FB100-US01-01", "FB-100", "US-FB100-01", "TODO")

    _mark_story_tasks_done("FB100-US01", backlog_dir=backlog)

    assert _state_of(backlog / "tasks" / "T-FB100-US01-01.md") == "DONE"
    assert _state_of(backlog / "user-stories" / "US-FB100-01.md") == "DONE"
