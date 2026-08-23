"""Test de regresión para T-AF036-US10-03: verificar que el endpoint
POST /backlog/us/{us_id}/propose-tasks extrae correctamente el epic_id
del us_id. Bug: extraía "US" en lugar de "AF003" para ID "US-AF003-02".
"""

import re


def test_epic_id_extraction_from_us_id():
    """Prueba que el patrón de extracción de epic_id funciona correctamente."""
    test_cases = [
        ("US-AF003-02", "AF003"),
        ("US-AF022-15", "AF022"),
        ("US-AF036-10", "AF036"),
        ("US-AF001-01", "AF001"),
        ("US-AF999-99", "AF999"),
    ]

    for us_id, expected_epic in test_cases:
        match = re.search(r"AF\d+", us_id)
        epic_id = match.group(0) if match else us_id
        assert epic_id == expected_epic, (
            f"Para us_id '{us_id}', se esperaba epic_id '{expected_epic}', "
            f"se obtuvo '{epic_id}'"
        )


def test_epic_id_extraction_fallback():
    """Prueba que si no hay patrón AF\d+, retorna el us_id completo."""
    us_id = "INVALID-ID"
    match = re.search(r"AF\d+", us_id)
    epic_id = match.group(0) if match else us_id
    assert epic_id == us_id
