"""Tests de T-AF023-US02-02: ciclo de supervisión que ejecuta la recuperación
automática de un agente colgado, respetando el límite de reintentos. Sin
infraestructura (kill/relaunch inyectados y mockeados)."""

from unittest.mock import Mock, patch

from atlas_forge.agents.recovery import RecoveryRetryTracker
from atlas_forge.agents.supervision_recovery import (
    SupervisionRecoveryResult,
    run_supervision_recovery_cycle,
)
from atlas_forge.models import Agent, DevelopmentSession


def _agent(aid: str = "a1", status: str = "working") -> Agent:
    return Agent(id=aid, name="dev", role="developer", prompt="p", runtime_id="opencode", status=status)


def _session_with(*agents: Agent) -> DevelopmentSession:
    session = DevelopmentSession(id="s1", project_id="p1")
    session.agents = list(agents)
    return session


class _FakeRuntime:
    session_name = "sess-1"
    runtime = Mock(type="opencode")


def _make_colgado(agent: Agent, *args, **kwargs) -> None:
    agent.supervision_status = "colgado"


def test_colgado_agent_is_recovered_and_returns_to_idle() -> None:
    """Criterio: un agente colgado se recupera automáticamente (kill +
    relaunch) sin intervención manual, y tras la recuperación vuelve a un
    estado operativo normal consultable (`idle`)."""
    agent = _agent(status="working")
    session = _session_with(agent)
    kill = Mock()
    relaunch = Mock()

    with patch(
        "atlas_forge.agents.supervision_recovery.refresh_agent_supervision", side_effect=_make_colgado
    ), patch(
        "atlas_forge.agents.supervision_recovery.get_runtime_instance_for_agent",
        return_value=_FakeRuntime(),
    ):
        result = run_supervision_recovery_cycle(session, kill_fn=kill, relaunch_fn=relaunch)

    assert agent.id in result.recovered
    kill.assert_called_once()
    relaunch.assert_called_once()
    # Tras la recuperación, un agente `working` vuelve a `idle` (normal).
    assert agent.status == "idle"


def test_healthy_agent_is_not_touched() -> None:
    """Un agente NO colgado no se recupera ni se toca."""
    agent = _agent(status="idle")

    def _set_healthy(a, *x, **k):
        a.supervision_status = "vivo"

    session = _session_with(agent)
    kill = Mock()
    relaunch = Mock()
    with patch(
        "atlas_forge.agents.supervision_recovery.refresh_agent_supervision", side_effect=_set_healthy
    ):
        result = run_supervision_recovery_cycle(session, kill_fn=kill, relaunch_fn=relaunch)
    assert result.recovered == []
    kill.assert_not_called()
    relaunch.assert_not_called()


def test_retry_limit_is_respected_and_failure_consultable() -> None:
    """Criterio: tras el límite de reintentos (por defecto 3), se deja de
    reintentar y el fallo queda consultable."""
    agent = _agent(status="working")
    session = _session_with(agent)
    trackers: dict[str, RecoveryRetryTracker] = {}

    # Simular que la recuperación SIEMPRE falla (el relaunch lanza).
    def _failing_relaunch(a, plan):
        raise RuntimeError("relaunch falló")

    with patch(
        "atlas_forge.agents.supervision_recovery.refresh_agent_supervision", side_effect=_make_colgado
    ), patch(
        "atlas_forge.agents.supervision_recovery.get_runtime_instance_for_agent",
        return_value=_FakeRuntime(),
    ):
        for _ in range(3):
            run_supervision_recovery_cycle(
                session, retry_trackers=trackers, kill_fn=lambda ri: None,
                relaunch_fn=_failing_relaunch,
            )

        # 4º ciclo: el límite (3) ya se superó -> no se reintenta más.
        result = run_supervision_recovery_cycle(
            session, retry_trackers=trackers, kill_fn=lambda ri: None,
            relaunch_fn=_failing_relaunch,
        )

    tracker = trackers[agent.id]
    assert tracker.status == "failed"
    assert not tracker.should_retry()
    assert agent.id in result.failed
    assert agent.id not in result.recovered


def test_success_resets_tracker_so_future_recovery_allowed() -> None:
    """Tras un éxito, el contador se resetea; si el agente se vuelve a colgar
    más tarde, se puede recuperar de nuevo (no queda en 'recuperándose' ni en
    fallo indefinido)."""
    agent = _agent(status="working")
    session = _session_with(agent)
    trackers: dict[str, RecoveryRetryTracker] = {}
    kill = Mock()
    relaunch = Mock()

    with patch(
        "atlas_forge.agents.supervision_recovery.refresh_agent_supervision", side_effect=_make_colgado
    ), patch(
        "atlas_forge.agents.supervision_recovery.get_runtime_instance_for_agent",
        return_value=_FakeRuntime(),
    ):
        # Primer ciclo: recupera con éxito.
        run_supervision_recovery_cycle(session, retry_trackers=trackers, kill_fn=kill, relaunch_fn=relaunch)
        assert trackers[agent.id].status == "ok"
        assert trackers[agent.id].consecutive_retries == 0

        # Vuelve a colgarse en un ciclo posterior: se recupera de nuevo
        # (el contador se reseteó tras el éxito).
        agent.status = "working"
        result = run_supervision_recovery_cycle(session, retry_trackers=trackers, kill_fn=kill, relaunch_fn=relaunch)
        assert agent.id in result.recovered


def test_recovered_agent_not_anymore_hung_resets_tracker() -> None:
    """Si un agente en fallo deja de estar colgado (recuperó por su cuenta),
    el contador se resetea y no queda en el limbo del fallo."""
    agent = _agent(status="working")
    session = _session_with(agent)
    trackers = {agent.id: RecoveryRetryTracker(max_retries=3, status="failed", consecutive_retries=3)}

    def _set_healthy(a, *x, **k):
        a.supervision_status = "vivo"

    with patch(
        "atlas_forge.agents.supervision_recovery.refresh_agent_supervision", side_effect=_set_healthy
    ):
        run_supervision_recovery_cycle(session, retry_trackers=trackers)

    assert trackers[agent.id].status == "ok"
    assert trackers[agent.id].should_retry()
