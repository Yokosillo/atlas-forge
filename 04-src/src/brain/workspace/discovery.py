import os
from pathlib import Path

from brain.models import Project

# Directorios cuyo contenido nunca debe recorrerse en busca de repositorios:
# no son proyectos de trabajo del desarrollador, son artefactos de
# dependencias o infraestructura interna que pueden contener su propio
# `.git` (submódulos, paquetes vendorizados) sin representar un proyecto real.
_EXCLUDED_DIR_NAMES = {
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".git",
}


def is_git_repository(directory: Path) -> bool:
    return (directory / ".git").exists()


def discover_projects(root: Path) -> list[Project]:
    projects: list[Project] = []

    if not root.exists() or not root.is_dir():
        return projects

    for current_dir, subdir_names, _file_names in os.walk(root):
        current_path = Path(current_dir)

        # Poda in-place: os.walk no descenderá a estos subdirectorios.
        subdir_names[:] = [
            name for name in subdir_names if name not in _EXCLUDED_DIR_NAMES
        ]

        if is_git_repository(current_path):
            projects.append(
                Project(
                    id=str(current_path),
                    name=current_path.name,
                    path=str(current_path),
                    repository="",
                )
            )
            # Un repositorio no contiene otros repositorios de trabajo
            # dentro de sí mismo (salvo submódulos, ya excluidos arriba):
            # no seguir descendiendo una vez detectado.
            subdir_names[:] = []

    return projects
