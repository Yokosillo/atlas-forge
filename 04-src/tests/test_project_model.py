from atlas_forge.models import Project


def test_project_construction() -> None:
    project = Project(
        id="p1",
        name="atlas-forge",
        path="/home/dev/atlas-forge",
        repository="git@github.com:example/atlas-forge.git",
        workspace_id="ws-1",
    )

    assert project.id == "p1"
    assert project.name == "atlas-forge"
    assert project.path == "/home/dev/atlas-forge"
    assert project.repository == "git@github.com:example/atlas-forge.git"
    assert project.workspace_id == "ws-1"


def test_project_requires_workspace_association() -> None:
    try:
        Project(
            id="p1",
            name="atlas-forge",
            path="/home/dev/atlas-forge",
            repository="git@github.com:example/atlas-forge.git",
        )
    except TypeError:
        pass
    else:
        raise AssertionError(
            "Un Project debe asociarse siempre a un Workspace "
            "(campo `workspace_id` obligatorio)."
        )
