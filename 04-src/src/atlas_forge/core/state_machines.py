"""Máquinas de estado canónicas de Task y User Story (AF-040).

Única fuente de verdad del vocabulario de estados y de las transiciones
legales de los dos objetos de dominio del backlog. NINGÚN otro módulo
debe declarar conjuntos literales de estados de Task/User Story — todo el
sistema consume este módulo (ver guardián de T-AF040-US01-05).

## Modelo objetivo (decisión de producto, US-AF040-01)

- **Task:** `READY` → `TO_DEVELOP` → `IN_PROGRESS` → `IN_REVIEW` → `DONE`.
  - `TO_DEVELOP → READY` está permitido (desencolar, T-AF024-US12-*).
  - `IN_REVIEW → IN_PROGRESS` está permitido (el Tester rechaza la Task y
    vuelve al Developer).
- **User Story:** `NO_TASKS` → `TO_PLAN` mientras se planifica; después
  deriva automáticamente del estado de sus Tasks (`derive_user_story_state`,
  "estado menos avanzado"); cuando todas sus Tasks están `DONE` pasa a
  `IN_REVIEW` para la validación final del Arquitecto; solo después puede
  pasar a `DONE`. `OUT_OF_SCOPE` es exclusivo de User Story — una Task
  nunca puede estar en `OUT_OF_SCOPE`.
- La User Story **nunca** llega a `DONE` directamente desde un estado
  derivado: debe pasar por `IN_REVIEW` (validación final del Arquitecto).
"""

from __future__ import annotations

from typing import Iterable, Literal

TASK = "task"
USER_STORY = "user_story"

Kind = Literal["task", "user_story"]

# ── estados canónicos ────────────────────────────────────────────────────

# Constantes por estado para que los consumidores eviten magic strings.
READY = "READY"
TO_DEVELOP = "TO_DEVELOP"
IN_PROGRESS = "IN_PROGRESS"
IN_REVIEW = "IN_REVIEW"
DONE = "DONE"
NO_TASKS = "NO_TASKS"
TO_PLAN = "TO_PLAN"
OUT_OF_SCOPE = "OUT_OF_SCOPE"

TASK_STATES = frozenset({READY, TO_DEVELOP, IN_PROGRESS, IN_REVIEW, DONE})

USER_STORY_STATES = frozenset(
    {
        NO_TASKS,
        TO_PLAN,
        READY,
        TO_DEVELOP,
        IN_PROGRESS,
        IN_REVIEW,
        DONE,
        OUT_OF_SCOPE,
    }
)

# Vocabulario de Epics: FUERA del contrato canónico Task/User Story (la
# epic AF-040 solo cubre Task y User Story), pero centralizado AQUÍ para
# que ningún otro módulo declare conjuntos de estados literales (guardián,
# T-AF040-US01-05). Las Epics conservan `TO_DO`/`DONE`/`FUERA_ROADMAP`.
EPIC_STATES = frozenset({"TO_DO", "DONE", "FUERA_ROADMAP"})

# Estados "pendientes" (todo lo que no es `DONE` ni `OUT_OF_SCOPE`) —
# consumido por `backlog/parser.py` para clasificar items como trabajo
# pendiente. Centralizado aquí para el guardián.
PENDING_STATES = frozenset((TASK_STATES | USER_STORY_STATES) - {DONE, OUT_OF_SCOPE})

# Orden de progresión de Task: un valor menor = menos avanzada. Es la base
# de la derivación de la User Story ("estado de la Task menos avanzada").
_TASK_ORDER = {
    "READY": 0,
    "TO_DEVELOP": 1,
    "IN_PROGRESS": 2,
    "IN_REVIEW": 3,
    "DONE": 4,
}

# ── transiciones legales ─────────────────────────────────────────────────

# Task: exactamente el flujo de la epic. `TO_DEVELOP → READY` (desencolar)
# e `IN_REVIEW → IN_PROGRESS` (rechazo del Tester) son las dos únicas
# salidas del avance lineal justificadas por el pipeline.
TASK_TRANSITIONS: dict[str, frozenset[str]] = {
    "READY": frozenset({"TO_DEVELOP"}),
    "TO_DEVELOP": frozenset({"READY", "IN_PROGRESS"}),
    "IN_PROGRESS": frozenset({"IN_REVIEW"}),
    "IN_REVIEW": frozenset({"IN_PROGRESS", "DONE"}),
    "DONE": frozenset(),
}

