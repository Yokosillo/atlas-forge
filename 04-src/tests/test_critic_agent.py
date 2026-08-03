import time
import uuid

import libtmux
import pytest

from brain.agents import (
    CRITIC_PROMPT,
    CRITIC_ROLE,
    DEVELOPER_PROMPT,
    DEVELOPER_ROLE,
    get_agent_state,
    mark_working,
    register_critic,
    register_developer,
    stop_agent,
)
from brain.core import activate, list_agents
from brain.models import DevelopmentSession, Runtime
from brain.runtime import is_runtime_alive, stop_runtime


@pytest.fixture
def isolated_socket():
    """Aísla los tests de esta Task en su propio servidor tmux, para no
    interferir con sesiones tmux reales del entorno (nunca lanzar los
    binarios reales de Claude Code/OpenCode en tests — misma precaución ya
    aplicada en las Tasks de FB-004 y FB-005 anteriores)."""
    name = f"brain-test-{uuid.uuid4().hex[:8]}"
    yield name
    try:
        libtmux.Server(socket_name=name).kill()
    except Exception:
        pass


def _test_runtime(runtime_id: str = "test-runtime") -> Runtime:
    # Comando de prueba inocuo (`sleep`), NO un binario real de runtime.
    return Runtime(
        id=runtime_id, name="Test Runtime", type="test", command="sleep", args=["5"]
    )


def _active_session() -> DevelopmentSession:
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    return session


def test_critic_registers_with_fixed_role_and_prompt_distinct_from_developer(
    isolated_socket: str, tmp_path
) -> None:
    session = _active_session()
    runtime = _test_runtime()

    agent, _ = register_critic(
        session, runtime, str(tmp_path), socket_name=isolated_socket
    )

    assert agent.role == CRITIC_ROLE
    assert agent.prompt == CRITIC_PROMPT
    assert agent.role != DEVELOPER_ROLE
    assert agent.prompt != DEVELOPER_PROMPT


def test_critic_associated_with_own_runtime_and_active_session(
    isolated_socket: str, tmp_path
) -> None:
    session = _active_session()
    runtime = _test_runtime()

    agent, runtime_instance = register_critic(
        session, runtime, str(tmp_path), socket_name=isolated_socket
    )
    time.sleep(0.3)

    assert agent in list_agents(session)
    assert agent.runtime_id == runtime.id
    assert is_runtime_alive(runtime_instance, socket_name=isolated_socket) is True


def test_critic_state_can_be_queried_same_as_developer(
    isolated_socket: str, tmp_path
) -> None:
    session = _active_session()
    runtime = _test_runtime()

    agent, _ = register_critic(
        session, runtime, str(tmp_path), socket_name=isolated_socket
    )

    assert get_agent_state(agent)["status"] == "idle"
    mark_working(agent)
    assert get_agent_state(agent)["status"] == "working"


def test_developer_and_critic_coexist_without_interference(
    isolated_socket: str, tmp_path
) -> None:
    session = _active_session()

    developer_agent, developer_instance = register_developer(
        session, _test_runtime("dev-runtime"), str(tmp_path), socket_name=isolated_socket
    )
    critic_agent, critic_instance = register_critic(
        session, _test_runtime("critic-runtime"), str(tmp_path), socket_name=isolated_socket
    )
    time.sleep(0.3)

    # Runtimes independientes: session_name distintos, ambos vivos.
    assert developer_instance.session_name != critic_instance.session_name
    assert is_runtime_alive(developer_instance, socket_name=isolated_socket) is True
    assert is_runtime_alive(critic_instance, socket_name=isolated_socket) is True

    # Ambos coexisten en la misma sesión, cada uno con su propio rol.
    agents_in_session = list_agents(session)
    assert developer_agent in agents_in_session
    assert critic_agent in agents_in_session
    assert developer_agent.role == DEVELOPER_ROLE
    assert critic_agent.role == CRITIC_ROLE

    # Estados independientes: cambiar uno no afecta al otro.
    mark_working(developer_agent)
    assert get_agent_state(developer_agent)["status"] == "working"
    assert get_agent_state(critic_agent)["status"] == "idle"

    # Detener el runtime de uno no afecta al del otro.
    stop_runtime(developer_instance, socket_name=isolated_socket)
    assert is_runtime_alive(developer_instance, socket_name=isolated_socket) is False
    assert is_runtime_alive(critic_instance, socket_name=isolated_socket) is True

    stop_runtime(critic_instance, socket_name=isolated_socket)


