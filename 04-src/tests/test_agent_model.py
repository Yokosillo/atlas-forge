"""Tests de T-FB004-US05-01: get_active_model / set_active_model
sobre agentes OpenCode en ejecucion via tmux."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from brain.agent_model import (
    _find_model_index,
    _model_names_match,
    _parse_model_from_claude_code_status,
    _parse_model_from_pane,
    get_active_model,
    get_active_model_claude_code,
    set_active_model,
    set_active_model_claude_code,
)


# -- _parse_model_from_pane ------------------------------------------------


@pytest.mark.parametrize(
    "lines,expected",
    [
        (["Build · DeepSeek V4 Flash DeepSeek"], "DeepSeek V4 Flash DeepSeek"),
        (
            ["Build · DeepSeek V4 Flash Free (New) OpenCode Zen"],
            "DeepSeek V4 Flash Free (New) OpenCode Zen",
        ),
        (["algo", "Build · claude-sonnet-4-20250514 Anthropic"], "claude-sonnet-4-20250514 Anthropic"),
        (["sin barra de estado"], None),
        ([], None),
        (
            ["Build · "],
            None,
        ),
        (
            [  # barra de estado en la ultima linea del pane
                "otras lineas del pane",
                "Build · DeepSeek V4 Flash DeepSeek",
            ],
            "DeepSeek V4 Flash DeepSeek",
        ),
    ],
)
def test_parse_model_from_pane(lines: list[str], expected: str | None) -> None:
    assert _parse_model_from_pane(lines) == expected


# -- _model_names_match ----------------------------------------------------


@pytest.mark.parametrize(
    "current,requested,expected",
    [
        ("DeepSeek V4 Flash DeepSeek", "DeepSeek V4 Flash DeepSeek", True),
        ("DeepSeek V4 Flash DeepSeek", "deepseek v4 flash deepseek", True),
        ("deepseek/deepseek-chat SomeProvider", "deepseek/deepseek-chat", True),
        ("claude-sonnet-4-20250514 Anthropic", "anthropic/claude-sonnet-4-20250514", True),
        ("DeepSeek V4 Flash DeepSeek", "claude-sonnet", False),
        ("", "deepseek", False),
    ],
)
def test_model_names_match(current: str, requested: str, expected: bool) -> None:
    assert _model_names_match(current, requested) == expected


# -- _find_model_index -----------------------------------------------------


def test_find_model_index_exact_match() -> None:
    lines = ["uno", "DeepSeek V4 Flash DeepSeek", "tres"]
    assert _find_model_index(lines, "DeepSeek V4 Flash DeepSeek") == 1


def test_find_model_index_partial_match() -> None:
    lines = ["Modelos disponibles:", "  deepseek/deepseek-chat (DeepSeek)"]
    assert _find_model_index(lines, "deepseek/deepseek-chat") == 1


def test_find_model_index_no_match() -> None:
    assert _find_model_index(["otro", "modelo"], "DeepSeek") is None


def test_find_model_index_empty() -> None:
    assert _find_model_index([], "x") is None


# -- get_active_model ------------------------------------------------------


class _FakeRuntime:
    def __init__(self, rt_type: str = "opencode") -> None:
        self.type = rt_type


class _FakeRuntimeInstance:
    def __init__(self, rt_type: str = "opencode", session_name: str = "test-session") -> None:
        self.runtime = _FakeRuntime(rt_type)
        self.session_name = session_name


def test_get_active_model_returns_none_when_no_runtime_registered() -> None:
    with patch("brain.agent_model.get_runtime_instance_for_agent", return_value=None):
        assert get_active_model("agente-inexistente") is None


def test_get_active_model_returns_none_for_non_opencode_runtime() -> None:
    with patch("brain.agent_model.get_runtime_instance_for_agent",
               return_value=_FakeRuntimeInstance(rt_type="claude-code")):
        assert get_active_model("claude-agent") is None


def test_get_active_model_returns_none_when_session_not_alive() -> None:
    with (
        patch("brain.agent_model.get_runtime_instance_for_agent",
              return_value=_FakeRuntimeInstance()),
        patch("brain.agent_model.is_alive", return_value=False),
    ):
        assert get_active_model("opencode-agent") is None


def test_get_active_model_extracts_model_from_pane() -> None:
    with (
        patch("brain.agent_model.get_runtime_instance_for_agent",
              return_value=_FakeRuntimeInstance()),
        patch("brain.agent_model.is_alive", return_value=True),
        patch("brain.agent_model.capture_pane_lines",
              return_value=["Build · DeepSeek V4 Flash DeepSeek"]),
    ):
        assert get_active_model("opencode-agent") == "DeepSeek V4 Flash DeepSeek"


def test_get_active_model_returns_none_when_pattern_not_found() -> None:
    with (
        patch("brain.agent_model.get_runtime_instance_for_agent",
              return_value=_FakeRuntimeInstance()),
        patch("brain.agent_model.is_alive", return_value=True),
        patch("brain.agent_model.capture_pane_lines", return_value=["otra cosa"]),
    ):
        assert get_active_model("opencode-agent") is None


def test_get_active_model_handles_capture_exception() -> None:
    with (
        patch("brain.agent_model.get_runtime_instance_for_agent",
              return_value=_FakeRuntimeInstance()),
        patch("brain.agent_model.is_alive", return_value=True),
        patch("brain.agent_model.capture_pane_lines",
              side_effect=RuntimeError("tmux caido")),
    ):
        assert get_active_model("opencode-agent") is None  # no exception


# -- _parse_model_from_claude_code_status -----------------------------------


@pytest.mark.parametrize(
    "lines,expected",
    [
        (
            ["Model:            Default (Sonnet 5 · Efficient for routine tasks)"],
            "Default (Sonnet 5 · Efficient for routine tasks)",
        ),
        (
            ["otras lineas", "Model: Opus 5", "mas lineas del panel"],
            "Opus 5",
        ),
        (["sin panel de status"], None),
        ([], None),
        (["Model:"], None),
        (["Model:   "], None),
    ],
)
def test_parse_model_from_claude_code_status(
    lines: list[str], expected: str | None
) -> None:
    assert _parse_model_from_claude_code_status(lines) == expected


# -- get_active_model_claude_code --------------------------------------------


def test_get_active_model_claude_code_returns_none_when_no_runtime_registered() -> None:
    with patch("brain.agent_model.get_runtime_instance_for_agent", return_value=None):
        assert get_active_model_claude_code("agente-inexistente") is None


def test_get_active_model_claude_code_returns_none_for_non_claude_code_runtime() -> None:
    with patch("brain.agent_model.get_runtime_instance_for_agent",
               return_value=_FakeRuntimeInstance(rt_type="opencode")):
        assert get_active_model_claude_code("opencode-agent") is None


def test_get_active_model_claude_code_returns_none_when_session_not_alive() -> None:
    with (
        patch("brain.agent_model.get_runtime_instance_for_agent",
              return_value=_FakeRuntimeInstance(rt_type="claude-code")),
        patch("brain.agent_model.is_alive", return_value=False),
    ):
        assert get_active_model_claude_code("claude-agent") is None


def test_get_active_model_claude_code_sends_status_and_parses_panel() -> None:
    with (
        patch("brain.agent_model.get_runtime_instance_for_agent",
              return_value=_FakeRuntimeInstance(rt_type="claude-code")),
        patch("brain.agent_model.is_alive", return_value=True),
        patch("brain.agent_model.run_command") as mock_run_command,
        patch("brain.agent_model.capture_pane_lines",
              return_value=["Model:  Default (Sonnet 5 · Efficient for routine tasks)"]),
        patch("brain.agent_model.send_keys_literal") as mock_send_keys,
        patch("brain.agent_model.time.sleep"),
    ):
        result = get_active_model_claude_code("claude-agent")
        assert result == "Default (Sonnet 5 · Efficient for routine tasks)"
        # Envía exactamente "/status" al pane (mismo mecanismo que lanzar
        # el prompt inicial: run_command ya añade Enter por defecto).
        mock_run_command.assert_called_once_with(
            "test-session", "/status", socket_name="factory-brain"
        )
        # Cierra el panel con Escape tras leer, sin dejar residuo.
        mock_send_keys.assert_called_once_with(
            "test-session", "Escape", socket_name="factory-brain"
        )


def test_get_active_model_claude_code_returns_none_when_pattern_not_found() -> None:
    with (
        patch("brain.agent_model.get_runtime_instance_for_agent",
              return_value=_FakeRuntimeInstance(rt_type="claude-code")),
        patch("brain.agent_model.is_alive", return_value=True),
        patch("brain.agent_model.run_command"),
        patch("brain.agent_model.capture_pane_lines", return_value=["otra cosa"]),
        patch("brain.agent_model.send_keys_literal") as mock_send_keys,
        patch("brain.agent_model.time.sleep"),
    ):
        assert get_active_model_claude_code("claude-agent") is None
        # Escape se envía igual, aunque el parseo falle (criterio de
        # aceptación 4: nunca deja el pane en un estado distinto).
        mock_send_keys.assert_called_once()


def test_get_active_model_claude_code_closes_status_panel_even_if_capture_fails() -> None:
    """Criterio de aceptación 4: el panel se cierra con Escape incluso si
    `capture_pane_lines` lanza una excepción — nunca se propaga, nunca se
    deja el pane sin cerrar."""
    with (
        patch("brain.agent_model.get_runtime_instance_for_agent",
              return_value=_FakeRuntimeInstance(rt_type="claude-code")),
        patch("brain.agent_model.is_alive", return_value=True),
        patch("brain.agent_model.run_command"),
        patch("brain.agent_model.capture_pane_lines",
              side_effect=RuntimeError("tmux caido")),
        patch("brain.agent_model.send_keys_literal") as mock_send_keys,
        patch("brain.agent_model.time.sleep"),
    ):
        assert get_active_model_claude_code("claude-agent") is None  # no exception
        mock_send_keys.assert_called_once_with(
            "test-session", "Escape", socket_name="factory-brain"
        )


def test_get_active_model_claude_code_closes_status_panel_even_if_run_command_fails() -> None:
    """Mismo criterio, cubriendo también el fallo al ENVIAR /status (no
    solo al capturar después)."""
    with (
        patch("brain.agent_model.get_runtime_instance_for_agent",
              return_value=_FakeRuntimeInstance(rt_type="claude-code")),
        patch("brain.agent_model.is_alive", return_value=True),
        patch("brain.agent_model.run_command", side_effect=RuntimeError("tmux caido")),
        patch("brain.agent_model.send_keys_literal") as mock_send_keys,
        patch("brain.agent_model.time.sleep"),
    ):
        assert get_active_model_claude_code("claude-agent") is None  # no exception
        mock_send_keys.assert_called_once_with(
            "test-session", "Escape", socket_name="factory-brain"
        )


# -- set_active_model_claude_code (T-FB024-US11-13) ------------------------
#
# Bug real reportado por el usuario en vivo (2026-08-17), reproducido a
# mano contra una sesión Claude Code real antes de corregir: enviar solo
# '/model <id>' + Enter no basta cuando aparece el diálogo interno
# "Switch model? ... 1. Yes, switch to <modelo>" (se abre cuando hay
# contexto cacheado sustancial) — el modelo NUNCA cambia sin una segunda
# confirmación. Sin diálogo (poco contexto cacheado), el cambio se aplica
# directo y una segunda confirmación de más sería una línea en blanco no
# deseada — de ahí que la función compruebe el pane antes de decidir si
# manda el Enter extra.


def test_set_active_model_claude_code_confirms_dialog_when_it_appears() -> None:
    with (
        patch("brain.agent_model.run_command") as mock_run_command,
        patch("brain.agent_model.capture_pane_lines",
              return_value=["Switch model?", "❯ 1. Yes, switch to Haiku 4.5", "  2. No, go back"]),
        patch("brain.agent_model.send_keys_literal") as mock_send_keys,
        patch("brain.agent_model.time.sleep"),
    ):
        set_active_model_claude_code("test-session", "haiku", socket_name="factory-brain")
        mock_run_command.assert_called_once_with(
            "test-session", "/model haiku", socket_name="factory-brain"
        )
        # El diálogo apareció: se confirma con un segundo Enter.
        mock_send_keys.assert_called_once_with(
            "test-session", "Enter", socket_name="factory-brain"
        )


def test_set_active_model_claude_code_skips_extra_enter_when_no_dialog() -> None:
    with (
        patch("brain.agent_model.run_command") as mock_run_command,
        patch("brain.agent_model.capture_pane_lines", return_value=["❯ "]),
        patch("brain.agent_model.send_keys_literal") as mock_send_keys,
        patch("brain.agent_model.time.sleep"),
    ):
        set_active_model_claude_code("test-session", "sonnet", socket_name="factory-brain")
        mock_run_command.assert_called_once_with(
            "test-session", "/model sonnet", socket_name="factory-brain"
        )
        # Sin diálogo: nunca se envía un Enter de más (línea en blanco).
        mock_send_keys.assert_not_called()


# -- set_active_model ------------------------------------------------------


def test_set_active_model_returns_false_for_non_opencode() -> None:
    with patch("brain.agent_model.get_runtime_instance_for_agent",
               return_value=_FakeRuntimeInstance(rt_type="claude-code")):
        assert set_active_model("claude-agent", "any-model") is False


def test_set_active_model_returns_false_when_session_not_alive() -> None:
    with (
        patch("brain.agent_model.get_runtime_instance_for_agent",
              return_value=_FakeRuntimeInstance()),
        patch("brain.agent_model.is_alive", return_value=False),
    ):
        assert set_active_model("dead-agent", "deepseek") is False


def test_set_active_model_returns_false_when_no_runtime() -> None:
    with patch("brain.agent_model.get_runtime_instance_for_agent", return_value=None):
        assert set_active_model("no-agent", "deepseek") is False


def test_set_active_model_success_flow() -> None:
    """Camino feliz (flujo corregido T-FB024-US11-13, 2026-08-17: Ctrl+X
    directo + 'm', Search por nombre, offset sobre listado FILTRADO —
    ver docstring de `set_active_model`). Las verificaciones de cambio de
    pane pasan y el modelo leido al final coincide (match laxo)."""
    # 5 llamadas a capture_pane_lines:
    # 0: get_active_model inicial (previous)
    # 1: _capture_safe before 'm' (_send_and_verify_change)
    # 2: _capture_safe after 'm'
    # 3: _capture_safe del listado YA FILTRADO por Search
    # 4: get_active_model verificacion final
    mock_captures = [
        ["Build · old-model OldCo"],
        ["Select variant"],
        ["Select model", "deepseek", "", "deepseek-chat                          SomeProvider"],
        ["Select model", "deepseek", "", "deepseek-chat                          SomeProvider"],
        ["Build · deepseek-chat SomeProvider"],
    ]

    call_count = 0

    def fake_capture(*args, **kwargs):
        nonlocal call_count
        idx = call_count if call_count < len(mock_captures) else len(mock_captures) - 1
        result = mock_captures[idx]
        call_count += 1
        return list(result)

    with (
        patch("brain.agent_model.get_runtime_instance_for_agent",
              return_value=_FakeRuntimeInstance()),
        patch("brain.agent_model.is_alive", return_value=True),
        patch("brain.agent_model.capture_pane_lines", side_effect=fake_capture),
        patch("brain.agent_model.send_keys_literal"),
        patch("brain.agent_model.time.sleep"),
    ):
        result = set_active_model("agent-1", "deepseek-chat")
        assert result is True


def test_set_active_model_handles_exception_gracefully() -> None:
    with (
        patch("brain.agent_model.get_runtime_instance_for_agent",
              return_value=_FakeRuntimeInstance()),
        patch("brain.agent_model.is_alive", return_value=True),
        patch("brain.agent_model.capture_pane_lines",
              side_effect=RuntimeError("exploto")),
        patch("brain.agent_model.send_keys_literal"),
        patch("brain.agent_model.time.sleep"),
    ):
        assert set_active_model("agent-1", "deepseek") is False
