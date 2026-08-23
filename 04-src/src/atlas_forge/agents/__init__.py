from atlas_forge.agents.arquitecto import (
    ARQUITECTO_PROMPT,
    ARQUITECTO_ROLE,
    build_arquitecto_prompt,
    register_arquitecto,
)
from atlas_forge.agents.auditor_oss import (
    AUDITOR_OSS_PROMPT,
    AUDITOR_OSS_ROLE,
    build_auditor_oss_prompt,
    register_auditor_oss,
)
from atlas_forge.agents.developer import (
    DEVELOPER_PROMPT,
    DEVELOPER_ROLE,
    MAX_SIMULTANEOUS_DEVELOPERS,
    build_developer_prompt,
    register_developer,
)
from atlas_forge.agents.documentador import (
    DOCUMENTADOR_PROMPT,
    DOCUMENTADOR_ROLE,
    build_documentador_prompt,
    register_documentador,
)
from atlas_forge.agents.tester import (
    TESTER_PROMPT,
    TESTER_ROLE,
    build_tester_prompt,
    register_tester,
)
from atlas_forge.agents.governance import (
    project_governance_instruction,
    project_has_governance,
)
from atlas_forge.agents.lifecycle import (
    InvalidAgentTransitionError,
    clear_session_limit,
    get_agent_state,
    mark_idle,
    mark_limited,
    mark_stopped,
    mark_unavailable,
    mark_working,
)
from atlas_forge.agents.liveness import refresh_agent_liveness
from atlas_forge.agents.registry import register_agent, register_agent_with_reuse
from atlas_forge.agents.release import AgentReleaseError, release_agent
from atlas_forge.agents.roles import RoleConfig, get_role, get_register_fn_for_role, list_roles, register_role
from atlas_forge.agents.stop import AgentRuntimeNotFoundError, stop_agent
from atlas_forge.agents.ux import (
    UX_PROMPT,
    UX_ROLE,
    build_ux_prompt,
    register_ux,
)

__all__ = [
    "AgentReleaseError",
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
    "clear_session_limit",
    "get_agent_state",
    "get_role",
    "get_register_fn_for_role",
    "list_roles",
    "mark_idle",
    "mark_limited",
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
    "release_agent",
    "stop_agent",
]
