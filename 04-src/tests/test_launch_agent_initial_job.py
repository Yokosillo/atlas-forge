import uuid
from pathlib import Path

import libtmux
import pytest

from brain.agents import DEVELOPER_ROLE
from brain.agents.developer import DEVELOPER_PROMPT
from brain.agents.launch import AgentLaunchError, launch_agent_with_initial_job
from brain.core.session_lifecycle import activate, list_agents
from brain.core.session_registry import _reset_registry_for_tests
from brain.dispatcher import create_and_record_job, dispatch_job
from brain.dispatcher.job_history_registry import (
    _reset_registry_for_tests as _reset_job_history,
    list_jobs_for_session,
)
from brain.models import DevelopmentSession
from brain.runtime import is_runtime_alive, stop_runtime

_COOPERATIVE_AGENT_SCRIPT = str(
    Path(__file__).parent / "fixtures" / "cooperative_agent_sim.sh"
)


@pytest.fixture(autouse=True)
def _clean_registries():
    _reset_registry_for_tests()
    _reset_job_history()
    yield
    _reset_registry_for_tests()
    _reset_job_history()


@pytest.fixture(autouse=True)
def _no_real_runtime(monkeypatch):
    """Sustituye los comandos reales de Claude Code/OpenCode por el doble
    cooperativo determinista (`cooperative_agent_sim.sh`), para poder
    despachar Jobs reales (tmux real) sin invocar nunca los binarios
    reales — mismo patrón que `test_job_dispatch.py`."""
    import brain.runtime.claude_code as claude_code_module
    import brain.runtime.opencode as opencode_module

    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_COMMAND", "bash")
    monkeypatch.setattr(
        claude_code_module, "DEFAULT_CLAUDE_CODE_ARGS", [_COOPERATIVE_AGENT_SCRIPT]
    )
    monkeypatch.setattr(opencode_module, "DEFAULT_OPENCODE_COMMAND", "bash")
    monkeypatch.setattr(
        opencode_module, "DEFAULT_OPENCODE_ARGS", [_COOPERATIVE_AGENT_SCRIPT]
    )


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


