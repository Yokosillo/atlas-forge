"""Tests de T-FB005-US01-05: el rol de Arquitecto/Developer se construye en
DOS capas, ambas decididas por Factory Brain antes de arrancar el agente:

1. Rol base (`ARQUITECTO_PROMPT`/`DEVELOPER_PROMPT`): responsabilidad y
   límites + protocolo de reporte. Para Developer: Resultado/Resumen/
   Siguiente paso sugerido. Para Arquitecto (T-FB022-US05-01, antes
   Critic): formato estructurado de veredicto (ESTADO/JUSTIFICACIÓN/
   SIGUIENTE_PROMPT_PARA_WORKER).
2. Gobierno específico del proyecto (`project_governance_instruction`):
   instrucción explícita de leer `00-gobierno/<rol>.md` +
   `00-gobierno/METODOLOGIA.md` SOLO si ambos existen — la decisión se toma
   en Python (`project_has_governance`, comprobación determinista de
   ficheros en disco), NUNCA como condición textual ("si existen, léelos")
   dentro del prompt que el agente tendría que autoevaluar.
"""

import time
import uuid

import libtmux
import pytest

from brain.agents import (
    ARQUITECTO_PROMPT,
    ARQUITECTO_ROLE,
    DEVELOPER_PROMPT,
    DEVELOPER_ROLE,
    build_arquitecto_prompt,
    build_developer_prompt,
    project_governance_instruction,
    project_has_governance,
    register_arquitecto,
    register_developer,
)
from brain.agents.governance import (
    GOVERNANCE_DIRNAME,
    METODOLOGIA_FILENAME,
)
from brain.agents.roles import get_governance_filename_for_role
from brain.core import activate
from brain.models import DevelopmentSession, Runtime


@pytest.fixture
def isolated_socket():
    name = f"brain-test-{uuid.uuid4().hex[:8]}"
    yield name
    try:
        libtmux.Server(socket_name=name).kill()
    except Exception:
        pass


def _test_runtime() -> Runtime:
    # Comando de prueba inocuo (`sleep`), NO un binario real de runtime.
    return Runtime(
        id="test-runtime", name="Test Runtime", type="test", command="sleep", args=["5"]
    )


def _active_session() -> DevelopmentSession:
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    return session


def _create_governance_project(tmp_path, role: str) -> str:
    """Proyecto real de prueba con `00-gobierno/<rol>.md` +
    `00-gobierno/METODOLOGIA.md` (ficheros reales en disco, no mockeados)."""
    governance_dir = tmp_path / GOVERNANCE_DIRNAME
    governance_dir.mkdir(parents=True)
    (governance_dir / get_governance_filename_for_role(role)).write_text(
        f"# Rol {role} del proyecto de prueba\n", encoding="utf-8"
    )
    (governance_dir / METODOLOGIA_FILENAME).write_text(
        "# Metodología del proyecto de prueba\n", encoding="utf-8"
    )
    return str(tmp_path)


# ---------------------------------------------------------------------------
# La decisión es de Factory Brain, en Python, por existencia en disco
# ---------------------------------------------------------------------------


def test_project_has_governance_false_without_governance_dir(tmp_path) -> None:
    assert project_has_governance(str(tmp_path), "arquitecto") is False
    assert project_has_governance(str(tmp_path), "developer") is False


def test_project_has_governance_requires_role_file_and_metodologia(tmp_path) -> None:
    governance_dir = tmp_path / GOVERNANCE_DIRNAME
    governance_dir.mkdir(parents=True)

    # Solo el fichero de rol, sin METODOLOGIA.md -> no hay gobierno específico.
    (governance_dir / get_governance_filename_for_role("arquitecto")).write_text("x")
    assert project_has_governance(str(tmp_path), "arquitecto") is False

    # Solo METODOLOGIA.md, sin el fichero de rol -> no hay gobierno específico.
    (governance_dir / METODOLOGIA_FILENAME).write_text("x")
    assert project_has_governance(str(tmp_path), "arquitecto") is True  # ahora ambos
    # Developer necesita SU fichero de rol, no el de Arquitecto.
    assert project_has_governance(str(tmp_path), "developer") is False


def test_project_has_governance_true_with_both_files(tmp_path) -> None:
    project = _create_governance_project(tmp_path, "arquitecto")
    assert project_has_governance(project, "arquitecto") is True

    project_dev = _create_governance_project(tmp_path / "dev", "developer")
    assert project_has_governance(project_dev, "developer") is True


def test_governance_instruction_empty_when_project_has_no_governance(tmp_path) -> None:
    assert project_governance_instruction(str(tmp_path), "arquitecto") == ""
    assert project_governance_instruction(str(tmp_path), "developer") == ""


def test_governance_instruction_mentions_the_role_specific_file(tmp_path) -> None:
    arquitecto_project = _create_governance_project(tmp_path / "c", "arquitecto")
    arquitecto_instruction = project_governance_instruction(
        arquitecto_project, "arquitecto"
    )
    assert "00-gobierno/ARQUITECTO.md" in arquitecto_instruction
    assert "00-gobierno/METODOLOGIA.md" in arquitecto_instruction

    developer_project = _create_governance_project(tmp_path / "d", "developer")
    developer_instruction = project_governance_instruction(
        developer_project, "developer"
    )
    assert "00-gobierno/developer.md" in developer_instruction
    assert "00-gobierno/METODOLOGIA.md" in developer_instruction


