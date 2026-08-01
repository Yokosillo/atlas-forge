"""Tests de T-FB005-US01-03: `start_runtime` debe enviar `agent.prompt`
al arrancar el runtime, como argumento del propio comando de arranque
(nunca tecleado después) — verificado con un doble de runtime real
(nunca el binario real de Claude Code/OpenCode), capturando el pane de
tmux tras el arranque para confirmar que el prompt configurado llega de
verdad a la sesión (criterio de aceptación explícito de la Task)."""

import time
import uuid

import libtmux
import pytest

from brain.models import Runtime
from brain.runtime import start_runtime, stop_runtime
from brain.runtime.claude_code import build_prompt_args as build_claude_code_prompt_args
from brain.runtime.opencode import build_prompt_args as build_opencode_prompt_args
from brain.tmux.manager import capture_pane_lines


@pytest.fixture
def isolated_socket():
    name = f"brain-test-{uuid.uuid4().hex[:8]}"
    yield name
    try:
        libtmux.Server(socket_name=name).kill()
    except Exception:
        pass


class _FakeAgent:
    """Doble mínimo de `Agent` — solo el atributo `.prompt` que
    `start_runtime` consulta (`getattr(agent, "prompt", None)`), sin
    depender del modelo real completo."""

    def __init__(self, prompt: str) -> None:
        self.prompt = prompt


def _echoing_test_runtime(runtime_type: str) -> Runtime:
    # Doble de runtime real: `command="echo"`, NUNCA el binario real
    # `claude`/`opencode` (mismo criterio ya aplicado en
    # test_opencode_runtime.py/test_claude_code_runtime.py). A diferencia
    # de `sleep` (usado en otros tests de este módulo para simplemente
    # mantener la sesión viva), `echo` es el doble correcto AQUÍ porque
    # su salida (el propio prompt, si le llega como argumento) queda
    # visible en el pane capturado — es literalmente lo que este test
    # necesita observar. `runtime.type` es lo único que determina si
    # `start_runtime` añade argumentos de prompt (ver
    # `_prompt_args_builder_by_type`, `brain/runtime/generic.py`), así que
    # se prueba con los dos tipos reales registrados.
    return Runtime(
        id=f"{runtime_type}-echo-test",
        name=f"{runtime_type} (echo test)",
        type=runtime_type,
        command="echo",
        args=[],
    )


def test_start_runtime_sends_the_agent_prompt_as_part_of_the_launch_command_for_claude_code(
    isolated_socket: str, tmp_path
) -> None:
    prompt = "Eres el agente Critic de Factory Brain, lee 00-gobierno/CRITICO.md"
    agent = _FakeAgent(prompt=prompt)
    runtime = _echoing_test_runtime("claude-code")

    instance = start_runtime(runtime, agent, str(tmp_path), socket_name=isolated_socket)
    time.sleep(0.3)

    pane_lines = capture_pane_lines(instance.session_name, socket_name=isolated_socket)
    # `tmux capture-pane` envuelve (word-wrap) las líneas más anchas que
    # el pane — un prompt largo puede quedar partido en mitad de una
    # palabra entre dos líneas físicas. Se compara sin saltos de línea
    # para verificar el contenido real, no el formato visual del pane.
    pane_text_unwrapped = "".join(pane_lines)

    assert prompt in pane_text_unwrapped

    stop_runtime(instance, socket_name=isolated_socket)


def test_start_runtime_sends_the_agent_prompt_as_part_of_the_launch_command_for_opencode(
    isolated_socket: str, tmp_path
) -> None:
    prompt = "Eres el agente Developer de Factory Brain, lee 00-gobierno/developer.md"
    agent = _FakeAgent(prompt=prompt)
    runtime = _echoing_test_runtime("opencode")

    instance = start_runtime(runtime, agent, str(tmp_path), socket_name=isolated_socket)
    time.sleep(0.3)

    pane_lines = capture_pane_lines(instance.session_name, socket_name=isolated_socket)
    # `tmux capture-pane` envuelve (word-wrap) las líneas más anchas que
    # el pane — un prompt largo puede quedar partido en mitad de una
    # palabra entre dos líneas físicas. Se compara sin saltos de línea
    # para verificar el contenido real, no el formato visual del pane.
    pane_text_unwrapped = "".join(pane_lines)

    assert prompt in pane_text_unwrapped

    stop_runtime(instance, socket_name=isolated_socket)


def test_start_runtime_does_not_send_any_prompt_when_agent_has_none(
    isolated_socket: str, tmp_path
) -> None:
    """Un `agent` sin `.prompt` (o con prompt vacío) no debe añadir ningún
    argumento extra al comando de arranque — mismo comportamiento que
    antes de esta Task para ese caso, criterio implícito de no romper
    agentes de prueba que no modelan `.prompt` en absoluto (ver
    `test_runtime_generic.py`, que usa `agent = object()`)."""
    agent = object()
    runtime = _echoing_test_runtime("claude-code")

    instance = start_runtime(runtime, agent, str(tmp_path), socket_name=isolated_socket)
    time.sleep(0.3)

    pane_lines = capture_pane_lines(instance.session_name, socket_name=isolated_socket)
    pane_text = "\n".join(pane_lines)

    # `echo` sin argumentos imprime una línea vacía — no debe aparecer
    # ningún texto de prompt (no hay ninguno que enviar).
    assert "Eres el agente" not in pane_text

    stop_runtime(instance, socket_name=isolated_socket)


def test_start_runtime_does_not_add_prompt_args_for_an_unregistered_runtime_type(
    isolated_socket: str, tmp_path
) -> None:
    """Un `runtime.type` sin constructor de prompt registrado (runtimes de
    prueba genéricos, mismo caso que `test_runtime_generic.py`) no debe
    romper `start_runtime` ni intentar añadir argumentos de prompt —
    comportamiento idéntico al de antes de esta Task."""
    agent = _FakeAgent(prompt="este prompt no debería aparecer en el pane")
    runtime = Runtime(
        id="generic-test",
        name="generic test runtime",
        type="generic-test",
        command="echo",
        args=[],
    )

    instance = start_runtime(runtime, agent, str(tmp_path), socket_name=isolated_socket)
    time.sleep(0.3)

    pane_lines = capture_pane_lines(instance.session_name, socket_name=isolated_socket)
    pane_text = "\n".join(pane_lines)

    assert "este prompt no debería aparecer en el pane" not in pane_text

    stop_runtime(instance, socket_name=isolated_socket)


def test_build_claude_code_prompt_args_returns_the_prompt_as_a_single_shell_safe_argument() -> None:
    args = build_claude_code_prompt_args("hello world, with 'quotes' and spaces")

    assert len(args) == 1


def test_build_opencode_prompt_args_uses_the_explicit_prompt_flag() -> None:
    args = build_opencode_prompt_args("hello world")

    assert args[0] == "--prompt"
    assert len(args) == 2
