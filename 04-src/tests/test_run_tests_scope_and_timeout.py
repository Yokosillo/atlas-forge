"""Tests deterministas de la política de subconjunto de suite y del timeout
de `run_tests` (T-AF025-US04-02, US-AF025-04):

- `_any_unit_marker`: detecta si un proyecto divide su suite con el marcador
  `unit` (entonces `run_tests` por defecto selecciona `-m unit`); si no,
  ejecuta el directorio `tests/` completo (fallback genérico).
- `RUN_PROJECT_TESTS_TIMEOUT_SECONDS`: timeout DEFINITIVO de `run_tests`,
  por-call (no infla el default global de los scripts regulares).
- El default de scripts regulares (`DEFAULT_SCRIPT_TIMEOUT_SECONDS`) vuelve a
  un valor coherente (retirado el parche provisional 30→600)."""

from pathlib import Path

from atlas_forge.workspace.generic_scripts import (
    RUN_PROJECT_TESTS_TIMEOUT_SECONDS,
    _any_unit_marker,
)
from atlas_forge.workspace.project_scripts import DEFAULT_SCRIPT_TIMEOUT_SECONDS


def _write_test(tmp: Path, filename: str, marker: bool) -> None:
    (tmp / "tests").mkdir(parents=True, exist_ok=True)
    content = "import pytest\n\n"
    if marker:
        content += "pytestmark = pytest.mark.unit\n\n"
    content += "def test_demo():\n    assert True\n"
    (tmp / "tests" / filename).write_text(content, encoding="utf-8")


def test_any_unit_marker_detecta_el_marcador_unit(tmp_path: Path) -> None:
    _write_test(tmp_path, "test_a.py", marker=True)
    assert _any_unit_marker(tmp_path / "tests") is True


def test_any_unit_marker_false_sin_marcador(tmp_path: Path) -> None:
    _write_test(tmp_path, "test_a.py", marker=False)
    assert _any_unit_marker(tmp_path / "tests") is False


def test_any_unit_marker_false_sin_directorio(tmp_path: Path) -> None:
    assert _any_unit_marker(tmp_path / "no-existe") is False


def test_run_tests_timeout_es_definitivo_y_por_call() -> None:
    # El timeout de run_tests es explícito y sustancialmente mayor que el
    # default de los scripts regulares — no se infla el global.
    assert RUN_PROJECT_TESTS_TIMEOUT_SECONDS >= 600.0
    assert RUN_PROJECT_TESTS_TIMEOUT_SECONDS > DEFAULT_SCRIPT_TIMEOUT_SECONDS


def test_default_script_timeout_retirado_el_parche_provisional() -> None:
    # El parche provisional (30→600 para tapar el cuelgue de la suite) se
    # retiró: el default de scripts regulares vuelve a un valor coherente
    # con scripts que terminan en segundos (gracias al timeout por-call de
    # run_tests no hace falta inflar el global).
    assert DEFAULT_SCRIPT_TIMEOUT_SECONDS == 60.0


def test_run_tests_no_se_anida_bajo_otra_ejecucion_antirrecursion(
    tmp_path: Path, monkeypatch,
) -> None:
    """Guard anti-recursión (T-AF025-US04-02): si `run_tests` se invoca
    estando YA dentro de una ejecución de tests lanzada por él mismo (el
    pytest padre), NO anida otro `pytest` — devuelve un resultado explícito
    en vez de recursar hasta el timeout (causa del cuelgue del subconjunto
    `unit` vía `test_action_list_is_known` → acción `testear`)."""
    import os

    from atlas_forge.workspace.generic_scripts import (
        _ATLAS_FORGE_RUNNING_TESTS,
        _run_project_tests,
    )

    _write_test(tmp_path, "test_a.py", marker=True)

    # Simula el entorno del pytest padre lanzado por run_tests.
    monkeypatch.setenv(_ATLAS_FORGE_RUNNING_TESTS, "1")

    result = _run_project_tests(str(tmp_path))

    assert result.success is False
    assert result.exit_code is None
    assert "no se anidian" in (result.error_message or "")
    assert "recursión" in (result.error_message or "")

    # Y si el marcador NO está, sí lanza el subproceso pytest (no recursa).
    monkeypatch.delenv(_ATLAS_FORGE_RUNNING_TESTS, raising=False)
    result2 = _run_project_tests(str(tmp_path))
    assert result2.success is True
    assert result2.exit_code == 0