from brain.dispatcher import (
    DEFAULT_JOB_COUNT_THRESHOLD,
    DEFAULT_SIZE_THRESHOLD_CHARACTERS,
    compose_job_instruction_with_scribe_context,
    extract_scribe_context,
    should_invoke_scribe,
    should_invoke_scribe_by_job_count,
    should_invoke_scribe_by_size,
)


def test_should_invoke_scribe_by_size_positive_case_above_threshold() -> None:
    content = "x" * (DEFAULT_SIZE_THRESHOLD_CHARACTERS + 1)
    assert should_invoke_scribe_by_size(content) is True


def test_should_invoke_scribe_by_size_negative_case_below_threshold() -> None:
    content = "x" * (DEFAULT_SIZE_THRESHOLD_CHARACTERS - 1)
    assert should_invoke_scribe_by_size(content) is False


def test_should_invoke_scribe_by_size_edge_case_exactly_at_threshold() -> None:
    # Estrictamente mayor que el umbral, no "mayor o igual" — un Job
    # justo en el límite no dispara todavía (documentado en la función).
    content = "x" * DEFAULT_SIZE_THRESHOLD_CHARACTERS
    assert should_invoke_scribe_by_size(content) is False


def test_should_invoke_scribe_by_job_count_before_threshold() -> None:
    assert should_invoke_scribe_by_job_count(DEFAULT_JOB_COUNT_THRESHOLD - 1) is False


def test_should_invoke_scribe_by_job_count_at_threshold() -> None:
    assert should_invoke_scribe_by_job_count(DEFAULT_JOB_COUNT_THRESHOLD) is True


def test_should_invoke_scribe_by_job_count_after_threshold() -> None:
    assert should_invoke_scribe_by_job_count(DEFAULT_JOB_COUNT_THRESHOLD + 5) is True


def test_should_invoke_scribe_combines_both_criteria_with_or_neither_triggers() -> None:
    small_content = "x" * (DEFAULT_SIZE_THRESHOLD_CHARACTERS - 1)
    low_count = DEFAULT_JOB_COUNT_THRESHOLD - 1
    assert should_invoke_scribe(small_content, low_count) is False


def test_should_invoke_scribe_combines_both_criteria_with_or_only_size_triggers() -> None:
    large_content = "x" * (DEFAULT_SIZE_THRESHOLD_CHARACTERS + 1)
    low_count = DEFAULT_JOB_COUNT_THRESHOLD - 1
    assert should_invoke_scribe(large_content, low_count) is True


def test_should_invoke_scribe_combines_both_criteria_with_or_only_count_triggers() -> None:
    small_content = "x" * (DEFAULT_SIZE_THRESHOLD_CHARACTERS - 1)
    high_count = DEFAULT_JOB_COUNT_THRESHOLD
    assert should_invoke_scribe(small_content, high_count) is True


def test_should_invoke_scribe_combines_both_criteria_with_or_both_trigger() -> None:
    large_content = "x" * (DEFAULT_SIZE_THRESHOLD_CHARACTERS + 1)
    high_count = DEFAULT_JOB_COUNT_THRESHOLD
    assert should_invoke_scribe(large_content, high_count) is True


def test_compose_job_instruction_keeps_original_description_intact() -> None:
    instruction = compose_job_instruction_with_scribe_context(
        "Implementa la función X", "Resumen: el documento trata sobre Y."
    )
    assert instruction.startswith("Implementa la función X")


def test_compose_job_instruction_delimits_scribe_section_explicitly() -> None:
    instruction = compose_job_instruction_with_scribe_context(
        "Implementa la función X", "Resumen: el documento trata sobre Y."
    )
    assert "--- Contexto pre-procesado por Scribe ---" in instruction
    assert "--- Fin del contexto pre-procesado por Scribe ---" in instruction
    assert "Resumen: el documento trata sobre Y." in instruction


def test_agent_can_programmatically_distinguish_scribe_section_from_original_request() -> (
    None
):
    # Criterio de aceptación: "el agente puede distinguir
    # programáticamente la sección de Scribe de la petición original (no
    # solo visualmente para un humano)" — verificado con
    # `extract_scribe_context`, que aísla solo el contenido de Scribe.
    original_description = "Implementa la función X, revisando el fichero adjunto."
    scribe_result = "Resumen: el fichero define 3 funciones auxiliares."

    instruction = compose_job_instruction_with_scribe_context(
        original_description, scribe_result
    )
    extracted = extract_scribe_context(instruction)

    assert extracted == scribe_result
    assert original_description not in extracted


def test_extract_scribe_context_returns_none_when_no_scribe_section_present() -> None:
    plain_instruction = "Implementa la función X sin ningún contexto de Scribe."
    assert extract_scribe_context(plain_instruction) is None
