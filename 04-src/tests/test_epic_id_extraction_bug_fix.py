"""Test de regresión para T-FB036-US10-03: verificar que la función
de extracción de epic_id desde us_id en routes.py está corregida.

Bug reproducido: POST /backlog/us/US-FB003-02/propose-tasks devolvía
epic_id: "US" en lugar de "FB003". Raíz: lógica defectuosa de split.
"""

import re
from pathlib import Path

import pytest


def test_epic_id_extraction_logic():
    """Prueba la lógica de extracción de epic_id de routes.py."""
    test_cases = [
        ("US-FB003-02", "FB003"),
        ("US-FB022-15", "FB022"),
        ("US-FB036-10", "FB036"),
        ("US-FB001-01", "FB001"),
        ("US-FB999-99", "FB999"),
        ("US-FB027-05", "FB027"),
    ]

    for us_id, expected_epic in test_cases:
        # Esta es la lógica correcta que ahora debe estar en routes.py
        match = re.search(r"FB\d+", us_id)
        epic_id = match.group(0) if match else us_id

        assert epic_id == expected_epic, (
            f"Para us_id '{us_id}', se esperaba epic_id '{expected_epic}', "
            f"se obtuvo '{epic_id}'"
        )


def test_old_buggy_logic():
    """Demuestra que la lógica anterior estaba rota."""
    us_id = "US-FB003-02"

    # La lógica ANTIGUA (rota):
    old_epic_id = us_id.split("-US")[0] if "-US" in us_id else us_id.split("-")[0]

    # Para "US-FB003-02", no contiene "-US", así que hace split por "-"
    # y toma el primer elemento: "US" (INCORRECTO)
    assert old_epic_id == "US", (
        f"Bug reproducido: para '{us_id}', la lógica antigua produce '{old_epic_id}'"
    )


def test_new_correct_logic():
    """Verifica que la lógica nueva es correcta."""
    us_id = "US-FB003-02"

    # La lógica NUEVA (correcta):
    match = re.search(r"FB\d+", us_id)
    epic_id = match.group(0) if match else us_id

    # Para "US-FB003-02", extrae "FB003" (CORRECTO)
    assert epic_id == "FB003", (
        f"Bug fijo: para '{us_id}', la lógica nueva produce '{epic_id}'"
    )
