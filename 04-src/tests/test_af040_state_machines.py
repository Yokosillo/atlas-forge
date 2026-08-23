"""T-AF040-US01-05 · Tests de máquinas de estado y guardián contra estados
literales (US-AF040-01).

Cubre:
1. `can_transition`/`valid_states` por tipo (Task vs User Story).
2. `derive_user_story_state`: NO_TASKS, TO_PLAN, estado menos avanzado,
   validación final IN_REVIEW cuando todas las Tasks están DONE, y
   OUT_OF_SCOPE exclusivo de User Story.
3. Guardián: ningún módulo de `04-src/src/atlas_forge/` declara conjuntos de
   estados literales fuera de `state_machines.py` (salvo excepciones
   documentadas: el validador legacy `backlog/validator.py`).
4. Regresión del pipeline: Task sigue READY→TO_DEVELOP→IN_PROGRESS→
   IN_REVIEW→DONE; la US queda en IN_REVIEW antes de la validación final
   del Arquitecto y solo pasa a DONE después; una Task nunca admite
   OUT_OF_SCOPE mientras una US sí puede.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from atlas_forge.core.state_machines import (
    DONE,
    IN_PROGRESS,
    IN_REVIEW,
    NO_TASKS,
    OUT_OF_SCOPE,
    READY,
    TASK,
    TASK_STATES,
    TO_DEVELOP,
    TO_PLAN,
    USER_STORY,
    USER_STORY_STATES,
    can_transition,
    derive_user_story_state,
    valid_states,
)

# Estados literales que el guardián persigue (canónicos + legado, para que
# tampoco reaparezcan los antiguos).
_GUARDED_TOKENS = frozenset({
    "READY", "TO_DEVELOP", "IN_PROGRESS", "IN_REVIEW", "DONE",
    "NO_TASKS", "TO_PLAN", "OUT_OF_SCOPE",
    "TO_DO", "EN_DESARROLLO", "REVIEW", "EN_DISEÑO", "FUERA_ROADMAP",
})

_SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "atlas_forge"

# Excepciones documentadas del guardián: módulos que conservan vocabulario
# propio por compatibilidad técnica explícita.
_GUARDIAN_EXCEPTIONS = {
    "core/state_machines.py",  # la única fuente de verdad
    "backlog/validator.py",    # validador legacy del formato Markdown antiguo
    "backlog/promote.py",      # consolidación de estados (promover/reabrir/NO_TASKS): referencia estados canónicos
}


def test_valid_states_task_never_includes_out_of_scope() -> None:
    assert valid_states(TASK) == TASK_STATES
    assert OUT_OF_SCOPE not in valid_states(TASK)
    assert "TO_PLAN" not in valid_states(TASK)
    assert "NO_TASKS" not in valid_states(TASK)


def test_valid_states_user_story_includes_out_of_scope() -> None:
    assert valid_states(USER_STORY) == USER_STORY_STATES
    assert OUT_OF_SCOPE in valid_states(USER_STORY)
    assert TO_PLAN in valid_states(USER_STORY)
    assert NO_TASKS in valid_states(USER_STORY)


def test_task_can_transition_follows_the_product_flow() -> None:
    # Avance canónico: READY -> TO_DEVELOP -> IN_PROGRESS -> IN_REVIEW -> DONE.
    assert can_transition(TASK, READY, TO_DEVELOP)
    assert can_transition(TASK, TO_DEVELOP, IN_PROGRESS)
    assert can_transition(TASK, IN_PROGRESS, IN_REVIEW)
    assert can_transition(TASK, IN_REVIEW, DONE)
    # Desencolar y rechazo del Tester (salidas justificadas del avance lineal).
    assert can_transition(TASK, TO_DEVELOP, READY)
    assert can_transition(TASK, IN_REVIEW, IN_PROGRESS)


def test_task_rejects_illegal_jumps() -> None:
    assert not can_transition(TASK, READY, DONE)
    assert not can_transition(TASK, READY, IN_PROGRESS)
    assert not can_transition(TASK, IN_PROGRESS, DONE)
    assert not can_transition(TASK, READY, OUT_OF_SCOPE)
    assert not can_transition(TASK, DONE, READY)
    assert not can_transition(TASK, DONE, IN_REVIEW)


def test_task_never_accepts_out_of_scope() -> None:
    for state in TASK_STATES:
        assert not can_transition(TASK, state, OUT_OF_SCOPE)


def test_user_story_can_go_out_of_scope_from_any_state() -> None:
    # OUT_OF_SCOPE es terminal: no puede volver a OUT_OF_SCOPE desde sí mismo.
    for state in USER_STORY_STATES:
        if state == OUT_OF_SCOPE:
            continue
        assert can_transition(USER_STORY, state, OUT_OF_SCOPE)


def test_user_story_phase_boundaries() -> None:
    # NO_TASKS solo a TO_PLAN (empezar a planificar) o OUT_OF_SCOPE.
    assert can_transition(USER_STORY, NO_TASKS, TO_PLAN)
    assert not can_transition(USER_STORY, NO_TASKS, DONE)
    assert not can_transition(USER_STORY, NO_TASKS, READY)
    # IN_REVIEW -> DONE requiere la validación final del Arquitecto.
    assert can_transition(USER_STORY, IN_REVIEW, DONE)
    assert not can_transition(USER_STORY, IN_PROGRESS, DONE)
    assert not can_transition(USER_STORY, READY, DONE)
    # DONE/OUT_OF_SCOPE son terminales.
    assert not can_transition(USER_STORY, DONE, IN_REVIEW)
    assert not can_transition(USER_STORY, OUT_OF_SCOPE, DONE)


def test_derive_user_story_state_no_tasks() -> None:
    assert derive_user_story_state([]) == NO_TASKS


def test_derive_user_story_state_least_advanced_task() -> None:
    assert derive_user_story_state([DONE, DONE, READY]) == READY
    assert derive_user_story_state([DONE, TO_DEVELOP]) == TO_DEVELOP
    assert derive_user_story_state([IN_REVIEW, IN_PROGRESS, DONE]) == IN_PROGRESS
    assert derive_user_story_state([IN_REVIEW, IN_REVIEW, DONE]) == IN_REVIEW


def test_derive_user_story_state_all_done_is_in_review_not_done() -> None:
    # Cuando todas las Tasks están DONE, la US deriva a IN_REVIEW (validación
    # final del Arquitecto pendiente) — NUNCA a DONE automáticamente.
    assert derive_user_story_state([DONE]) == IN_REVIEW
    assert derive_user_story_state([DONE, DONE, DONE]) == IN_REVIEW


def test_derive_user_story_state_rejects_invalid_task_states() -> None:
    with pytest.raises(ValueError, match="no canónicos"):
        derive_user_story_state([OUT_OF_SCOPE])
    with pytest.raises(ValueError, match="no canónicos"):
        derive_user_story_state(["TO_PLAN"])


def test_can_transition_returns_false_for_unknown_states() -> None:
    assert not can_transition(TASK, "NOPE", READY)
    assert not can_transition(TASK, READY, "NOPE")
    assert not can_transition("banana", READY, TO_DEVELOP)


def test_guardian_no_literal_state_sets_outside_state_machines() -> None:
    """Guardián (criterio 2 de la Task): recorre `04-src/src/atlas_forge/` y falla
    si algún módulo vuelve a declarar conjuntos de estados literales (set /
    frozenset / dict) con tokens de estado fuera de `state_machines.py` y de
    las excepciones documentadas.

    El escaneo ignora los docstrings/strings largos (donde el contrato de la
    API describe estados válidos, p. ej. `{"state": "READY" | ...}`) y solo
    señala asignaciones reales de colecciones (`= {`, `frozenset({`) con ≥2
    tokens de estado."""
    set_pattern = re.compile(r"(?:=\s*\{|frozenset\(\s*\{)")
    token_pattern = re.compile(r'"([A-Z_]+)"')
    violations: list[str] = []

    for path in sorted(_SRC_ROOT.rglob("*.py")):
        rel = path.relative_to(_SRC_ROOT).as_posix()
        if rel in _GUARDIAN_EXCEPTIONS:
            continue
        content = path.read_text(encoding="utf-8")
        # Quita docstrings y strings largos para no señalar contratos de API
        # ni textos explicativos.
        content = re.sub(r'"""(?:[^"]|"(?!""))*"""', "", content, flags=re.DOTALL)
        content = re.sub(r"'''(?:[^']|'(?!''))*'''", "", content, flags=re.DOTALL)
        for match in set_pattern.finditer(content):
            start = match.end()
            block = content[start:start + 800]
            closing = block.find("}")
            if closing == -1:
                continue
            block = block[:closing]
            tokens = {t for t in token_pattern.findall(block) if t in _GUARDED_TOKENS}
            if len(tokens) >= 2:
                violations.append(f"{rel}: {{{', '.join(sorted(tokens))}}}")

    assert violations == [], (
        "Conjuntos de estados literales fuera de state_machines.py: "
        + "; ".join(violations)
    )


def test_pipeline_regression_task_flow() -> None:
    """Regresión: Task sigue exactamente
    READY -> TO_DEVELOP -> IN_PROGRESS -> IN_REVIEW -> DONE."""
    flow = [READY, TO_DEVELOP, IN_PROGRESS, IN_REVIEW, DONE]
    for _from, _to in zip(flow, flow[1:]):
        assert can_transition(TASK, _from, _to), f"{_from} -> {_to} debe ser legal"


def test_pipeline_regression_user_story_final_review_then_done() -> None:
    """Regresión: la US queda en IN_REVIEW (todas sus Tasks DONE) y solo pasa
    a DONE tras la validación final del Arquitecto — nunca antes."""
    assert derive_user_story_state([DONE, DONE]) == IN_REVIEW
    # Solo IN_REVIEW -> DONE está permitido; los derivados no saltan a DONE.
    assert can_transition(USER_STORY, IN_REVIEW, DONE)
    for derived in (READY, TO_DEVELOP, IN_PROGRESS):
        assert not can_transition(USER_STORY, derived, DONE)
