import uuid

import libtmux
import pytest

from brain.agents import ARQUITECTO_ROLE, DEVELOPER_ROLE
from brain.core.session_lifecycle import activate, list_agents
from brain.agents.launch import AgentLaunchError, launch_agent
from brain.models import DevelopmentSession
from brain.runtime import is_runtime_alive, stop_runtime


@pytest.fixture(autouse=True)
def _no_real_runtime(monkeypatch):
    """Sustituye los comandos reales de Claude Code/OpenCode/Codex por un
    comando de prueba inocuo (`sleep`), para no invocar los binarios
    reales en ningún test de esta Task — mismo patrón ya usado en
    T-FB004-US01-02/US02-01, extendido a Codex en T-FB024-US11-13."""
    import brain.runtime.claude_code as claude_code_module
    import brain.runtime.codex as codex_module
    import brain.runtime.opencode as opencode_module

    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_COMMAND", "sleep")
    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_ARGS", ["5"])
    monkeypatch.setattr(opencode_module, "DEFAULT_OPENCODE_COMMAND", "sleep")
    monkeypatch.setattr(opencode_module, "DEFAULT_OPENCODE_AUTONOMY_FLAG", "5")
    monkeypatch.setattr(opencode_module, "DEFAULT_OPENCODE_ARGS", ["5"])
    monkeypatch.setattr(codex_module, "DEFAULT_CODEX_COMMAND", "sleep")
    monkeypatch.setattr(codex_module, "DEFAULT_CODEX_ARGS", ["5"])


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


def _active_session() -> DevelopmentSession:
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    return session


def test_launch_arquitecto_on_claude_code_and_developer_on_opencode_with_model(
    isolated_socket: str, tmp_path
) -> None:
    session = _active_session()

    arquitecto_agent, arquitecto_instance = launch_agent(
        ARQUITECTO_ROLE,
        "claude-code",
        None,
        session,
        str(tmp_path),
        socket_name=isolated_socket,
    )
    developer_agent, developer_instance = launch_agent(
        DEVELOPER_ROLE,
        "opencode",
        "deepseek/deepseek-chat",
        session,
        str(tmp_path),
        socket_name=isolated_socket,
    )

    assert arquitecto_agent.role == ARQUITECTO_ROLE
    assert developer_agent.role == DEVELOPER_ROLE
    assert arquitecto_agent in list_agents(session)
    assert developer_agent in list_agents(session)
    assert is_runtime_alive(arquitecto_instance, socket_name=isolated_socket) is True
    assert is_runtime_alive(developer_instance, socket_name=isolated_socket) is True

    stop_runtime(arquitecto_instance, socket_name=isolated_socket)
    stop_runtime(developer_instance, socket_name=isolated_socket)


def test_launching_arquitecto_on_opencode_is_still_supported_directly(
    isolated_socket: str, tmp_path
) -> None:
    """El dominio `launch_agent` admite cualquier combinación rol/runtime
    reconocida cuando se invoca directamente, incluida Arquitecto +
    OpenCode, sin ningún filtro de presentación aplicado en este nivel."""
    session = _active_session()

    arquitecto_agent, arquitecto_instance = launch_agent(
        ARQUITECTO_ROLE,
        "opencode",
        None,
        session,
        str(tmp_path),
        socket_name=isolated_socket,
    )

    assert arquitecto_agent.role == ARQUITECTO_ROLE
    assert arquitecto_agent in list_agents(session)
    assert is_runtime_alive(arquitecto_instance, socket_name=isolated_socket) is True

    stop_runtime(arquitecto_instance, socket_name=isolated_socket)


