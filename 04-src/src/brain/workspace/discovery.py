import os
from pathlib import Path

from brain.models import Project
from brain.storage.workspace_store import resolve_workspace_id
from brain.workspace.discovery_cache import TTLCache

# Directorios cuyo contenido nunca debe recorrerse en busca de repositorios:
# no son proyectos de trabajo del desarrollador, son artefactos de
# dependencias o infraestructura interna que pueden contener su propio
# `.git` (submódulos, paquetes vendorizados) sin representar un proyecto real.
# Red de seguridad explícita: el recorrido ya excluye todo directorio oculto
# (nombre que empieza por `.`) de forma general, así que las entradas `.venv`
# y `.git` quedan cubiertas por esa regla; se conservan por claridad y
# defensa en profundidad junto con los nombres no ocultos (node_modules, venv,
# __pycache__) que sí requieren esta lista.
_EXCLUDED_DIR_NAMES = {
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".git",
}


def is_git_repository(directory: Path) -> bool:
    return (directory / ".git").exists()


# Caché TTL (T-FB001-US01-06): `discover_projects` recorre el filesystem
# completo (`os.walk`) — verificado ~90ms en un workspace real grande — y la
# API lo invoca de nuevo en cada request (`GET /projects`, `POST /project`).
# La caché por `root` absorbe ráfagas de requests sin repetir el recorrido,
# y un TTL corto (5s) evita servir datos obsoletos por más de unos segundos.
# Los errores de `os.walk` NO se cachean (la excepción se propaga).
_PROJECTS_CACHE = TTLCache()


def invalidate_discovery_cache() -> None:
    """Vacía la caché de discovery de proyectos — se llama al cambiar de
    proyecto activo (`POST /project`, T-FB001-US01-06) para que el catálogo
    del nuevo proyecto se refleje sin esperar al TTL anterior."""
    _PROJECTS_CACHE.invalidate()


def discover_projects(
    root: Path,
    *,
    workspace_id: str | None = None,
    state_dir: Path | None = None,
) -> list[Project]:
    """Descubre los repositorios Git bajo `root` y los etiqueta con el
    Workspace al que pertenecen (T-FB001-US02-02).

    El Workspace de un proyecto descubierto es el de la raíz de
    descubrimiento: se resuelve con `resolve_workspace_id` — el Workspace
    registrado para `root` si existe (CRUD de T-FB001-US02-01), o un id
    determinista derivado de la ruta para el workspace implícito. `workspace_id`
    permite sobreescribir la resolución si el llamador ya conoce el Workspace.
    """
    ws_id = (
        workspace_id
        if workspace_id is not None
        else resolve_workspace_id(root, state_dir=state_dir)
    )
    # `cache_if=bool`: no se cachea un escaneo vacío (sin repos). Un escaneo
    # vacío es barato de recomputar y representa un estado transitorio — un
    # repo puede aparecer en cualquier momento (el `_lifespan` del backend
    # escanea el workspace al arrancar, cuando aún puede estar vacío), y
    # cachearlo ocultaría el cambio hasta el TTL.
    #
    # `validate` (subdirectorios de primer nivel del root): aunque una
    # entrada siga dentro del TTL, si el contenido observado del directorio
    # cambió (un repo creado o borrado a primer nivel, el patrón real en uso
    # y en tests), la entrada se descarta y se recomputa al instante sin
    # esperar al TTL. Se compara el SET de subdirectorios de primer nivel:
    # un `os.scandir` O(n) barato, fiable e independiente de la resolución
    # temporal del filesystem (a diferencia de un mtime, que puede no
    # detectar un borrado ocurrido en la misma marca de tiempo).
    baseline: list[frozenset[str]] = [frozenset()]

    def compute() -> list[Project]:
        baseline[0] = _first_level_dir_names(root)
        return _discover_projects_walk(root, ws_id)

    def validate() -> bool:
        return _first_level_dir_names(root) == baseline[0]

    # La clave de caché incluye `ws_id` (no solo `root`): el Workspace al que
    # pertenecen los proyectos puede cambiar sin que cambie el filesystem —
    # p. ej. al registrar vía el CRUD (T-FB001-US02-01) un Workspace para una
    # raíz que antes era implícita. Sin `ws_id` en la clave, la entrada con la
    # asociación antigua seguiría sirviéndose hasta el TTL.
    return _PROJECTS_CACHE.get_or_compute(
        f"{root}|{ws_id}", compute, cache_if=bool, validate=validate
    )


def _first_level_dir_names(path: Path) -> frozenset[str]:
    """Nombres de los subdirectorios de primer nivel de `path` (barato,
    `os.scandir`; `None` src del directorio vía exception = no existe)."""
    try:
        return frozenset(
            entry.name for entry in path.iterdir() if entry.is_dir()
        )
    except OSError:
        return frozenset()


def _discover_projects_walk(root: Path, workspace_id: str) -> list[Project]:
    """Recorrido real del filesystem (`os.walk`) con la lógica original de
    discovery — extraído a esta función privada para que `discover_projects`
    lo envuelva con la caché TTL sin tocar ningún comportamiento: exclusión
    de directorios internos y ocultos, detección de `.git`, no descender
    dentro de un repo ya detectado, y orden alfabético case-insensitive."""
    projects: list[Project] = []

    if not root.exists() or not root.is_dir():
        return projects

    for current_dir, subdir_names, _file_names in os.walk(root):
        current_path = Path(current_dir)

        # Poda in-place: os.walk no descenderá a estos subdirectorios.
        # Además de la lista explícita de nombres internos, se excluye todo
        # directorio oculto (nombre que empieza por `.`): son infraestructura
        # interna (p. ej. `.brain`, `.venv`, `.git`) que puede contener su
        # propio `.git` sin representar un proyecto de trabajo real.
        subdir_names[:] = [
            name
            for name in subdir_names
            if name not in _EXCLUDED_DIR_NAMES and not name.startswith(".")
        ]

        if is_git_repository(current_path):
            projects.append(
                Project(
                    id=str(current_path),
                    name=current_path.name,
                    path=str(current_path),
                    repository="",
                    workspace_id=workspace_id,
                )
            )
            # Un repositorio no contiene otros repositorios de trabajo
            # dentro de sí mismo (salvo submódulos, ya excluidos arriba):
            # no seguir descendiendo una vez detectado.
            subdir_names[:] = []

    # Orden estable y predecible: `os.walk` recorre el filesystem en el
    # orden de entradas del directorio (no determinista ni alfabético).
    # Se ordena por `name` case-insensitive antes de devolver, para que la
    # pantalla Workspace presente los proyectos siempre igual (T-FB001-US01-05).
    projects.sort(key=lambda project: project.name.casefold())

    return projects
