import uuid

import libtmux
import pytest

from brain.agents import AUDITOR_OSS_PROMPT, AUDITOR_OSS_ROLE, register_auditor_oss
from brain.core import activate
from brain.models import DevelopmentSession, Runtime


@pytest.fixture
def isolated_socket():
    """Mismo criterio que `test_developer_agent.py`/`test_ux_agent.py`:
    aislar en un servidor tmux propio, nunca lanzar el binario real de
    Claude Code/OpenCode."""
    name = f"brain-test-{uuid.uuid4().hex[:8]}"
    yield name
    try:
        libtmux.Server(socket_name=name).kill()
    except Exception:
        pass


def _test_runtime() -> Runtime:
    return Runtime(
        id="test-runtime",
        name="Test Runtime",
        type="test",
        command="sleep",
        args=["5"],
    )


def _active_session() -> DevelopmentSession:
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    return session


def test_auditor_oss_registers_with_fixed_role_and_prompt(
    isolated_socket: str, tmp_path
) -> None:
    session = _active_session()
    runtime = _test_runtime()

    agent, _ = register_auditor_oss(
        session, runtime, str(tmp_path), socket_name=isolated_socket
    )

    assert agent.role == AUDITOR_OSS_ROLE
    assert agent.prompt.startswith(AUDITOR_OSS_PROMPT)
    assert tmp_path.name in agent.prompt


def test_registering_auditor_oss_twice_reuses_the_same_instance(
    isolated_socket: str, tmp_path
) -> None:
    session = _active_session()
    runtime = _test_runtime()

    agent1, _ = register_auditor_oss(
        session, runtime, str(tmp_path), socket_name=isolated_socket
    )
    agent2, _ = register_auditor_oss(
        session, runtime, str(tmp_path), socket_name=isolated_socket
    )

    assert agent1.id == agent2.id


def test_auditor_oss_prompt_includes_project_governance_when_declared(tmp_path) -> None:
    from brain.agents.auditor_oss import build_auditor_oss_prompt

    governance_dir = tmp_path / "00-gobierno"
    governance_dir.mkdir()
    (governance_dir / "AUDITOR-OSS.md").write_text("gobierno auditor oss")
    (governance_dir / "METODOLOGIA.md").write_text("metodologia")

    prompt = build_auditor_oss_prompt(str(tmp_path))

    assert "00-gobierno/AUDITOR-OSS.md" in prompt
