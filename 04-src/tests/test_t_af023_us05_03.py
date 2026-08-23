"""T-AF023-US05-03: tests deterministas de la vigilancia proactiva de agentes
persistentes (US05-01) y de su constancia (US05-02). Prefijo `T-AF023-US05-`.

Runtime mockeado (proveedor de liveness y funciones de runtime), SIN procesos
reales ni tmux. Cubre los 4 criterios de US-AF023-05:
  1. detección sin depender de `GET /agents`;
  2. reflejo del agente como inalcanzable (`unavailable`);
  3. constancia visible en un canal consultable (`reconciliation_log.jsonl`);
  4. NO se relanza automáticamente el agente (solo detección y constancia).
"""

from __future__ import annotations

import json
from unittest.mock import Mock, patch

from atlas_forge.agents.persistent_watcher import run_persistent_agent_cycle
from atlas_forge.core.reconciliation_log import reconciliation_log_path
from atlas_forge.core.session_lifecycle import activate
from atlas_forge.models import Agent, DevelopmentSession


def _agent(aid: str, name: str, role: str, persistent: bool) -> Agent:
    return Agent(id=aid, name=name, role=role, prompt="p", runtime_id="r", persistent=persistent)


def _session_with(*agents: Agent) -> DevelopmentSession:
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    session.agents = list(agents)
    return session


def _make_unavailable(agent, socket_name=None) -> Agent:
    """Proveedor de liveness mockeado que simula que el proceso/sesión real
    del agente desapareció (agente -> unavailable)."""
    agent.status = "unavailable"
    return agent


def _read_log(tmp_path, project_name="proj") -> list[dict]:
    log_path = reconciliation_log_path(tmp_path, project_name)
    if not log_path.is_file():
        return []
    return [json.loads(line) for line in log_path.read_text(encoding="utf-8").strip().splitlines()]


# ── criterio 1 + 2: detección sin GET /agents y reflejo como inalcanzable ──


def test_t_af023_us05_03_detects_persistent_agent_without_get_agents(tmp_path) -> None:
    arch = _agent("a1", "Arquitecto", "arquitecto", True)
    session = _session_with(arch)

    with patch(
        "atlas_forge.agents.persistent_watcher.refresh_agent_liveness", side_effect=_make_unavailable
    ):
        became = run_persistent_agent_cycle(
            session, project_root=str(tmp_path), project_name="proj"
        )

    # Criterio 1: el ciclo detecta el cuelgue sin que nadie llame a GET /agents.
    assert arch.id in became
    # Criterio 2: el agente queda reflejado como inalcanzable (unavailable).
    assert arch.status == "unavailable"


def test_t_af023_us05_03_non_persistent_agent_not_checked(tmp_path) -> None:
    dev = _agent("d1", "Developer-1", "developer", False)
    session = _session_with(dev)

    with patch(
        "atlas_forge.agents.persistent_watcher.refresh_agent_liveness", side_effect=_make_unavailable
    ):
        became = run_persistent_agent_cycle(
            session, project_root=str(tmp_path), project_name="proj"
        )

    assert dev.id not in became
    assert dev.status != "unavailable"


# ── criterio 3: constancia visible en un canal consultable ────────────────


def test_t_af023_us05_03_constancia_persisted_in_reconciliation_log(tmp_path) -> None:
    arch = _agent("a1", "Arquitecto", "arquitecto", True)
    session = _session_with(arch)

    with patch(
        "atlas_forge.agents.persistent_watcher.refresh_agent_liveness", side_effect=_make_unavailable
    ):
        run_persistent_agent_cycle(session, project_root=str(tmp_path), project_name="proj")

    entries = _read_log(tmp_path)
    assert len(entries) == 1
    assert entries[0]["reason"] == "persistent_agent_unreachable"
    assert entries[0]["agent_id"] == arch.id
    assert entries[0]["agent_name"] == arch.name
    assert entries[0]["ts"]  # timestamp presente
    assert entries[0]["motivo"]


def test_t_af023_us05_03_no_log_without_project_context(tmp_path) -> None:
    arch = _agent("a1", "Arquitecto", "arquitecto", True)
    session = _session_with(arch)

    with patch(
        "atlas_forge.agents.persistent_watcher.refresh_agent_liveness", side_effect=_make_unavailable
    ):
        became = run_persistent_agent_cycle(session)

    # Sin project_root/name (comportamiento previo a US05-02) no se escribe
    # constancia, pero la detección sí ocurre.
    assert arch.id in became
    assert _read_log(tmp_path) == []


# ── criterio 4: NO se relanza automáticamente ─────────────────────────────


def test_t_af023_us05_03_does_not_relaunch_the_agent(tmp_path) -> None:
    arch = _agent("a1", "Arquitecto", "arquitecto", True)
    session = _session_with(arch)

    # Espías: un relanzamiento habría que matar/arrancar un runtime real.
    start_runtime = Mock()
    stop_runtime = Mock()

    with patch("atlas_forge.agents.persistent_watcher.refresh_agent_liveness", side_effect=_make_unavailable):
        with patch("atlas_forge.agents.persistent_watcher.start_runtime", start_runtime, create=True):
            with patch("atlas_forge.agents.persistent_watcher.stop_runtime", stop_runtime, create=True):
                run_persistent_agent_cycle(
                    session, project_root=str(tmp_path), project_name="proj"
                )

    # Criterio 4: solo se detecta y deja constancia; el agente NO se relanza
    # (sigue `unavailable`, ningún runtime se arrancó/paró).
    assert arch.status == "unavailable"
    start_runtime.assert_not_called()
    stop_runtime.assert_not_called()