def test_registering_critic_twice_still_returns_the_same_instance(
    isolated_socket: str, tmp_path
) -> None:
    """Test de regresión explícito (T-FB005-US01-04, criterio de
    aceptación: "Lanzar Critic dos veces sigue devolviendo el mismo
    Critic — sin cambios de comportamiento"). A diferencia de
    `register_developer` (ver
    `test_registering_developer_twice_creates_two_distinct_instances`,
    `test_developer_agent.py`), `register_critic` sigue usando
    `register_agent_with_reuse` sin ningún cambio — el alcance de
    T-FB005-US01-04 está acotado explícitamente solo a Developer."""
    session = _active_session()
    runtime = _test_runtime()

    first_agent, first_instance = register_critic(
        session, runtime, str(tmp_path), socket_name=isolated_socket
    )
    time.sleep(0.3)

    second_agent, second_instance = register_critic(
        session, runtime, str(tmp_path), socket_name=isolated_socket
    )

    assert second_agent is first_agent
    assert second_instance.session_name == first_instance.session_name
    assert is_runtime_alive(second_instance, socket_name=isolated_socket) is True

    critics = [a for a in list_agents(session) if a.role == CRITIC_ROLE]
    assert len(critics) == 1

    stop_runtime(first_instance, socket_name=isolated_socket)


def test_stopping_and_relaunching_critic_starts_a_new_live_runtime(
    isolated_socket: str, tmp_path
) -> None:
    """Reproduce el bug real (T-FB005-US01-06): registrar Critic,
    detenerlo (`stop_agent`), volver a registrarlo con el mismo `role` en la
    misma sesión. El segundo lanzamiento debe crear un RUNTIME NUEVO (sesión
    tmux distinta) y VIVO (`is_runtime_alive`), NO reutilizar el mismo
    agente `stopped` con su runtime muerto.

    Revisado y decidido: el `Agent` `stopped` anterior se SUSTITUYE en
    `session.agents` por el nuevo (no conviven ambos con el mismo `role`),
    para que `_find_agent_by_role` de `dispatch_plan` resuelva siempre al
    agente vivo. El histórico de Jobs es por `session_id` + `agent_id` como
    string, independiente de `session.agents`, así que sustituir no borra
    histórico.
    """
    session = _active_session()
    runtime = _test_runtime()

    first_agent, first_instance = register_critic(
        session, runtime, str(tmp_path), socket_name=isolated_socket
    )
    time.sleep(0.3)
    assert is_runtime_alive(first_instance, socket_name=isolated_socket) is True

    stop_agent(first_agent, socket_name=isolated_socket)
    assert first_agent.status == "stopped"
    assert is_runtime_alive(first_instance, socket_name=isolated_socket) is False

    second_agent, second_instance = register_critic(
        session, runtime, str(tmp_path), socket_name=isolated_socket
    )
    time.sleep(0.3)

    # Un agente DISTINTO (nuevo), no el mismo objeto `stopped`.
    assert second_agent is not first_agent
    assert second_agent.id != first_agent.id
    assert second_agent.status == "idle"

    # Runtime nuevo: sesión tmux distinta y VIVA (no la misma ya muerta).
    assert second_instance.session_name != first_instance.session_name
    assert is_runtime_alive(first_instance, socket_name=isolated_socket) is False
    assert is_runtime_alive(second_instance, socket_name=isolated_socket) is True

    # Decisión de sustitución: el `stopped` histórico queda fuera de la
    # lista; solo hay UN Critic en la sesión, y es el nuevo (vivo).
    critics = [a for a in list_agents(session) if a.role == CRITIC_ROLE]
    assert critics == [second_agent]

    stop_runtime(second_instance, socket_name=isolated_socket)
