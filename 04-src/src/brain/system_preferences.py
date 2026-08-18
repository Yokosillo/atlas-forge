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
# T-FB008-US12-01: mapeo dificultad → tier mínimo requerido del modelo
DEFAULT_DIFFICULTY_MODEL_MAP = {
    "Baja": 1,      # Baja dificultad: tier 1 (modelos básicos)
    "Media": 2,     # Media dificultad: tier 2
    "Alta": 4,      # Alta dificultad: tier 4
    "Crítica": 5,   # Crítica dificultad: tier 5 (modelos avanzados)
}
# T-FB002-US04-01: gate de arranque de la TUI por seguridad
DEFAULT_TUI_ENABLED = False
# T-FB008-US14-02: si True (decisión de producto explícita, 2026-08-17),
# el Developer que cierra una Task no se considera `idle` para el
# reparto de Tasks nuevas mientras esa Task siga en REVIEW (esperando al
# Tester) — evita que certifique su propio trabajo cogiendo ya la
# siguiente Task mientras la anterior aún puede volver con una
# corrección. Configurable a futuro desde Configuración (fuera de
# alcance de esta Task); por ahora solo el valor por defecto real.
DEFAULT_DEVELOPER_WAITS_FOR_TESTER_REVIEW = True


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
            "difficulty_model_map": DEFAULT_DIFFICULTY_MODEL_MAP,
            "tui_enabled": DEFAULT_TUI_ENABLED,
            "developer_waits_for_tester_review": DEFAULT_DEVELOPER_WAITS_FOR_TESTER_REVIEW,
        }
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        "max_simultaneous_developers": payload.get(
            "max_simultaneous_developers", DEFAULT_MAX_SIMULTANEOUS_DEVELOPERS
        ),
        "difficulty_model_map": payload.get(
            "difficulty_model_map", DEFAULT_DIFFICULTY_MODEL_MAP
        ),
        "tui_enabled": payload.get(
            "tui_enabled", DEFAULT_TUI_ENABLED
        ),
        "developer_waits_for_tester_review": payload.get(
            "developer_waits_for_tester_review", DEFAULT_DEVELOPER_WAITS_FOR_TESTER_REVIEW
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
    - `difficulty_model_map`: dict difficulty → tier mínimo (default
      `DEFAULT_DIFFICULTY_MODEL_MAP` si no se indica).
    - `tui_enabled`: bool — gate de arranque de la TUI (default
      `DEFAULT_TUI_ENABLED` si no se indica).
    - `developer_waits_for_tester_review`: bool — si el Developer que
      cierra una Task espera al veredicto del Tester antes de coger una
      Task nueva (default `DEFAULT_DEVELOPER_WAITS_FOR_TESTER_REVIEW`
      si no se indica).
    """
    path = _preferences_file(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "max_simultaneous_developers": preferences.get(
            "max_simultaneous_developers", DEFAULT_MAX_SIMULTANEOUS_DEVELOPERS
        ),
        "difficulty_model_map": preferences.get(
            "difficulty_model_map", DEFAULT_DIFFICULTY_MODEL_MAP
        ),
        "tui_enabled": preferences.get(
            "tui_enabled", DEFAULT_TUI_ENABLED
        ),
        "developer_waits_for_tester_review": preferences.get(
            "developer_waits_for_tester_review", DEFAULT_DEVELOPER_WAITS_FOR_TESTER_REVIEW
        ),
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def get_max_simultaneous_developers(state_dir: Path | None = None) -> int:
    """Atajo para `register_developer`: solo el limite resuelto, sin que
    el llamador tenga que conocer la forma completa del diccionario de
    preferencias."""
    return load_system_preferences(state_dir=state_dir)["max_simultaneous_developers"]


def get_difficulty_model_map(state_dir: Path | None = None) -> dict:
    """Atajo para obtener el mapeo dificultad → tier mínimo (T-FB008-US12-01).

    Devuelve un dict {difficulty: tier_minimo} que el Dispatcher usa para
    resolver qué modelo/runtime usar dada una Task de cierta dificultad."""
    return load_system_preferences(state_dir=state_dir)["difficulty_model_map"]


def get_tui_enabled(state_dir: Path | None = None) -> bool:
    """Atajo para obtener el gate de arranque de la TUI (T-FB002-US04-01).

    Devuelve un bool indicando si la TUI está habilitada. Por defecto es False
    (TUI bloqueada por seguridad, superficie sin mantenimiento activo)."""
    return load_system_preferences(state_dir=state_dir)["tui_enabled"]


def get_developer_waits_for_tester_review(state_dir: Path | None = None) -> bool:
    """Atajo para obtener si el Developer espera al veredicto del Tester
    antes de coger una Task nueva (T-FB008-US14-02). Por defecto True."""
    return load_system_preferences(state_dir=state_dir)["developer_waits_for_tester_review"]
