from brain.models import Project


def test_project_construction() -> None:
    project = Project(
        id="p1",
        name="factory-brain",
        path="/home/dev/factory-brain",
        repository="git@github.com:example/factory-brain.git",
        workspace_id="ws-1",
    )

    assert project.id == "p1"
    assert project.name == "factory-brain"
    assert project.path == "/home/dev/factory-brain"
    assert project.repository == "git@github.com:example/factory-brain.git"
    assert project.workspace_id == "ws-1"


def test_project_requires_workspace_association() -> None:
    try:
        Project(
            id="p1",
            name="factory-brain",
            path="/home/dev/factory-brain",
            repository="git@github.com:example/factory-brain.git",
        )
    except TypeError:
        pass
    else:
        raise AssertionError(
            "Un Project debe asociarse siempre a un Workspace "
            "(campo `workspace_id` obligatorio)."
        )
