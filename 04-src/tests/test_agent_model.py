"""Tests de T-FB004-US05-01: get_active_model / set_active_model
sobre agentes OpenCode en ejecucion via tmux."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from brain.agent_model import (
    _find_model_index,
    _model_names_match,
    _parse_model_from_pane,
    get_active_model,
    set_active_model,
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
    """Camino feliz: las verificaciones de cambio de pane pasan y el modelo
    leido al final coincide (match laxo)."""
    # 7 llamadas a capture_pane_lines:
    # 0: get_active_model inicial (previous)
    # 1: _capture_safe before C-p
    # 2: _capture_safe after C-p
    # 3: _capture_safe before C-x
    # 4: _capture_safe after C-x
    # 5: _capture_safe lectura del selector
    # 6: get_active_model verificacion final
    mock_captures = [
        ["Build · old-model OldCo"],
        ["Build · old-model OldCo"],
        ["paleta de comandos abierta"],
        ["paleta de comandos abierta"],
        ["selector de modelos"],
        ["selector de modelos", "  modelo-a", "  deepseek/deepseek-chat", "  modelo-c"],
        ["Build · deepseek/deepseek-chat SomeProvider"],
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
        result = set_active_model("agent-1", "deepseek/deepseek-chat")
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
