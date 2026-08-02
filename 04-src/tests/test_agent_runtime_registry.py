import uuid

import libtmux
import pytest

from brain.agents import DEVELOPER_ROLE, register_agent, register_critic, register_developer
from brain.core import activate
from brain.agents.launch import launch_agent
from brain.models import DevelopmentSession, Runtime
from brain.runtime import get_runtime_instance_for_agent
from brain.runtime.agent_runtime_registry import _reset_registry_for_tests


@pytest.fixture(autouse=True)
def _reset_agent_runtime_registry():
    # Registro nuevo en memoria de proceso (T-FB002-US03-00) — se
    # resetea antes/después de cada test para no depender del orden de
    # ejecución, mismo patrón que session_registry/job_count_registry.
    _reset_registry_for_tests()
    yield
    _reset_registry_for_tests()


@pytest.fixture(autouse=True)
def _no_real_runtime(monkeypatch):
    """Sustituye los comandos reales de Claude Code/OpenCode por `sleep`
    para no invocar los binarios reales en ningún test de esta Task —
    mismo patrón ya usado en test_launch_agent.py/test_dashboard_screen.py.
    Necesario aquí porque `launch_agent` (usado en un test de esta
    suite) construye su Runtime desde `register_claude_code_runtime`, que
    por defecto apunta al binario real `claude`."""
    import brain.runtime.claude_code as claude_code_module
    import brain.runtime.opencode as opencode_module

    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_COMMAND", "sleep")
    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_ARGS", ["5"])
    monkeypatch.setattr(opencode_module, "DEFAULT_OPENCODE_COMMAND", "sleep")
    monkeypatch.setattr(opencode_module, "DEFAULT_OPENCODE_AUTONOMY_FLAG", "5")


@pytest.fixture
def isolated_socket():
    """Aísla los tests de esta Task en su propio servidor tmux, con
    limpieza garantizada incluso si el test falla a medio camino."""
    name = f"brain-test-{uuid.uuid4().hex[:8]}"
    try:
        yield name
    finally:
        try:
            libtmux.Server(socket_name=name).kill()
        except Exception:
            pass


def _test_runtime(runtime_id: str = "test-runtime") -> Runtime:
    return Runtime(
        id=runtime_id, name="Test Runtime", type="test", command="sleep", args=["5"]
    )


def _active_session(session_id: str = "s1") -> DevelopmentSession:
    session = DevelopmentSession(id=session_id, project_id="p1")
    activate(session)
    return session


def test_runtime_instance_is_queryable_after_register_agent(
    isolated_socket: str, tmp_path
) -> None:
    session = _active_session()
    runtime = _test_runtime()

    agent, runtime_instance = register_agent(
        name="test-agent",
        role="developer",
        prompt="p",
        runtime=runtime,
        session=session,
        project_path=str(tmp_path),
        socket_name=isolated_socket,
    )

    assert get_runtime_instance_for_agent(agent.id) == runtime_instance


def test_runtime_instance_is_queryable_after_register_developer(
    isolated_socket: str, tmp_path
) -> None:
    session = _active_session()
    runtime = _test_runtime()

    agent, runtime_instance = register_developer(
        session, runtime, str(tmp_path), socket_name=isolated_socket
    )

    assert get_runtime_instance_for_agent(agent.id) == runtime_instance


def test_runtime_instance_is_queryable_after_register_critic(
    isolated_socket: str, tmp_path
) -> None:
    session = _active_session()
    runtime = _test_runtime()

    agent, runtime_instance = register_critic(
        session, runtime, str(tmp_path), socket_name=isolated_socket
    )

    assert get_runtime_instance_for_agent(agent.id) == runtime_instance


def test_runtime_instance_is_queryable_after_launch_agent(
    isolated_socket: str, tmp_path
) -> None:
    session = _active_session()

    agent, runtime_instance = launch_agent(
        DEVELOPER_ROLE,
        "claude-code",
        None,
        session,
        str(tmp_path),
        socket_name=isolated_socket,
    )

    assert get_runtime_instance_for_agent(agent.id) == runtime_instance


def test_reusing_an_already_launched_critic_does_not_lose_or_duplicate_the_association(
    isolated_socket: str, tmp_path
) -> None:
    # Segunda llamada sobre el mismo rol/sesión (register_agent_with_reuse,
    # vía register_critic — Critic, no Developer: desde T-FB005-US01-04,
    # Developer ya NO reutiliza, ver el test siguiente) reutiliza el Agent
    # ya lanzado sin volver a invocar `start_runtime` ni `register_agent`
    # — la asociación ya registrada en el primer lanzamiento debe seguir
    # siendo válida.
    session = _active_session()
    runtime = _test_runtime()

    first_agent, first_instance = register_critic(
        session, runtime, str(tmp_path), socket_name=isolated_socket
    )
    second_agent, second_instance = register_critic(
        session, runtime, str(tmp_path), socket_name=isolated_socket
    )

    assert first_agent is second_agent
    assert first_instance == second_instance
    assert get_runtime_instance_for_agent(first_agent.id) == first_instance


def test_each_new_developer_gets_its_own_registered_association(
    isolated_socket: str, tmp_path
) -> None:
    """T-FB005-US01-04: `register_developer` ya no reutiliza — cada
    llamada registra una asociación `agent.id` -> `RuntimeInstance`
    NUEVA y distinta, sin perder la del Developer anterior (ambas deben
    seguir siendo consultables independientemente)."""
    session = _active_session()
    runtime = _test_runtime()

    first_agent, first_instance = register_developer(
        session, runtime, str(tmp_path), socket_name=isolated_socket
    )
    second_agent, second_instance = register_developer(
        session, runtime, str(tmp_path), socket_name=isolated_socket
    )

    assert first_agent is not second_agent
    assert first_instance != second_instance
    assert get_runtime_instance_for_agent(first_agent.id) == first_instance
    assert get_runtime_instance_for_agent(second_agent.id) == second_instance


def test_querying_an_agent_id_that_was_never_launched_returns_none() -> None:
    assert get_runtime_instance_for_agent("never-launched-agent-id") is None
