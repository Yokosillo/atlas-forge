"""Tests de US-AF024-12: persistencia de preferencias de sistema
(limite de Developer simultaneos, primer valor del catalogo abierto)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from atlas_forge.system_preferences import (
    DEFAULT_DEVELOPER_WAITS_FOR_TESTER_REVIEW,
    DEFAULT_MAX_SIMULTANEOUS_DEVELOPERS,
    get_developer_waits_for_tester_review,
    get_max_simultaneous_developers,
    load_system_preferences,
    save_system_preferences,
)


class TestSystemPreferences:
    def test_load_returns_default_when_no_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            prefs = load_system_preferences(state_dir=state_dir)
            assert prefs["max_simultaneous_developers"] == DEFAULT_MAX_SIMULTANEOUS_DEVELOPERS

    def test_save_and_load_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            save_system_preferences({"max_simultaneous_developers": 7}, state_dir=state_dir)
            loaded = load_system_preferences(state_dir=state_dir)
            assert loaded["max_simultaneous_developers"] == 7

    def test_save_survives_across_loads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            save_system_preferences({"max_simultaneous_developers": 5}, state_dir=state_dir)
            save_system_preferences({"max_simultaneous_developers": 2}, state_dir=state_dir)
            loaded = load_system_preferences(state_dir=state_dir)
            assert loaded["max_simultaneous_developers"] == 2

    def test_get_max_simultaneous_developers_shortcut(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            assert get_max_simultaneous_developers(state_dir=state_dir) == DEFAULT_MAX_SIMULTANEOUS_DEVELOPERS
            save_system_preferences({"max_simultaneous_developers": 4}, state_dir=state_dir)
            assert get_max_simultaneous_developers(state_dir=state_dir) == 4

    def test_save_missing_key_uses_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            save_system_preferences({}, state_dir=state_dir)
            loaded = load_system_preferences(state_dir=state_dir)
            assert loaded["max_simultaneous_developers"] == DEFAULT_MAX_SIMULTANEOUS_DEVELOPERS

    def test_get_developer_waits_for_tester_review_shortcut(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            assert (
                get_developer_waits_for_tester_review(state_dir=state_dir)
                == DEFAULT_DEVELOPER_WAITS_FOR_TESTER_REVIEW
            )
            save_system_preferences(
                {"developer_waits_for_tester_review": False}, state_dir=state_dir
            )
            assert get_developer_waits_for_tester_review(state_dir=state_dir) is False
