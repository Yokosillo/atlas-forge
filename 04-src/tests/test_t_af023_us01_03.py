"""T-AF023-US01-03: tests deterministas de la detección de cuelgue
(T-AF023-US01-01) y de su exposición consultable (T-AF023-US01-02), SIN
depender de tmux ni de procesos reales.

Cubre los criterios de US-AF023-01:
  1. detección: sin actividad -> colgado (varias lecturas sin cambio > umbral);
  2. sin falsos positivos: actividad espaciada pero real -> no colgado;
  3. umbral configurable con default documentado;
  4. estado colgado consultable (vivo/colgado/detenido) — expuesto por la API.

Los casos de la función pura usan la fixture `opencode_activity_sim.json`
(secuencias de timestamps simuladas, sin procesos reales); el caso de API
mockea el proveedor de actividad (`refresh_agent_supervision`).
"""

from __future__ import annotations

import json
from pathlib import Path

from atlas_forge.agents.inactivity import (
    DEFAULT_INACTIVITY_THRESHOLD_SECONDS,
    VERDICT_ALIVE,
    VERDICT_HUNG,
    VERDICT_PROCESSING,
    detect_agent_activity,
)
from atlas_forge.agents.supervision import compute_supervision_state

_FIXTURE = Path(__file__).parent / "fixtures" / "opencode_activity_sim.json"


def _fixture() -> dict:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


# ── Criterio 1: detección (sin actividad -> colgado) ─────────────────────


def test_t_af023_us01_03_frozen_activity_is_hung() -> None:
    f = _fixture()
    verdict = detect_agent_activity(
        f["frozen_history"],
        threshold_seconds=f["default_threshold_seconds"],
        now=f["now"],
    )
    assert verdict == VERDICT_HUNG

    # Y vía el estado de supervisión (compute_supervision_state) -> colgado.
    from atlas_forge.models import Agent

    agent = Agent(id="a", name="X", role="developer", prompt="p", runtime_id="r", status="working")
    state = compute_supervision_state(
        agent, f["frozen_history"],
        threshold_seconds=f["default_threshold_seconds"], now=f["now"],
    )
    assert state == "colgado"


# ── Criterio 2: sin falsos positivos (actividad espaciada pero real) ─────


def test_t_af023_us01_03_spaced_activity_is_not_hung() -> None:
    f = _fixture()
    # La última actividad es antigua (> umbral) pero AVANZÓ entre lecturas:
    # trabajo espaciado pero real -> nunca colgado (procesando/vivo).
    verdict = detect_agent_activity(
        f["spaced_history"],
        threshold_seconds=f["default_threshold_seconds"],
        now=f["now"],
    )
    assert verdict != VERDICT_HUNG


def test_t_af023_us01_03_recent_activity_is_alive() -> None:
    f = _fixture()
    verdict = detect_agent_activity(
        f["recent_history"],
        threshold_seconds=f["default_threshold_seconds"],
        now=f["now"],
    )
    assert verdict == VERDICT_ALIVE


# ── Criterio 3: umbral configurable + default documentado ─────────────────


def test_t_af023_us01_03_threshold_is_configurable() -> None:
    f = _fixture()
    # Con los mismos datos (frozen, now=1300 -> 300s sin actividad):
    # - umbral 120 -> colgado
    assert detect_agent_activity(f["frozen_history"], threshold_seconds=120.0, now=f["now"]) == VERDICT_HUNG
    # - umbral 400 (300 <= 400) -> no colgado (actividad "reciente" bajo ese umbral)
    assert detect_agent_activity(f["frozen_history"], threshold_seconds=400.0, now=f["now"]) != VERDICT_HUNG


def test_t_af023_us01_03_default_threshold_is_documented() -> None:
    # Criterio 3: el default está centralizado y documentado (120s, sesión de
    # origen) — no un valor hardcodeado disperso.
    assert DEFAULT_INACTIVITY_THRESHOLD_SECONDS == 120.0
    assert _fixture()["default_threshold_seconds"] == DEFAULT_INACTIVITY_THRESHOLD_SECONDS


def test_t_af023_us01_03_spaced_is_processing_not_hung() -> None:
    # El veredicto intermedio distingue "trabajo espaciado" (procesando) de
    # un cuelgue real, garantizando el criterio 2.
    f = _fixture()
    verdict = detect_agent_activity(f["spaced_history"], threshold_seconds=120.0, now=f["now"])
    assert verdict == VERDICT_PROCESSING


# ── Criterio 4: estado colgado consultable (exposición por API) ──────────


def _active_project_and_session(tmp_path, monkeypatch):
    import atlas_forge.api.routes as routes_module
    from atlas_forge.core import resolve_startup_session
    from atlas_forge.workspace import discover_projects, select_active_project

    workspace = tmp_path / "workspace"
    (workspace / "project-a" / ".git").mkdir(parents=True)
    state_dir = tmp_path / "state"
    discovered = discover_projects(workspace)
    select_active_project(discovered[0], discovered=discovered, state_dir=state_dir)
    monkeypatch.setattr(routes_module, "get_active_project", lambda **_kwargs: discovered[0])
    session = resolve_startup_session(workspace_root=workspace, state_dir=state_dir)
    assert session is not None
    return discovered[0], session


def test_t_af023_us01_03_api_exposes_hung_and_alive_supervision(
    tmp_path, monkeypatch,
) -> None:
    """Criterio 4: el estado `colgado` es consultable vía `GET /agents`
    (campo `supervision`), distinto de `vivo`. Proveedor de actividad
    mockeado (sin tmux real)."""
    import atlas_forge.api.routes as routes_module
    from atlas_forge.api import create_app
    from atlas_forge.models import Agent
    from fastapi.testclient import TestClient

    _project, session = _active_project_and_session(tmp_path, monkeypatch)
    hung = Agent(id="a-hung", name="Developer-1", role="developer", prompt="p", runtime_id="r")
    alive = Agent(id="a-alive", name="Developer-2", role="developer", prompt="p", runtime_id="r")
    session.agents.extend([hung, alive])

    def fake_refresh(agent, socket_name=None):
        agent.supervision_status = "colgado" if agent.id == "a-hung" else "vivo"
        return agent

    monkeypatch.setattr(routes_module, "refresh_agent_supervision", fake_refresh)
    client = TestClient(create_app())

    response = client.get("/agents")
    assert response.status_code == 200
    by_id = {a["id"]: a for a in response.json()}
    assert by_id["a-hung"]["supervision"] == "colgado"
    assert by_id["a-alive"]["supervision"] == "vivo"
