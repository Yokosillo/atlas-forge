from pathlib import Path

import pytest

from brain.core import (
    SessionAlreadyActiveError,
    get_current_session,
    resolve_startup_session,
    shutdown_current_session,
)
from brain.core.session_registry import _reset_registry_for_tests
from brain.workspace import discover_projects, select_active_project


@pytest.fixture(autouse=True)
def _clean_registry():
    _reset_registry_for_tests()
    yield
    _reset_registry_for_tests()


def _make_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()


def _workspace_with_active_project(tmp_path: Path) -> tuple[Path, Path]:
    workspace = tmp_path / "workspace"
    _make_git_repo(workspace / "project-a")
    state_dir = tmp_path / "state"

    discovered = discover_projects(workspace)
    select_active_project(discovered[0], discovered=discovered, state_dir=state_dir)

    return workspace, state_dir


def test_starting_with_valid_active_project_creates_active_session(
    tmp_path: Path,
) -> None:
    workspace, state_dir = _workspace_with_active_project(tmp_path)

    session = resolve_startup_session(workspace_root=workspace, state_dir=state_dir)

    assert session is not None
    assert session.status == "active"
    assert get_current_session() is session


def test_starting_without_active_project_creates_no_session(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_dir = tmp_path / "state"

    session = resolve_startup_session(workspace_root=workspace, state_dir=state_dir)

    assert session is None
    assert get_current_session() is None


def test_shutdown_closes_the_active_session(tmp_path: Path) -> None:
    workspace, state_dir = _workspace_with_active_project(tmp_path)
    resolve_startup_session(workspace_root=workspace, state_dir=state_dir)

    shutdown_current_session()

    session = get_current_session()
    assert session is not None
    assert session.status == "closed"


def test_shutdown_without_any_session_does_nothing() -> None:
    shutdown_current_session()

    assert get_current_session() is None


def test_cannot_have_two_active_sessions_simultaneously(tmp_path: Path) -> None:
    workspace, state_dir = _workspace_with_active_project(tmp_path)
    resolve_startup_session(workspace_root=workspace, state_dir=state_dir)

    with pytest.raises(SessionAlreadyActiveError):
        resolve_startup_session(workspace_root=workspace, state_dir=state_dir)

    # La sesión original sigue siendo la única y sigue activa.
    assert get_current_session().status == "active"


def test_starting_again_after_shutdown_is_allowed(tmp_path: Path) -> None:
    workspace, state_dir = _workspace_with_active_project(tmp_path)

    first_session = resolve_startup_session(
        workspace_root=workspace, state_dir=state_dir
    )
    shutdown_current_session()

    second_session = resolve_startup_session(
        workspace_root=workspace, state_dir=state_dir
    )

    assert second_session is not None
    assert second_session.status == "active"
    assert first_session.status == "closed"
