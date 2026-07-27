from pathlib import Path

from brain.models import Project
from brain.storage import load_active_project, save_active_project


def _make_project() -> Project:
    return Project(
        id="p1",
        name="factory-brain",
        path="/home/dev/factory-brain",
        repository="git@github.com:example/factory-brain.git",
    )


def test_load_active_project_returns_none_when_never_saved(tmp_path: Path) -> None:
    assert load_active_project(state_dir=tmp_path) is None


def test_save_and_load_active_project_round_trip(tmp_path: Path) -> None:
    project = _make_project()

    save_active_project(project, state_dir=tmp_path)
    loaded = load_active_project(state_dir=tmp_path)

    assert loaded == project


def test_save_active_project_overwrites_previous_selection(tmp_path: Path) -> None:
    first = _make_project()
    second = Project(
        id="p2",
        name="other-project",
        path="/home/dev/other-project",
        repository="git@github.com:example/other-project.git",
    )

    save_active_project(first, state_dir=tmp_path)
    save_active_project(second, state_dir=tmp_path)
    loaded = load_active_project(state_dir=tmp_path)

    assert loaded == second
