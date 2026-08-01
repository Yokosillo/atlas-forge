from brain.runtime.agent_runtime_registry import (
    get_runtime_instance_for_agent,
    register_runtime_instance_for_agent,
)
from brain.runtime.claude_code import build_prompt_args as build_claude_code_prompt_args
from brain.runtime.claude_code import register_claude_code_runtime
from brain.runtime.generic import (
    RuntimeInstance,
    extract_model_from_runtime,
    is_runtime_alive,
    session_name_for,
    start_runtime,
    stop_runtime,
)
from brain.runtime.opencode import build_prompt_args as build_opencode_prompt_args
from brain.runtime.opencode import register_opencode_runtime

__all__ = [
    "RuntimeInstance",
    "build_claude_code_prompt_args",
    "build_opencode_prompt_args",
    "extract_model_from_runtime",
    "get_runtime_instance_for_agent",
    "is_runtime_alive",
    "register_claude_code_runtime",
    "register_opencode_runtime",
    "register_runtime_instance_for_agent",
    "session_name_for",
    "start_runtime",
    "stop_runtime",
]
