"""T-AF036-US03-01 · Tests de la lógica central pura de US-AF036-03
("aterrizar una Epic en User Stories", `atlas_forge/architect/epic_landing.py`).

Verifica que la funcionalidad principal es invocable programáticamente y
que no depende de infraestructura (HTTP, persistencia, I/O): todos los
tests construyen el `EpicContext` en memoria y nunca tocan disco."""
from __future__ import annotations

import pytest

from atlas_forge.architect.epic_landing import (
    EpicLandingPlan,
    can_approve_landing,
    plan_epic_landing,
)
from atlas_forge.architect.propose_user_stories import EpicContext
from atlas_forge.architect.us_pipeline import USSelfAuditVerdict


def _epic(**overrides) -> EpicContext:
    base: dict = {
        "epic_id": "AF-999",
        "title": "Epic de prueba",
        "objective": "Objetivo real de la Epic.",
        "scope": "Alcance general.",
        "scope_v1": "- Pieza uno.\n- Pieza dos.\n- Pieza tres.",
        "scope_v2_deferred": "",
        "dependencies": "",
        "file_path": "",
    }
    base.update(overrides)
    return EpicContext(**base)


def test_plan_epic_landing_is_invocable_programmatically() -> None:
    """La lógica central se invoca directamente desde código, sin pasar por
    HTTP ni por ningún endpoint."""
    epic = _epic()
    plan = plan_epic_landing(epic)
    assert isinstance(plan, EpicLandingPlan)


def test_plan_epic_landing_produces_stories_from_scope_v1() -> None:
    epic = _epic()
    plan = plan_epic_landing(epic)
    assert len(plan.proposal.stories) == 3
    assert [s.title for s in plan.proposal.stories] == ["Pieza uno", "Pieza dos", "Pieza tres"]
    assert all(s.epic_id == "AF-999" for s in plan.proposal.stories)
    assert plan.validation.valid
    assert plan.self_audit is not None
    assert plan.self_audit.status == "APROBADO"


def test_plan_epic_landing_without_scope_rejects_cleanly() -> None:
    """Epic sin alcance v1 ni objetivo: no lanza excepción, queda reflejado
    como caso de negocio (sin stories, autoauditoría RECHAZADO)."""
    epic = _epic(scope_v1="", objective="")
    plan = plan_epic_landing(epic)
    assert plan.proposal.stories == []
    assert plan.proposal.notes  # explica que no hay contexto
    assert plan.self_audit is not None
    assert plan.self_audit.status == "RECHAZADO"
    assert not can_approve_landing(plan)


def test_plan_epic_landing_with_unparseable_scope_notes_it() -> None:
    epic = _epic(scope_v1="Texto de alcance sin lista de items.")
    plan = plan_epic_landing(epic)
    assert plan.proposal.stories == []
    assert any("alcance" in n.lower() for n in plan.proposal.notes)
    assert plan.self_audit is not None
    assert plan.self_audit.status == "RECHAZADO"


def test_plan_epic_landing_with_v2_deferred_notes_it() -> None:
    epic = _epic(scope_v2_deferred="- Futuro trabajo v2.")
    plan = plan_epic_landing(epic)
    assert any("v2" in n.lower() for n in plan.proposal.notes)


def test_can_approve_landing_policy() -> None:
    approved = plan_epic_landing(_epic())
    assert can_approve_landing(approved) is True
    assert can_approve_landing(approved, auto_approve=True) is True

    rejected = plan_epic_landing(_epic(scope_v1="", objective=""))
    assert can_approve_landing(rejected) is False
    assert can_approve_landing(rejected, auto_approve=True) is False


def test_plan_epic_landing_has_no_io_side_effects(tmp_path) -> None:
    """La lógica central es pura: invocarla no escribe ningún fichero."""
    epic = _epic()
    before = set(p for p in tmp_path.rglob("*")) if tmp_path.exists() else set()
    plan_epic_landing(epic)
    after = set(p for p in tmp_path.rglob("*")) if tmp_path.exists() else set()
    assert before == after


def test_plan_epic_landing_is_repeatable() -> None:
    """Determinista: dos invocaciones con el mismo contexto producen el
    mismo plan (mismo ids, títulos y veredicto)."""
    plan_a = plan_epic_landing(_epic())
    plan_b = plan_epic_landing(_epic())
    assert [s.id for s in plan_a.proposal.stories] == [s.id for s in plan_b.proposal.stories]
    assert [s.title for s in plan_a.proposal.stories] == [s.title for s in plan_b.proposal.stories]
    assert plan_a.self_audit is not None and plan_b.self_audit is not None
    assert plan_a.self_audit.status == plan_b.self_audit.status


def test_can_approve_landing_with_none_self_audit_rejects() -> None:
    """Política de aprobación: sin veredicto de autoauditoría el plan nunca
    se aprueba, aunque se pida auto-aprobación."""
    plan = plan_epic_landing(_epic())
    none_audit = EpicLandingPlan(plan.proposal, plan.validation, None)
    assert can_approve_landing(none_audit) is False
    assert can_approve_landing(none_audit, auto_approve=True) is False


def test_can_approve_landing_observaciones_respects_auto_approve() -> None:
    """Política de aprobación: APROBADO_CON_OBSERVACIONES solo se aprueba con
    `auto_approve` activo; sin él se rechaza."""
    plan = plan_epic_landing(_epic())
    obs = EpicLandingPlan(
        plan.proposal,
        plan.validation,
        USSelfAuditVerdict(status="APROBADO_CON_OBSERVACIONES"),
    )
    assert can_approve_landing(obs) is False
    assert can_approve_landing(obs, auto_approve=True) is True
