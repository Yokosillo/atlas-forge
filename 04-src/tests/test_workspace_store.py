from pathlib import Path

import pytest

from brain.models import Workspace
from brain.storage import (
    WorkspaceAlreadyExistsError,
    WorkspaceHasActiveDependenciesError,
    WorkspaceNotFoundError,
    create_workspace,
    delete_workspace,
    get_workspace,
    list_workspaces,
    update_workspace,
)


def _base_workspace() -> dict:
    return {
        "id": "ws-1",
        "name": "cliente-alfa",
        "description": "Entorno de trabajo del cliente Alfa",
        "path": "/home/dev/alfa",
    }


def test_create_get_and_list_workspace(tmp_path: Path) -> None:
    created = create_workspace(
        id="ws-1",
        name="cliente-alfa",
        description="Entorno de trabajo del cliente Alfa",
        path="/home/dev/alfa",
        state_dir=tmp_path,
    )

    assert isinstance(created, Workspace)
    assert created.id == "ws-1"
    assert created.name == "cliente-alfa"

    fetched = get_workspace("ws-1", state_dir=tmp_path)
    assert fetched == created

    listed = list_workspaces(state_dir=tmp_path)
    assert listed == [created]


def test_get_missing_workspace_raises_controlled_error(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceNotFoundError):
        get_workspace("no-existe", state_dir=tmp_path)


def test_create_duplicate_workspace_is_rejected(tmp_path: Path) -> None:
    create_workspace(state_dir=tmp_path, **_base_workspace())
    with pytest.raises(WorkspaceAlreadyExistsError):
        create_workspace(state_dir=tmp_path, **_base_workspace())


def test_update_workspace(tmp_path: Path) -> None:
    create_workspace(state_dir=tmp_path, **_base_workspace())

    updated = update_workspace(
        "ws-1",
        name="cliente-alfa-v2",
        description="Descripción actualizada",
        path="/home/dev/alfa",
        state_dir=tmp_path,
    )

    assert updated.name == "cliente-alfa-v2"
    assert updated.description == "Descripción actualizada"
    assert get_workspace("ws-1", state_dir=tmp_path) == updated


def test_delete_workspace_without_dependencies(tmp_path: Path) -> None:
    create_workspace(state_dir=tmp_path, **_base_workspace())

    delete_workspace("ws-1", state_dir=tmp_path)

    assert list_workspaces(state_dir=tmp_path) == []
    with pytest.raises(WorkspaceNotFoundError):
        get_workspace("ws-1", state_dir=tmp_path)


def test_delete_workspace_with_active_project_is_rejected(tmp_path: Path) -> None:
    create_workspace(state_dir=tmp_path, **_base_workspace())

    with pytest.raises(WorkspaceHasActiveDependenciesError) as excinfo:
        delete_workspace(
            "ws-1",
            dependent_project_ids=["proyecto-en-uso"],
            state_dir=tmp_path,
        )

    message = str(excinfo.value)
    assert "ws-1" in message
    assert "proyecto-en-uso" in message

    # El workspace sigue existiendo tras el rechazo.
    assert get_workspace("ws-1", state_dir=tmp_path).id == "ws-1"


def test_delete_workspace_with_active_session_is_rejected(tmp_path: Path) -> None:
    create_workspace(state_dir=tmp_path, **_base_workspace())

    with pytest.raises(WorkspaceHasActiveDependenciesError) as excinfo:
        delete_workspace(
            "ws-1",
            dependent_session_ids=["session-en-uso"],
            state_dir=tmp_path,
        )

    assert "session-en-uso" in str(excinfo.value)
    assert get_workspace("ws-1", state_dir=tmp_path).id == "ws-1"


def test_workspace_round_trip_persists_between_runs(tmp_path: Path) -> None:
    create_workspace(state_dir=tmp_path, **_base_workspace())

    # Recargar desde disco en una segunda "ejecución".
    reloaded = list_workspaces(state_dir=tmp_path)
    assert len(reloaded) == 1
    assert reloaded[0].id == "ws-1"
    assert reloaded[0].name == "cliente-alfa"
    assert reloaded[0].path == "/home/dev/alfa"

    # Y un segundo workspace, también recuperable.
    create_workspace(
        id="ws-2",
        name="cliente-beta",
        description="Entorno de trabajo del cliente Beta",
        path="/home/dev/beta",
        state_dir=tmp_path,
    )
    assert [w.id for w in list_workspaces(state_dir=tmp_path)] == ["ws-1", "ws-2"]