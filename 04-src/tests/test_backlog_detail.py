"""Tests de T-FB008-US04-05: `build_item_detail` (`brain/backlog/detail.py`)
debe listar las Tasks reales de una User Story usando el campo
`user_story:` de cada Task, nunca `dependencies` — bug real reproducido
aquí: antes del fix, `GET /backlog/{us_id}` devolvía `tasks: []` para
CUALQUIER User Story real del proyecto, porque ninguna Task declaró jamás
su propia US dentro de `dependencies` (esa relación siempre vivió en
`user_story:`)."""

from pathlib import Path

import pytest

from brain.backlog import load_backlog
from brain.backlog.detail import build_epic_detail, build_item_detail

_US = (
    "---\n"
    "id: US-FB999-01\n"
    "type: user_story\n"
    "title: Historia de ejemplo\n"
    "state: TODO\n"
    "dependencies: []\n"
    "epic: FB-999\n"
    "priority: Alta\n"
    "---\n\n"
    "# US-FB999-01 · Historia de ejemplo\n\n"
    "## Historia\n\n"
    "Como usuario quiero X.\n\n"
    "## Criterios de aceptación\n\n"
    "1. Y.\n"
)


def _task(task_id: str, story_id: str, state: str, dependencies: str = "[]") -> str:
    return (
        "---\n"
        f"id: {task_id}\n"
        "type: task\n"
        "title: Task de ejemplo\n"
        f"state: {state}\n"
        f"dependencies: {dependencies}\n"
        "epic: FB-999\n"
        f"user_story: {story_id}\n"
        "priority: Alta\n"
        "---\n\n"
        f"# {task_id} · Task de ejemplo\n\n"
        "## Objetivo\n\nHacer algo.\n\n"
        "## Criterios de aceptación\n\n1. Hecho.\n"
    )


def _write(tmp_path: Path, subdir: str, filename: str, content: str) -> None:
    directory = tmp_path / subdir
    directory.mkdir(parents=True, exist_ok=True)
    (directory / filename).write_text(content, encoding="utf-8")


@pytest.fixture
def backlog_root(tmp_path: Path) -> Path:
    _write(tmp_path, "user-stories", "US-FB999-01-historia.md", _US)
    _write(
        tmp_path,
        "tasks",
        "T-FB999-US01-01-primera.md",
        _task("T-FB999-US01-01", "US-FB999-01", "TODO"),
    )
    _write(
        tmp_path,
        "tasks",
        "T-FB999-US01-02-segunda.md",
        _task("T-FB999-US01-02", "US-FB999-01", "DONE"),
    )
    return tmp_path


def test_build_item_detail_lists_real_tasks_of_a_user_story_by_user_story_field(
    backlog_root: Path,
) -> None:
    graph = load_backlog(backlog_root)

    detail = build_item_detail(graph, "US-FB999-01")

    assert detail is not None
    task_ids = {task["id"] for task in detail["tasks"]}
    assert task_ids == {"T-FB999-US01-01", "T-FB999-US01-02"}
    states = {task["id"]: task["state"] for task in detail["tasks"]}
    assert states == {"T-FB999-US01-01": "TODO", "T-FB999-US01-02": "DONE"}


def test_build_item_detail_ignores_dependencies_field_for_task_us_relationship(
    tmp_path: Path,
) -> None:
    # Bug real: una Task cuyas `dependencies` SÍ mencionan la US (por
    # coincidencia o por una dependencia real declarada) no debe listarse
    # dos veces ni ser la única forma de encontrarla — y una Task cuyas
    # `dependencies` están vacías pero cuyo `user_story:` apunta a la
    # Story sigue apareciendo (era exactamente el caso que fallaba antes
    # del fix, ya cubierto por `backlog_root`, pero aquí se verifica
    # además que `dependencies` no aporta ni quita nada al cálculo).
    _write(tmp_path, "user-stories", "US-FB999-01-historia.md", _US)
    _write(
        tmp_path,
        "tasks",
        "T-FB999-US01-01-con-dependencia.md",
        _task(
            "T-FB999-US01-01",
            "US-FB999-01",
            "TODO",
            dependencies='["US-FB999-01"]',
        ),
    )

    graph = load_backlog(tmp_path)
    detail = build_item_detail(graph, "US-FB999-01")

    assert detail is not None
    assert [task["id"] for task in detail["tasks"]] == ["T-FB999-US01-01"]


