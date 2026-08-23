"""Tests de T-AF001-US02-02: el proyecto activo pasa a pertenecer a un
Workspace explícito (`Project.workspace_id`), con migración del formato
persistido anterior (sin `workspace_id`) que no rompe la lectura."""

import json
from pathlib import Path

from atlas_forge.storage import (
    create_workspace,
    derive_workspace_id,
    list_workspaces,
    load_active_project,
    resolve_workspace_id,
)
from atlas_forge.workspace import (
    discover_projects,
    get_active_project,
    select_active_project,
)


def _make_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()


def test_discovered_projects_carry_a_non_empty_workspace_id(tmp_path: Path) -> None:
    _make_git_repo(tmp_path / "project-a")
    _make_git_repo(tmp_path / "project-b")

    projects = discover_projects(tmp_path)

    assert len(projects) == 2
    for project in projects:
        assert project.workspace_id
    # Todos los proyectos descubiertos bajo la misma raíz comparten el
    # mismo Workspace.
    assert len({project.workspace_id for project in projects}) == 1
    assert projects[0].workspace_id == resolve_workspace_id(
        tmp_path, state_dir=tmp_path
    )


def test_discovery_uses_the_registered_workspace_id_for_the_root(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    workspace = tmp_path / "workspace"
    _make_git_repo(workspace / "project-a")

    create_workspace(
        id="ws-alfa",
        name="cliente-alfa",
        description="Entorno del cliente Alfa",
        path=str(workspace),
        state_dir=state_dir,
    )

    projects = discover_projects(workspace, state_dir=state_dir)

    assert projects[0].workspace_id == "ws-alfa"


def test_select_active_project_persists_the_workspace_id(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    _make_git_repo(tmp_path / "project-a")
    discovered = discover_projects(tmp_path, state_dir=state_dir)
    selected = discovered[0]

    select_active_project(selected, discovered=discovered, state_dir=state_dir)

    stored = json.loads(
        (state_dir / "active_project.json").read_text(encoding="utf-8")
    )
    assert stored["workspace_id"] == selected.workspace_id
    assert load_active_project(state_dir=state_dir) == selected


def test_load_active_project_migrates_legacy_format_without_workspace_id(
    tmp_path: Path,
) -> None:
    """Un proyecto activo persistido antes de T-AF001-US02-02 no tenía
    `workspace_id`: seguir leyéndolo no debe lanzar excepción no controlada
    ni dejar el campo sin asociar."""
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    legacy = {
        "id": str(tmp_path / "project-a"),
        "name": "project-a",
        "path": str(tmp_path / "project-a"),
        "repository": "",
    }
    (state_dir / "active_project.json").write_text(
        json.dumps(legacy), encoding="utf-8"
    )

    project = load_active_project(state_dir=state_dir)

    assert project is not None
    assert project.id == legacy["id"]
    assert project.name == "project-a"
    assert project.workspace_id  # siempre asociado a un Workspace


def test_resolve_workspace_id_prefers_registered_exact_path(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    create_workspace(
        id="ws-beta",
        name="cliente-beta",
        description="Entorno del cliente Beta",
        path=str(tmp_path),
        state_dir=state_dir,
    )

    assert resolve_workspace_id(tmp_path, state_dir=state_dir) == "ws-beta"


def test_resolve_workspace_id_falls_back_to_nearest_ancestor(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    root = tmp_path / "workspace"
    create_workspace(
        id="ws-alfa",
        name="cliente-alfa",
        description="Entorno del cliente Alfa",
        path=str(root),
        state_dir=state_dir,
    )

    # Un proyecto dentro del Workspace registrado (p. ej. al migrar un
    # proyecto activo antiguo) resuelve al Workspace ancestro, no a un id
    # derivado.
    project_path = root / "nested" / "project-a"
    assert resolve_workspace_id(project_path, state_dir=state_dir) == "ws-alfa"


def test_resolve_workspace_id_derives_deterministically_for_unregistered_root(
    tmp_path: Path,
) -> None:
    assert resolve_workspace_id(tmp_path, state_dir=tmp_path / "state") == (
        derive_workspace_id(tmp_path)
    )
    assert list_workspaces(state_dir=tmp_path / "state") == []


def test_get_active_project_preserves_the_workspace_id(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    _make_git_repo(tmp_path / "project-a")
    discovered = discover_projects(tmp_path, state_dir=state_dir)

    select_active_project(discovered[0], discovered=discovered, state_dir=state_dir)
    active = get_active_project(state_dir=state_dir)

    assert active is not None
    assert active.workspace_id == discovered[0].workspace_id