"""Tests de T-AF022-US10-01: persistencia de modelos habilitados y default por rol."""

from __future__ import annotations

import tempfile
from pathlib import Path

from atlas_forge.model_preferences import (
    load_model_preferences,
    save_model_preferences,
)


class TestModelPreferences:
    def test_load_returns_defaults_when_no_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            prefs = load_model_preferences(state_dir=state_dir)
            assert prefs["enabled_model_ids"] == []
            assert prefs["default_model_by_role"] == {}

    def test_save_and_load_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            prefs = {
                "enabled_model_ids": [
                    "opencode-go/deepseek-v4-pro",
                    "claude-code",
                ],
                "default_model_by_role": {
                    "developer": "opencode-go/deepseek-v4-pro",
                    "critic": "claude-code",
                },
            }
            save_model_preferences(prefs, state_dir=state_dir)
            loaded = load_model_preferences(state_dir=state_dir)
            assert loaded == prefs

    def test_save_empty_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            prefs = {
                "enabled_model_ids": [],
                "default_model_by_role": {},
            }
            save_model_preferences(prefs, state_dir=state_dir)
            loaded = load_model_preferences(state_dir=state_dir)
            assert loaded == prefs

    def test_update_partial_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            save_model_preferences({
                "enabled_model_ids": ["a", "b"],
                "default_model_by_role": {"dev": "a"},
            }, state_dir=state_dir)
            save_model_preferences({
                "enabled_model_ids": ["c"],
                "default_model_by_role": {},
            }, state_dir=state_dir)
            loaded = load_model_preferences(state_dir=state_dir)
            assert loaded["enabled_model_ids"] == ["c"]
            assert loaded["default_model_by_role"] == {}
