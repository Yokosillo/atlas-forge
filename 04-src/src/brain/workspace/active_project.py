from pathlib import Path

from brain.models import Project
from brain.storage import load_active_project, save_active_project
from brain.workspace.discovery import discover_projects


class ProjectNotDiscoveredError(ValueError):
    """El proyecto indicado no pertenece a la lista de repositorios descubiertos."""


def select_active_project(
    project: Project,
    discovered: list[Project] | None = None,
    workspace_root: Path | None = None,
    state_dir: Path | None = None,
) -> None:
    """Marca `project` como proyecto activo, validando que pertenece a los
    repositorios descubiertos, y persiste la selección sustituyendo
    cualquiera anterior.

    La lista de descubiertos puede pasarse directamente (`discovered`) o
    recalcularse a partir de `workspace_root` usando `discover_projects`
    (T-FB001-US01-02). Si no se indica ninguno de los dos, se usa el
    directorio de trabajo actual como raíz del workspace.
    """
    if discovered is None:
        root = workspace_root if workspace_root is not None else Path.cwd()
        discovered = discover_projects(root, state_dir=state_dir)

    if project.id not in {candidate.id for candidate in discovered}:
        raise ProjectNotDiscoveredError(
            f"El proyecto '{project.name}' ({project.path}) no pertenece a "
            "la lista de repositorios descubiertos."
        )

    save_active_project(project, state_dir=state_dir)


def get_active_project(state_dir: Path | None = None) -> Project | None:
    """Consulta el proyecto activo actual (nombre, ruta, repositorio), o
    `None` si no hay ninguno seleccionado todavía."""
    return load_active_project(state_dir=state_dir)
