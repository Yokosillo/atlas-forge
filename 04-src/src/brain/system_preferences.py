"""Persistencia de preferencias de sistema (US-FB024-12): valores
operativos configurables desde la interfaz web en vez de constantes fijas
en codigo — mismo patron que `model_preferences.py` (T-FB022-US10-01),
mismo `state_dir` de Factory Brain.

Diseñado como un diccionario abierto de claves, no como un unico campo
hardcodeado: el primer valor es `max_simultaneous_developers`, pero
añadir un segundo valor configurable en el futuro (timeout de Job, umbral
de Scribe...) no debe requerir cambiar el esquema del fichero ni la forma
del endpoint que lo expone.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_MAX_SIMULTANEOUS_DEVELOPERS = 3


def _default_state_dir() -> Path:
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg_data_home) if xdg_data_home else Path.home() / ".local" / "share"
    return base / "brain"


def _preferences_file(state_dir: Path | None = None) -> Path:
    directory = state_dir if state_dir is not None else _default_state_dir()
    return directory / "system_preferences.json"


def load_system_preferences(
    state_dir: Path | None = None,
) -> dict:
    """Carga las preferencias de sistema desde `state_dir`.
    Si el fichero no existe, devuelve los valores por defecto (vacio =
    "usa el default de cada valor", mismo criterio que `model_preferences`)."""
    path = _preferences_file(state_dir)
    if not path.exists():
        return {
            "max_simultaneous_developers": DEFAULT_MAX_SIMULTANEOUS_DEVELOPERS,
        }
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        "max_simultaneous_developers": payload.get(
            "max_simultaneous_developers", DEFAULT_MAX_SIMULTANEOUS_DEVELOPERS
        ),
    }


def save_system_preferences(
    preferences: dict,
    state_dir: Path | None = None,
) -> None:
    """Guarda las preferencias de sistema en `state_dir`.

    `preferences` debe ser un dict con:
    - `max_simultaneous_developers`: int > 0 — limite de Developer
      simultaneos (default `DEFAULT_MAX_SIMULTANEOUS_DEVELOPERS` si no se
      indica).
    """
    path = _preferences_file(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "max_simultaneous_developers": preferences.get(
            "max_simultaneous_developers", DEFAULT_MAX_SIMULTANEOUS_DEVELOPERS
        ),
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def get_max_simultaneous_developers(state_dir: Path | None = None) -> int:
    """Atajo para `register_developer`: solo el limite resuelto, sin que
    el llamador tenga que conocer la forma completa del diccionario de
    preferencias."""
    return load_system_preferences(state_dir=state_dir)["max_simultaneous_developers"]