def test_indicating_model_for_claude_code_launches_with_model_flag(
    isolated_socket: str, tmp_path
) -> None:
    """T-FB024-US11-13 (2026-08-17): Claude Code SÍ admite indicar modelo
    al lanzar — corrección de la premisa original (T-FB002-US01-01) que
    asumía lo contrario sin verificarlo contra `claude --help`."""
    session = _active_session()

    agent, runtime_instance = launch_agent(
        DEVELOPER_ROLE,
        "claude-code",
        "sonnet",
        session,
        str(tmp_path),
        socket_name=isolated_socket,
    )

    assert agent is not None
    assert "--model" in runtime_instance.runtime.args
    assert "sonnet" in runtime_instance.runtime.args
    assert list_agents(session) == [agent]

    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_launch_developer_on_codex_with_model(
    isolated_socket: str, tmp_path
) -> None:
    """T-FB024-US11-13 (2026-08-17, ampliación de alcance explícita del
    usuario): Codex activado como runtime real, con modelo indicado al
    lanzar (mismo patrón que OpenCode/Claude Code)."""
    session = _active_session()

    agent, runtime_instance = launch_agent(
        DEVELOPER_ROLE,
        "codex",
        "gpt-5.6-terra",
        session,
        str(tmp_path),
        socket_name=isolated_socket,
    )

    assert agent is not None
    assert runtime_instance.runtime.type == "codex"
    assert "--model" in runtime_instance.runtime.args
    assert "gpt-5.6-terra" in runtime_instance.runtime.args
    assert list_agents(session) == [agent]

    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_launching_on_inactive_session_is_rejected(tmp_path) -> None:
    session = DevelopmentSession(id="s1", project_id="p1")
    # La sesión permanece en `created`, nunca se activa.

    with pytest.raises(AgentLaunchError):
        launch_agent(DEVELOPER_ROLE, "claude-code", None, session, str(tmp_path))


def test_launching_developer_twice_creates_two_distinct_instances(
    isolated_socket: str, tmp_path
) -> None:
    """T-FB005-US01-04: `launch_agent` con `DEVELOPER_ROLE` ya no
    reutiliza — cada llamada crea un Developer nuevo (comportamiento
    actualizado desde `register_developer`, ver
    `test_developer_agent.py`)."""
    session = _active_session()

    first_agent, first_instance = launch_agent(
        DEVELOPER_ROLE,
        "claude-code",
        None,
        session,
        str(tmp_path),
        socket_name=isolated_socket,
    )
    second_agent, second_instance = launch_agent(
        DEVELOPER_ROLE,
        "claude-code",
        None,
        session,
        str(tmp_path),
        socket_name=isolated_socket,
    )

    assert second_agent is not first_agent
    assert second_instance.session_name != first_instance.session_name
    developers = [a for a in list_agents(session) if a.role == DEVELOPER_ROLE]
    assert len(developers) == 2

    stop_runtime(first_instance, socket_name=isolated_socket)
    stop_runtime(second_instance, socket_name=isolated_socket)


def test_launching_arquitecto_twice_still_reuses_the_existing_agent(
    isolated_socket: str, tmp_path
) -> None:
    """Test de regresión explícito (a través de `launch_agent`/dashboard,
    no `register_arquitecto` directo): Arquitecto sigue reutilizándose,
    igual que Critic lo hacía antes de eliminarse (FB-022)."""
    session = _active_session()

    first_agent, first_instance = launch_agent(
        ARQUITECTO_ROLE,
        "claude-code",
        None,
        session,
        str(tmp_path),
        socket_name=isolated_socket,
    )
    second_agent, second_instance = launch_agent(
        ARQUITECTO_ROLE,
        "claude-code",
        None,
        session,
        str(tmp_path),
        socket_name=isolated_socket,
    )

    assert second_agent is first_agent
    assert second_instance.session_name == first_instance.session_name
    arquitectos = [a for a in list_agents(session) if a.role == ARQUITECTO_ROLE]
    assert len(arquitectos) == 1

    stop_runtime(first_instance, socket_name=isolated_socket)


def test_unrecognized_role_is_rejected(tmp_path) -> None:
    session = _active_session()

    with pytest.raises(AgentLaunchError):
        launch_agent("architect", "claude-code", None, session, str(tmp_path))


def test_unrecognized_runtime_is_rejected(tmp_path) -> None:
    """"codex" ya no sirve como ejemplo de runtime NO reconocido —
    T-FB024-US11-13 (2026-08-17) lo activó como runtime real."""
    session = _active_session()

    with pytest.raises(AgentLaunchError):
        launch_agent(DEVELOPER_ROLE, "unknown-runtime", None, session, str(tmp_path))
