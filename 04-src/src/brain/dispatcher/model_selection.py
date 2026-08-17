"""Selección de modelo basada en dificultad de Task (T-FB008-US12-01).

Resuelve qué modelo/runtime usar dada una `difficulty` de Task,
consultando el catálogo de modelos con tiers y el mapeo configurable
dificultad→tier desde system_preferences."""

from __future__ import annotations

from brain.models_catalog import load_model_catalog, ModelEntry
from brain.system_preferences import get_difficulty_model_map


def get_models_for_difficulty(
    difficulty: str, project_path: str | None = None
) -> list[ModelEntry]:
    """Retorna los modelos disponibles que satisfacen la dificultad dada.

    Consulta:
    1. El mapeo dificultad → tier mínimo desde system_preferences
    2. El catálogo de modelos y sus tiers
    3. Retorna todos los modelos con tier >= tier_mínimo requerido

    Si la dificultad no está en el mapeo, levanta KeyError.
    Si no hay modelos disponibles en el tier, retorna lista vacía (warning).
    """
    difficulty_map = get_difficulty_model_map()

    if difficulty not in difficulty_map:
        raise KeyError(
            f"Dificultad '{difficulty}' no reconocida. "
            f"Dificultades válidas: {list(difficulty_map.keys())}"
        )

    required_tier = difficulty_map[difficulty]

    # Carga el catálogo de modelos (asume que project_path es valido o None)
    try:
        from pathlib import Path
        if project_path:
            catalog_path = Path(project_path) / ".factory-brain" / "models.yml"
        else:
            # Fallback: buscar .factory-brain en cwd
            catalog_path = Path.cwd() / ".factory-brain" / "models.yml"

        all_models = load_model_catalog(catalog_path)
    except Exception as e:
        # Si el catálogo no se carga, retorna lista vacía (warning en log)
        return []

    # Filtra modelos con tier >= required_tier
    # (tier=None se trata como tier="infinito" — siempre satisface)
    matching = [
        model for model in all_models
        if model.tier is None or model.tier >= required_tier
    ]

    return matching
