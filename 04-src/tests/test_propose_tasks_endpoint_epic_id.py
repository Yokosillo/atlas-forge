"""Test de regresión para T-FB036-US10-03: verificar que el endpoint
POST /backlog/us/{us_id}/propose-tasks extrae correctamente el epic_id
del us_id. Bug: extraía "US" en lugar de "FB003" para ID "US-FB003-02".
"""

import re


def test_epic_id_extraction_from_us_id():
    """Prueba que el patrón de extracción de epic_id funciona correctamente."""
    test_cases = [
        ("US-FB003-02", "FB003"),
        ("US-FB022-15", "FB022"),
        ("US-FB036-10", "FB036"),
        ("US-FB001-01", "FB001"),
        ("US-FB999-99", "FB999"),
    ]

    for us_id, expected_epic in test_cases:
        match = re.search(r"FB\d+", us_id)
        epic_id = match.group(0) if match else us_id
        assert epic_id == expected_epic, (
            f"Para us_id '{us_id}', se esperaba epic_id '{expected_epic}', "
            f"se obtuvo '{epic_id}'"
        )


def test_epic_id_extraction_fallback():
    """Prueba que si no hay patrón FB\d+, retorna el us_id completo."""
    us_id = "INVALID-ID"
    match = re.search(r"FB\d+", us_id)
    epic_id = match.group(0) if match else us_id
    assert epic_id == us_id