def test_build_item_detail_returns_empty_tasks_when_user_story_has_none(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "user-stories", "US-FB999-01-historia.md", _US)

    graph = load_backlog(tmp_path)
    detail = build_item_detail(graph, "US-FB999-01")

    assert detail is not None
    assert detail["tasks"] == []


# ---------------------------------------------------------------------------
# T-FB022-US13-05: build_item_detail/build_epic_detail nunca sirven un padre
# DONE con un hijo pendiente (reutilizan detect_reopened_drift_in_graph de
# T-FB022-US13-04 sobre el grafo ya cargado, sin escribir nada).
# ---------------------------------------------------------------------------


def _us_done(us_id: str, epic_id: str) -> str:
    return (
        "---\n"
        f"id: {us_id}\ntype: user_story\ntitle: Historia\nstate: DONE\n"
        f"dependencies: []\nepic: {epic_id}\npriority: Alta\n---\n\n"
        "## Historia\n\nHistoria.\n\n## Criterios de aceptación\n\n1. Y.\n"
    )


def _epic_done(epic_id: str) -> str:
    return (
        "---\n"
        f"id: {epic_id}\ntype: epic\ntitle: Epic\nstate: DONE\ndependencies: []\n"
        "---\n\n## Objetivo\n\nObjetivo.\n"
    )


def test_build_item_detail_reconciles_user_story_done_with_reopened_task(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "user-stories", "US-FB998-01.md", _us_done("US-FB998-01", "FB-998"))
    _write(
        tmp_path, "tasks", "T-FB998-US01-01.md",
        _task("T-FB998-US01-01", "US-FB998-01", "TODO"),
    )

    graph = load_backlog(tmp_path)
    detail = build_item_detail(graph, "US-FB998-01")

    assert detail is not None
    assert detail["state"] == "IN_PROGRESS"
    assert detail["drift"] is True


def test_build_item_detail_no_drift_field_when_consistent(tmp_path: Path) -> None:
    _write(tmp_path, "user-stories", "US-FB998-01.md", _us_done("US-FB998-01", "FB-998"))
    _write(
        tmp_path, "tasks", "T-FB998-US01-01.md",
        _task("T-FB998-US01-01", "US-FB998-01", "DONE"),
    )

    graph = load_backlog(tmp_path)
    detail = build_item_detail(graph, "US-FB998-01")

    assert detail is not None
    assert detail["state"] == "DONE"
    assert "drift" not in detail


def test_build_epic_detail_reconciles_epic_with_reopened_user_story(
    tmp_path: Path,
) -> None:
    # Drift directo de la Epic: FB-998 está DONE en disco pero una de sus
    # US (US-FB998-02) sigue en TODO — no depende de que la propia US
    # tenga a su vez drift con sus Tasks (esta Task cubre "hijo directo
    # reabierto", no cascada transitiva a través de más de un nivel).
    _write(tmp_path, "epics", "FB-998-epic.md", _epic_done("FB-998"))
    _write(tmp_path, "user-stories", "US-FB998-01.md", _us_done("US-FB998-01", "FB-998"))
    _write(
        tmp_path, "tasks", "T-FB998-US01-01.md",
        _task("T-FB998-US01-01", "US-FB998-01", "DONE"),
    )
    _write(
        tmp_path, "user-stories", "US-FB998-02.md",
        "---\nid: US-FB998-02\ntype: user_story\ntitle: Historia 2\nstate: TODO\n"
        "dependencies: []\nepic: FB-998\npriority: Alta\n---\n\n"
        "## Historia\n\nHistoria 2.\n\n## Criterios de aceptación\n\n1. Y.\n",
    )

    graph = load_backlog(tmp_path)
    detail = build_epic_detail(tmp_path, graph, "FB-998")

    assert detail is not None
    assert detail["state"] == "IN_PROGRESS"
    assert detail["drift"] is True
    # US-FB998-01 (DONE, consistente) no se ve afectada por el drift de
    # su Epic — solo se reconcilia lo que realmente tiene drift propio.
    us1_entry = next(us for us in detail["user_stories"] if us["id"] == "US-FB998-01")
    assert us1_entry["state"] == "DONE"
    assert "drift" not in us1_entry


