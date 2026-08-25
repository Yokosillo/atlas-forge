"""Conjunto cerrado de fases del roadmap (T-AF036-US14-05, US-AF036-14).

El backlog solo admite las fases del roadmap vigente: `Fase 0.9`,
`Fase 0.9.1`, `Fase 0.9.2`. Cualquier otro valor (incluidos los 0.x
legados como `Fase 0.1`..`Fase 0.8`) es inválido en todos los puntos de
entrada: edición (`set_item_fase`), creación
(`create_epic`/`create_user_story`) y el validador determinista
(`validator_v2`).

Además del conjunto cerrado se reconocen dos valores de "sin fase":
`None`/ausente (sin fase) y el marcador legacy `SIN_ASIGNAR` que ya usa
el backlog real. `SIN_ASIGNAR` se TOLERA en el validador (persistencia
existente) pero NO es asignable por edición/creación — el conjunto de
asignación es `VALID_FASES` o `None`; para "quitar la fase" se usa
`None`/`null`.

Los 65 items con fases 0.x (49 US + 16 Epics) se migran a `Fase 0.9` en
T-AF036-US14-06, que depende de esta Task.
"""

from __future__ import annotations

VALID_FASES = frozenset({"Fase 0.9", "Fase 0.9.1", "Fase 0.9.2"})

# Marcador legacy de "sin fase" presente en el backlog real.
SIN_ASIGNAR = "SIN_ASIGNAR"

# Valores tratados como "sin fase" a efectos de validación.
_NO_FASE_VALUES = frozenset({"", SIN_ASIGNAR})


def is_valid_fase(value: object) -> bool:
    """¿`value` es una fase aceptable en el backlog (o ausencia de fase)?

    Acepta: una fase de `VALID_FASES`, `None`, cadena vacía o
    `SIN_ASIGNAR`. Es el gate del validador determinista: un fichero
    persistido (o a persistir) con cualquier otra cadena es inválido.

    Solo acepta `None` o cadenas; un valor de otro tipo (p. ej. un int
    tras un YAML `fase: 123`) se considera inválido."""
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    return value in VALID_FASES or value in _NO_FASE_VALUES


def is_assignable_fase(value: object) -> bool:
    """¿`value` es asignable por edición/creación?

    Más estricto que `is_valid_fase`: solo `VALID_FASES` o `None`. El
    `SIN_ASIGNAR` legacy se tolera en datos ya persistidos, pero no se
    puede escribir desde la interfaz; "sin fase" se asigna con `None`."""
    if value is None:
        return True
    return isinstance(value, str) and value in VALID_FASES


def format_valid_fases() -> str:
    """Lista legible de las fases válidas para mensajes de error."""
    return ", ".join(sorted(VALID_FASES))


# T-AF036-US25-01: `version` es el campo único de versión de Epics y User
# Stories, con un conjunto cerrado (coherente con `version.yml`: `open: 0.9`,
# `future: [0.9.1, 0.9.2]`). `fase` queda deprecado (no asignable por
# edición/creación, solo tolerado como legacy en datos persistidos).
VALID_VERSIONS = frozenset({"0.9", "0.9.1", "0.9.2"})


def is_valid_version(value: object) -> bool:
    """¿`value` es una versión aceptable en el backlog (o ausencia)?

    Acepta: una versión de `VALID_VERSIONS` o `None`/ausente (sin versión).
    Es el gate del validador determinista: un fichero persistido (o a
    persistir) con cualquier otra versión es inválido. Solo acepta `None` o
    cadenas; un valor de otro tipo (p. ej. un int tras YAML) es inválido."""
    if value is None:
        return True
    return isinstance(value, str) and value in VALID_VERSIONS


def is_assignable_version(value: object) -> bool:
    """¿`value` es asignable por edición/creación?

    Idéntico a `is_valid_version` en este caso (no hay marcador legacy como
    `SIN_ASIGNAR` para versiones); "sin versión" se asigna con `None`."""
    return is_valid_version(value)


def format_valid_versions() -> str:
    """Lista legible de las versiones válidas para mensajes de error."""
    return ", ".join(sorted(VALID_VERSIONS))