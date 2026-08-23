"""T-AF036-US13-01: cobertura de `updated_at` en los caminos de cambio de
estado que el Tester detectó como hueco en la revisión inicial.

Inicialmente (revisión del Tester) dos caminos escribían `state` de forma
directa en disco sin actualizar `updated_at`:
  - `job_plan_dispatch.trigger_architect_verdict` (US -> IN_REVIEW)
  - `job_plan_dispatch._mark_story_tasks_done` (Task -> DONE)
Tras la corrección del Developer, ambos pasan por `_set_state` y DEBEN
escribir `updated_at` en el frontmatter. Estos tests verifican la corrección.
"""

from __future__ import annotations

from pathlib import Path

from atlas_forge.backlog.promote import promote_backlog


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


def _updated_at_of(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("updated_at:"):
            return line.split(":", 1)[1].strip()
    return ""

def _has_updated_at(path: Path) -> bool:
    return bool(_updated_at_of(path))

def test_trigger_architect_verdict_escribe_updated_at(tmp_path: Path) -> None:
    """La corrección del Developer: al marcar la US a IN_REVIEW al completarse
    un Job con story_id, el fichero de la US cambia de estado Y escribe
    updated_at en el frontmatter."""
    from atlas_forge.dispatcher.job_plan_dispatch import trigger_architect_verdict

    backlog = tmp_path / "02-backlog"
    _epic(backlog, "AF-100", "READY")
    _story(backlog, "US-AF100-01", "AF-100", "READY")
    task_path = backlog / "tasks" / "T-AF100-US01-01.md"
    _task(backlog, "T-AF100-US01-01", "AF-100", "US-AF100-01", "DONE")

    promote_backlog(backlog)  # deja la US en IN_REVIEW (todas las tasks DONE)

    us_path = backlog / "user-stories" / "US-AF100-01.md"

    # Volver la US a READY y disparar el trigger directo, que ahora pasa por
    # _set_state y DEBE escribir updated_at.
    us_path.write_text(
        us_path.read_text(encoding="utf-8").replace("state: IN_REVIEW", "state: READY", 1).replace("updated_at: " + _updated_at_of(us_path) + "\n", ""),
        encoding="utf-8",
    )

    trigger_architect_verdict("US-AF100-01", session=None, backlog_dir=backlog)

    assert _state_of(us_path) == "IN_REVIEW"
    assert _has_updated_at(us_path), (
        "trigger_architect_verdict debe escribir updated_at al cambiar la US a IN_REVIEW."
    )


def test_mark_story_tasks_done_escribe_updated_at_en_tasks(tmp_path: Path) -> None:
    """La corrección del Developer: al aprobarse el veredicto del Arquitecto,
    `_mark_story_tasks_done` marca las Tasks residuales a DONE Y escribe
    updated_at en su frontmatter."""
    from atlas_forge.dispatcher.job_plan_dispatch import _mark_story_tasks_done

    backlog = tmp_path / "02-backlog"
    _epic(backlog, "AF-100", "READY")
    _story(backlog, "US-AF100-01", "AF-100", "READY")
    task_path = backlog / "tasks" / "T-AF100-US01-01.md"
    _task(backlog, "T-AF100-US01-01", "AF-100", "US-AF100-01", "READY")

    _mark_story_tasks_done("US-AF100-01", backlog_dir=backlog)

    assert _state_of(task_path) == "DONE"
    assert _has_updated_at(task_path), (
        "_mark_story_tasks_done debe escribir updated_at al marcar la Task a DONE."
    )