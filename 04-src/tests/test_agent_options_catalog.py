"""Tests de T-FB022-US11-01: catalogo rol x modelo."""

from unittest.mock import patch

from brain.agents import ARQUITECTO_ROLE, DEVELOPER_ROLE, DIRECTOR_ROLE
from brain.agents.agent_options import AgentLaunchOption, list_available_agent_options


def _mock_model_entries() -> list[dict]:
    return [
        {"id": "deepseek-pro", "name": "DeepSeek Pro", "runtime": "opencode"},
        {"id": "claude-code", "name": "Claude Code", "runtime": "claude_code"},
    ]


def _mock_preferences_all_enabled() -> dict:
    return {"enabled_model_ids": [], "default_model_by_role": {}}


class TestCatalogRolModelo:
    def test_catalog_is_rol_x_model_not_rol_x_runtime(self) -> None:
        with (
            patch("brain.agents.agent_options.get_available_model_entries",
                  return_value=_mock_model_entries()),
            patch("brain.agents.agent_options.load_model_preferences",
                  return_value=_mock_preferences_all_enabled()),
        ):
            options = list_available_agent_options()
            # 3 roles x 2 modelos = 6 opciones.
            assert len(options) == 6

            # Cada opcion tiene model_id y model_name.
            for opt in options:
                assert opt.model_id in ("deepseek-pro", "claude-code")
                assert opt.model_name in ("DeepSeek Pro", "Claude Code")

    def test_runtime_is_resolved_internally(self) -> None:
        with (
            patch("brain.agents.agent_options.get_available_model_entries",
                  return_value=_mock_model_entries()),
            patch("brain.agents.agent_options.load_model_preferences",
                  return_value=_mock_preferences_all_enabled()),
        ):
            options = list_available_agent_options()
            for opt in options:
                if opt.model_id == "deepseek-pro":
                    assert opt.runtime_type == "opencode"
                    assert opt.supports_model is True
                elif opt.model_id == "claude-code":
                    assert opt.runtime_type == "claude_code"
                    assert opt.supports_model is False

    def test_all_roles_work(self) -> None:
        with (
            patch("brain.agents.agent_options.get_available_model_entries",
                  return_value=_mock_model_entries()),
            patch("brain.agents.agent_options.load_model_preferences",
                  return_value=_mock_preferences_all_enabled()),
        ):
            options = list_available_agent_options()
            roles = {opt.agent_role for opt in options}
            assert {DEVELOPER_ROLE, DIRECTOR_ROLE, ARQUITECTO_ROLE}.issubset(roles)

    def test_disabled_models_not_included(self) -> None:
        with (
            patch("brain.agents.agent_options.get_available_model_entries",
                  return_value=_mock_model_entries()),
            patch("brain.agents.agent_options.load_model_preferences",
                  return_value={"enabled_model_ids": ["deepseek-pro"], "default_model_by_role": {}}),
        ):
            options = list_available_agent_options()
            # Solo 3 opciones (3 roles x 1 modelo habilitado).
            assert len(options) == 3
            for opt in options:
                assert opt.model_id == "deepseek-pro"

    def test_empty_enabled_ids_means_all_enabled(self) -> None:
        with (
            patch("brain.agents.agent_options.get_available_model_entries",
                  return_value=_mock_model_entries()),
            patch("brain.agents.agent_options.load_model_preferences",
                  return_value=_mock_preferences_all_enabled()),
        ):
            options = list_available_agent_options()
            assert len(options) == 6

    def test_option_is_plain_data(self) -> None:
        option = AgentLaunchOption(
            agent_role=DEVELOPER_ROLE,
            model_id="deepseek-pro",
            model_name="DeepSeek Pro",
            runtime_type="opencode",
            runtime_name="OpenCode",
            supports_model=True,
        )
        assert option.agent_role == DEVELOPER_ROLE
        assert option.model_id == "deepseek-pro"
        assert option.model_name == "DeepSeek Pro"
        assert option.runtime_type == "opencode"
        assert option.supports_model is True
