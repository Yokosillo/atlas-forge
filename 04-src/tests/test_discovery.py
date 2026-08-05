from pathlib import Path

from brain.workspace import discover_projects


def _make_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()


def test_discover_projects_returns_empty_list_when_no_repos(tmp_path: Path) -> None:
    (tmp_path / "just-a-folder").mkdir()
    (tmp_path / "another-folder" / "nested").mkdir(parents=True)

    assert discover_projects(tmp_path) == []


def test_discover_projects_returns_empty_list_for_missing_root(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"

    assert discover_projects(missing) == []


def test_discover_projects_finds_real_repos_and_skips_false_positives(
    tmp_path: Path,
) -> None:
    # Repos reales, en distintos niveles del árbol.
    _make_git_repo(tmp_path / "project-alpha")
    _make_git_repo(tmp_path / "nested" / "project-beta")

    # Falso positivo: node_modules con su propio .git anidado (paquete
    # vendorizado o dependencia que es en sí misma un repo Git).
    _make_git_repo(tmp_path / "project-alpha" / "node_modules" / "some-package")

    # Falso positivo: directorio normal sin .git.
    (tmp_path / "not-a-repo").mkdir()

    # Falso positivo: directorio oculto de entorno virtual.
    _make_git_repo(tmp_path / ".venv" / "lib")

    projects = discover_projects(tmp_path)
    paths = {project.path for project in projects}

    assert paths == {
        str(tmp_path / "project-alpha"),
        str(tmp_path / "nested" / "project-beta"),
    }


def test_discover_projects_populates_name_and_path(tmp_path: Path) -> None:
    repo_path = tmp_path / "factory-brain"
    _make_git_repo(repo_path)

    projects = discover_projects(tmp_path)

    assert len(projects) == 1
    assert projects[0].name == "factory-brain"
    assert projects[0].path == str(repo_path)


def test_discover_projects_does_not_descend_into_detected_repo(tmp_path: Path) -> None:
    # Un repo real que a su vez contiene un submódulo con su propio .git:
    # el submódulo no debe aparecer como candidato independiente.
    repo_path = tmp_path / "project-with-submodule"
    _make_git_repo(repo_path)
    _make_git_repo(repo_path / "vendor" / "some-submodule")

    projects = discover_projects(tmp_path)

    assert len(projects) == 1
    assert projects[0].path == str(repo_path)


def test_discover_projects_detects_root_itself_when_it_is_a_repo(
    tmp_path: Path,
) -> None:
    (tmp_path / ".git").mkdir()

    projects = discover_projects(tmp_path)

    assert len(projects) == 1
    assert projects[0].path == str(tmp_path)


def test_discover_projects_returns_alphabetical_order_when_created_unsorted(
    tmp_path: Path,
) -> None:
    # Repos creados en orden no alfabético (zeta antes que alfa): el orden
    # de os.walk en el filesystem no debe determinar el resultado.
    _make_git_repo(tmp_path / "zeta")
    _make_git_repo(tmp_path / "mike")
    _make_git_repo(tmp_path / "alfa")

    projects = discover_projects(tmp_path)

    assert [project.name for project in projects] == ["alfa", "mike", "zeta"]


def test_discover_projects_sort_is_case_insensitive(tmp_path: Path) -> None:
    # Orden alfabético case-insensitive: las mayúsculas no deben adelantar
    # nombres en minúscula que alfabéticamente van antes.
    _make_git_repo(tmp_path / "Bravo")
    _make_git_repo(tmp_path / "alfa")
    _make_git_repo(tmp_path / "Charlie")

    projects = discover_projects(tmp_path)

    assert [project.name for project in projects] == ["alfa", "Bravo", "Charlie"]
