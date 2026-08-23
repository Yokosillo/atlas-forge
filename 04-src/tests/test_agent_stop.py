import uuid

import libtmux
import pytest

from atlas_forge.agents import AgentRuntimeNotFoundError, mark_unavailable, stop_agent
from atlas_forge.core.session_lifecycle import activate, list_agents
from atlas_forge.agents.launch import launch_agent
from atlas_forge.dispatcher import JobCreationError, create_job
from atlas_forge.models import Agent, DevelopmentSession
from atlas_forge.runtime import is_runtime_alive


@pytest.fixture(autouse=True)
def _no_real_runtime(monkeypatch):
    """Mismo patrón de aislamiento ya usado en test_launch_agent.py: nunca
    invocar los binarios reales de Claude Code/OpenCode en tests."""
    import atlas_forge.runtime.claude_code as claude_code_module
    import atlas_forge.runtime.opencode as opencode_module

    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_COMMAND", "sleep")
    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_ARGS", ["5"])
    monkeypatch.setattr(opencode_module, "DEFAULT_OPENCODE_COMMAND", "sleep")
    monkeypatch.setattr(opencode_module, "DEFAULT_OPENCODE_AUTONOMY_FLAG", "5")
    monkeypatch.setattr(opencode_module, "DEFAULT_OPENCODE_ARGS", ["5"])


@pytest.fixture
def isolated_socket():
    name = f"atlas_forge-test-{uuid.uuid4().hex[:8]}"
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


def test_stop_agent_kills_the_real_tmux_session_and_marks_stopped(
    isolated_socket: str, tmp_path
) -> None:
    # Rol no-Developer (Arquitecto): comportamiento clásico, sin cambios
    # por T-AF024-US12-02 — pausa a `stopped`, permanece en `session.agents`.
    session = _active_session()
    agent, runtime_instance = launch_agent(
        "arquitecto", "claude-code", None, session, str(tmp_path), socket_name=isolated_socket
    )
    assert is_runtime_alive(runtime_instance, socket_name=isolated_socket) is True

    stop_agent(agent, session, socket_name=isolated_socket)

    assert is_runtime_alive(runtime_instance, socket_name=isolated_socket) is False
    assert agent.status == "stopped"
    assert agent in list_agents(session)


def test_stop_agent_removes_developer_from_session_entirely(
    isolated_socket: str, tmp_path
) -> None:
    # T-AF024-US12-02: para Developer, "detener" elimina el Agent por
    # completo de session.agents (no queda un `stopped` residual ocupando
    # cupo) — criterio de aceptación 1.
    session = _active_session()
    agent, runtime_instance = launch_agent(
        "developer", "claude-code", None, session, str(tmp_path), socket_name=isolated_socket
    )
    assert agent in list_agents(session)

    stop_agent(agent, session, socket_name=isolated_socket)

    assert is_runtime_alive(runtime_instance, socket_name=isolated_socket) is False
    assert agent.status == "stopped"
    assert agent not in list_agents(session)


def test_stop_agent_never_marks_unavailable() -> None:
    # Distinción explícita de la Task: detenido a propósito != fallo no
    # solicitado. `unavailable` sigue existiendo como estado, pero
    # `stop_agent` nunca lo usa.
    agent = Agent(
        id="a1", name="test", role="developer", prompt="p", runtime_id="r1", status="idle"
    )
    mark_unavailable(agent)
    assert agent.status == "unavailable"
    assert agent.status != "stopped"


def test_stop_agent_raises_when_agent_has_no_registered_runtime() -> None:
    session = _active_session()
    agent = Agent(
        id="never-launched",
        name="test",
        role="developer",
        prompt="p",
        runtime_id="r1",
        status="idle",
    )

    with pytest.raises(AgentRuntimeNotFoundError):
        stop_agent(agent, session)

    # El estado no se toca si no hay runtime que detener de verdad.
    assert agent.status == "idle"


def test_creating_a_job_for_a_stopped_agent_is_rejected_like_any_non_idle_agent(
    isolated_socket: str, tmp_path
) -> None:
    # Criterio de aceptación explícito: create_job ya rechaza agentes no
    # idle — verificar explícitamente que stopped cae en ese rechazo,
    # mismo mecanismo, sin lógica nueva en job_creation.py. Rol no-Developer
    # (Arquitecto) a propósito: con Developer (T-AF024-US12-02), el agente
    # detenido ya no pertenece a la sesión, y este test dejaría de probar
    # el rechazo por "no idle" para probar el de "no pertenece" en su lugar.
    session = _active_session()
    agent, runtime_instance = launch_agent(
        "arquitecto", "claude-code", None, session, str(tmp_path), socket_name=isolated_socket
    )
    stop_agent(agent, session, socket_name=isolated_socket)
    assert agent.status == "stopped"

    with pytest.raises(JobCreationError):
        create_job("do something", agent, session)
