import pytest

from pathlib import Path

from brain.models import Project
from brain.storage import load_active_project
from brain.workspace import (
    ProjectNotDiscoveredError,
    get_active_project,
    select_active_project,
)


def _project(path: Path, name: str) -> Project:
    return Project(
        id=str(path),
        name=name,
        path=str(path),
        repository="",
        workspace_id=f"ws-{name}",
    )


def test_select_active_project_persists_it(tmp_path: Path) -> None:
    project = _project(tmp_path / "alpha", "alpha")

    select_active_project(project, discovered=[project], state_dir=tmp_path)

    assert load_active_project(state_dir=tmp_path) == project


def test_select_active_project_replaces_previous_selection(tmp_path: Path) -> None:
    first = _project(tmp_path / "alpha", "alpha")
    second = _project(tmp_path / "beta", "beta")

    select_active_project(first, discovered=[first, second], state_dir=tmp_path)
    select_active_project(second, discovered=[first, second], state_dir=tmp_path)

    assert load_active_project(state_dir=tmp_path) == second


def test_select_active_project_rejects_project_not_in_discovered_list(
    tmp_path: Path,
) -> None:
    discovered_project = _project(tmp_path / "alpha", "alpha")
    other_project = _project(tmp_path / "not-discovered", "not-discovered")

    with pytest.raises(ProjectNotDiscoveredError):
        select_active_project(
            other_project, discovered=[discovered_project], state_dir=tmp_path
        )

    assert load_active_project(state_dir=tmp_path) is None


def test_get_active_project_returns_basic_information(tmp_path: Path) -> None:
    project = _project(tmp_path / "alpha", "alpha")

    select_active_project(project, discovered=[project], state_dir=tmp_path)
    active = get_active_project(state_dir=tmp_path)

    assert active is not None
    assert active.name == project.name
    assert active.path == project.path
    assert active.repository == project.repository


def test_get_active_project_returns_none_when_nothing_selected(
    tmp_path: Path,
) -> None:
    assert get_active_project(state_dir=tmp_path) is None
