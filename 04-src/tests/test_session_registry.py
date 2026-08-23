from pathlib import Path

import pytest

from atlas_forge.core import (
    get_current_session,
    resolve_startup_session,
    shutdown_current_session,
)
from atlas_forge.core.session_registry import _reset_registry_for_tests, focus_project_session
from atlas_forge.workspace import discover_projects, select_active_project


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


def _workspace_with_two_projects(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    _make_git_repo(workspace / "project-a")
    _make_git_repo(workspace / "project-b")
    return workspace


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


def test_starting_two_different_projects_keeps_both_sessions_alive(
    tmp_path: Path,
) -> None:
    workspace = _workspace_with_two_projects(tmp_path)
    state_dir = tmp_path / "state"
    discovered = discover_projects(workspace)

    select_active_project(discovered[0], discovered=discovered, state_dir=state_dir)
    session_a = resolve_startup_session(workspace_root=workspace, state_dir=state_dir)

    select_active_project(discovered[1], discovered=discovered, state_dir=state_dir)
    session_b = resolve_startup_session(workspace_root=workspace, state_dir=state_dir)

    assert session_a.status == "active"
    assert session_b.status == "active"
    assert session_a.id != session_b.id
    # El foco quedó en B, la última en arrancar.
    assert get_current_session() is session_b

    # Volver a poner el foco en A la recupera tal cual, sin relanzarla.
    refocused_a = focus_project_session(session_a.project_id)
    assert refocused_a is session_a
    assert get_current_session() is session_a


def test_re_starting_an_already_active_project_reuses_it_and_moves_focus(
    tmp_path: Path,
) -> None:
    workspace = _workspace_with_two_projects(tmp_path)
    state_dir = tmp_path / "state"
    discovered = discover_projects(workspace)

    select_active_project(discovered[0], discovered=discovered, state_dir=state_dir)
    first = resolve_startup_session(workspace_root=workspace, state_dir=state_dir)

    select_active_project(discovered[1], discovered=discovered, state_dir=state_dir)
    resolve_startup_session(workspace_root=workspace, state_dir=state_dir)

    # Re-enfocar A (ya viva) no crea una segunda sesión ni cambia su id.
    again = focus_project_session(first.project_id)

    assert again is first
    assert again.id == first.id
    assert get_current_session() is first


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
