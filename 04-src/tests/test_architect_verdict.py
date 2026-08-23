"""Tests del parser de veredicto estructurado del Arquitecto
(T-AF022-US05-01)."""

from atlas_forge.dispatcher.architect_verdict import (
    VERDICT_APPROVED,
    VERDICT_APPROVED_WITH_NOTES,
    VERDICT_REJECTED,
    parse_verdict,
)


def test_parse_verdict_extracts_approved() -> None:
    output = (
        "ESTADO: APROBADO\n"
        "JUSTIFICACIÓN:\n"
        "El trabajo cumple todos los criterios de aceptación.\n"
        "Los tests pasan y el código está limpio.\n"
        "SIGUIENTE_PROMPT_PARA_WORKER:\n"
        "Implementa T-AF022-US05-02."
    )
    estado, justificacion, siguiente = parse_verdict(output)

    assert estado == VERDICT_APPROVED
    assert "todos los criterios" in justificacion
    assert "T-AF022-US05-02" in siguiente


def test_parse_verdict_extracts_approved_with_observations() -> None:
    output = (
        "ESTADO: APROBADO_CON_OBSERVACIONES\n"
        "JUSTIFICACIÓN:\n"
        "El trabajo es correcto pero hay una mejora menor.\n"
        "SIGUIENTE_PROMPT_PARA_WORKER:\n"
        "Añade el test de cobertura para el caso borde."
    )
    estado, justificacion, siguiente = parse_verdict(output)

    assert estado == VERDICT_APPROVED_WITH_NOTES
    assert "mejora menor" in justificacion
    assert "caso borde" in siguiente


def test_parse_verdict_extracts_rejected() -> None:
    output = (
        "ESTADO: RECHAZADO\n"
        "JUSTIFICACIÓN:\n"
        "Falta el test de integración para el flujo completo.\n"
        "SIGUIENTE_PROMPT_PARA_WORKER:\n"
        "Añade test de integración en test_job_report.py"
    )
    estado, justificacion, siguiente = parse_verdict(output)

    assert estado == VERDICT_REJECTED
    assert "Falta el test" in justificacion
    assert "test_job_report.py" in siguiente


def test_parse_verdict_returns_empty_state_for_unrecognized_format() -> None:
    output = "Texto libre sin formato estructurado de veredicto."
    estado, justificacion, _ = parse_verdict(output)

    assert estado == ""
    assert output in justificacion


def test_parse_verdict_handles_missing_justificacion() -> None:
    output = "ESTADO: APROBADO\nSIGUIENTE_PROMPT_PARA_WORKER:\nSigue."
    estado, justificacion, siguiente = parse_verdict(output)

    assert estado == VERDICT_APPROVED
    assert "Sigue." in siguiente


def test_parse_verdict_handles_missing_siguiente_prompt() -> None:
    output = "ESTADO: RECHAZADO\nJUSTIFICACIÓN:\nNo se cumple el criterio."
    estado, justificacion, siguiente = parse_verdict(output)

    assert estado == VERDICT_REJECTED
    assert "No se cumple" in justificacion
    assert siguiente == ""


def test_process_verdict_rejected_creates_correction_task_on_same_story(tmp_path) -> None:
    """Rediseño 2026-08-17 ('PIPELINE OPERATIVO Y RECONCILIACIÓN',
    sustituye el diseño anterior que solo escribía
    07-informes/<story_id>/_rechazo.md): RECHAZADO crea una Task nueva
    bajo LA MISMA User Story, directamente en TO_DEVELOP — nunca
    propone una US nueva."""
    from atlas_forge.dispatcher.job_plan_dispatch import _process_verdict_result

    backlog_dir = tmp_path / "02-backlog"
    us_dir = backlog_dir / "user-stories"
    us_dir.mkdir(parents=True)
    (us_dir / "US-AF999-01-titulo.md").write_text(
        "---\nid: US-AF999-01\ntype: user_story\ntitle: Titulo\nstate: IN_REVIEW\n"
        "dependencies: []\nepic: AF-999\npriority: Alta\n---\n\n"
        "# US-AF999-01 · Titulo\n\n## Historia\n\nComo usuario quiero X.\n\n"
        "## Criterios de aceptación\n\n- C1\n",
        encoding="utf-8",
    )
    tasks_dir = backlog_dir / "tasks"
    tasks_dir.mkdir(parents=True)
    (tasks_dir / "T-AF999-US01-01.md").write_text(
        "---\nid: T-AF999-US01-01\ntype: task\ntitle: Task\nstate: DONE\n"
        "dependencies: []\nepic: AF-999\nuser_story: US-AF999-01\npriority: Alta\n---\n\n"
        "# T-AF999-US01-01 · Task\n\n## Objetivo\n\nO.\n\n## Descripción\n\nD.\n\n"
        "## Criterios de aceptación\n\n- C1\n",
        encoding="utf-8",
    )

    rejected_output = (
        "ESTADO: RECHAZADO\n"
        "JUSTIFICACIÓN:\n"
        "Falta implementación de validación.\n"
        "SIGUIENTE_PROMPT_PARA_WORKER:\n"
        "Añade validación en el endpoint."
    )

    _process_verdict_result("US-AF999-01", rejected_output, backlog_dir=backlog_dir)

    correction_files = list(tasks_dir.glob("T-AF999-US01-02-*.md"))
    assert len(correction_files) == 1
    correction_text = correction_files[0].read_text(encoding="utf-8")
    assert "state: TO_DEVELOP" in correction_text
    assert "user_story: US-AF999-01" in correction_text
    assert "Añade validación" in correction_text

    # La US original no se promueve a DONE — sigue en IN_REVIEW (o el estado
    # que tuviera), no queda cerrada con trabajo pendiente.
    us_text = (us_dir / "US-AF999-01-titulo.md").read_text(encoding="utf-8")
    assert "state: DONE" not in us_text
