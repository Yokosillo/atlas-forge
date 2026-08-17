"""Catalogo de modelos disponibles (T-FB022-US09-01): fichero de configuracion
YAML (`models.yml`) que declara los modelos conocidos con su nombre visible,
identificador real y runtime asociado, sustituyendo la constante fija
`AVAILABLE_MODELS` de `agent_model.py`.

## Formato del manifiesto: `.factory-brain/models.yml`, YAML

Mismo patron que `project_scripts.py` (`.factory-brain/scripts.yml`):
parser determinista, validacion en carga (runtime dentro del conjunto
soportado, sin IDs duplicados), fallo claro si esta mal formado.
Fichero editado por humanos — YAML por los mismos motivos que el
manifiesto de scripts (comentarios, sin comillas obligatorias).

```yaml
models:
  - id: opencode-go/deepseek-v4-pro
    name: "DeepSeek V4 Pro"
    runtime: opencode
  - id: opencode-go/deepseek-v4-flash
    name: "DeepSeek V4 Flash"
    runtime: opencode
```

`id`, `name` y `runtime` son obligatorios por entrada.
`runtime` debe ser uno de: `opencode`, `claude_code`, `codex`.
No se admiten IDs duplicados.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from brain.workspace.discovery_cache import TTLCache

CATALOG_RELATIVE_PATH = Path(".factory-brain") / "models.yml"

_SUPPORTED_RUNTIMES = frozenset({"opencode", "claude_code", "codex"})

_MODELS_CACHE = TTLCache()


@dataclass(frozen=True)
class ModelEntry:
    """Una entrada del catalogo de modelos: nombre visible, identificador
    real (el que se pasa a `--model`), runtime asociado, y tier opcional
    (T-FB008-US12-01: mapeo dificultad↔modelo).

    `tier` es un entero 1-5 que agrupa modelos por capacidad:
    - tier 1: modelos básicos (bajo costo, menor capacidad)
    - tier 5: modelos avanzados (alto costo, mayor capacidad)
    Usado para resolver qué modelo usar dada una `difficulty` de Task."""

    id: str
    name: str
    runtime: str
    tier: int | None = None


class MalformedModelCatalogError(ValueError):
    """El fichero de catalogo de modelos existe pero no se puede interpretar:
    YAML invalido, estructura inesperada (no es una lista bajo `models`),
    falta algun campo obligatorio (`id`, `name`, `runtime`), runtime no
    soportado o ID duplicado — nunca una excepcion no controlada, siempre
    este error explicito con un mensaje legible sobre que esta mal."""


def _validate_model_entry(raw_entry: Any, index: int, seen_ids: set[str]) -> ModelEntry:
    if not isinstance(raw_entry, dict):
        raise MalformedModelCatalogError(
            f"La entrada en la posicion {index} del catalogo de modelos "
            f"no es un objeto con campos (id/name/runtime) — se encontro: "
            f"{raw_entry!r}."
        )

    missing_fields = [
        field for field in ("id", "name", "runtime")
        if not raw_entry.get(field)
    ]
    if missing_fields:
        raise MalformedModelCatalogError(
            f"La entrada en la posicion {index} del catalogo de modelos "
            f"no tiene los campos obligatorios: {', '.join(missing_fields)}."
        )

    entry_id = str(raw_entry["id"])
    entry_runtime = str(raw_entry["runtime"])

    if entry_runtime not in _SUPPORTED_RUNTIMES:
        raise MalformedModelCatalogError(
            f"La entrada en la posicion {index} del catalogo de modelos "
            f"tiene un runtime no soportado: '{entry_runtime}'. "
            f"Runtimes soportados: {sorted(_SUPPORTED_RUNTIMES)}."
        )

    if entry_id in seen_ids:
        raise MalformedModelCatalogError(
            f"ID de modelo duplicado en el catalogo: '{entry_id}' "
            f"(primera aparicion en la posicion {index})."
        )
    seen_ids.add(entry_id)

    tier = raw_entry.get("tier")
    if tier is not None:
        try:
            tier = int(tier)
            if tier < 1 or tier > 5:
                raise ValueError
        except (ValueError, TypeError):
            raise MalformedModelCatalogError(
                f"La entrada en la posicion {index} del catalogo de modelos "
                f"tiene un valor 'tier' invalido: '{tier}'. "
                f"'tier' debe ser un entero entre 1 y 5, o ausente."
            )

    return ModelEntry(
        id=entry_id,
        name=str(raw_entry["name"]),
        runtime=entry_runtime,
        tier=tier,
    )


def _manifest_fingerprint(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def _load_model_catalog_uncached(catalog_path: Path) -> list[ModelEntry]:
    if not catalog_path.exists():
        raise MalformedModelCatalogError(
            f"El catalogo de modelos '{catalog_path}' no existe."
        )

    try:
        raw_content = catalog_path.read_text(encoding="utf-8")
        parsed = yaml.safe_load(raw_content)
    except yaml.YAMLError as error:
        raise MalformedModelCatalogError(
            f"El catalogo de modelos '{catalog_path}' no es YAML "
            f"valido: {error}."
        ) from error

    if parsed is None:
        raise MalformedModelCatalogError(
            f"El catalogo de modelos '{catalog_path}' esta vacio o solo "
            f"contiene comentarios — debe declarar al menos un modelo."
        )

    if not isinstance(parsed, dict) or "models" not in parsed:
        raise MalformedModelCatalogError(
            f"El catalogo de modelos '{catalog_path}' debe tener una "
            f"clave raiz 'models' con la lista de modelos declarados."
        )

    raw_models = parsed["models"]
    if not isinstance(raw_models, list):
        raise MalformedModelCatalogError(
            f"'models' en '{catalog_path}' debe ser una lista de "
            f"modelos, no {type(raw_models).__name__}."
        )

    if not raw_models:
        raise MalformedModelCatalogError(
            f"El catalogo de modelos '{catalog_path}' no declara "
            f"ningun modelo — la lista 'models' esta vacia."
        )

    seen_ids: set[str] = set()
    return [
        _validate_model_entry(raw_entry, index, seen_ids)
        for index, raw_entry in enumerate(raw_models)
    ]


def load_model_catalog(
    catalog_path: Path | None = None,
) -> list[ModelEntry]:
    """Lee el catalogo de modelos desde `catalog_path` (por defecto
    `.factory-brain/models.yml` en la raiz del repo de Factory Brain) y
    devuelve la lista de entradas validadas.

    Cacheada por TTL con validacion de mtime (mismo patron que
    `discover_project_scripts`) — las rafagas de requests no releen el
    YAML del disco si el fichero no cambio. Los errores de parseo NO se
    cachean (la excepcion se propaga para que el siguiente intento
    reintente de verdad).

    Nunca devuelve una lista vacia — un catalogo sin modelos es un error
    de configuracion (`MalformedModelCatalogError`)."""
    path = (
        catalog_path
        if catalog_path is not None
        else Path(__file__).resolve().parents[3] / CATALOG_RELATIVE_PATH
    )
    baseline: list[tuple[int, int] | None] = [None]

    def compute() -> list[ModelEntry]:
        baseline[0] = _manifest_fingerprint(path)
        return _load_model_catalog_uncached(path)

    def validate() -> bool:
        return _manifest_fingerprint(path) == baseline[0]

    return _MODELS_CACHE.get_or_compute(
        str(path.resolve()), compute, validate=validate
    )


def invalidate_model_catalog_cache() -> None:
    """Vacia la cache del catalogo de modelos — util cuando el fichero
    se edita externamente y se quiere forzar una recarga inmediata sin
    esperar al TTL."""
    _MODELS_CACHE.invalidate()
