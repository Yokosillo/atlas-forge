import json
import os
from pathlib import Path

from atlas_forge.models import Project
from atlas_forge.storage.workspace_store import resolve_workspace_id

# Justificación del mecanismo de almacenamiento (T-AF001-US01-01):
#
# docs/concepts.md sitúa `Project` bajo `Workspace`, pero no
# obliga a ninguna tecnología concreta de persistencia. En el alcance v1 de
# AF-001 (ver 02-backlog/epics/AF-001-workspace-management.md) el Workspace es
# implícito y solo hay un dato real que persistir entre ejecuciones: cuál es
# el proyecto activo. Un motor de base de datos (SQLite) introduciría un
# esquema, migraciones y una capa de consultas para almacenar una única
# clave-valor — sobreingeniería para este alcance. Un fichero JSON simple es
# suficiente, legible por el propio usuario y trivial de inspeccionar/borrar
# a mano si algo se corrompe. SQLite se justificará cuando existan entidades
# con relaciones reales entre sí (Job/Pipeline/Task de AF-008, o el índice de
# AF-007 Knowledge Engine), no para este caso.


def _default_state_dir() -> Path:
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg_data_home) if xdg_data_home else Path.home() / ".local" / "share"
    return base / "atlas_forge"


def _active_project_file(state_dir: Path | None = None) -> Path:
    directory = state_dir if state_dir is not None else _default_state_dir()
    return directory / "active_project.json"


def save_active_project(project: Project, state_dir: Path | None = None) -> None:
    path = _active_project_file(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "id": project.id,
        "name": project.name,
        "path": project.path,
        "repository": project.repository,
        "workspace_id": project.workspace_id,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def load_active_project(state_dir: Path | None = None) -> Project | None:
    path = _active_project_file(state_dir)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    # Migración T-AF001-US02-02: un proyecto activo persistido antes de esta
    # Task no tiene `workspace_id`. Se resuelve en lugar de romper con una
    # excepción al leer el formato anterior: el Workspace registrado para su
    # ubicación (path exacto o ancestro) si existe, o un id determinista
    # derivado del path (workspace implícito) si todavía no hay ninguno
    # registrado. Al guardar de nuevo el proyecto activo, el formato nuevo
    # (con `workspace_id`) sustituye al antiguo.
    workspace_id = payload.get("workspace_id")
    if workspace_id is None:
        workspace_id = resolve_workspace_id(
            Path(payload["path"]), state_dir=state_dir
        )
    return Project(
        id=payload["id"],
        name=payload["name"],
        path=payload["path"],
        repository=payload["repository"],
        workspace_id=workspace_id,
    )
