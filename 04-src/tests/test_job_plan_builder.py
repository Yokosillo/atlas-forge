from pathlib import Path

from brain.dispatcher import build_job_plan_for_story
from brain.models import JobPlan, JobPlanStep


def _write_task(
    tasks_dir: Path,
    story_id: str,
    correlative: str,
    slug: str,
    title: str,
    state: str,
    extra_body: str = "",
) -> None:
    content = (
        f"# T-{story_id}-{correlative}-{slug} · {title}\n\n"
        f"**User Story:** {story_id}\n\n"
        "## Descripción\n\n"
        f"{extra_body}\n\n"
        "## Estado\n\n"
        f"{state}\n"
    )
    (tasks_dir / f"T-{story_id}-{correlative}-{slug}.md").write_text(
        content, encoding="utf-8"
    )


def test_job_plan_and_job_plan_step_construction() -> None:
    step = JobPlanStep(
        description="Implementar X", mechanism="agent", agent_role="developer"
    )
    plan = JobPlan(goal="US-FB999-01", steps=[step], status="proposed")

    assert plan.goal == "US-FB999-01"
    assert plan.steps == [step]
    assert plan.status == "proposed"
    assert step.description == "Implementar X"
    assert step.mechanism == "agent"
    assert step.agent_role == "developer"


def test_job_plan_defaults_to_proposed_status_and_empty_steps() -> None:
    plan = JobPlan(goal="US-FB999-01")

    assert plan.status == "proposed"
    assert plan.steps == []


def test_build_job_plan_returns_one_step_per_pending_task_in_backlog_order(
    tmp_path: Path,
) -> None:
    story_id = "FB999-US01"
    _write_task(
        tmp_path, story_id, "02", "segundo-paso", "Segundo paso", state="TODO"
    )
    _write_task(
        tmp_path, story_id, "01", "primer-paso", "Primer paso", state="TODO"
    )
    _write_task(
        tmp_path, story_id, "03", "ya-hecho", "Ya cerrado", state="DONE"
    )

    plan = build_job_plan_for_story(story_id, tasks_dir=tmp_path)

    assert plan.goal == story_id
    assert plan.status == "proposed"
    assert [step.description for step in plan.steps] == [
        "Primer paso",
        "Segundo paso",
    ]


def test_build_job_plan_ignores_tasks_from_other_stories(tmp_path: Path) -> None:
    _write_task(
        tmp_path, "FB999-US01", "01", "propia", "Task propia", state="TODO"
    )
    _write_task(
        tmp_path, "FB999-US02", "01", "ajena", "Task de otra story", state="TODO"
    )

    plan = build_job_plan_for_story("FB999-US01", tasks_dir=tmp_path)

    assert [step.description for step in plan.steps] == ["Task propia"]


def test_build_job_plan_marks_task_mentioning_script_as_script_mechanism(
    tmp_path: Path,
) -> None:
    story_id = "FB999-US01"
    _write_task(
        tmp_path,
        story_id,
        "01",
        "paso-script",
        "Ejecutar el script de limpieza",
        state="TODO",
        extra_body="Reutiliza un script determinista ya existente.",
    )

    plan = build_job_plan_for_story(story_id, tasks_dir=tmp_path)

    assert len(plan.steps) == 1
    assert plan.steps[0].mechanism == "script"
    assert plan.steps[0].agent_role is None


def test_build_job_plan_marks_task_mentioning_scribe_as_scribe_mechanism(
    tmp_path: Path,
) -> None:
    story_id = "FB999-US01"
    _write_task(
        tmp_path,
        story_id,
        "01",
        "paso-scribe",
        "Resumir con Scribe el contexto",
        state="TODO",
        extra_body="Invoca a Scribe para resumir el documento.",
    )

    plan = build_job_plan_for_story(story_id, tasks_dir=tmp_path)

    assert len(plan.steps) == 1
    assert plan.steps[0].mechanism == "scribe"
    assert plan.steps[0].agent_role is None


def test_build_job_plan_marks_task_without_script_or_scribe_as_agent_mechanism(
    tmp_path: Path,
) -> None:
    story_id = "FB999-US01"
    _write_task(
        tmp_path,
        story_id,
        "01",
        "paso-agente",
        "Diseñar la nueva pantalla",
        state="TODO",
        extra_body="Requiere criterio de diseño y juicio del desarrollador.",
    )

    plan = build_job_plan_for_story(story_id, tasks_dir=tmp_path)

    assert len(plan.steps) == 1
    assert plan.steps[0].mechanism == "agent"
    assert plan.steps[0].agent_role == "developer"


def test_build_job_plan_with_only_deterministic_steps_has_no_agent_step(
    tmp_path: Path,
) -> None:
    story_id = "FB999-US01"
    _write_task(
        tmp_path,
        story_id,
        "01",
        "paso-script",
        "Automatizar el chequeo",
        state="TODO",
        extra_body="Un script determinista ya resuelve este paso.",
    )
    _write_task(
        tmp_path,
        story_id,
        "02",
        "paso-scribe",
        "Resumir con Scribe",
        state="TODO",
        extra_body="Se apoya en Scribe para el resumen.",
    )

    plan = build_job_plan_for_story(story_id, tasks_dir=tmp_path)

    assert len(plan.steps) == 2
    assert all(step.mechanism != "agent" for step in plan.steps)


def test_build_job_plan_returns_empty_steps_when_no_pending_tasks(
    tmp_path: Path,
) -> None:
    story_id = "FB999-US01"
    _write_task(tmp_path, story_id, "01", "cerrada", "Ya cerrada", state="DONE")

    plan = build_job_plan_for_story(story_id, tasks_dir=tmp_path)

    assert plan.steps == []
    assert plan.status == "proposed"
