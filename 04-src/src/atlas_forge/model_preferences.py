"""Persistencia de preferencias de modelos (T-AF022-US10-01): que modelos
estan habilitados y que modelo es el default por rol, separado del fichero
de catalogo (`models.yml`) que es la lista completa de modelos disponibles.

Las preferencias viven en `model_preferences.json` dentro del `state_dir`
de Atlas Forge (misma ubicacion que `active_project.json`) — son estado
editable desde la interfaz web, no desde edicion manual del YAML.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def _default_state_dir() -> Path:
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg_data_home) if xdg_data_home else Path.home() / ".local" / "share"
    return base / "atlas_forge"


def _preferences_file(state_dir: Path | None = None) -> Path:
    directory = state_dir if state_dir is not None else _default_state_dir()
    return directory / "model_preferences.json"


def load_model_preferences(
    state_dir: Path | None = None,
) -> dict:
    """Carga las preferencias de modelos desde `state_dir`.
    Si el fichero no existe, devuelve los valores por defecto:
    todos los modelos del catalogo habilitados, sin defaults por rol."""
    path = _preferences_file(state_dir)
    if not path.exists():
        return {
            "enabled_model_ids": [],  # vacio = "todos habilitados"
            "default_model_by_role": {},
        }
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        "enabled_model_ids": payload.get("enabled_model_ids", []),
        "default_model_by_role": payload.get("default_model_by_role", {}),
    }


def save_model_preferences(
    preferences: dict,
    state_dir: Path | None = None,
) -> None:
    """Guarda las preferencias de modelos en `state_dir`.

    `preferences` debe ser un dict con:
    - `enabled_model_ids`: list[str] — IDs de modelos habilitados
      (vacio = todos habilitados).
    - `default_model_by_role`: dict[str, str] — rol -> modelo default
      (vacio = sin defaults).
    """
    path = _preferences_file(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "enabled_model_ids": preferences.get("enabled_model_ids", []),
        "default_model_by_role": preferences.get("default_model_by_role", {}),
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
