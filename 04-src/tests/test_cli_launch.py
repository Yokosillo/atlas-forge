import uuid

import libtmux
import pytest

from brain.agents import CRITIC_ROLE, DEVELOPER_ROLE
from brain.core.session_lifecycle import activate, list_agents
from brain.dashboard import AgentChoice, confirm_launch, format_catalog
from brain.models import DevelopmentSession


@pytest.fixture(autouse=True)
def _no_real_runtime(monkeypatch):
    """Sustituye los comandos reales de Claude Code/OpenCode por un
    comando de prueba inocuo (`sleep`), para no invocar los binarios
    reales en ningún test de esta Task."""
    import brain.runtime.claude_code as claude_code_module
    import brain.runtime.opencode as opencode_module

    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_COMMAND", "sleep")
    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_ARGS", ["5"])
    monkeypatch.setattr(opencode_module, "DEFAULT_OPENCODE_COMMAND", "sleep")
    monkeypatch.setattr(opencode_module, "DEFAULT_OPENCODE_ARGS", ["5"])


@pytest.fixture
def isolated_socket():
    """Aísla los tests de esta Task en su propio servidor tmux, con
    limpieza garantizada incluso si el test falla a medio camino.
    Se pasa explícitamente como `socket_name` a `confirm_launch` (que lo
    propaga a `launch_agent`) en vez de depender de un default de módulo
    congelado en tiempo de definición (lección ya aplicada en Tasks
    anteriores: `monkeypatch` sobre ese default no tiene efecto)."""
    name = f"brain-test-{uuid.uuid4().hex[:8]}"
    try:
        yield name
    finally:
        try:
            libtmux.Server(socket_name=name).kill()
        except Exception:
            pass


def _active_session() -> DevelopmentSession:
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    return session


def test_format_catalog_shows_agent_types_and_runtimes_and_model_support() -> None:
    output = format_catalog()

    assert DEVELOPER_ROLE in output
    assert CRITIC_ROLE in output
    assert "claude-code" in output
    assert "opencode" in output
    assert "admite indicar modelo" in output
    assert "no admite modelo" in output


def test_confirm_launch_with_valid_combination_shows_agent_operational(
    isolated_socket: str, tmp_path
) -> None:
    session = _active_session()
    choice = AgentChoice(agent_role=DEVELOPER_ROLE, runtime_type="claude-code")

    message = confirm_launch(choice, session, str(tmp_path), socket_name=isolated_socket)

    assert "operativo" in message
    assert DEVELOPER_ROLE in message
    developers = [a for a in list_agents(session) if a.role == DEVELOPER_ROLE]
    assert len(developers) == 1


def test_confirm_launch_with_invalid_combination_shows_clear_message_without_launching(
    tmp_path,
) -> None:
    session = _active_session()
    # Modelo indicado para Claude Code, que no lo soporta.
    choice = AgentChoice(
        agent_role=DEVELOPER_ROLE, runtime_type="claude-code", model="some-model"
    )

    message = confirm_launch(choice, session, str(tmp_path))

    assert "No se pudo lanzar" in message
    assert list_agents(session) == []


def test_confirm_launch_twice_for_a_second_agent_works_on_same_session(
    isolated_socket: str, tmp_path
) -> None:
    # Repetir la elección para un segundo agente (Critic tras Developer)
    # funciona sobre la misma sesión sin reiniciar nada.
    session = _active_session()

    first_message = confirm_launch(
        AgentChoice(agent_role=DEVELOPER_ROLE, runtime_type="claude-code"),
        session,
        str(tmp_path),
        socket_name=isolated_socket,
    )
    second_message = confirm_launch(
        AgentChoice(agent_role=CRITIC_ROLE, runtime_type="opencode"),
        session,
        str(tmp_path),
        socket_name=isolated_socket,
    )

    assert "operativo" in first_message
    assert "operativo" in second_message
    roles_in_session = {a.role for a in list_agents(session)}
    assert roles_in_session == {DEVELOPER_ROLE, CRITIC_ROLE}
