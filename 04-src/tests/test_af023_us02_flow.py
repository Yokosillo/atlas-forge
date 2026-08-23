"""Validación del flujo COMPLETO de recuperación de US-AF023-02
(T-AF023-US02-03): detección (T-AF023-US01) → recuperación automática
(T-AF023-US02-01/02) → vuelta a estado operativo, con límite de reintentos y
fallo consultable.

Tests deterministas (prefijo `T-AF023-US02-`) con un agente simulado aislado
en un socket tmux de test (doble cooperativo, nunca un runtime real). La
detección de "colgado" se controla inyectando una fuente de actividad congelada
(`resolve_runtime_last_activity`) y el kill/relaunch se inyecta; el ciclo real
(`run_supervision_recovery_cycle`) y el `RecoveryRetryTracker` se ejercitan tal
cual."""

import time
import uuid

import libtmux
import pytest

from atlas_forge.agents.supervision_recovery import run_supervision_recovery_cycle
from atlas_forge.models import Agent, DevelopmentSession, Runtime
from atlas_forge.runtime import (
    register_runtime_instance_for_agent,
    start_runtime,
    stop_runtime,
)

_COOPERATIVE_AGENT_SCRIPT = str(
    __import__("pathlib").Path(__file__).parent / "fixtures" / "cooperative_agent_sim.sh"
)


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


def _launch_opencode_agent(isolated_socket: str, tmp_path, session_id: str = "sess-flow"):
    runtime = Runtime(
        id="opencode", name="OpenCode", type="opencode", command="bash",
        args=[str(_COOPERATIVE_AGENT_SCRIPT)],
    )
    agent = Agent(
        id="a-flow", name="Developer-1", role="developer", prompt="p", runtime_id="opencode",
        status="working",
    )
    real_ri = start_runtime(runtime, agent, str(tmp_path), socket_name=isolated_socket)
    # El runtime del agente simulado conserva el contexto de la sesión
    # (mecanismo tmux; T-AF023-US04 headless revertida).
    registered_ri = real_ri.__class__(
        runtime=real_ri.runtime,
        session_name=session_id,
    )
    register_runtime_instance_for_agent(agent.id, registered_ri)
    return agent, real_ri


_FROZEN_TS = 1_000_000.0  # timestamp fijo hace mucho -> el agente aparece colgado


def _frozen_activity(*args, **kwargs):
    # Fuente de actividad congelada (timestamp fijo) -> el agente aparece colgado.
    return _FROZEN_TS


def test_T_AF023_US02_flow_complete_recovery_detects_hung_and_recovers(
    isolated_socket: str, tmp_path, monkeypatch,
) -> None:
    """Flujo completo: detección de colgado -> recuperación automática (kill +
    relaunch conservando contexto) -> vuelta a estado operativo (`idle`)."""
    from atlas_forge.agents.supervision import resolve_runtime_last_activity

    agent, runtime_instance = _launch_opencode_agent(isolated_socket, tmp_path)
    # El watcher ya acumuló 3 lecturas de actividad congelada (detección de
    # cuelgue de T-AF023-US01) antes de este ciclo.
    agent.activity_history = [_frozen_activity()] * 3
    session = DevelopmentSession(id="s1", project_id="p1")
    session.agents = [agent]

    monkeypatch.setattr(
        "atlas_forge.agents.supervision.resolve_runtime_last_activity", _frozen_activity
    )
    monkeypatch.setattr("atlas_forge.agents.supervision.is_alive", lambda *a, **k: True)

    calls = {"kill": 0, "relaunch": []}

    def kill_fn(ri):
        calls["kill"] += 1

    def relaunch_fn(a, plan):
        calls["relaunch"].append(plan)

    # El ciclo real: refresca supervisión (detecta colgado por la actividad
    # congelada), planifica (OpenCode conserva contexto con --session) y
    # recupera.
    result = run_supervision_recovery_cycle(
        session, socket_name=isolated_socket, kill_fn=kill_fn, relaunch_fn=relaunch_fn
    )

    assert agent.id in result.recovered
    assert calls["kill"] == 1
    assert len(calls["relaunch"]) == 1
    # OpenCode: se conserva el contexto de la sesión en el plan.
    plan = calls["relaunch"][0]
    assert plan.action == "relaunch_preserving_context"
    assert "--session" in plan.relaunch_args
    assert "sess-flow" in plan.relaunch_args
    # Vuelve a un estado operativo normal consultable.
    assert agent.status == "idle"
    assert agent.supervision_status in ("vivo", "colgado")

    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_T_AF023_US02_flow_stops_after_retry_limit_with_consultable_failure(
    isolated_socket: str, tmp_path, monkeypatch,
) -> None:
    """Tras el límite de reintentos (3 por defecto), el sistema deja de
    reintentar y expone el fallo como estado consultable."""
    from atlas_forge.agents.supervision import resolve_runtime_last_activity

    agent, runtime_instance = _launch_opencode_agent(isolated_socket, tmp_path)
    agent.activity_history = [_frozen_activity()] * 3
    session = DevelopmentSession(id="s1", project_id="p1")
    session.agents = [agent]

    monkeypatch.setattr(
        "atlas_forge.agents.supervision.resolve_runtime_last_activity", _frozen_activity
    )
    monkeypatch.setattr("atlas_forge.agents.supervision.is_alive", lambda *a, **k: True)

    retry_trackers: dict = {}
    calls = {"kill": 0}

    def kill_fn(ri):
        calls["kill"] += 1

    def failing_relaunch_fn(a, plan):
        raise RuntimeError("relaunch falló")

    # 3 ciclos con fallo -> el contador llega al límite.
    for _ in range(3):
        run_supervision_recovery_cycle(
            session, socket_name=isolated_socket, retry_trackers=retry_trackers,
            kill_fn=kill_fn, relaunch_fn=failing_relaunch_fn,
        )

    kill_before = calls["kill"]
    # 4º ciclo: el límite (3) ya se superó -> no se reintenta más.
    result = run_supervision_recovery_cycle(
        session, socket_name=isolated_socket, retry_trackers=retry_trackers,
        kill_fn=kill_fn, relaunch_fn=failing_relaunch_fn,
    )

    assert calls["kill"] == kill_before  # no se volvió a matar
    assert agent.id in result.failed
    assert agent.id not in result.recovered
    tracker = retry_trackers[agent.id]
    assert tracker.status == "failed"
    assert not tracker.should_retry()

    stop_runtime(runtime_instance, socket_name=isolated_socket)
