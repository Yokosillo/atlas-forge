from pathlib import Path

from brain.dispatcher import build_job_plan_for_story
from brain.dispatcher.job_plan_builder import task_file_story_prefix
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
    """Fixture en el formato Markdown ANTIGUO (pre-FB-027, sección
    `## Estado`) — se mantiene para no perder cobertura de ese camino
    (criterio 4 de T-FB008-US04-05: una Task legacy sin migrar no debe
    romperse con el fix)."""
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


def _write_yaml_task(
    tasks_dir: Path,
    story_id: str,
    correlative: str,
    slug: str,
    title: str,
    state: str,
    extra_body: str = "",
) -> None:
    """Fixture en el formato YAML VIGENTE (frontmatter, FB-027,
    2026-08-06) — el formato real de toda Task escrita hoy en
    `02-backlog/tasks/`. T-FB008-US04-05: los tests existentes solo
    cubrían el formato antiguo, por eso el bug (cualquier Task en este
    formato quedaba invisible para el generador de planes) no se detectó
    antes."""
    content = (
        "---\n"
        f"id: T-{story_id}-{correlative}\n"
        "type: task\n"
        f"title: {title}\n"
        f"state: {state}\n"
        "dependencies: []\n"
        f"user_story: US-{story_id}\n"
        "---\n\n"
        f"# T-{story_id}-{correlative}-{slug} · {title}\n\n"
        "## Descripción\n\n"
        f"{extra_body}\n"
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


def test_task_file_story_prefix_normalizes_canonical_and_normalized_forms() -> None:
    # T-FB022-US13-01B: la forma canónica (US-FBnnn-nn) y la ya normalizada
    # (FBnnn-USnn) deben resolver al mismo prefijo de fichero.
    assert task_file_story_prefix("US-FB020-01") == "FB020-US01"
    assert task_file_story_prefix("FB020-US01") == "FB020-US01"
    assert task_file_story_prefix("US-FB022-13") == "FB022-US13"


def test_build_job_plan_accepts_canonical_us_prefixed_story_id(tmp_path: Path) -> None:
    # T-FB022-US13-01B: build_job_plan_for_story debe encontrar las Tasks
    # reales (T-FB999-US01-...) aunque reciba la forma canónica US-FB999-01,
    # que es la que envía la web desde el selector de historias.
    _write_task(
        tmp_path, "FB999-US01", "01", "primer-paso", "Primer paso", state="TO_DO"
    )
    _write_task(
        tmp_path, "FB999-US01", "02", "segundo-paso", "Segundo paso", state="DONE"
    )

    plan = build_job_plan_for_story("US-FB999-01", tasks_dir=tmp_path)

    assert plan.goal == "US-FB999-01"
    assert [step.description for step in plan.steps] == ["Primer paso"]


def test_build_job_plan_returns_one_step_per_pending_task_in_backlog_order(
    tmp_path: Path,
) -> None:
    story_id = "FB999-US01"
    _write_task(
        tmp_path, story_id, "02", "segundo-paso", "Segundo paso", state="TO_DO"
    )
    _write_task(
        tmp_path, story_id, "01", "primer-paso", "Primer paso", state="TO_DO"
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
        tmp_path, "FB999-US01", "01", "propia", "Task propia", state="TO_DO"
    )
    _write_task(
        tmp_path, "FB999-US02", "01", "ajena", "Task de otra story", state="TO_DO"
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
        state="TO_DO",
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
        state="TO_DO",
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
        state="TO_DO",
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
        state="TO_DO",
        extra_body="Un script determinista ya resuelve este paso.",
    )
    _write_task(
        tmp_path,
        story_id,
        "02",
        "paso-scribe",
        "Resumir con Scribe",
        state="TO_DO",
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


def test_build_job_plan_reads_pending_tasks_in_yaml_frontmatter_format(
    tmp_path: Path,
) -> None:
    # T-FB008-US04-05: bug real — cualquier Task en el formato YAML
    # vigente (FB-027) quedaba invisible para el generador de planes.
    # `POST /plans` con una Story real de 5 Tasks TODO devolvía `steps: []`.
    story_id = "FB999-US01"
    _write_yaml_task(
        tmp_path, story_id, "01", "primer-paso", "Primer paso", state="TO_DO"
    )
    _write_yaml_task(
        tmp_path, story_id, "02", "segundo-paso", "Segundo paso", state="TO_DO"
    )
    _write_yaml_task(
        tmp_path, story_id, "03", "ya-hecho", "Ya cerrado", state="DONE"
    )

    plan = build_job_plan_for_story(story_id, tasks_dir=tmp_path)

    assert [step.description for step in plan.steps] == [
        "Primer paso",
        "Segundo paso",
    ]


def test_build_job_plan_skips_yaml_task_in_review_or_in_progress(
    tmp_path: Path,
) -> None:
    story_id = "FB999-US01"
    _write_yaml_task(
        tmp_path, story_id, "01", "pendiente", "Pendiente", state="TO_DO"
    )
    _write_yaml_task(
        tmp_path, story_id, "02", "en-curso", "En curso", state="IN_PROGRESS"
    )
    _write_yaml_task(
        tmp_path, story_id, "03", "en-revision", "En revisión", state="REVIEW"
    )

    plan = build_job_plan_for_story(story_id, tasks_dir=tmp_path)

    assert [step.description for step in plan.steps] == ["Pendiente"]


# T-FB008-US04-07: bug real — "Escribe el fichero..." (redacción natural
# en español para casi cualquier Task que cree un fichero) contiene
# "scribe" como subcadena literal ("e-scribe"), lo que antes clasificaba
# estas Tasks reales de desarrollo como mecanismo `scribe` en vez de
# `agent`/`developer`. Reproducido con `US-FB036-02`: 3 de sus 6 Tasks
# (`T-FB036-US02-01/02/03`) salían mal clasificadas porque su sección
# `## Descripción` real dice literalmente "Escribe {id}-{slug}.md...".
def test_build_job_plan_does_not_misclassify_spanish_escribe_as_scribe_mechanism(
    tmp_path: Path,
) -> None:
    story_id = "FB999-US01"
    # Fixture equivalente a las 3 Tasks reales de T-FB036-US02-01/02/03:
    # misma frase real "Escribe el fichero..." en la descripción, sin
    # ninguna mención al rol Scribe.
    _write_yaml_task(
        tmp_path,
        story_id,
        "01",
        "endpoint-crear-epic",
        "Endpoint para crear una Epic",
        state="TO_DO",
        extra_body="Escribe el fichero `02-backlog/epics/{id}-{slug}.md` con el esquema exacto.",
    )
    _write_yaml_task(
        tmp_path,
        story_id,
        "02",
        "endpoint-crear-us",
        "Endpoint para crear una User Story",
        state="TO_DO",
        extra_body="Escribe el fichero `02-backlog/user-stories/{id}-{slug}.md` con el esquema exacto.",
    )
    _write_yaml_task(
        tmp_path,
        story_id,
        "03",
        "endpoint-crear-task",
        "Endpoint para crear una Task",
        state="TO_DO",
        extra_body="Escribe el fichero `02-backlog/tasks/T-{id}-{slug}.md` con el esquema exacto.",
    )

    plan = build_job_plan_for_story(story_id, tasks_dir=tmp_path)

    assert len(plan.steps) == 3
    assert all(step.mechanism == "agent" for step in plan.steps)
    assert all(step.agent_role == "developer" for step in plan.steps)


def test_build_job_plan_does_not_misclassify_describe_suscribe_inscribe_as_scribe(
    tmp_path: Path,
) -> None:
    # Otras conjugaciones/palabras españolas reales que también contienen
    # "scribe" como subcadena literal, no solo "escribe".
    story_id = "FB999-US01"
    _write_yaml_task(
        tmp_path,
        story_id,
        "01",
        "describe-comportamiento",
        "Documentar el comportamiento",
        state="TO_DO",
        extra_body="Esta sección describe el comportamiento esperado del endpoint.",
    )
    _write_yaml_task(
        tmp_path,
        story_id,
        "02",
        "suscribe-webhook",
        "Registrar webhook",
        state="TO_DO",
        extra_body="El cliente se suscribe a las notificaciones del backend.",
    )

    plan = build_job_plan_for_story(story_id, tasks_dir=tmp_path)

    assert len(plan.steps) == 2
    assert all(step.mechanism == "agent" for step in plan.steps)


def test_build_job_plan_still_marks_task_mentioning_scribe_as_word_as_scribe_mechanism(
    tmp_path: Path,
) -> None:
    # El fix no debe romper la detección real: "Scribe" mencionado como
    # palabra suelta (el rol/modelo local de FB-014) sigue clasificándose
    # como mecanismo `scribe`.
    story_id = "FB999-US01"
    _write_yaml_task(
        tmp_path,
        story_id,
        "01",
        "paso-scribe",
        "Resumir contexto",
        state="TO_DO",
        extra_body="Invoca al rol Scribe para resumir el documento generado.",
    )

    plan = build_job_plan_for_story(story_id, tasks_dir=tmp_path)

    assert len(plan.steps) == 1
    assert plan.steps[0].mechanism == "scribe"
    assert plan.steps[0].agent_role is None


def test_build_job_plan_script_keyword_matches_whole_word_only(
    tmp_path: Path,
) -> None:
    # Mismo patrón de palabra completa aplicado a `_SCRIPT_KEYWORDS`
    # (criterio 4 de la Task, sin falso positivo real conocido hoy, pero
    # verificado por consistencia): un texto que contuviera "script" como
    # subcadena de otra palabra no debería disparar el mecanismo
    # `"script"`, y una mención real de "script" como palabra suelta debe
    # seguir haciéndolo.
    story_id = "FB999-US01"
    _write_yaml_task(
        tmp_path,
        story_id,
        "01",
        "postscriptum",
        "Postscriptum del informe",
        state="TO_DO",
        extra_body="Añadir un postscriptum al final del informe generado.",
    )
    _write_yaml_task(
        tmp_path,
        story_id,
        "02",
        "ejecutar-tarea",
        "Ejecutar el script real",
        state="TO_DO",
        extra_body="Este paso ejecuta un script determinista ya existente.",
    )

    plan = build_job_plan_for_story(story_id, tasks_dir=tmp_path)

    assert len(plan.steps) == 2
    assert plan.steps[0].mechanism == "agent"
    assert plan.steps[0].agent_role == "developer"
    assert plan.steps[1].mechanism == "script"
    assert plan.steps[1].agent_role is None
