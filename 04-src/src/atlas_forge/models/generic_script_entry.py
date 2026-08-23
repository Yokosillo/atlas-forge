from dataclasses import dataclass


@dataclass(frozen=True)
class GenericScriptEntry:
    """Un script genérico del catálogo fijo de Atlas Forge (T-AF018-US01-01) —
    a diferencia de [ScriptEntry] (scripts particulares que cada proyecto
    declara en su propio manifiesto, T-AF001-US03-01), estos son iguales
    para cualquier proyecto del workspace y viven en el propio Atlas Forge,
    no en el repositorio del usuario.

    `id` es el identificador estable por el que `run_generic_script`
    (T-AF018-US01-01) lo localizará para ejecutarlo; `name` es el nombre
    visible en la interfaz; `description` es una descripción de una línea
    (T-AF024-US03-01)."""

    id: str
    name: str
    description: str | None = None
