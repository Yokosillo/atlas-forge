from brain.models import Project


def test_project_construction() -> None:
    project = Project(
        id="p1",
        name="factory-brain",
        path="/home/dev/factory-brain",
        repository="git@github.com:example/factory-brain.git",
    )

    assert project.id == "p1"
    assert project.name == "factory-brain"
    assert project.path == "/home/dev/factory-brain"
    assert project.repository == "git@github.com:example/factory-brain.git"
