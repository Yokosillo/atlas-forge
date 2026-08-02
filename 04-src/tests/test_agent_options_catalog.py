from brain.agents import CRITIC_ROLE, DEVELOPER_ROLE
from brain.agents.agent_options import AgentLaunchOption, list_available_agent_options


def test_catalog_includes_developer_and_critic_as_agent_roles() -> None:
    options = list_available_agent_options()

    agent_roles = {option.agent_role for option in options}
    assert agent_roles == {DEVELOPER_ROLE, CRITIC_ROLE}


def test_catalog_includes_claude_code_and_opencode_as_runtimes() -> None:
    options = list_available_agent_options()

    runtime_types = {option.runtime_type for option in options}
    assert runtime_types == {"claude-code", "opencode"}


def test_opencode_options_support_model_and_claude_code_options_do_not() -> None:
    options = list_available_agent_options()

    for option in options:
        if option.runtime_type == "opencode":
            assert option.supports_model is True
        elif option.runtime_type == "claude-code":
            assert option.supports_model is False


def test_catalog_contains_exactly_the_four_expected_combinations() -> None:
    options = list_available_agent_options()

    expected = {
        (DEVELOPER_ROLE, "claude-code", False),
        (DEVELOPER_ROLE, "opencode", True),
        (CRITIC_ROLE, "claude-code", False),
        (CRITIC_ROLE, "opencode", True),
    }
    actual = {
        (option.agent_role, option.runtime_type, option.supports_model)
        for option in options
    }

    assert actual == expected
    assert len(options) == 4


def test_agent_launch_option_is_a_plain_data_description_without_launch_logic() -> None:
    # No incluye lógica de lanzamiento — solo describe la combinación
    # disponible, tal como pide el objetivo de la Task.
    option = AgentLaunchOption(
        agent_role=DEVELOPER_ROLE,
        runtime_type="claude-code",
        runtime_name="Claude Code",
        supports_model=False,
    )

    assert option.agent_role == DEVELOPER_ROLE
    assert option.runtime_type == "claude-code"
    assert option.runtime_name == "Claude Code"
    assert option.supports_model is False
