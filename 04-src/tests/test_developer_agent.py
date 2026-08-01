import time
import uuid

import libtmux
import pytest

from brain.agents import (
    DEVELOPER_PROMPT,
    DEVELOPER_ROLE,
    get_agent_state,
    mark_working,
    register_developer,
)
from brain.core import activate, list_agents
from brain.models import DevelopmentSession, Runtime
from brain.runtime import is_runtime_alive


@pytest.fixture
def isolated_socket():
    """Aísla los tests de esta Task en su propio servidor tmux, para no
    interferir con sesiones tmux reales del entorno (nunca lanzar el
    binario real de Claude Code/OpenCode en tests — misma precaución ya
    aplicada en las Tasks de FB-004 y T-FB005-US01-01)."""
    name = f"brain-test-{uuid.uuid4().hex[:8]}"
    yield name
    try:
        libtmux.Server(socket_name=name).kill()
    except Exception:
        pass


def _test_runtime() -> Runtime:
    # Comando de prueba inocuo (`sleep`), NO el binario real de Claude
    # Code/OpenCode.
    return Runtime(
        id="test-runtime",
        name="Test Runtime",
        type="test",
        command="sleep",
        args=["5"],
    )


def _active_session() -> DevelopmentSession:
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    return session


def test_developer_registers_with_fixed_role_and_prompt(
    isolated_socket: str, tmp_path
) -> None:
    session = _active_session()
    runtime = _test_runtime()

    agent, _ = register_developer(
        session, runtime, str(tmp_path), socket_name=isolated_socket
    )

    assert agent.role == DEVELOPER_ROLE
    assert agent.prompt == DEVELOPER_PROMPT


def test_developer_associated_with_runtime_and_active_session(
    isolated_socket: str, tmp_path
) -> None:
    session = _active_session()
    runtime = _test_runtime()

    agent, runtime_instance = register_developer(
        session, runtime, str(tmp_path), socket_name=isolated_socket
    )
    time.sleep(0.3)

    assert agent in list_agents(session)
    assert agent.runtime_id == runtime.id
    assert is_runtime_alive(runtime_instance, socket_name=isolated_socket) is True


def test_developer_state_can_be_queried_idle_working_unavailable(
    isolated_socket: str, tmp_path
) -> None:
    session = _active_session()
    runtime = _test_runtime()

    agent, _ = register_developer(
        session, runtime, str(tmp_path), socket_name=isolated_socket
    )

    assert get_agent_state(agent)["status"] == "idle"

    mark_working(agent)
    assert get_agent_state(agent)["status"] == "working"


def test_registering_developer_twice_creates_two_distinct_instances(
    isolated_socket: str, tmp_path
) -> None:
    """T-FB005-US01-04: `register_developer` deja de reutilizar — cada
    llamada crea un `Agent`/`RuntimeInstance` NUEVO, a diferencia del
    comportamiento anterior (y del que sigue teniendo Critic, ver
    `test_critic_agent.py`). Verificado con tmux real: dos sesiones
    distintas, ambas vivas simultáneamente."""
    session = _active_session()
    runtime = _test_runtime()

    first_agent, first_instance = register_developer(
        session, runtime, str(tmp_path), socket_name=isolated_socket
    )
    time.sleep(0.3)

    second_agent, second_instance = register_developer(
        session, runtime, str(tmp_path), socket_name=isolated_socket
    )
    time.sleep(0.3)

    # Agent distinto (id distinto), RuntimeInstance distinto (sesión tmux
    # distinta) — nunca la misma instancia devuelta dos veces.
    assert second_agent is not first_agent
    assert second_agent.id != first_agent.id
    assert second_instance.session_name != first_instance.session_name

    # Ambas sesiones tmux reales están vivas SIMULTÁNEAMENTE (criterio de
    # aceptación explícito) — no se detiene la primera al lanzar la
    # segunda.
    assert is_runtime_alive(first_instance, socket_name=isolated_socket) is True
    assert is_runtime_alive(second_instance, socket_name=isolated_socket) is True

    # Dos Developer en la sesión, no uno reutilizado.
    developers = [a for a in list_agents(session) if a.role == DEVELOPER_ROLE]
    assert len(developers) == 2


def test_each_developer_instance_has_a_distinguishable_name(
    isolated_socket: str, tmp_path
) -> None:
    """Criterio de aceptación: 'cada Developer lanzado tiene un nombre
    distinguible en GET /agents (no todos aparecen como Developer
    indistinguibles)'. Esquema elegido: numeración incremental
    (Developer-1, Developer-2, ...) — ver justificación completa en el
    docstring de `_next_developer_name`, `agents/developer.py`."""
    session = _active_session()
    runtime = _test_runtime()

    first_agent, _ = register_developer(
        session, runtime, str(tmp_path), socket_name=isolated_socket
    )
    second_agent, _ = register_developer(
        session, runtime, str(tmp_path), socket_name=isolated_socket
    )
    third_agent, _ = register_developer(
        session, runtime, str(tmp_path), socket_name=isolated_socket
    )

    assert first_agent.name == "Developer-1"
    assert second_agent.name == "Developer-2"
    assert third_agent.name == "Developer-3"
    assert len({first_agent.name, second_agent.name, third_agent.name}) == 3


def test_session_name_for_does_not_collide_between_multiple_developers(
    isolated_socket: str, tmp_path
) -> None:
    """Criterio de aceptación explícito: verificar que `session_name_for`
    sigue generando nombres de sesión tmux únicos para cada Developer
    nuevo — no requiere ningún cambio (ya usa `runtime.id` + `agent.id`,
    y cada `register_agent` genera un `agent.id` con UUID nuevo), pero se
    confirma aquí explícitamente en vez de asumirlo."""
    from brain.runtime import session_name_for

    session = _active_session()
    runtime = _test_runtime()

    agents_and_instances = [
        register_developer(session, runtime, str(tmp_path), socket_name=isolated_socket)
        for _ in range(5)
    ]

    session_names = {
        session_name_for(runtime, agent) for agent, _instance in agents_and_instances
    }
    assert len(session_names) == 5  # las 5 llamadas a session_name_for son únicas

    # Coincide exactamente con el session_name real que start_runtime ya
    # asignó a cada RuntimeInstance devuelto.
    for agent, instance in agents_and_instances:
        assert session_name_for(runtime, agent) == instance.session_name
