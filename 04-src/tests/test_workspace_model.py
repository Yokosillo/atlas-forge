from brain.models import Workspace


def test_workspace_construction() -> None:
    workspace = Workspace(
        id="ws-1",
        name="cliente-alfa",
        description="Entorno de trabajo del cliente Alfa",
        path="/home/dev/alfa",
    )

    assert workspace.id == "ws-1"
    assert workspace.name == "cliente-alfa"
    assert workspace.description == "Entorno de trabajo del cliente Alfa"
    assert workspace.path == "/home/dev/alfa"


def test_workspace_is_immutable() -> None:
    workspace = Workspace(
        id="ws-1",
        name="cliente-alfa",
        description="Entorno de trabajo del cliente Alfa",
        path="/home/dev/alfa",
    )

    try:
        workspace.name = "otro"
    except Exception:
        pass
    else:
        raise AssertionError("Workspace debe ser inmutable (frozen dataclass).")

    assert workspace.name == "cliente-alfa"