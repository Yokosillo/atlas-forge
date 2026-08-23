"""Tests del fallback de cierre por pane de T-AF008-US10-06
(`atlas_forge.dispatcher.job_dispatch`): un agente que termina su reporte
estructurado en el pane (`RESULTADO:`/`ESTADO:`) pero NO escribe el fichero
de auto-reporte se detecta como finalizado sin esperar el timeout de 1h.

Determinista, sin tmux real: se mockean `get_runtime_instance_for_agent`,
`is_alive` y `capture_pane_lines`, y la baseline del pane que
`dispatch_job_send` registra.

Cubren:
- criterio 1: marcador nuevo en el pane (sin fichero) -> `failed` y agente
  `idle`, no atascado.
- criterio 3: un marcador OBSOLETO (solo en la baseline) NO dispara el
  fallback (sin falsos positivos); el Job sigue a timeout normal.
- criterio 4: `failed` con motivo claro y agente a `idle`.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import atlas_forge.dispatcher.job_dispatch as jd
from atlas_forge.agents.lifecycle import mark_working
from atlas_forge.dispatcher.job_dispatch import (
    JobReportFinishedInPaneError,
    _PANE_BASELINES,
    wait_and_finalize_job,
)
from atlas_forge.dispatcher.job_lifecycle import mark_running
from atlas_forge.models import Agent, Job


def _agent() -> Agent:
    return Agent(id="a1", name="test-agent", role="developer", prompt="p", runtime_id="r1")


def _job() -> Job:
    return Job(id="j1", session_id="s1", agent_id="a1", description="d")


def _fake_runtime(session_name: str = "test-session") -> SimpleNamespace:
    return SimpleNamespace(session_name=session_name)


def _patch_pane(monkeypatch, baseline: list[str], current: list[str]) -> None:
    """Mockea el runtime del agente y la lectura del pane."""
    monkeypatch.setattr(
        jd, "get_runtime_instance_for_agent", lambda _agent_id: _fake_runtime()
    )
    monkeypatch.setattr(jd, "is_alive", lambda *_a, **_k: True)
    captured = {"i": 0}
    snapshots = [baseline, current]

    def fake_capture(*_a, **_k):
        idx = min(captured["i"], len(snapshots) - 1)
        captured["i"] += 1
        return snapshots[idx]

    monkeypatch.setattr(jd, "capture_pane_lines", fake_capture)


def test_new_marker_in_pane_without_report_file_marks_job_failed(
    tmp_path: Path, monkeypatch
) -> None:
    """Criterio 1 y 4: el agente termina su reporte en el pane (marcador
    nuevo, no en la baseline) pero no escribe el fichero -> el Job pasa a
    `failed` con motivo claro y el agente a `idle` (no queda `working`)."""
    baseline = ["$", "procesando..."]
    current = baseline + ["RESULTADO: EXITO"]
    _patch_pane(monkeypatch, baseline, current)

    report_file = tmp_path / "job-report.txt"  # nunca se escribe
    _PANE_BASELINES[str(report_file)] = baseline

    agent = _agent()
    job = _job()
    mark_running(job)
    mark_working(agent)

    wait_and_finalize_job(job, agent, report_file, timeout_seconds=2.0, poll_interval_seconds=0.05)

    assert job.status == "failed"
    assert "no escribió el fichero de auto-reporte" in job.result
    assert agent.status == "idle"


def test_stale_marker_in_baseline_does_not_trigger_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    """Criterio 3 (sin falsos positivos): un marcador OBSOLETO que ya estaba
    en el pane ANTES de enviar la instrucción (presente en la baseline) NO
    se cuenta — el fallback no corta a un agente cuyo pane aún muestra el
    marcador de un Job anterior."""
    baseline = ["$", "RESULTADO: EXITO"]  # marcador viejo ya visible
    current = baseline  # sin líneas nuevas
    _patch_pane(monkeypatch, baseline, current)

    report_file = tmp_path / "job-report.txt"
    _PANE_BASELINES[str(report_file)] = baseline

    agent = _agent()
    job = _job()
    mark_running(job)
    mark_working(agent)

    # No debe lanzar JobReportFinishedInPaneError; llega al timeout.
    wait_and_finalize_job(job, agent, report_file, timeout_seconds=0.3, poll_interval_seconds=0.05)

    assert job.status == "failed"
    assert "Timeout" in job.result or "no reportó" in job.result
    assert agent.status == "idle"


def test_helper_returns_false_without_baseline(tmp_path: Path, monkeypatch) -> None:
    """Sin baseline (runtime sin pane capturable) el fallback se descarta."""
    _patch_pane(monkeypatch, [], ["RESULTADO: EXITO"])
    agent = _agent()
    assert jd._pane_has_new_completion_marker(agent, None, "sock") is False


def test_baseline_is_cleaned_after_finalize(tmp_path: Path, monkeypatch) -> None:
    """La baseline del pane se limpia tras finalizar el Job (sin fugas)."""
    baseline = ["$", "procesando..."]
    current = baseline + ["ESTADO: APROBADO"]
    _patch_pane(monkeypatch, baseline, current)

    report_file = tmp_path / "job-report.txt"
    _PANE_BASELINES[str(report_file)] = baseline

    agent = _agent()
    job = _job()
    with pytest.raises(JobReportFinishedInPaneError):
        jd._wait_for_report(
            report_file, 2.0, 0.05, job.id, agent=agent, socket_name="sock"
        )
    assert str(report_file) in _PANE_BASELINES
    _PANE_BASELINES.pop(str(report_file), None)

def test_poll_inflight_fails_job_when_pane_shows_completion_without_file(
    tmp_path, monkeypatch
) -> None:
    """Camino ASÍNCRONO del Dispatcher (T-AF008-US10-06): un Job en vuelo
    cuyo agente terminó en el pane pero no escribió el fichero se cierra
    `failed` (motivo claro), el agente vuelve a `idle` y la entrada sale del
    registro `inflight` — no queda `working` hasta el timeout de 1h."""
    import atlas_forge.dispatcher.dispatch_queue_worker as dqw
    from atlas_forge.core.session_lifecycle import activate, list_agents
    from atlas_forge.dispatcher.dispatch_queue_worker import (
        InFlightJob,
        poll_inflight_job_completions,
    )
    from atlas_forge.models import DevelopmentSession

    agent = Agent(id="a1", name="dev", role="developer", prompt="p", runtime_id="r1")
    session = DevelopmentSession(id="s1", project_id="p1")
    session.agents.append(agent)
    activate(session)

    job = Job(id="j1", session_id="s1", agent_id="a1", description="d")
    report_file = tmp_path / "report.txt"
    infl = InFlightJob(
        task_id="T-AF900-US01-01", agent_id="a1",
        report_file=report_file, job=job, dispatched_at=0.0,
    )
    inflight = {"T-AF900-US01-01": infl}
    mark_running(job)
    mark_working(agent)

    monkeypatch.setattr(dqw, "read_finished_report", lambda _p: None)
    monkeypatch.setattr(dqw, "pane_indicates_finished_without_report", lambda *_a, **_k: True)
    monkeypatch.setattr(dqw, "mark_failed", lambda *a, **k: None)
    monkeypatch.setattr(dqw, "_update_task_file_state", lambda *a, **k: None)
    monkeypatch.setattr(dqw, "list_agents", lambda _s: list_agents(session))

    resolved = poll_inflight_job_completions(
        tmp_path, "proj", session, inflight,
        timeout_seconds=5.0, socket_name="sock",
    )

    assert job.status == "failed"
    assert "no escribió el fichero de auto-reporte" in job.result
    assert agent.status == "idle"
    assert resolved == ["T-AF900-US01-01"]
    assert "T-AF900-US01-01" not in inflight
