"""Tests del parser de veredicto estructurado del Arquitecto
(T-FB022-US05-01)."""

from brain.dispatcher.architect_verdict import (
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
        "Implementa T-FB022-US05-02."
    )
    estado, justificacion, siguiente = parse_verdict(output)

    assert estado == VERDICT_APPROVED
    assert "todos los criterios" in justificacion
    assert "T-FB022-US05-02" in siguiente


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


def test_process_verdict_writes_rejection_instruction() -> None:
    """T-FB022-US05-03: RECHAZADO genera instrucción de corrección en
    07-informes/<story_id>/_rechazo.md."""
    from brain.dispatcher.job_plan_dispatch import (
        _process_verdict_result,
    )

    rejected_output = (
        "ESTADO: RECHAZADO\n"
        "JUSTIFICACIÓN:\n"
        "Falta implementación de validación.\n"
        "SIGUIENTE_PROMPT_PARA_WORKER:\n"
        "Añade validación en el endpoint."
    )

    _process_verdict_result("US-FB022-99", rejected_output)

    import shutil
    from pathlib import Path as _P

    root = _P(__file__).resolve().parents[2] / "07-informes"
    rejection_file = root / "US-FB022-99" / "_rechazo.md"
    assert rejection_file.exists()
    content = rejection_file.read_text()
    assert "RECHAZADO" in content
    assert "Falta implementación" in content
    assert "Añade validación" in content

    shutil.rmtree(root / "US-FB022-99", ignore_errors=True)
