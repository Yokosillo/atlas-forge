from dataclasses import dataclass


@dataclass(frozen=True)
class GenericScriptEntry:
    """Un script genérico del catálogo fijo de Factory Brain (T-FB018-US01-01) —
    a diferencia de [ScriptEntry] (scripts particulares que cada proyecto
    declara en su propio manifiesto, T-FB001-US03-01), estos son iguales
    para cualquier proyecto del workspace y viven en el propio Factory Brain,
    no en el repositorio del usuario.

    `id` es el identificador estable por el que `run_generic_script`
    (T-FB018-US01-01) lo localizará para ejecutarlo; `name` es el nombre
    visible en la interfaz."""

    id: str
    name: str