# User Story: el estado derivado (READY/TO_DEVELOP/IN_PROGRESS/IN_REVIEW)
# lo calcula `derive_user_story_state` y lo aplica el pipeline de forma
# automática — por eso los movimientos entre estados derivados se admiten
# (siguen a las Tasks, no a una decisión manual). Lo que `can_transition`
# vigila aquí son las fronteras de fase:
#   - `NO_TASKS` solo puede pasar a `TO_PLAN` (empezar a planificar) o
#     `OUT_OF_SCOPE`.
#   - `IN_REVIEW` solo pasa a `DONE` (validación final del Arquitecto) o
#     `OUT_OF_SCOPE` — nunca un estado derivado vuelve a entrar en
#     `IN_REVIEW`→`DONE` sin la validación.
#   - `DONE` y `OUT_OF_SCOPE` son terminales.
#   - `OUT_OF_SCOPE` es accesible desde cualquier estado, solo en US.
_USER_STORY_DERIVED = frozenset({"READY", "TO_DEVELOP", "IN_PROGRESS", "IN_REVIEW"})

USER_STORY_TRANSITIONS: dict[str, frozenset[str]] = {
    "NO_TASKS": frozenset({"TO_PLAN", "OUT_OF_SCOPE"}),
    "TO_PLAN": _USER_STORY_DERIVED | frozenset({"OUT_OF_SCOPE"}),
    "READY": frozenset({"TO_DEVELOP", "IN_PROGRESS", "IN_REVIEW", "OUT_OF_SCOPE"}),
    "TO_DEVELOP": frozenset({"READY", "IN_PROGRESS", "IN_REVIEW", "OUT_OF_SCOPE"}),
    "IN_PROGRESS": frozenset({"READY", "TO_DEVELOP", "IN_REVIEW", "OUT_OF_SCOPE"}),
    "IN_REVIEW": frozenset({"DONE", "OUT_OF_SCOPE"}),
    "DONE": frozenset({"OUT_OF_SCOPE"}),
    "OUT_OF_SCOPE": frozenset(),
}

_STATES_BY_KIND: dict[Kind, frozenset[str]] = {
    TASK: TASK_STATES,
    USER_STORY: USER_STORY_STATES,
    # Epics no tienen máquina de transición canónica (fuera de alcance de
    # AF-040) — su vocabulario está centralizado aquí por el guardián.
    "epic": EPIC_STATES,
}

_TRANSITIONS_BY_KIND: dict[Kind, dict[str, frozenset[str]]] = {
    TASK: TASK_TRANSITIONS,
    USER_STORY: USER_STORY_TRANSITIONS,
}


def valid_states(kind: Kind) -> frozenset[str]:
    """Conjunto cerrado de estados válidos para `kind`.

    `valid_states("task")` nunca incluye `OUT_OF_SCOPE`; `valid_states(
    "user_story")` sí. Fuera de este módulo no se deben definir conjuntos
    de estados de Task/User Story (guardián, T-AF040-US01-05)."""
    return _STATES_BY_KIND[kind]


def can_transition(kind: Kind, from_state: str, to_state: str) -> bool:
    """`True` si `from_state → to_state` es una transición legal para
    `kind`. Estados desconocidos devuelven `False` (defensivo, nunca
    propaga excepción). Para User Story, los movimientos entre estados
    derivados son automáticos (siguen a las Tasks); `can_transition` vela
    por las fronteras de fase (planificación, validación final, salida de
    alcance)."""
    transitions = _TRANSITIONS_BY_KIND.get(kind)
    if transitions is None:
        return False
    return to_state in transitions.get(from_state, frozenset())


def derive_user_story_state(task_states: Iterable[str]) -> str:
    """Deriva el estado de una User Story a partir del estado de sus Tasks
    (US-AF040-01, criterio 5/6).

    Regla:
    - Sin Tasks → `NO_TASKS`.
    - Con Tasks → el estado de la **menos avanzada** (menor posición en
      `_TASK_ORDER`).
    - Si la Task menos avanzada está `DONE` (es decir, TODAS lo están) →
      `IN_REVIEW` (queda pendiente la validación final del Arquitecto;
      la US **no** deriva a `DONE` directamente, criterio 7).

    Levanta `ValueError` si algún estado de Task no es un estado canónico
    de Task (invarianza de dominio: las Tasks solo pueden estar en
    `TASK_STATES`, `OUT_OF_SCOPE` no aplica a Tasks)."""
    states = list(task_states)
    if not states:
        return "NO_TASKS"
    unknown = [s for s in states if s not in TASK_STATES]
    if unknown:
        raise ValueError(
            f"Estados de Task no canónicos: {sorted(set(unknown))}. "
            f"Las Tasks solo admiten {sorted(TASK_STATES)}."
        )
    least_advanced = min(states, key=lambda s: _TASK_ORDER[s])
    if least_advanced == "DONE":
        return "IN_REVIEW"
    return least_advanced
