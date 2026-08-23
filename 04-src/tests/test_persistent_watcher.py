"""T-AF023-US05-01: vigilancia periódica proactiva de agentes persistentes
(Arquitecto y otros con `persistent=true`) — comprueba su operatividad real
sin depender de `GET /agents`. No relanza automáticamente; solo detecta y
deja el agente como `unavailable`."""

import uuid

import libtmux
import pytest

from atlas_forge.agents.launch import launch_agent
from atlas_forge.agents.persistent_watcher import PersistentAgentWatcher, run_persistent_agent_cycle
from atlas_forge.core.session_lifecycle import activate
from atlas_forge.core.session_registry import _reset_registry_for_tests
from atlas_forge.models import DevelopmentSession
from atlas_forge.runtime import is_runtime_alive
from atlas_forge.tmux.manager import kill_session


@pytest.fixture(autouse=True)
def _clean_registry():
    _reset_registry_for_tests()
    yield
    _reset_registry_for_tests()


@pytest.fixture(autouse=True)
def _no_real_runtime(monkeypatch):
    import atlas_forge.runtime.claude_code as claude_code_module
    import atlas_forge.runtime.opencode as opencode_module

    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_COMMAND", "sleep")
    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_ARGS", ["5"])
    monkeypatch.setattr(opencode_module, "DEFAULT_OPENCODE_COMMAND", "sleep")
    monkeypatch.setattr(opencode_module, "DEFAULT_OPENCODE_AUTONOMY_FLAG", "5")
    monkeypatch.setattr(opencode_module, "DEFAULT_OPENCODE_ARGS", ["5"])


@pytest.fixture
def isolated_socket():
    name = f"atlas_forge-test-{uuid.uuid4().hex[:8]}"
    try:
        yield name
    finally:
        try:
            libtmux.Server(socket_name=name).kill()
        except Exception:
            pass


def _active_session() -> DevelopmentSession:
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    return session


def _launch(role, session, isolated_socket, tmp_path):
    return launch_agent(role, "claude-code", None, session, str(tmp_path), socket_name=isolated_socket)


def test_persistent_agent_died_is_marked_unavailable_without_get_agents(
    isolated_socket, tmp_path
) -> None:
    session = _active_session()
    arch_agent, arch_runtime = _launch("arquitecto", session, isolated_socket, tmp_path)
    assert arch_agent.persistent is True
    assert is_runtime_alive(arch_runtime, socket_name=isolated_socket) is True

    # El proceso/sesión del Arquitecto muere fuera de atlas_forge (crash/kill manual).
    kill_session(arch_runtime.session_name, socket_name=isolated_socket)
    assert is_runtime_alive(arch_runtime, socket_name=isolated_socket) is False

    # Un único ciclo del watcher (sin llamar a GET /agents) lo marca unavailable.
    became = run_persistent_agent_cycle(session, socket_name=isolated_socket)

    assert arch_agent.id in became
    assert arch_agent.status == "unavailable"


def test_non_persistent_agent_is_not_checked_by_watcher(
    isolated_socket, tmp_path
) -> None:
    session = _active_session()
    dev_agent, dev_runtime = _launch("developer", session, isolated_socket, tmp_path)
    assert dev_agent.persistent is False

    # El Developer (no persistente) muere, pero el watcher NO lo comprueba.
    kill_session(dev_runtime.session_name, socket_name=isolated_socket)

    became = run_persistent_agent_cycle(session, socket_name=isolated_socket)

    assert dev_agent.id not in became
    assert dev_agent.status != "unavailable"


def test_persistent_agent_alive_remains_unchanged(isolated_socket, tmp_path) -> None:
    session = _active_session()
    arch_agent, arch_runtime = _launch("arquitecto", session, isolated_socket, tmp_path)
    assert is_runtime_alive(arch_runtime, socket_name=isolated_socket) is True

    became = run_persistent_agent_cycle(session, socket_name=isolated_socket)

    assert arch_agent.id not in became
    assert arch_agent.status != "unavailable"


def test_watcher_class_run_once_and_idempotent_after_unavailable(
    isolated_socket, tmp_path
) -> None:
    session = _active_session()
    arch_agent, arch_runtime = _launch("arquitecto", session, isolated_socket, tmp_path)

    watcher = PersistentAgentWatcher(session, socket_name=isolated_socket)

    kill_session(arch_runtime.session_name, socket_name=isolated_socket)
    became = watcher.run_once()
    assert arch_agent.id in became
    assert arch_agent.status == "unavailable"

    # Ya unavailable, el siguiente ciclo no lo vuelve a marcar (sin cambio).
    became2 = watcher.run_once()
    assert arch_agent.id not in became2
    assert arch_agent.status == "unavailable"


def test_unreachable_persistent_agent_is_persisted_in_reconciliation_log(
    isolated_socket, tmp_path
) -> None:
    """T-AF023-US05-02: cada detección de agente persistente inalcanzable
    queda registrada en el `reconciliation_log.jsonl` (append-only) con
    timestamp, agente y motivo, además de reflejarse el estado `unavailable`
    en el registro de agentes. No se relanza nada."""
    import json

    from atlas_forge.core.reconciliation_log import reconciliation_log_path

    session = _active_session()
    arch_agent, arch_runtime = _launch("arquitecto", session, isolated_socket, tmp_path)

    kill_session(arch_runtime.session_name, socket_name=isolated_socket)

    became = run_persistent_agent_cycle(
        session,
        socket_name=isolated_socket,
        project_root=str(tmp_path),
        project_name="proj",
    )

    assert arch_agent.id in became
    assert arch_agent.status == "unavailable"

    log_path = reconciliation_log_path(tmp_path, "proj")
    assert log_path.is_file(), "debe existir el log de reconciliación"
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["reason"] == "persistent_agent_unreachable"
    assert entry["agent_id"] == arch_agent.id
    assert entry["agent_name"] == arch_agent.name
    assert entry["ts"]  # timestamp presente
    assert entry["motivo"]

    # Sin project_root/name no se escribe el log (comportamiento previo).
    became2 = run_persistent_agent_cycle(session, socket_name=isolated_socket)
    assert arch_agent.id not in became2  # ya unavailable, no se re-marca
