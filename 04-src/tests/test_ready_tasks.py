"""Tests de T-AF022-US14-01: `find_ready_tasks` (Tasks en `TODO` con todas
sus dependencias `DONE`), sobre un mini-backlog sintético en `tmp_path` con
resultado totalmente controlado — mismo patrón que `test_backlog_status.py`."""

from pathlib import Path

from atlas_forge.backlog import find_ready_tasks, load_backlog


def _write(backlog_path: Path, subdir: str, filename: str, frontmatter: dict) -> Path:
    directory = backlog_path / subdir
    directory.mkdir(parents=True, exist_ok=True)
    lines = ["---"]
    for key, value in frontmatter.items():
        if isinstance(value, list):
            rendered = "[" + ", ".join(value) + "]"
            lines.append(f"{key}: {rendered}")
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    lines.append(f"\n# {frontmatter['id']}\n")
    target = directory / filename
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


def _task(item_id: str, state: str, dependencies: list, priority: str) -> dict:
    return {
        "id": item_id,
        "type": "task",
        "title": item_id,
        "state": state,
        "dependencies": dependencies,
        "priority": priority,
        "epic": "AF-100",
        "user_story": "US-AF100-01",
    }


def _user_story(item_id: str, state: str) -> dict:
    return {
        "id": item_id,
        "type": "user_story",
        "title": item_id,
        "state": state,
        "dependencies": [],
        "priority": "Alta",
        "epic": "AF-100",
    }


def test_find_ready_tasks_returns_exactly_the_tasks_that_qualify(
    tmp_path: Path,
) -> None:
    backlog = tmp_path / "backlog"
    _write(
        backlog, "user-stories", "US-AF100-01.md", _user_story("US-AF100-01", "READY")
    )
    # Ya DONE: su dependiente si puede quedar lista.
    _write(
        backlog, "tasks", "T-AF100-US01-01.md",
        _task("T-AF100-US01-01", "DONE", [], "Media"),
    )
    # Lista: su unica dependencia (01) esta DONE.
    _write(
        backlog, "tasks", "T-AF100-US01-02.md",
        _task("T-AF100-US01-02", "READY", ["T-AF100-US01-01"], "Media"),
    )
    # No lista: ya esta DONE, no es candidata.
    _write(
        backlog, "tasks", "T-AF100-US01-03.md",
        _task("T-AF100-US01-03", "DONE", [], "Media"),
    )

    graph = load_backlog(backlog)
    ready = find_ready_tasks(graph)

    assert [item.id for item in ready] == ["T-AF100-US01-02"]


def test_task_with_a_dependency_not_done_is_excluded(tmp_path: Path) -> None:
    for blocker_state in ("READY", "IN_PROGRESS", "IN_REVIEW"):
        backlog = tmp_path / f"backlog-{blocker_state}"
        _write(
            backlog, "tasks", "T-AF100-US01-blocker.md",
            _task("T-AF100-US01-blocker", blocker_state, [], "Media"),
        )
        _write(
            backlog, "tasks", "T-AF100-US01-blocked.md",
            _task("T-AF100-US01-blocked", "READY", ["T-AF100-US01-blocker"], "Media"),
        )

        graph = load_backlog(backlog)
        ready = find_ready_tasks(graph)

        assert "T-AF100-US01-blocked" not in [item.id for item in ready], (
            f"bloqueador en estado {blocker_state} no debería dejar pasar la Task"
        )


def test_task_without_dependencies_is_ready_if_todo(tmp_path: Path) -> None:
    backlog = tmp_path / "backlog"
    _write(
        backlog, "tasks", "T-AF100-US01-01.md",
        _task("T-AF100-US01-01", "READY", [], "Baja"),
    )

    graph = load_backlog(backlog)
    ready = find_ready_tasks(graph)

    assert [item.id for item in ready] == ["T-AF100-US01-01"]


def test_result_order_respects_priority_then_id_tie_break(tmp_path: Path) -> None:
    backlog = tmp_path / "backlog"
    _write(
        backlog, "tasks", "T-AF100-US01-03.md",
        _task("T-AF100-US01-03", "READY", [], "Media"),
    )
    _write(
        backlog, "tasks", "T-AF100-US01-01.md",
        _task("T-AF100-US01-01", "READY", [], "Alta"),
    )
    _write(
        backlog, "tasks", "T-AF100-US01-02.md",
        _task("T-AF100-US01-02", "READY", [], "Alta"),
    )
    _write(
        backlog, "tasks", "T-AF100-US01-04.md",
        _task("T-AF100-US01-04", "READY", [], "Crítica"),
    )

    graph = load_backlog(backlog)
    ready = find_ready_tasks(graph)

    assert [item.id for item in ready] == [
        "T-AF100-US01-04",  # Critica
        "T-AF100-US01-01",  # Alta, id menor
        "T-AF100-US01-02",  # Alta, id mayor
        "T-AF100-US01-03",  # Media
    ]


def test_dependency_with_nonexistent_id_does_not_qualify_the_task(
    tmp_path: Path,
) -> None:
    backlog = tmp_path / "backlog"
    _write(
        backlog, "tasks", "T-AF100-US01-01.md",
        _task("T-AF100-US01-01", "READY", ["T-AF100-US01-999"], "Alta"),
    )

    graph = load_backlog(backlog)
    ready = find_ready_tasks(graph)

    assert ready == []


def test_user_stories_and_epics_are_never_returned_even_when_todo(
    tmp_path: Path,
) -> None:
    backlog = tmp_path / "backlog"
    _write(
        backlog, "epics", "AF-100-epic.md",
        {
            "id": "AF-100",
            "type": "epic",
            "title": "Epic",
            "state": "READY",
            "dependencies": [],
        },
    )
    _write(
        backlog, "user-stories", "US-AF100-01.md", _user_story("US-AF100-01", "READY")
    )

    graph = load_backlog(backlog)
    ready = find_ready_tasks(graph)

    assert ready == []