# ---------------------------------------------------------------------------
# T-FB036-US01-09: build_epic_detail añade task_count por User Story —
# número de Tasks cuyo campo user_story coincide con el id de esa US,
# contado sobre el grafo ya cargado, sin llamada adicional.
# ---------------------------------------------------------------------------


def test_build_epic_detail_adds_task_count_per_user_story(tmp_path: Path) -> None:
    _write(tmp_path, "epics", "FB-999-epic.md", _epic_done("FB-999").replace("DONE", "TODO"))
    _write(tmp_path, "user-stories", "US-FB999-01-historia.md", _US)
    _write(
        tmp_path, "tasks", "T-FB999-US01-01-primera.md",
        _task("T-FB999-US01-01", "US-FB999-01", "TODO"),
    )
    _write(
        tmp_path, "tasks", "T-FB999-US01-02-segunda.md",
        _task("T-FB999-US01-02", "US-FB999-01", "DONE"),
    )
    _write(
        tmp_path, "user-stories", "US-FB999-02-sin-tasks.md",
        _US.replace("US-FB999-01", "US-FB999-02"),
    )

    graph = load_backlog(tmp_path)
    detail = build_epic_detail(tmp_path, graph, "FB-999")

    assert detail is not None
    counts = {us["id"]: us["task_count"] for us in detail["user_stories"]}
    # US-FB999-01 tiene 2 Tasks reales (una TODO, una DONE — ambas
    # cuentan, task_count no filtra por estado).
    assert counts["US-FB999-01"] == 2
    # US-FB999-02 no tiene ninguna Task todavía — 0, no ausente.
    assert counts["US-FB999-02"] == 0


def test_build_epic_detail_task_count_ignores_dependencies_field(tmp_path: Path) -> None:
    # Mismo criterio ya verificado para build_item_detail: `dependencies`
    # nunca es la relación Task→US, solo `user_story:` lo es. Una Task
    # cuyas `dependencies` mencionan la US pero cuyo `user_story:` apunta
    # a OTRA no debe contarse aquí.
    _write(tmp_path, "epics", "FB-999-epic.md", _epic_done("FB-999").replace("DONE", "TODO"))
    _write(tmp_path, "user-stories", "US-FB999-01-historia.md", _US)
    _write(
        tmp_path, "tasks", "T-FB999-US01-01-otra-us.md",
        _task(
            "T-FB999-US01-01", "US-FB999-99", "TODO", dependencies='["US-FB999-01"]'
        ),
    )

    graph = load_backlog(tmp_path)
    detail = build_epic_detail(tmp_path, graph, "FB-999")

    assert detail is not None
    counts = {us["id"]: us["task_count"] for us in detail["user_stories"]}
    assert counts["US-FB999-01"] == 0


def test_build_item_detail_does_not_write_any_file(tmp_path: Path) -> None:
    us_path = tmp_path / "user-stories" / "US-FB998-01.md"
    _write(tmp_path, "user-stories", "US-FB998-01.md", _us_done("US-FB998-01", "FB-998"))
    _write(
        tmp_path, "tasks", "T-FB998-US01-01.md",
        _task("T-FB998-US01-01", "US-FB998-01", "TODO"),
    )

    before = us_path.read_text(encoding="utf-8")
    graph = load_backlog(tmp_path)
    build_item_detail(graph, "US-FB998-01")
    after = us_path.read_text(encoding="utf-8")

    assert before == after
    assert "state: DONE" in after
