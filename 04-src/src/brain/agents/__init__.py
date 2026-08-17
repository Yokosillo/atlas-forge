from brain.agents.arquitecto import (
    ARQUITECTO_PROMPT,
    ARQUITECTO_ROLE,
    build_arquitecto_prompt,
    register_arquitecto,
)
from brain.agents.auditor_oss import (
    AUDITOR_OSS_PROMPT,
    AUDITOR_OSS_ROLE,
    build_auditor_oss_prompt,
    register_auditor_oss,
)
from brain.agents.developer import (
    DEVELOPER_PROMPT,
    DEVELOPER_ROLE,
    MAX_SIMULTANEOUS_DEVELOPERS,
    build_developer_prompt,
    register_developer,
)
from brain.agents.documentador import (
    DOCUMENTADOR_PROMPT,
    DOCUMENTADOR_ROLE,
    build_documentador_prompt,
    register_documentador,
)
from brain.agents.tester import (
    TESTER_PROMPT,
    TESTER_ROLE,
    build_tester_prompt,
    register_tester,
)
from brain.agents.governance import (
    project_governance_instruction,
    project_has_governance,
)
from brain.agents.lifecycle import (
    InvalidAgentTransitionError,
    get_agent_state,
    mark_idle,
    mark_stopped,
    mark_unavailable,
    mark_working,
)
from brain.agents.liveness import refresh_agent_liveness
from brain.agents.registry import register_agent, register_agent_with_reuse
from brain.agents.roles import RoleConfig, get_role, get_register_fn_for_role, list_roles, register_role
from brain.agents.stop import AgentRuntimeNotFoundError, stop_agent
from brain.agents.ux import (
    UX_PROMPT,
    UX_ROLE,
    build_ux_prompt,
    register_ux,
)

__all__ = [
    "AgentRuntimeNotFoundError",
    "ARQUITECTO_PROMPT",
    "ARQUITECTO_ROLE",
    "AUDITOR_OSS_PROMPT",
    "AUDITOR_OSS_ROLE",
    "DEVELOPER_PROMPT",
    "DEVELOPER_ROLE",
    "DOCUMENTADOR_PROMPT",
    "DOCUMENTADOR_ROLE",
    "InvalidAgentTransitionError",
    "MAX_SIMULTANEOUS_DEVELOPERS",
    "RoleConfig",
    "TESTER_PROMPT",
    "TESTER_ROLE",
    "UX_PROMPT",
    "UX_ROLE",
    "build_arquitecto_prompt",
    "build_auditor_oss_prompt",
    "build_developer_prompt",
    "build_documentador_prompt",
    "build_tester_prompt",
    "build_ux_prompt",
    "get_agent_state",
    "get_role",
    "get_register_fn_for_role",
    "list_roles",
    "mark_idle",
    "mark_stopped",
    "mark_unavailable",
    "mark_working",
    "project_governance_instruction",
    "project_has_governance",
    "refresh_agent_liveness",
    "register_agent",
    "register_agent_with_reuse",
    "register_arquitecto",
    "register_auditor_oss",
    "register_developer",
    "register_documentador",
    "register_role",
    "register_tester",
    "register_ux",
    "stop_agent",
]
