from pathlib import Path

from atlas_forge.workspace import (
    ProjectRecovered,
    ProjectSelectionRequired,
    ProjectSelectionRequiredAfterInvalid,
    resolve_startup_project,
    select_active_project,
)


def _make_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()


def test_first_run_without_previous_selection_offers_discovered_projects(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    _make_git_repo(workspace / "project-a")
    _make_git_repo(workspace / "project-b")
    state_dir = tmp_path / "state"

    outcome = resolve_startup_project(workspace_root=workspace, state_dir=state_dir)

    assert isinstance(outcome, ProjectSelectionRequired)
    assert {project.name for project in outcome.discovered} == {
        "project-a",
        "project-b",
    }


def test_run_with_valid_previous_selection_recovers_it_automatically(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    repo_path = workspace / "project-a"
    _make_git_repo(repo_path)
    state_dir = tmp_path / "state"

    discovered = [
        project
        for project in resolve_startup_project(
            workspace_root=workspace, state_dir=state_dir
        ).discovered
    ]
    select_active_project(discovered[0], discovered=discovered, state_dir=state_dir)

    outcome = resolve_startup_project(workspace_root=workspace, state_dir=state_dir)

    assert isinstance(outcome, ProjectRecovered)
    assert outcome.project.name == "project-a"


def test_previous_selection_with_missing_path_reports_problem_without_crashing(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    repo_path = workspace / "project-a"
    _make_git_repo(repo_path)
    state_dir = tmp_path / "state"

    discovered = resolve_startup_project(
        workspace_root=workspace, state_dir=state_dir
    ).discovered
    select_active_project(discovered[0], discovered=discovered, state_dir=state_dir)

    # El repositorio persistido desaparece del disco (movido/borrado).
    import shutil

    shutil.rmtree(repo_path)

    outcome = resolve_startup_project(workspace_root=workspace, state_dir=state_dir)

    assert isinstance(outcome, ProjectSelectionRequiredAfterInvalid)
    assert outcome.invalid_project.name == "project-a"
    assert "ya no existe" in outcome.reason
    assert outcome.discovered == []


def test_previous_selection_pointing_to_dir_without_git_reports_problem(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    repo_path = workspace / "project-a"
    _make_git_repo(repo_path)
    state_dir = tmp_path / "state"

    discovered = resolve_startup_project(
        workspace_root=workspace, state_dir=state_dir
    ).discovered
    select_active_project(discovered[0], discovered=discovered, state_dir=state_dir)

    # El directorio sigue existiendo, pero deja de ser un repositorio Git.
    import shutil

    shutil.rmtree(repo_path / ".git")

    outcome = resolve_startup_project(workspace_root=workspace, state_dir=state_dir)

    assert isinstance(outcome, ProjectSelectionRequiredAfterInvalid)
    assert "ya no es un repositorio Git" in outcome.reason
