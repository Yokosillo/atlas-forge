from pathlib import Path

from atlas_forge.models import Project
from atlas_forge.storage import load_active_project, save_active_project


def _make_project() -> Project:
    return Project(
        id="p1",
        name="atlas-forge",
        path="/home/dev/atlas-forge",
        repository="git@github.com:example/atlas-forge.git",
        workspace_id="ws-1",
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
        workspace_id="ws-2",
    )

    save_active_project(first, state_dir=tmp_path)
    save_active_project(second, state_dir=tmp_path)
    loaded = load_active_project(state_dir=tmp_path)

    assert loaded == second
