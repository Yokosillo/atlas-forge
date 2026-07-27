import uuid

import libtmux
import pytest

from brain.tmux import (
    CommandCaptureTimeoutError,
    create_session,
    run_command_and_capture,
)


@pytest.fixture
def isolated_socket():
    """Aísla los tests en su propio servidor tmux, con limpieza garantizada
    incluso si el test falla a medio camino."""
    name = f"brain-test-{uuid.uuid4().hex[:8]}"
    try:
        yield name
    finally:
        try:
            libtmux.Server(socket_name=name).kill()
        except Exception:
            pass


def test_run_command_and_capture_returns_output_and_success_exit_code(
    isolated_socket: str, tmp_path
) -> None:
    create_session("test-session", str(tmp_path), socket_name=isolated_socket)

    lines, exit_code = run_command_and_capture(
        "test-session", "echo predictable_output", socket_name=isolated_socket
    )

    assert exit_code == 0
    assert any("predictable_output" in line for line in lines)


def test_run_command_and_capture_returns_nonzero_exit_code_on_failure(
    isolated_socket: str, tmp_path
) -> None:
    create_session("test-session", str(tmp_path), socket_name=isolated_socket)

    lines, exit_code = run_command_and_capture(
        "test-session", "false", socket_name=isolated_socket
    )

    assert exit_code != 0


def test_run_command_and_capture_raises_on_timeout(
    isolated_socket: str, tmp_path
) -> None:
    create_session("test-session", str(tmp_path), socket_name=isolated_socket)

    with pytest.raises(CommandCaptureTimeoutError):
        run_command_and_capture(
            "test-session",
            "sleep 5",
            timeout_seconds=0.5,
            socket_name=isolated_socket,
        )


def test_run_command_and_capture_isolates_consecutive_commands_in_same_session(
    isolated_socket: str, tmp_path
) -> None:
    create_session("test-session", str(tmp_path), socket_name=isolated_socket)

    first_lines, _ = run_command_and_capture(
        "test-session", "echo alpha_marker", socket_name=isolated_socket
    )
    second_lines, _ = run_command_and_capture(
        "test-session", "echo beta_marker", socket_name=isolated_socket
    )

    assert any("alpha_marker" in line for line in first_lines)
    assert any("beta_marker" in line for line in second_lines)
    assert not any("alpha_marker" in line for line in second_lines)
