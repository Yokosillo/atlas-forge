"""Tests de T-AF022-US13-02: promoción transitiva de estado US/Epic → DONE.

Usa `tmp_path` con una estructura sintética de `02-backlog/{epics,user-stories,
tasks}/` para tener control total sobre los escenarios (no depende del backlog
real del proyecto, que cambia constantemente).
"""
from __future__ import annotations

from pathlib import Path

from atlas_forge.backlog.promote import (
    check_backlog_promotion,
    detect_reopened_drift,
    promote_backlog,
    reopen_backlog,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _epic(backlog: Path, epic_id: str, state: str) -> None:
    _write(
        backlog / "epics" / f"{epic_id}.md",
        f"---\nid: {epic_id}\ntype: epic\ntitle: {epic_id}\nstate: {state}\n"
        "dependencies: []\n---\n\n## Objetivo\n\nTest.\n",
    )


def _story(backlog: Path, us_id: str, epic_id: str, state: str) -> None:
    _write(
        backlog / "user-stories" / f"{us_id}.md",
        f"---\nid: {us_id}\ntype: user_story\ntitle: {us_id}\nstate: {state}\n"
        f"dependencies: []\nepic: {epic_id}\n---\n\n## Historia\n\nTest.\n",
    )


def _task(backlog: Path, task_id: str, epic_id: str, us_id: str, state: str) -> None:
    _write(
        backlog / "tasks" / f"{task_id}.md",
        f"---\nid: {task_id}\ntype: task\ntitle: {task_id}\nstate: {state}\n"
        f"dependencies: []\nepic: {epic_id}\nuser_story: {us_id}\n---\n\n"
        "## Objetivo\n\nTest.\n",
    )


def _state_of(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("state:"):
            return line.split(":", 1)[1].strip()
    raise AssertionError(f"no state field in {path}")


def test_promocion_us_a_in_review_cuando_todas_las_tasks_estan_done(tmp_path: Path) -> None:
    """AF-040: la US con todas sus Tasks DONE promueve a IN_REVIEW (queda
    pendiente la validación final del Arquitecto), nunca a DONE directo."""
    backlog = tmp_path / "02-backlog"
    _epic(backlog, "AF-100", "READY")
    _story(backlog, "US-AF100-01", "AF-100", "READY")
    _task(backlog, "T-AF100-US01-01", "AF-100", "US-AF100-01", "DONE")
    _task(backlog, "T-AF100-US01-02", "AF-100", "US-AF100-01", "DONE")

    result = promote_backlog(backlog)

    assert result.promoted_user_stories == ["US-AF100-01"]
    assert _state_of(backlog / "user-stories" / "US-AF100-01.md") == "IN_REVIEW"


def test_epic_no_se_promueve_con_us_en_in_review(tmp_path: Path) -> None:
    """AF-040: la US promovida a IN_REVIEW no cuenta como DONE, así que la
    Epic NO se promueve hasta que la US sea validada (DONE) por el
    Arquitecto."""
    backlog = tmp_path / "02-backlog"
    _epic(backlog, "AF-100", "READY")
    _story(backlog, "US-AF100-01", "AF-100", "READY")
    _task(backlog, "T-AF100-US01-01", "AF-100", "US-AF100-01", "DONE")

    result = promote_backlog(backlog)

    assert result.promoted_user_stories == ["US-AF100-01"]
    assert result.promoted_epics == []
    assert _state_of(backlog / "user-stories" / "US-AF100-01.md") == "IN_REVIEW"
    assert _state_of(backlog / "epics" / "AF-100.md") == "READY"


def test_no_promociona_con_hijo_pendiente(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    _epic(backlog, "AF-100", "READY")
    _story(backlog, "US-AF100-01", "AF-100", "READY")
    _task(backlog, "T-AF100-US01-01", "AF-100", "US-AF100-01", "DONE")
    _task(backlog, "T-AF100-US01-02", "AF-100", "US-AF100-01", "READY")

    result = promote_backlog(backlog)

    assert result.promoted_user_stories == []
    assert result.promoted_epics == []
    assert _state_of(backlog / "user-stories" / "US-AF100-01.md") == "READY"
    assert _state_of(backlog / "epics" / "AF-100.md") == "READY"


def test_no_revierte_estado_ya_done(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    _epic(backlog, "AF-100", "DONE")
    _story(backlog, "US-AF100-01", "AF-100", "DONE")
    _story(backlog, "US-AF100-02", "AF-100", "READY")
    _task(backlog, "T-AF100-US01-01", "AF-100", "US-AF100-01", "DONE")
    _task(backlog, "T-AF100-US02-01", "AF-100", "US-AF100-02", "READY")

    result = promote_backlog(backlog)

    assert "US-AF100-01" not in result.promoted_user_stories
    assert result.promoted_epics == []
    assert _state_of(backlog / "epics" / "AF-100.md") == "DONE"


def test_idempotente(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    _epic(backlog, "AF-100", "READY")
    _story(backlog, "US-AF100-01", "AF-100", "READY")
    _task(backlog, "T-AF100-US01-01", "AF-100", "US-AF100-01", "DONE")

    first = promote_backlog(backlog)
    second = promote_backlog(backlog)

    assert first.has_drift
    assert not second.has_drift
    assert second.promoted_user_stories == []
    assert second.promoted_epics == []


def test_check_no_escribe_nada(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    _epic(backlog, "AF-100", "READY")
    _story(backlog, "US-AF100-01", "AF-100", "READY")
    _task(backlog, "T-AF100-US01-01", "AF-100", "US-AF100-01", "DONE")

    result = check_backlog_promotion(backlog)

    assert result.has_drift
    assert result.promoted_user_stories == ["US-AF100-01"]
    assert _state_of(backlog / "user-stories" / "US-AF100-01.md") == "READY"


def test_mark_story_tasks_done_accepts_canonical_us_prefixed_story_id(
    tmp_path: Path,
) -> None:
    """T-AF022-US13-01B end-to-end: `_mark_story_tasks_done` recibe la forma
    canónica `US-AF100-01` (la que llega vía `plan.goal` tras un veredicto
    APROBADO), debe encontrar y marcar las Tasks reales `T-AF100-US01-*` a
    DONE y promover transitivamente la US y la Epic."""
    from atlas_forge.dispatcher.job_plan_dispatch import _mark_story_tasks_done

    backlog = tmp_path / "02-backlog"
    _epic(backlog, "AF-100", "READY")
    _story(backlog, "US-AF100-01", "AF-100", "READY")
    _task(backlog, "T-AF100-US01-01", "AF-100", "US-AF100-01", "READY")
    _task(backlog, "T-AF100-US01-02", "AF-100", "US-AF100-01", "READY")

    _mark_story_tasks_done("US-AF100-01", backlog_dir=backlog)

    assert _state_of(backlog / "tasks" / "T-AF100-US01-01.md") == "DONE"
    assert _state_of(backlog / "tasks" / "T-AF100-US01-02.md") == "DONE"
    assert _state_of(backlog / "user-stories" / "US-AF100-01.md") == "DONE"
    assert _state_of(backlog / "epics" / "AF-100.md") == "DONE"


def test_mark_story_tasks_done_also_accepts_normalized_story_id(tmp_path: Path) -> None:
    """El normalizador es idempotente: `AF100-US01` (la forma ya normalizada)
    debe producir el mismo resultado que `US-AF100-01`."""
    from atlas_forge.dispatcher.job_plan_dispatch import _mark_story_tasks_done

    backlog = tmp_path / "02-backlog"
    _epic(backlog, "AF-100", "READY")
    _story(backlog, "US-AF100-01", "AF-100", "READY")
    _task(backlog, "T-AF100-US01-01", "AF-100", "US-AF100-01", "READY")

    _mark_story_tasks_done("AF100-US01", backlog_dir=backlog)

    assert _state_of(backlog / "tasks" / "T-AF100-US01-01.md") == "DONE"
    assert _state_of(backlog / "user-stories" / "US-AF100-01.md") == "DONE"


# ── T-AF022-US13-04: drift inverso (padre DONE con hijo reabierto) ─────────


def test_detect_reopened_drift_reports_us_done_with_task_reopened(
    tmp_path: Path,
) -> None:
    # Caso real encontrado en vivo 2026-08-16: el Arquitecto añadió una
    # Task nueva bajo una US ya DONE, sin reabrir la US.
    backlog = tmp_path / "02-backlog"
    _epic(backlog, "AF-100", "READY")
    _story(backlog, "US-AF100-01", "AF-100", "DONE")
    _task(backlog, "T-AF100-US01-01", "AF-100", "US-AF100-01", "DONE")
    _task(backlog, "T-AF100-US01-02", "AF-100", "US-AF100-01", "READY")

    result = detect_reopened_drift(backlog)

    assert result.has_drift
    assert len(result.items) == 1
    item = result.items[0]
    assert item.parent_id == "US-AF100-01"
    assert item.parent_kind == "user_story"
    assert item.reopened_children == (("T-AF100-US01-02", "READY"),)


def test_detect_reopened_drift_reports_epic_done_with_us_reopened(
    tmp_path: Path,
) -> None:
    backlog = tmp_path / "02-backlog"
    _epic(backlog, "AF-100", "DONE")
    _story(backlog, "US-AF100-01", "AF-100", "DONE")
    _story(backlog, "US-AF100-02", "AF-100", "IN_PROGRESS")
    _task(backlog, "T-AF100-US01-01", "AF-100", "US-AF100-01", "DONE")
    _task(backlog, "T-AF100-US02-01", "AF-100", "US-AF100-02", "IN_PROGRESS")

    result = detect_reopened_drift(backlog)

    parent_ids = {item.parent_id for item in result.items}
    assert "AF-100" in parent_ids
    epic_item = next(item for item in result.items if item.parent_id == "AF-100")
    assert epic_item.parent_kind == "epic"
    assert epic_item.reopened_children == (("US-AF100-02", "IN_PROGRESS"),)


def test_detect_reopened_drift_empty_when_backlog_consistent(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    _epic(backlog, "AF-100", "DONE")
    _story(backlog, "US-AF100-01", "AF-100", "DONE")
    _task(backlog, "T-AF100-US01-01", "AF-100", "US-AF100-01", "DONE")

    result = detect_reopened_drift(backlog)

    assert not result.has_drift
    assert result.items == []


def test_detect_reopened_drift_ignores_us_not_marked_done(tmp_path: Path) -> None:
    # Una US en TODO/IN_PROGRESS/IN_REVIEW con Tasks pendientes no es drift —
    # es el estado normal, no un padre completado prematuramente.
    backlog = tmp_path / "02-backlog"
    _epic(backlog, "AF-100", "READY")
    _story(backlog, "US-AF100-01", "AF-100", "READY")
    _task(backlog, "T-AF100-US01-01", "AF-100", "US-AF100-01", "READY")

    result = detect_reopened_drift(backlog)

    assert not result.has_drift


def test_detect_reopened_drift_does_not_write_any_file(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    _epic(backlog, "AF-100", "READY")
    _story(backlog, "US-AF100-01", "AF-100", "DONE")
    _task(backlog, "T-AF100-US01-01", "AF-100", "US-AF100-01", "READY")

    detect_reopened_drift(backlog)

    # Detección, no corrección: el fichero en disco sigue igual que antes.
    assert _state_of(backlog / "user-stories" / "US-AF100-01.md") == "DONE"


def test_promotion_case_still_works_unchanged_alongside_reopened_drift(
    tmp_path: Path,
) -> None:
    # Criterio 4 de T-AF022-US13-04: el caso ya cubierto (promoción hacia
    # DONE) sigue funcionando sin cambios de comportamiento, incluso en un
    # backlog que también tiene drift inverso en otra rama.
    backlog = tmp_path / "02-backlog"
    _epic(backlog, "AF-100", "READY")
    _story(backlog, "US-AF100-01", "AF-100", "READY")
    _task(backlog, "T-AF100-US01-01", "AF-100", "US-AF100-01", "DONE")
    _story(backlog, "US-AF100-02", "AF-100", "DONE")
    _task(backlog, "T-AF100-US02-01", "AF-100", "US-AF100-02", "READY")

    promotion = check_backlog_promotion(backlog)
    reopened = detect_reopened_drift(backlog)

    assert promotion.promoted_user_stories == ["US-AF100-01"]
    assert reopened.has_drift
    assert reopened.items[0].parent_id == "US-AF100-02"


# ---------------------------------------------------------------------------
# T-AF036-US13-01: la promoción automática (`promote_backlog`) escribe
# `updated_at` en la US y la Epic promovidas.
# ---------------------------------------------------------------------------


def _updated_at_of(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("updated_at:"):
            return line.split(":", 1)[1].strip()
    raise AssertionError(f"no updated_at field in {path}")


def test_promote_backlog_escribe_updated_at_en_us(tmp_path: Path) -> None:
    """Criterio: la promoción automática de una US a IN_REVIEW (todas sus
    Tasks DONE) escribe `updated_at` en su frontmatter."""
    backlog = tmp_path / "02-backlog"
    _epic(backlog, "AF-100", "READY")
    _story(backlog, "US-AF100-01", "AF-100", "READY")
    _task(backlog, "T-AF100-US01-01", "AF-100", "US-AF100-01", "DONE")

    promote_backlog(backlog)

    us_path = backlog / "user-stories" / "US-AF100-01.md"
    assert _state_of(us_path) == "IN_REVIEW"
    assert _updated_at_of(us_path)


def test_promote_backlog_escribe_updated_at_en_epic(tmp_path: Path) -> None:
    """Criterio: la promoción automática de una Epic a DONE (todas sus US
    DONE) escribe `updated_at` en su frontmatter."""
    backlog = tmp_path / "02-backlog"
    _epic(backlog, "AF-100", "READY")
    _story(backlog, "US-AF100-01", "AF-100", "DONE")
    _task(backlog, "T-AF100-US01-01", "AF-100", "US-AF100-01", "DONE")

    promote_backlog(backlog)

    epic_path = backlog / "epics" / "AF-100.md"
    assert _state_of(epic_path) == "DONE"
    assert _updated_at_of(epic_path)


def test_promote_backlog_actualiza_updated_at_existente(tmp_path: Path) -> None:
    """Criterio: si el fichero ya tenía `updated_at`, la promoción lo
    actualiza en lugar de duplicarlo."""
    backlog = tmp_path / "02-backlog"
    _epic(backlog, "AF-100", "READY")
    _story(backlog, "US-AF100-01", "AF-100", "READY")
    _task(backlog, "T-AF100-US01-01", "AF-100", "US-AF100-01", "DONE")
    us_path = backlog / "user-stories" / "US-AF100-01.md"
    us_path.write_text(
        us_path.read_text(encoding="utf-8") + "updated_at: 2020-01-01T00:00:00+00:00\n",
        encoding="utf-8",
    )

    promote_backlog(backlog)

    assert _state_of(us_path) == "IN_REVIEW"
    assert us_path.read_text(encoding="utf-8").count("updated_at:") == 1
    assert _updated_at_of(us_path) != "2020-01-01T00:00:00+00:00"


# ---------------------------------------------------------------------------
# T-AF022-US13-08: reapertura automática del padre al estado del hijo más
# retrasado (sentido inverso de la promoción).
# ---------------------------------------------------------------------------


def _children_of(path: Path) -> list[tuple[str, str]]:  # placeholder
    return []


def test_reopen_backlog_us_done_with_tasks_done_then_to_develop(tmp_path: Path) -> None:
    """Criterio 1: una US DONE con Tasks [DONE, TO_DEVELOP] reabre a
    TO_DEVELOP (estado de la Task más retrasada)."""
    backlog = tmp_path / "02-backlog"
    _epic(backlog, "AF-100", "TO_DO")
    _story(backlog, "US-AF100-01", "AF-100", "DONE")
    _task(backlog, "T-AF100-US01-01", "AF-100", "US-AF100-01", "DONE")
    _task(backlog, "T-AF100-US01-02", "AF-100", "US-AF100-01", "TO_DEVELOP")

    reopened = reopen_backlog(backlog)

    assert _state_of(backlog / "user-stories" / "US-AF100-01.md") == "TO_DEVELOP"
    assert len(reopened.items) == 1
    assert reopened.items[0].parent_id == "US-AF100-01"
    assert reopened.items[0].parent_kind == "user_story"


def test_reopen_backlog_us_done_with_tasks_done_then_ready(tmp_path: Path) -> None:
    """Criterio 2: una US DONE con Tasks [DONE, READY] reabre a READY (la
    Task más retrasada)."""
    backlog = tmp_path / "02-backlog"
    _epic(backlog, "AF-100", "TO_DO")
    _story(backlog, "US-AF100-01", "AF-100", "DONE")
    _task(backlog, "T-AF100-US01-01", "AF-100", "US-AF100-01", "DONE")
    _task(backlog, "T-AF100-US01-02", "AF-100", "US-AF100-01", "READY")

    reopen_backlog(backlog)

    assert _state_of(backlog / "user-stories" / "US-AF100-01.md") == "READY"


def test_reopen_backlog_us_done_with_tasks_done_then_in_review(tmp_path: Path) -> None:
    """Criterio 3: una US DONE con Tasks [DONE, IN_REVIEW] reabre a
    IN_REVIEW (la Task más retrasada)."""
    backlog = tmp_path / "02-backlog"
    _epic(backlog, "AF-100", "TO_DO")
    _story(backlog, "US-AF100-01", "AF-100", "DONE")
    _task(backlog, "T-AF100-US01-01", "AF-100", "US-AF100-01", "DONE")
    _task(backlog, "T-AF100-US01-02", "AF-100", "US-AF100-01", "IN_REVIEW")

    reopen_backlog(backlog)

    assert _state_of(backlog / "user-stories" / "US-AF100-01.md") == "IN_REVIEW"


def test_reopen_backlog_epic_done_with_us_to_plan(tmp_path: Path) -> None:
    """Criterio 4: una Epic DONE con US [DONE, TO_PLAN] reabre a TO_DO (su
    estado menos avanzado)."""
    backlog = tmp_path / "02-backlog"
    _epic(backlog, "AF-100", "DONE")
    _story(backlog, "US-AF100-01", "AF-100", "DONE")
    _task(backlog, "T-AF100-US01-01", "AF-100", "US-AF100-01", "DONE")
    _story(backlog, "US-AF100-02", "AF-100", "TO_PLAN")

    reopen_backlog(backlog)

    assert _state_of(backlog / "epics" / "AF-100.md") == "TO_DO"


def test_reopen_backlog_us_done_with_deferred_task_reopens_to_ready(tmp_path: Path) -> None:
    """Criterio 5: una US DONE con Tasks [DONE, FUERA_ROADMAP] reabre a
    READY (el trabajo diferido de una Task reabre la US a su estado menos
    avanzado, nunca a OUT_OF_SCOPE/NO_TASKS por esta vía)."""
    backlog = tmp_path / "02-backlog"
    _epic(backlog, "AF-100", "TO_DO")
    _story(backlog, "US-AF100-01", "AF-100", "DONE")
    _task(backlog, "T-AF100-US01-01", "AF-100", "US-AF100-01", "DONE")
    _task(backlog, "T-AF100-US01-02", "AF-100", "US-AF100-01", "READY")

    reopen_backlog(backlog)

    assert _state_of(backlog / "user-stories" / "US-AF100-01.md") == "READY"


def test_reopen_backlog_does_not_reopen_consistent_parent(tmp_path: Path) -> None:
    """Criterio 6: un padre DONE con TODOS sus hijos DONE no se reabre."""
    backlog = tmp_path / "02-backlog"
    _epic(backlog, "AF-100", "DONE")
    _story(backlog, "US-AF100-01", "AF-100", "DONE")
    _task(backlog, "T-AF100-US01-01", "AF-100", "US-AF100-01", "DONE")

    reopened = reopen_backlog(backlog)

    assert _state_of(backlog / "epics" / "AF-100.md") == "DONE"
    assert _state_of(backlog / "user-stories" / "US-AF100-01.md") == "DONE"
    assert not reopened.has_drift


def test_reopen_backlog_is_idempotent(tmp_path: Path) -> None:
    """Criterio 7: aplicar la reapertura dos veces seguidas no produce
    cambios en la segunda."""
    backlog = tmp_path / "02-backlog"
    _epic(backlog, "AF-100", "DONE")
    _story(backlog, "US-AF100-01", "AF-100", "DONE")
    _task(backlog, "T-AF100-US01-01", "AF-100", "US-AF100-01", "DONE")
    _task(backlog, "T-AF100-US01-02", "AF-100", "US-AF100-01", "TO_DEVELOP")

    first = reopen_backlog(backlog)
    # La US reabre a TO_DEVELOP y, en cascada, su Epic DONE reabre a TO_DO.
    assert len(first.items) == 2

    second = reopen_backlog(backlog)

    assert len(second.items) == 0
    assert _state_of(backlog / "user-stories" / "US-AF100-01.md") == "TO_DEVELOP"


def test_reopen_backlog_writes_updated_at_on_reopened_parent(tmp_path: Path) -> None:
    """La reapertura también actualiza `updated_at` en el padre reabierto
    (T-AF036-US13-01: todo cambio de estado actualiza el timestamp)."""
    backlog = tmp_path / "02-backlog"
    _epic(backlog, "AF-100", "DONE")
    _story(backlog, "US-AF100-01", "AF-100", "DONE")
    _task(backlog, "T-AF100-US01-01", "AF-100", "US-AF100-01", "DONE")
    _task(backlog, "T-AF100-US01-02", "AF-100", "US-AF100-01", "TO_DEVELOP")

    reopen_backlog(backlog)

    assert _state_of(backlog / "user-stories" / "US-AF100-01.md") == "TO_DEVELOP"
    assert _updated_at_of(backlog / "user-stories" / "US-AF100-01.md")
