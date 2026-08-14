import time
import uuid

import libtmux
import pytest

from brain.tmux.manager import (
    create_session,
    is_alive,
    kill_session,
    list_sessions,
    run_command,
)


@pytest.fixture
def socket_name():
    name = f"brain-test-{uuid.uuid4().hex[:8]}"
    yield name
    # Limpieza: si el servidor de prueba sigue vivo al final del test, se mata.
    try:
        libtmux.Server(socket_name=name).kill()
    except Exception:
        pass


def test_runtime_model_construction() -> None:
    from brain.models import Runtime

    runtime = Runtime(
        id="r1",
        name="claude-code",
        type="claude-code",
        command="claude",
        args=["--flag"],
        working_directory="/tmp",
    )

    assert runtime.id == "r1"
    assert runtime.name == "claude-code"
    assert runtime.type == "claude-code"
    assert runtime.command == "claude"
    assert runtime.args == ["--flag"]
    assert runtime.working_directory == "/tmp"


def test_is_alive_false_for_session_never_created(socket_name: str) -> None:
    assert is_alive("does-not-exist", socket_name=socket_name) is False


def test_create_session_and_run_command_keeps_it_alive(
    socket_name: str, tmp_path
) -> None:
    create_session("my-session", str(tmp_path), socket_name=socket_name)
    run_command("my-session", "sleep 2", socket_name=socket_name)

    time.sleep(0.3)

    assert is_alive("my-session", socket_name=socket_name) is True


def test_kill_session_makes_is_alive_false(socket_name: str, tmp_path) -> None:
    create_session("my-session", str(tmp_path), socket_name=socket_name)
    run_command("my-session", "sleep 5", socket_name=socket_name)
    time.sleep(0.3)

    kill_session("my-session", socket_name=socket_name)

    assert is_alive("my-session", socket_name=socket_name) is False


def test_kill_session_is_safe_when_session_does_not_exist(socket_name: str) -> None:
    # No debe lanzar excepción aunque la sesión nunca haya existido.
    kill_session("does-not-exist", socket_name=socket_name)


def test_list_sessions_empty_socket_returns_empty_list_without_raising(
    socket_name: str,
) -> None:
    """T-FB031-US01-01: socket sin ninguna sesión creada todavía — no debe
    lanzar excepción, y la lista debe estar vacía (criterio 2 de
    aceptación explícito)."""
    assert list_sessions(socket_name=socket_name) == []


def test_list_sessions_returns_exactly_the_real_sessions_created(
    socket_name: str, tmp_path
) -> None:
    """Criterio de aceptación explícito: crear varias sesiones tmux
    reales en un socket aislado y confirmar que `list_sessions` las
    devuelve todas, ni más ni menos — no requiere conocer los nombres de
    antemano."""
    create_session("session-a", str(tmp_path), socket_name=socket_name)
    create_session("session-b", str(tmp_path), socket_name=socket_name)
    create_session("session-c", str(tmp_path), socket_name=socket_name)

    assert set(list_sessions(socket_name=socket_name)) == {
        "session-a",
        "session-b",
        "session-c",
    }


def test_list_sessions_reflects_kill_session(socket_name: str, tmp_path) -> None:
    create_session("session-a", str(tmp_path), socket_name=socket_name)
    create_session("session-b", str(tmp_path), socket_name=socket_name)

    kill_session("session-a", socket_name=socket_name)

    assert list_sessions(socket_name=socket_name) == ["session-b"]
