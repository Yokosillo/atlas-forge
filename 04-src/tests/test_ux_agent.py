import uuid

import libtmux
import pytest

from atlas_forge.agents import UX_PROMPT, UX_ROLE, register_ux
from atlas_forge.core import activate
from atlas_forge.models import DevelopmentSession, Runtime


@pytest.fixture
def isolated_socket():
    """Mismo criterio que `test_developer_agent.py`: aislar en un servidor
    tmux propio, nunca lanzar el binario real de Claude Code/OpenCode."""
    name = f"atlas_forge-test-{uuid.uuid4().hex[:8]}"
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


def test_ux_registers_with_fixed_role_and_prompt(isolated_socket: str, tmp_path) -> None:
    session = _active_session()
    runtime = _test_runtime()

    agent, _ = register_ux(session, runtime, str(tmp_path), socket_name=isolated_socket)

    assert agent.role == UX_ROLE
    assert agent.prompt.startswith(UX_PROMPT)
    assert tmp_path.name in agent.prompt


def test_registering_ux_twice_reuses_the_same_instance(isolated_socket: str, tmp_path) -> None:
    session = _active_session()
    runtime = _test_runtime()

    agent1, _ = register_ux(session, runtime, str(tmp_path), socket_name=isolated_socket)
    agent2, _ = register_ux(session, runtime, str(tmp_path), socket_name=isolated_socket)

    assert agent1.id == agent2.id


def test_ux_prompt_includes_project_governance_when_declared(tmp_path) -> None:
    from atlas_forge.agents.ux import build_ux_prompt

    governance_dir = tmp_path / "00-gobierno"
    governance_dir.mkdir()
    (governance_dir / "UX.md").write_text("gobierno ux")
    (governance_dir / "METODOLOGIA.md").write_text("metodologia")

    prompt = build_ux_prompt(str(tmp_path))

    assert "00-gobierno/UX.md" in prompt
