from dataclasses import dataclass
from pathlib import Path

from atlas_forge.models import Project
from atlas_forge.workspace.active_project import get_active_project
from atlas_forge.workspace.discovery import discover_projects, is_git_repository


@dataclass(frozen=True)
class ProjectRecovered:
    """El proyecto activo persistido sigue siendo válido y se recupera
    automáticamente sin intervención del usuario."""

    project: Project


@dataclass(frozen=True)
class ProjectSelectionRequired:
    """No hay ningún proyecto activo persistido (primera ejecución): el
    usuario debe elegir uno de los repositorios descubiertos."""

    discovered: list[Project]


@dataclass(frozen=True)
class ProjectSelectionRequiredAfterInvalid:
    """El proyecto activo persistido ya no es válido (ruta movida o
    borrada, o ya no es un repositorio Git): se informa el motivo y se
    ofrece la lista de repositorios descubiertos para elegir otro."""

    discovered: list[Project]
    invalid_project: Project
    reason: str


StartupOutcome = (
    ProjectRecovered | ProjectSelectionRequired | ProjectSelectionRequiredAfterInvalid
)


def _validate_persisted_project(project: Project) -> str | None:
    """Devuelve `None` si el proyecto persistido sigue siendo un repositorio
    Git válido, o un mensaje explicando por qué ya no lo es."""
    path = Path(project.path)

    if not path.exists():
        return f"La ruta '{project.path}' ya no existe."
    if not path.is_dir():
        return f"La ruta '{project.path}' ya no es un directorio."
    if not is_git_repository(path):
        return f"'{project.path}' ya no es un repositorio Git."

    return None


def resolve_startup_project(
    workspace_root: Path | None = None, state_dir: Path | None = None
) -> StartupOutcome:
    """Resuelve qué proyecto debe quedar activo al arrancar Atlas Forge.

    No lanza excepción en ningún caso: cualquier fallo de validación se
    devuelve como parte del resultado tipado (`ProjectSelectionRequiredAfterInvalid`),
    para que quien llame pueda informar al usuario sin bloquear el arranque.
    """
    root = workspace_root if workspace_root is not None else Path.cwd()

    persisted = get_active_project(state_dir=state_dir)

    if persisted is None:
        return ProjectSelectionRequired(discovered=discover_projects(root, state_dir=state_dir))

    invalid_reason = _validate_persisted_project(persisted)
    if invalid_reason is not None:
        return ProjectSelectionRequiredAfterInvalid(
            discovered=discover_projects(root, state_dir=state_dir),
            invalid_project=persisted,
            reason=invalid_reason,
        )

    return ProjectRecovered(project=persisted)
