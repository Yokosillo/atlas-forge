"""Tests de T-AF023-US01-02: estado de supervisión (vivo/colgado/detenido)
del agente y su exposición — deterministas, sin infraestructura externa."""

from unittest.mock import patch

import pytest

from atlas_forge.agents.supervision import (
    SUPERVISION_ALIVE,
    SUPERVISION_HUNG,
    SUPERVISION_STOPPED,
    compute_supervision_state,
    refresh_agent_supervision,
)
from atlas_forge.models import Agent

_NOW = 1_000_000.0


def _agent(status: str = "idle", **kw) -> Agent:
    return Agent(id="a1", name="dev", role="developer", prompt="p", runtime_id="r1", status=status, **kw)


# ── compute_supervision_state (función pura) ───────────────────────────────


def test_compute_stopped_agent_is_detenido() -> None:
    assert compute_supervision_state(_agent(status="stopped"), [], now=_NOW) == SUPERVISION_STOPPED
    assert compute_supervision_state(_agent(status="unavailable"), [], now=_NOW) == SUPERVISION_STOPPED


def test_compute_no_activity_beyond_threshold_is_colgado() -> None:
    # Mismo timestamp antiguo en varias lecturas seguidas -> colgado.
    agent = _agent(status="working")
    history = [_NOW - 500.0, _NOW - 500.0, _NOW - 500.0]
    assert compute_supervision_state(agent, history, threshold_seconds=120.0, now=_NOW) == SUPERVISION_HUNG


def test_compute_recent_activity_is_vivo() -> None:
    agent = _agent(status="working")
    history = [_NOW - 5.0, _NOW - 5.0, _NOW - 5.0]
    assert compute_supervision_state(agent, history, threshold_seconds=120.0, now=_NOW) == SUPERVISION_ALIVE


def test_compute_empty_history_is_vivo() -> None:
    # Sin datos de actividad no se declara un cuelgue.
    assert compute_supervision_state(_agent(status="working"), [], now=_NOW) == SUPERVISION_ALIVE


def test_compute_spaced_activity_is_vivo_not_colgado() -> None:
    # Actividad espaciada pero real (el timestamp avanzó) -> vivo, no colgado.
    agent = _agent(status="working")
    history = [_NOW - 500.0, _NOW - 400.0, _NOW - 250.0]
    assert compute_supervision_state(agent, history, threshold_seconds=120.0, now=_NOW) == SUPERVISION_ALIVE


def test_compute_does_not_alter_functional_status() -> None:
    # Criterio 3: el estado de supervisión no toca el estado funcional.
    agent = _agent(status="working")
    compute_supervision_state(agent, [_NOW - 500.0] * 3, now=_NOW)
    assert agent.status == "working"


# ── refresh_agent_supervision (cálculo perezoso) ───────────────────────────


class _FakeRuntime:
    session_name = "fake-session"
    runtime = type("R", (), {"type": "opencode"})()


def test_refresh_agent_without_runtime_is_detenido() -> None:
    agent = _agent(status="idle")
    with patch(
        "atlas_forge.agents.supervision.get_runtime_instance_for_agent", return_value=None
    ):
        result = refresh_agent_supervision(agent)
    assert result.supervision_status == SUPERVISION_STOPPED


def test_refresh_stopped_agent_is_detenido() -> None:
    agent = _agent(status="stopped")
    refresh_agent_supervision(agent)
    assert agent.supervision_status == SUPERVISION_STOPPED


def test_refresh_alive_with_activity_is_vivo() -> None:
    agent = _agent(status="working")
    with patch(
        "atlas_forge.agents.supervision.get_runtime_instance_for_agent", return_value=_FakeRuntime()
    ), patch(
        "atlas_forge.agents.supervision.is_runtime_alive", return_value=True
    ), patch(
        "atlas_forge.agents.supervision.resolve_runtime_last_activity", return_value=_NOW - 5.0
    ), patch("atlas_forge.agents.supervision.time.time", return_value=_NOW):
        result = refresh_agent_supervision(agent)
    assert result.supervision_status == SUPERVISION_ALIVE


def test_refresh_hung_with_frozen_activity_is_colgado() -> None:
    """Criterio: un agente sin actividad dentro del umbral en varias lecturas
    seguidas aparece como `colgado`."""
    agent = _agent(status="working")
    # Tres lecturas consecutivas con el MISMO timestamp antiguo -> colgado.
    with patch(
        "atlas_forge.agents.supervision.get_runtime_instance_for_agent", return_value=_FakeRuntime()
    ), patch(
        "atlas_forge.agents.supervision.is_runtime_alive", return_value=True
    ), patch(
        "atlas_forge.agents.supervision.resolve_runtime_last_activity", return_value=_NOW - 500.0
    ), patch("atlas_forge.agents.supervision.time.time", return_value=_NOW):
        refresh_agent_supervision(agent)
        refresh_agent_supervision(agent)
        refresh_agent_supervision(agent)
    assert agent.supervision_status == SUPERVISION_HUNG


def test_refresh_does_not_alter_functional_status() -> None:
    agent = _agent(status="working")
    with patch(
        "atlas_forge.agents.supervision.get_runtime_instance_for_agent", return_value=_FakeRuntime()
    ), patch(
        "atlas_forge.agents.supervision.is_runtime_alive", return_value=True
    ), patch(
        "atlas_forge.agents.supervision.resolve_runtime_last_activity", return_value=_NOW - 5.0
    ), patch("atlas_forge.agents.supervision.time.time", return_value=_NOW):
        refresh_agent_supervision(agent)
    assert agent.status == "working"
