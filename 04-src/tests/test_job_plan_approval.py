import pytest

from atlas_forge.dispatcher import InvalidJobPlanTransitionError, present_plan_for_approval
from atlas_forge.models import JobPlan, JobPlanStep


def _make_plan(status: str = "proposed") -> JobPlan:
    return JobPlan(
        goal="AF999-US01",
        steps=[
            JobPlanStep(description="paso 1", mechanism="agent", agent_role="developer"),
            JobPlanStep(description="paso 2", mechanism="script"),
        ],
        status=status,
    )


def test_approving_a_proposed_plan_transitions_to_approved() -> None:
    plan = _make_plan(status="proposed")

    result = present_plan_for_approval(plan, approved=True)

    assert result.status == "approved"
    assert result is plan


def test_rejecting_a_proposed_plan_transitions_to_rejected() -> None:
    plan = _make_plan(status="proposed")

    result = present_plan_for_approval(plan, approved=False)

    assert result.status == "rejected"
    assert result is plan


def test_approval_does_not_mutate_steps() -> None:
    plan = _make_plan(status="proposed")
    original_steps = list(plan.steps)

    present_plan_for_approval(plan, approved=True)

    assert plan.steps == original_steps


def test_rejected_plan_cannot_transition_to_approved() -> None:
    plan = _make_plan(status="rejected")

    with pytest.raises(InvalidJobPlanTransitionError):
        present_plan_for_approval(plan, approved=True)

    assert plan.status == "rejected"


def test_approved_plan_cannot_be_rejected_afterwards() -> None:
    plan = _make_plan(status="approved")

    with pytest.raises(InvalidJobPlanTransitionError):
        present_plan_for_approval(plan, approved=False)

    assert plan.status == "approved"


def test_approved_plan_cannot_be_approved_again() -> None:
    plan = _make_plan(status="approved")

    with pytest.raises(InvalidJobPlanTransitionError):
        present_plan_for_approval(plan, approved=True)

    assert plan.status == "approved"


def test_no_public_function_approves_an_individual_step() -> None:
    # Criterio de aceptación explícito: no debe existir ninguna función
    # pública en el módulo de aprobación que opere sobre un JobPlanStep
    # individual, solo sobre el JobPlan completo.
    import atlas_forge.dispatcher.job_plan_approval as approval_module

    public_names = [name for name in dir(approval_module) if not name.startswith("_")]
    step_level_names = [name for name in public_names if "step" in name.lower()]

    assert step_level_names == []
