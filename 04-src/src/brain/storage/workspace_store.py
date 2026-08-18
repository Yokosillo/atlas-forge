import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

from brain.models import Workspace

# Mecanismo de persistencia (T-FB001-US02-01):
#
# Decision explícita, siguiendo el criterio ya que aplicamos en
# T-FB001-US01-01 (ficha simple JSON en lugar de SQLite):
#
# docs/concepts.md sitúa `Workspace` por encima de `Project`
# y `Development Session`, pero en este Task (T-FB001-US02-01) el Workspace
# todavía se gestiona como entidad aislada: crear/consultar/modificar/eliminar
# sobre su propio catálogo. La asociación del proyecto activo a un Workspace
# concreto es trabajo de la siguiente Task (T-FB001-US02-02), momento en que
# Project pasará a referenciar `workspace_id`. Por tanto, hoy no existen aún
# varias entidades con relaciones reales entre sí que requieran un motor de
# base de datos: la validación de dependencias para el borrado se resuelve en
# la frontera de llamada, pasándole qué proyectos/sesiones pertenecen al
# workspace, sin necesitar consultas relacionales.
#
# Un fichero JSON simple (catálogo de workspaces) es suficiente, legible e
# inspeccionable a mano. SQLite se justificará cuando existan entidades
# relacionadas persistidas conjuntamente (p. ej. Project.workspace_id tras
# T-FB001-US02-02, o el índice de FB-007 Knowledge Engine), no para este caso.


class WorkspaceNotFoundError(KeyError):
    """El workspace solicitado no existe en el catálogo persistido."""


class WorkspaceAlreadyExistsError(ValueError):
    """Ya existe un workspace con ese identificador."""


class WorkspaceHasActiveDependenciesError(ValueError):
    """No se puede eliminar un workspace con proyectos o sesiones activas."""


def _default_state_dir() -> Path:
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg_data_home) if xdg_data_home else Path.home() / ".local" / "share"
    return base / "brain"


def _workspaces_file(state_dir: Path | None = None) -> Path:
    directory = state_dir if state_dir is not None else _default_state_dir()
    return directory / "workspaces.json"


def _load_all(state_dir: Path | None = None) -> list[dict]:
    path = _workspaces_file(state_dir)
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _persist_all(state_dir: Path | None, workspaces: list[dict]) -> None:
    path = _workspaces_file(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(workspaces), encoding="utf-8")


def find_workspace_by_path(
    path: Path, *, state_dir: Path | None = None
) -> Workspace | None:
    """Devuelve el workspace registrado cuyo `path` coincide exactamente con
    `path`, o `None` si ninguno está registrado para esa ubicación."""
    target = str(path)
    for item in _load_all(state_dir):
        if item["path"] == target:
            return _to_workspace(item)
    return None


def derive_workspace_id(path: Path) -> str:
    """Identificador determinista y estable para un workspace implícito o
    no registrado todavía (T-FB001-US02-02): derivado del path absoluto.

    Cuando no existe un Workspace registrado (fichero de CRUD) para la raíz
    de descubrimiento, el proyecto activo sigue necesitando una asociación
    estable entre ejecuciones. Este id permite mantener la asociación sin
    efectos secundarios de escritura en un camino de solo lectura (discovery)
    y sin contaminar el estado real desde tests — la misma ruta absoluta
    produce siempre el mismo id. En cuanto el usuario registra el Workspace
    con ese path vía el CRUD (T-FB001-US02-01), `resolve_workspace_id` pasa a
    devolver su id real y las asociaciones posteriores usan ese id."""
    resolved = str(path.resolve())
    digest = hashlib.sha1(resolved.encode("utf-8")).hexdigest()
    return f"ws-{digest[:12]}"


def resolve_workspace_id(path: Path, *, state_dir: Path | None = None) -> str:
    """Resuelve el id del Workspace al que pertenece `path`.

    Prioridad: (1) un Workspace registrado cuyo `path` coincide exactamente;
    (2) el Workspace registrado cuyo path es el ancestro más cercano de
    `path` (caso de un proyecto dentro de la raíz de un Workspace registrado,
    p. ej. al migrar un proyecto activo antiguo); (3) `derive_workspace_id`
    para el workspace implícito aún no registrado."""
    items = _load_all(state_dir)
    target = str(path)
    for item in items:
        if item["path"] == target:
            return item["id"]

    for parent in path.parents:
        parent_str = str(parent)
        for item in items:
            if item["path"] == parent_str:
                return item["id"]

    return derive_workspace_id(path)


def _to_workspace(payload: dict) -> Workspace:
    return Workspace(
        id=payload["id"],
        name=payload["name"],
        description=payload["description"],
        path=payload["path"],
    )


def create_workspace(
    id: str,
    name: str,
    description: str,
    path: str,
    *,
    state_dir: Path | None = None,
) -> Workspace:
    workspaces = _load_all(state_dir)
    if any(item["id"] == id for item in workspaces):
        raise WorkspaceAlreadyExistsError(
            f"Ya existe un workspace con id='{id}'. El identificador debe ser único."
        )

    workspace = Workspace(
        id=id, name=name, description=description, path=path
    )
    workspaces.append(asdict(workspace))
    _persist_all(state_dir, workspaces)
    return workspace


def list_workspaces(state_dir: Path | None = None) -> list[Workspace]:
    return [_to_workspace(item) for item in _load_all(state_dir)]


def get_workspace(id: str, *, state_dir: Path | None = None) -> Workspace:
    for item in _load_all(state_dir):
        if item["id"] == id:
            return _to_workspace(item)
    raise WorkspaceNotFoundError(f"No existe un workspace con id='{id}'.")


def update_workspace(
    id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    path: str | None = None,
    state_dir: Path | None = None,
) -> Workspace:
    workspaces = _load_all(state_dir)
    for index, item in enumerate(workspaces):
        if item["id"] == id:
            if name is not None:
                item["name"] = name
            if description is not None:
                item["description"] = description
            if path is not None:
                item["path"] = path
            workspaces[index] = item
            _persist_all(state_dir, workspaces)
            return _to_workspace(item)

    raise WorkspaceNotFoundError(f"No existe un workspace con id='{id}'.")


def delete_workspace(
    id: str,
    *,
    dependent_project_ids: Sequence[str] = (),
    dependent_session_ids: Sequence[str] = (),
    state_dir: Path | None = None,
) -> None:
    """Elimina el workspace `id` del catálogo.

    Valida previamente que no existan dependencias activas: si se pasan
    proyectos o sesiones asociadas a este workspace (`dependent_project_ids`,
    `dependent_session_ids`), el borrado se rechaza con un motivo explícito.
    Es la frontera de llamada quien determina qué pertenece al workspace,
    puesto que la asociación Project.workspace_id / sessión se modela en
    Tasks posteriores (T-FB001-US02-02).
    """
    if dependent_project_ids or dependent_session_ids:
        raise WorkspaceHasActiveDependenciesError(
            f"No se puede eliminar el workspace '{id}': tiene dependencias "
            f"activas (proyectos: {sorted(dependent_project_ids)}, "
            f"sesiones: {sorted(dependent_session_ids)}). Cierra o desasocia "
            "esas dependencias antes de eliminar el workspace."
        )

    workspaces = _load_all(state_dir)
    remaining = [item for item in workspaces if item["id"] != id]
    if len(remaining) == len(workspaces):
        raise WorkspaceNotFoundError(f"No existe un workspace con id='{id}'.")

    _persist_all(state_dir, remaining)