def test_launch_with_initial_job_dispatches_job_after_registration(
    isolated_socket: str, tmp_path
) -> None:
    """Criterio de aceptación: lanzar un agente con Job inicial informado
    despacha el Job automáticamente tras el registro, verificado con tmux
    real (doble cooperativo). El agente vuelve a `idle` y el Job queda
    `completed` en el histórico de la sesión."""
    session = _active_session()

    agent, runtime_instance, job = launch_agent_with_initial_job(
        DEVELOPER_ROLE,
        "claude-code",
        None,
        session,
        str(tmp_path),
        initial_job_description="implement the feature",
        socket_name=isolated_socket,
    )

    assert agent in list_agents(session)
    assert is_runtime_alive(runtime_instance, socket_name=isolated_socket) is True
    assert agent.status == "idle"
    assert job is not None
    assert job.status == "completed"
    assert job.agent_id == agent.id
    assert job.session_id == session.id
    assert "line one of the cooperative result" in job.result
    assert job in list_jobs_for_session(session.id)

    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_launch_without_initial_job_behaves_exactly_like_launch_agent(
    isolated_socket: str, tmp_path
) -> None:
    """Criterio de aceptación: sin Job inicial, la nueva función se
    comporta exactamente igual que `launch_agent` — agente registrado e
    `idle`, sin ningún Job en el histórico ni efecto secundario nuevo."""
    session = _active_session()

    agent, runtime_instance, job = launch_agent_with_initial_job(
        DEVELOPER_ROLE,
        "claude-code",
        None,
        session,
        str(tmp_path),
        socket_name=isolated_socket,
    )

    assert agent in list_agents(session)
    assert agent.status == "idle"
    assert job is None
    assert list_jobs_for_session(session.id) == []

    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_launch_without_initial_job_matches_launch_agent_registration(
    isolated_socket: str, tmp_path
) -> None:
    """Mismo registro que `launch_agent` (misma firma/retorno de 2-tupla
    por delegación interna): el agente registrado tiene el rol y prompt de
    Developer, queda `idle` y con runtime vivo — sin ningún Job creado."""
    session = _active_session()

    agent, runtime_instance, job = launch_agent_with_initial_job(
        DEVELOPER_ROLE,
        "claude-code",
        None,
        session,
        str(tmp_path),
        socket_name=isolated_socket,
    )

    assert agent.role == DEVELOPER_ROLE
    assert agent.prompt == DEVELOPER_PROMPT
    assert agent.status == "idle"
    assert agent in list_agents(session)
    assert job is None
    assert list_jobs_for_session(session.id) == []
    assert is_runtime_alive(runtime_instance, socket_name=isolated_socket) is True

    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_initial_job_dispatch_failure_keeps_agent_registered_and_idle(
    isolated_socket: str, tmp_path, monkeypatch
) -> None:
    """Criterio de aceptación: un fallo en el despacho del Job inicial
    (runtime que nunca reporta → timeout) deja `job.status == "failed"`
    con el motivo en `job.result`, y el agente permanece registrado y
    `idle` — el fallo NO revierte el registro ni bloquea al agente."""
    import brain.runtime.claude_code as claude_code_module

    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_ARGS", [])
    session = _active_session()

    agent, runtime_instance, job = launch_agent_with_initial_job(
        DEVELOPER_ROLE,
        "claude-code",
        None,
        session,
        str(tmp_path),
        initial_job_description="this job will time out",
        socket_name=isolated_socket,
        job_timeout_seconds=0.5,
        job_poll_interval_seconds=0.1,
    )

    assert agent in list_agents(session)
    assert agent.status == "idle"
    assert job is not None
    assert job.status == "failed"
    assert "Timeout" in job.result
    assert job in list_jobs_for_session(session.id)

    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_manual_job_still_works_after_initial_job_dispatch_failure(
    isolated_socket: str, tmp_path, monkeypatch
) -> None:
    """Criterio de aceptación: tras un fallo del Job inicial, el mismo
    agente sigue disponible para un Job manual posterior (creación +
    despacho funcionan sobre el agente ya registrado)."""
    import brain.runtime.claude_code as claude_code_module

    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_ARGS", [])
    session = _active_session()

    agent, runtime_instance, initial_job = launch_agent_with_initial_job(
        DEVELOPER_ROLE,
        "claude-code",
        None,
        session,
        str(tmp_path),
        initial_job_description="this job will time out",
        socket_name=isolated_socket,
        job_timeout_seconds=0.5,
        job_poll_interval_seconds=0.1,
    )
    assert initial_job.status == "failed"
    assert agent.status == "idle"

    # Mismo agente, Job manual posterior — se crea y se intenta despachar
    # sin error de creación (el agente sigue `idle` y en la sesión).
    manual_job = create_and_record_job(
        "manual job after failure", agent, session
    )
    dispatch_job(
        manual_job,
        agent,
        runtime_instance,
        timeout_seconds=0.5,
        poll_interval_seconds=0.1,
        socket_name=isolated_socket,
    )

    assert manual_job.status == "failed"
    assert manual_job in list_jobs_for_session(session.id)
    assert agent.status == "idle"

    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_launch_agent_validations_still_apply_with_initial_job(
    isolated_socket: str, tmp_path
) -> None:
    """Las validaciones de `launch_agent` (sesión `active`, rol
    reconocido) se aplican igual aunque venga el Job inicial — no se
    lanza nada ni se crea ningún Job si el agente no se puede lanzar."""
    inactive_session = DevelopmentSession(id="s1", project_id="p1")

    with pytest.raises(AgentLaunchError):
        launch_agent_with_initial_job(
            DEVELOPER_ROLE,
            "claude-code",
            None,
            inactive_session,
            str(tmp_path),
            initial_job_description="should never be dispatched",
            socket_name=isolated_socket,
        )

    assert list_agents(inactive_session) == []