def test_decision_is_taken_in_python_using_path_exists(monkeypatch) -> None:
    """Criterio explícito: la comprobación de existencia la hace Factory
    Brain con `Path.exists()` — aquí mockeado — NO una condición textual
    dentro del prompt que el agente deba autoevaluar. El mismo
    `project_path` produce instrucción o no según lo que `exists()`
    devuelva, sin que el texto del prompt cambie de lógica."""
    import brain.agents.governance as governance

    class _FakePath:
        def __init__(self, exists: bool) -> None:
            self._exists = exists

        def __truediv__(self, other):
            return self

        def exists(self) -> bool:
            return self._exists

    # `exists()` devuelve True (ficheros "existentes") -> decisión: incluir.
    monkeypatch.setattr(governance, "Path", lambda *_: _FakePath(True))
    assert project_has_governance("/proyecto", "arquitecto") is True
    assert project_governance_instruction("/proyecto", "arquitecto") != ""

    # `exists()` devuelve False (ficheros "inexistentes") -> decisión: no incluir.
    monkeypatch.setattr(governance, "Path", lambda *_: _FakePath(False))
    assert project_has_governance("/proyecto", "arquitecto") is False
    assert project_governance_instruction("/proyecto", "arquitecto") == ""


# ---------------------------------------------------------------------------
# Rol base: no se reintroduce la condición textual "si existen, léelos"
# ---------------------------------------------------------------------------


def test_base_prompts_do_not_reintroduce_the_conditional_pattern() -> None:
    """Criterio explícito: 'No se reintroduce el patrón "si existen,
    léelos" como texto libre dentro del prompt'. La decisión de incluir la
    capa de gobierno se toma en Python; el rol base nunca debe contener esa
    condición textual para que el agente la autoevalúe."""
    for base_prompt in (ARQUITECTO_PROMPT, DEVELOPER_PROMPT):
        assert "si existen" not in base_prompt.lower()
        assert "léelos" not in base_prompt.lower()
        assert "léelo" not in base_prompt.lower()


def test_base_prompts_contain_the_generic_reporting_protocol() -> None:
    """El rol base incluye el protocolo de reporte GENÉRICO (campos
    Resultado/Resumen/Siguiente paso sugerido), sin asumir el protocolo
    específico de worker_output.txt/STORY_DONE de PROD-006."""
    for base_prompt in (ARQUITECTO_PROMPT, DEVELOPER_PROMPT):
        assert "Resultado" in base_prompt
        assert "Resumen" in base_prompt
        assert "Siguiente paso sugerido" in base_prompt
        # Genérico: NO asume la convención de entrega de un proyecto concreto.
        assert "worker_output.txt" not in base_prompt
        assert "STORY_DONE" not in base_prompt


# ---------------------------------------------------------------------------
# Contenido EXACTO de ambos prompts (con y sin gobierno) para ambos roles —
# 4 casos mínimo
# ---------------------------------------------------------------------------


def test_arquitecto_prompt_without_governance_is_exactly_the_base_role(tmp_path) -> None:
    assert build_arquitecto_prompt(str(tmp_path)) == ARQUITECTO_PROMPT


def test_developer_prompt_without_governance_is_exactly_the_base_role(tmp_path) -> None:
    assert build_developer_prompt(str(tmp_path)) == DEVELOPER_PROMPT


def test_arquitecto_prompt_with_governance_is_base_plus_explicit_instruction(
    tmp_path,
) -> None:
    project = _create_governance_project(tmp_path, "arquitecto")
    instruction = project_governance_instruction(project, ARQUITECTO_ROLE)
    prompt = build_arquitecto_prompt(project)

    # Concatenación exacta: rol base + capa de gobierno específico.
    assert prompt == ARQUITECTO_PROMPT + instruction
    # El rol base sigue íntegro (no degradado).
    assert prompt.startswith(ARQUITECTO_PROMPT)
    # La instrucción de lectura es EXPLÍCITA y determinista.
    assert "00-gobierno/ARQUITECTO.md" in prompt
    assert "00-gobierno/METODOLOGIA.md" in prompt


def test_developer_prompt_with_governance_is_base_plus_explicit_instruction(
    tmp_path,
) -> None:
    project = _create_governance_project(tmp_path, "developer")
    instruction = project_governance_instruction(project, DEVELOPER_ROLE)
    prompt = build_developer_prompt(project)

    assert prompt == DEVELOPER_PROMPT + instruction
    assert prompt.startswith(DEVELOPER_PROMPT)
    assert "00-gobierno/developer.md" in prompt
    assert "00-gobierno/METODOLOGIA.md" in prompt


# ---------------------------------------------------------------------------
# Integración: el registro usa el prompt en dos capas (end-to-end)
# ---------------------------------------------------------------------------


def test_register_developer_with_governance_project_builds_two_layer_prompt(
    isolated_socket: str, tmp_path
) -> None:
    project = _create_governance_project(tmp_path, "developer")
    agent, instance = register_developer(
        _active_session(), _test_runtime(), project, socket_name=isolated_socket
    )
    time.sleep(0.3)
    try:
        assert agent.prompt == build_developer_prompt(project)
        assert agent.prompt == DEVELOPER_PROMPT + project_governance_instruction(
            project, DEVELOPER_ROLE
        )
        assert "00-gobierno/developer.md" in agent.prompt
    finally:
        from brain.runtime import stop_runtime

        stop_runtime(instance, socket_name=isolated_socket)


def test_register_arquitecto_without_governance_gets_only_base_role(
    isolated_socket: str, tmp_path
) -> None:
    agent, instance = register_arquitecto(
        _active_session(), _test_runtime(), str(tmp_path), socket_name=isolated_socket
    )
    time.sleep(0.3)
    try:
        assert agent.prompt == ARQUITECTO_PROMPT
        assert agent.prompt == build_arquitecto_prompt(str(tmp_path))
    finally:
        from brain.runtime import stop_runtime

        stop_runtime(instance, socket_name=isolated_socket)
