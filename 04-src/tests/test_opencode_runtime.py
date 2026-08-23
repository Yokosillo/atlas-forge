import time
import uuid

import libtmux
import pytest

from atlas_forge.models import Runtime
from atlas_forge.runtime import is_runtime_alive, start_runtime, stop_runtime
from atlas_forge.runtime.claude_code import register_claude_code_runtime
from atlas_forge.runtime.opencode import register_opencode_runtime


@pytest.fixture
def isolated_socket():
    """Aísla los tests de esta Task en su propio servidor tmux, para no
    interferir con sesiones tmux reales del entorno (misma precaución que
    T-AF004-US01-02: nunca lanzar los binarios reales `claude`/`opencode`
    en tests)."""
    name = f"atlas_forge-test-{uuid.uuid4().hex[:8]}"
    yield name
    try:
        libtmux.Server(socket_name=name).kill()
    except Exception:
        pass


def _opencode_test_runtime() -> Runtime:
    # Runtime de prueba con un comando inocuo (`sleep`), NO el binario real
    # `opencode`. La configuración real (register_opencode_runtime) se
    # verifica aparte, en su forma, sin ejecutarla.
    return Runtime(
        id="opencode-test",
        name="OpenCode (test)",
        type="opencode",
        command="sleep",
        args=["5"],
    )


def _claude_code_test_runtime() -> Runtime:
    return Runtime(
        id="claude-code-test",
        name="Claude Code (test)",
        type="claude-code",
        command="sleep",
        args=["5"],
    )


def test_register_opencode_runtime_has_minimal_configuration() -> None:
    runtime = register_opencode_runtime()

    assert runtime.id == "opencode"
    assert runtime.type == "opencode"
    assert runtime.command == "opencode"
    assert isinstance(runtime.args, list)
    # No se ejecuta el comando real en este test.


def test_register_opencode_runtime_uses_same_mechanism_as_claude_code() -> None:
    opencode = register_opencode_runtime()
    claude_code = register_claude_code_runtime()

    assert type(opencode) is type(claude_code)  # ambos son `Runtime`


def test_register_opencode_runtime_includes_autonomy_flag_by_default() -> None:
    # T-AF002-US01-01: `--auto` es el mecanismo real de OpenCode
    # (investigado en la documentación oficial, https://opencode.ai/docs/permissions/,
    # NO el mismo nombre que la flag de Claude Code — no se asumió).
    runtime = register_opencode_runtime()

    assert "--auto" in runtime.args


def test_register_opencode_runtime_with_model_includes_model_flag() -> None:
    runtime = register_opencode_runtime(model="deepseek/deepseek-chat")

    assert "--model" in runtime.args
    model_index = runtime.args.index("--model")
    assert runtime.args[model_index + 1] == "deepseek/deepseek-chat"
    # La flag de autonomía sigue presente junto con la de modelo.
    assert "--auto" in runtime.args


def test_register_opencode_runtime_without_model_keeps_previous_behavior() -> None:
    # Test de regresión explícito sobre lo ya cerrado en T-AF004-US02-01:
    # sin `model`, no debe aparecer `--model` en los args.
    runtime = register_opencode_runtime()

    assert "--model" not in runtime.args


def test_start_opencode_creates_its_own_session_and_is_alive(
    isolated_socket: str, tmp_path
) -> None:
    runtime = _opencode_test_runtime()
    agent = object()

    instance = start_runtime(runtime, agent, str(tmp_path), socket_name=isolated_socket)
    time.sleep(0.3)

    assert is_runtime_alive(instance, socket_name=isolated_socket) is True

    stop_runtime(instance, socket_name=isolated_socket)


def test_claude_code_and_opencode_coexist_without_collision(
    isolated_socket: str, tmp_path
) -> None:
    agent = object()

    claude_instance = start_runtime(
        _claude_code_test_runtime(), agent, str(tmp_path), socket_name=isolated_socket
    )
    opencode_instance = start_runtime(
        _opencode_test_runtime(), agent, str(tmp_path), socket_name=isolated_socket
    )
    time.sleep(0.3)

    assert claude_instance.session_name != opencode_instance.session_name
    assert is_runtime_alive(claude_instance, socket_name=isolated_socket) is True
    assert is_runtime_alive(opencode_instance, socket_name=isolated_socket) is True

    stop_runtime(claude_instance, socket_name=isolated_socket)
    stop_runtime(opencode_instance, socket_name=isolated_socket)


def test_stopping_one_runtime_does_not_affect_the_other(
    isolated_socket: str, tmp_path
) -> None:
    agent = object()

    claude_instance = start_runtime(
        _claude_code_test_runtime(), agent, str(tmp_path), socket_name=isolated_socket
    )
    opencode_instance = start_runtime(
        _opencode_test_runtime(), agent, str(tmp_path), socket_name=isolated_socket
    )
    time.sleep(0.3)

    stop_runtime(claude_instance, socket_name=isolated_socket)

    assert is_runtime_alive(claude_instance, socket_name=isolated_socket) is False
    assert is_runtime_alive(opencode_instance, socket_name=isolated_socket) is True

    stop_runtime(opencode_instance, socket_name=isolated_socket)
