import time
import uuid

import libtmux
import pytest

from atlas_forge.models import Runtime
from atlas_forge.runtime import RuntimeInstance, is_runtime_alive, start_runtime, stop_runtime


@pytest.fixture
def isolated_socket():
    """Aísla los tests del mecanismo genérico en su propio servidor tmux,
    para no interferir con sesiones tmux reales del entorno (en particular,
    las que este mismo sistema usa para el ciclo worker/crítico con
    `claude` real). Se pasa explícitamente como `socket_name` en vez de
    usar el socket 'atlas-forge' real por defecto."""
    name = f"atlas_forge-test-{uuid.uuid4().hex[:8]}"
    yield name
    try:
        libtmux.Server(socket_name=name).kill()
    except Exception:
        pass


def _test_runtime(runtime_id: str = "generic-test") -> Runtime:
    # Runtime de prueba genérico con un comando inocuo (`sleep`), no atado
    # a ningún tipo concreto (ni Claude Code ni OpenCode): el mecanismo
    # verificado aquí (start_runtime/stop_runtime/is_runtime_alive) es
    # independiente del runtime concreto que lo use.
    return Runtime(
        id=runtime_id,
        name=f"{runtime_id} runtime",
        type=runtime_id,
        command="sleep",
        args=["5"],
    )


def test_start_runtime_creates_session_in_project_directory_and_is_alive(
    isolated_socket: str, tmp_path
) -> None:
    runtime = _test_runtime()
    agent = object()

    instance = start_runtime(runtime, agent, str(tmp_path), socket_name=isolated_socket)
    time.sleep(0.3)

    assert isinstance(instance, RuntimeInstance)
    assert is_runtime_alive(instance, socket_name=isolated_socket) is True


def test_stop_runtime_kills_session_and_is_no_longer_alive(
    isolated_socket: str, tmp_path
) -> None:
    runtime = _test_runtime()
    agent = object()
    instance = start_runtime(runtime, agent, str(tmp_path), socket_name=isolated_socket)
    time.sleep(0.3)

    stop_runtime(instance, socket_name=isolated_socket)

    assert is_runtime_alive(instance, socket_name=isolated_socket) is False


def test_start_runtime_uses_distinct_sessions_for_distinct_agents(
    isolated_socket: str, tmp_path
) -> None:
    runtime = _test_runtime()
    first_agent = object()
    second_agent = object()

    first_instance = start_runtime(
        runtime, first_agent, str(tmp_path), socket_name=isolated_socket
    )
    second_instance = start_runtime(
        runtime, second_agent, str(tmp_path), socket_name=isolated_socket
    )
    time.sleep(0.3)

    assert first_instance.session_name != second_instance.session_name
    assert is_runtime_alive(first_instance, socket_name=isolated_socket) is True
    assert is_runtime_alive(second_instance, socket_name=isolated_socket) is True

    stop_runtime(first_instance, socket_name=isolated_socket)
    stop_runtime(second_instance, socket_name=isolated_socket)
