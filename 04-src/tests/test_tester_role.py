"""Tests para el rol Tester (T-AF022-US15-01)."""

import pytest
from atlas_forge.agents import TESTER_ROLE, TESTER_PROMPT, build_tester_prompt
from atlas_forge.agents.roles import get_role, list_roles


def test_tester_role_is_registered():
    """El rol 'tester' está registrado en el catálogo de roles."""
    roles = list_roles()
    assert "tester" in roles


def test_tester_role_config_exists():
    """La configuración del rol 'tester' existe y es accesible."""
    role_config = get_role(TESTER_ROLE)
    assert role_config is not None
    assert role_config.role == TESTER_ROLE
    assert role_config.governance_filename == "TESTER.md"
    assert role_config.prompt == TESTER_PROMPT
    assert role_config.prompt_builder is not None
    assert role_config.register_fn is not None


def test_tester_prompt_covers_verification_responsibility():
    """El TESTER_PROMPT define explícitamente su responsabilidad de
    verificación funcional objetiva."""
    assert "verificación funcional objetiva" in TESTER_PROMPT.lower()
    assert "pasa/falla" in TESTER_PROMPT.lower()
    assert "criterios de aceptación" in TESTER_PROMPT.lower()
    assert "tests" in TESTER_PROMPT.lower()


def test_tester_prompt_excludes_ux_opinion():
    """El TESTER_PROMPT explícitamente NO incluye opinión sobre UX/producto."""
    assert "NO debes opinar sobre:" in TESTER_PROMPT
    assert "UX" in TESTER_PROMPT or "UX/Producto" in TESTER_PROMPT
    assert "Auditor-OSS/UX" in TESTER_PROMPT


def test_tester_prompt_is_base_prompt():
    """TESTER_PROMPT es la versión base sin governance."""
    assert TESTER_PROMPT.startswith("Eres el agente Tester de Atlas Forge")


def test_build_tester_prompt_adds_governance(tmp_path):
    """build_tester_prompt añade governance instruction al prompt base."""
    # Crear un proyecto con TESTER.md
    project_path = tmp_path / "test_project"
    project_path.mkdir()
    (project_path / "00-gobierno").mkdir()
    (project_path / "00-gobierno" / "TESTER.md").write_text("# Rol Tester\nEste es el governance del Tester.")
    (project_path / "00-gobierno" / "METODOLOGIA.md").write_text("# Metodología")

    prompt = build_tester_prompt(str(project_path))

    # El prompt debe contener el base + governance
    assert TESTER_PROMPT in prompt
    assert "Rol Tester" in prompt or len(prompt) > len(TESTER_PROMPT)


def test_tester_role_constant():
    """TESTER_ROLE tiene el valor esperado."""
    assert TESTER_ROLE == "tester"


def test_tester_has_register_function():
    """El rol tester tiene función de registro asignada."""
    from atlas_forge.agents import register_tester
    assert callable(register_tester)


def test_tester_role_with_reuse_pattern():
    """El rol tester usa register_agent_with_reuse (reutilizable),
    no register_agent (nueva instancia cada vez)."""
    from atlas_forge.agents.tester import register_tester
    import inspect
    source = inspect.getsource(register_tester)
    # Verifica que la función usa register_agent_with_reuse
    assert "register_agent_with_reuse" in source
