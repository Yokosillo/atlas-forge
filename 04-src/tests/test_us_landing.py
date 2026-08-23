"""T-AF036-US04-01 · Tests de la lógica central pura de US-AF036-04
("aterrizar una User Story en sus Tasks", `atlas_forge/architect/us_landing.py`).

Verifica que la funcionalidad principal es invocable programáticamente y
que no depende de infraestructura (HTTP, persistencia, I/O): todos los
tests construyen el `USReviewResult` en memoria y nunca tocan disco."""
from __future__ import annotations

import pytest

from atlas_forge.architect.propose_tasks import ProposedTasks
from atlas_forge.architect.review_user_story import USGap, USReviewResult
from atlas_forge.architect.task_pipeline import TaskSelfAuditVerdict
from atlas_forge.architect.us_landing import (
    USLandingPlan,
    can_approve_landing,
    plan_us_landing,
)


def _review(**overrides) -> USReviewResult:
    base: dict = {
        "story_id": "US-AF999-01",
        "has_gaps": False,
        "gaps": [],
        "ready_for_tasks": True,
    }
    base.update(overrides)
    return USReviewResult(**base)


def test_plan_us_landing_is_invocable_programmatically() -> None:
    """La lógica central se invoca directamente desde código, sin pasar por
    HTTP ni por ningún endpoint."""
    plan = plan_us_landing(_review(), "AF-999", "Aterrizar la US en Tasks")
    assert isinstance(plan, USLandingPlan)


def test_plan_us_landing_produces_tasks_for_ready_story() -> None:
    review = _review()
    plan = plan_us_landing(review, "AF-999", "Aterrizar la US en Tasks")
    # Los tres templates del generador determinista (núcleo, conexión,
    # validación del flujo) pasan el corte de valor independiente.
    assert len(plan.proposal.tasks) == 3
    assert all(t.us_id == "US-AF999-01" for t in plan.proposal.tasks)
    assert all(t.epic_id == "AF-999" for t in plan.proposal.tasks)
    assert plan.validation.valid
    assert plan.self_audit is not None
    assert plan.self_audit.status == "APROBADO"


def test_plan_us_landing_task_ids_follow_real_convention() -> None:
    """Los ids generados usan la convención real T-AF999-US01-NN (no el
    formato erróneo T-US-AF999-01-NN, bug ya corregido en el generador)."""
    plan = plan_us_landing(_review(), "AF-999", "Aterrizar la US en Tasks")
    ids = [t.id for t in plan.proposal.tasks]
    assert ids == ["T-AF999-US01-01", "T-AF999-US01-02", "T-AF999-US01-03"]


def test_plan_us_landing_with_gaps_rejects_cleanly() -> None:
    """US con huecos: no lanza excepción, queda reflejado como caso de
    negocio (sin Tasks, autoauditoría RECHAZADO)."""
    review = _review(
        has_gaps=True,
        gaps=[USGap(section="Historia", description="Vacia.")],
        ready_for_tasks=False,
    )
    plan = plan_us_landing(review, "AF-999", "Aterrizar la US en Tasks")
    assert plan.proposal.tasks == []
    assert any("huecos" in n.lower() for n in plan.proposal.notes)
    assert plan.self_audit is not None
    assert plan.self_audit.status == "RECHAZADO"
    assert not can_approve_landing(plan)


def test_plan_us_landing_not_ready_notes_it() -> None:
    review = _review(has_gaps=False, ready_for_tasks=False)
    plan = plan_us_landing(review, "AF-999", "Aterrizar la US en Tasks")
    assert plan.proposal.tasks == []
    assert any("no esta lista" in n.lower() for n in plan.proposal.notes)
    assert plan.self_audit is not None
    assert plan.self_audit.status == "RECHAZADO"


def test_plan_us_landing_without_title_uses_default() -> None:
    plan = plan_us_landing(_review(), "AF-999", "")
    assert len(plan.proposal.tasks) == 3
    assert plan.self_audit is not None
    assert plan.self_audit.status == "APROBADO"


def test_can_approve_landing_policy() -> None:
    approved = plan_us_landing(_review(), "AF-999", "Aterrizar la US en Tasks")
    assert can_approve_landing(approved) is True
    assert can_approve_landing(approved, auto_approve=True) is True

    rejected = plan_us_landing(
        _review(has_gaps=True, gaps=[USGap("Historia", "Vacia.")], ready_for_tasks=False),
        "AF-999",
        "Aterrizar la US en Tasks",
    )
    assert can_approve_landing(rejected) is False
    assert can_approve_landing(rejected, auto_approve=True) is False


def test_plan_us_landing_has_no_io_side_effects(tmp_path) -> None:
    """La lógica central es pura: invocarla no escribe ningún fichero."""
    before = set(p for p in tmp_path.rglob("*")) if tmp_path.exists() else set()
    plan_us_landing(_review(), "AF-999", "Aterrizar la US en Tasks")
    after = set(p for p in tmp_path.rglob("*")) if tmp_path.exists() else set()
    assert before == after


def test_plan_us_landing_is_repeatable() -> None:
    """Determinista: dos invocaciones con el mismo contexto producen el
    mismo plan (mismos ids, títulos y veredicto)."""
    plan_a = plan_us_landing(_review(), "AF-999", "Aterrizar la US en Tasks")
    plan_b = plan_us_landing(_review(), "AF-999", "Aterrizar la US en Tasks")
    assert [t.id for t in plan_a.proposal.tasks] == [t.id for t in plan_b.proposal.tasks]
    assert [t.title for t in plan_a.proposal.tasks] == [t.title for t in plan_b.proposal.tasks]
    assert plan_a.self_audit is not None and plan_b.self_audit is not None
    assert plan_a.self_audit.status == plan_b.self_audit.status


def test_can_approve_landing_with_none_self_audit_rejects() -> None:
    """Política de aprobación: sin veredicto de autoauditoría el plan nunca
    se aprueba, aunque se pida auto-aprobación."""
    plan = plan_us_landing(_review(), "AF-999", "Aterrizar la US en Tasks")
    none_audit = USLandingPlan(plan.proposal, plan.validation, None)
    assert can_approve_landing(none_audit) is False
    assert can_approve_landing(none_audit, auto_approve=True) is False


def test_can_approve_landing_observaciones_respects_auto_approve() -> None:
    """Política de aprobación: APROBADO_CON_OBSERVACIONES solo se aprueba con
    `auto_approve` activo; sin él se rechaza."""
    plan = plan_us_landing(_review(), "AF-999", "Aterrizar la US en Tasks")
    obs = USLandingPlan(
        plan.proposal,
        plan.validation,
        TaskSelfAuditVerdict(status="APROBADO_CON_OBSERVACIONES"),
    )
    assert can_approve_landing(obs) is False
    assert can_approve_landing(obs, auto_approve=True) is True
