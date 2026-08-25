"""Tests deterministas del modo autónomo del Dispatcher (T-AF023-US03-02) —
escalado por demanda, liberación segura, configuración y no-saturación.
Sin tmux real: se inyectan `launch`/`release` como mocks y se usan
`Agent`/`DevelopmentSession` sintéticos."""

from dataclasses import dataclass, field

import pytest

from atlas_forge.dispatcher.autonomous_scaling import (
    AutonomousConfig,
    RoleScaleConfig,
    autonomous_scale,
    compute_desired_agent_count,
    config_from_preferences,
    count_pending,
    select_agents_to_release,
)
from atlas_forge.models import Agent


@dataclass
class _Entry:
    task_id: str
    status: str


@dataclass
class _Session:
    agents: list = field(default_factory=list)


def _agent(role: str, status: str = "idle", persistent: bool = False, _id: str | None = None) -> Agent:
    return Agent(
        id=_id or f"{role}-{abs(hash((role, status, persistent)))%10000}",
        name=f"{role}-x", role=role, prompt="", runtime_id="r",
        status=status, persistent=persistent,
    )


# ── compute_desired_agent_count ──

def test_compute_desired_escala_con_la_demanda():
    cfg = RoleScaleConfig(min=0, max=3, tasks_per_agent=3)
    # 0 pendientes -> min (0); 1-3 -> 1; 4-6 -> 2; 7+ -> max 3.
    assert compute_desired_agent_count(0, cfg) == 0
    assert compute_desired_agent_count(1, cfg) == 1
    assert compute_desired_agent_count(3, cfg) == 1
    assert compute_desired_agent_count(4, cfg) == 2
    assert compute_desired_agent_count(7, cfg) == 3
    assert compute_desired_agent_count(100, cfg) == 3  # tope en max


def test_compute_desired_respeta_minimo():
    cfg = RoleScaleConfig(min=1, max=3, tasks_per_agent=3)
    assert compute_desired_agent_count(0, cfg) == 1  # no baja del mínimo


def test_config_invalida_rechazada():
    with pytest.raises(ValueError):
        RoleScaleConfig(min=4, max=3)  # min > max
    with pytest.raises(ValueError):
        AutonomousConfig(max_agents_total=2, roles={"developer": RoleScaleConfig(max=3)})
    with pytest.raises(ValueError):
        RoleScaleConfig(tasks_per_agent=0)


# ── select_agents_to_release ──

def test_release_solo_excedente_idle_no_persistente_no_retenido():
    ags = [
        _agent("developer", "idle", False, _id="d1"),
        _agent("developer", "idle", False, _id="d2"),
        _agent("developer", "idle", False, _id="d3"),
        _agent("developer", "working", False, _id="d4"),  # trabajando, no liberable
        _agent("arquitecto", "idle", True, _id="a1"),       # persistente, nunca
    ]
    # desired=1 -> liberar 1 excedente (d1) de los idle no retenidos.
    to_release = select_agents_to_release(
        ags, role="developer", desired=1, retained_agent_ids={"d2"}, inflight_agent_ids=set()
    )
    assert [a.id for a in to_release] == ["d1"]
    # Nunca libera persistentes.
    assert all(not a.persistent for a in to_release)


def test_release_no_libera_retenido_ni_en_vuelo():
    ags = [
        _agent("developer", "idle", False, _id="d1"),
        _agent("developer", "idle", False, _id="d2"),
    ]
    # d1 retenido (IN_REVIEW -> redespacho por corrección) y d2 en vuelo: nada liberable.
    to_release = select_agents_to_release(
        ags, role="developer", desired=0,
        retained_agent_ids={"d1"}, inflight_agent_ids={"d2"},
    )
    assert to_release == []


def test_release_sin_excedente_no_hace_nada():
    ags = [_agent("developer", "idle", False, _id="d1")]
    assert select_agents_to_release(ags, role="developer", desired=1) == []


# ── count_pending ──

def test_count_pending_solo_cuenta_queued():
    entries = [_Entry("T-1", "queued"), _Entry("T-2", "dispatched"), _Entry("T-3", "queued")]
    assert count_pending(entries) == 2


# ── autonomous_scale (con launch/release inyectados) ──

def _session_with(*agents):
    return _Session(agents=list(agents))


def test_autonomous_scale_lanza_segun_demanda_y_no_satura():
    session = _session_with()
    launched = []

    def launch(**kw):
        launched.append(kw["role"])
        session.agents.append(_agent(kw["role"], "idle", False))

    def release(agent, sess):
        sess.agents.remove(agent)

    config = config_from_preferences({
        "enabled": True,
        "roles": {"developer": {"min": 0, "max": 2, "tasks_per_agent": 1}},
        "max_agents_total": 3,
    })
    # 5 Tasks, tasks_per_agent=1, max=2 -> desired 2.
    result = autonomous_scale(
        session, config=config, pending=5, agents=list(session.agents),
        project_path="/p", socket_name="s", launch=launch, release=release,
    )
    assert launched == ["developer", "developer"]
    assert result["launched"] == ["developer", "developer"]
    assert len(session.agents) <= config.max_agents_total  # no satura


def test_autonomous_scale_respeta_limite_de_saturacion_total():
    # Ya hay 1 tester + 1 developer (total 2) y `max_agents_total=2`: aunque
    # la demanda pida más developers, no se lanza ninguno (no satura).
    session = _session_with(
        _agent("tester", "idle", False, _id="t1"),
        _agent("developer", "idle", False, _id="d1"),
    )
    launched = []

    def launch(**kw):
        launched.append(kw["role"])

    config = config_from_preferences({
        "enabled": True,
        "roles": {"developer": {"min": 0, "max": 2, "tasks_per_agent": 1}},
        "max_agents_total": 2,
    })
    autonomous_scale(
        session, config=config, pending=10, agents=list(session.agents),
        project_path="/p", socket_name="s", launch=launch, release=lambda a, s: None,
    )
    assert launched == []  # el límite total (ya 2 activos) impide lanzar


def test_autonomous_scale_libera_excedente_cuando_no_hay_demanda():
    session = _session_with(
        _agent("developer", "idle", False, _id="d1"),
        _agent("developer", "idle", False, _id="d2"),
    )
    released = []

    def release(agent, sess):
        released.append(agent.id)
        sess.agents.remove(agent)

    config = config_from_preferences({
        "enabled": True,
        "roles": {"developer": {"min": 0, "max": 3, "tasks_per_agent": 3}},
        "max_agents_total": 6,
    })
    # Sin demanda (pending=0) -> desired 0 -> libera ambos.
    result = autonomous_scale(
        session, config=config, pending=0, agents=list(session.agents),
        project_path="/p", socket_name="s",
        launch=lambda **kw: None, release=release,
    )
    assert result["released"] == ["d1", "d2"]
    assert session.agents == []


def test_autonomous_scale_no_libera_persistente_ni_retenido():
    arquit = _agent("arquitecto", "idle", True, _id="a1")
    dev_ret = _agent("developer", "idle", False, _id="d_ret")
    session = _session_with(arquit, dev_ret, _agent("developer", "idle", False, _id="d_free"))
    released = []

    def release(agent, sess):
        released.append(agent.id)
        sess.agents.remove(agent)

    config = config_from_preferences({
        "enabled": True,
        "roles": {"developer": {"min": 0, "max": 3, "tasks_per_agent": 3}},
        "max_agents_total": 6,
    })
    result = autonomous_scale(
        session, config=config, pending=0, agents=list(session.agents),
        project_path="/p", socket_name="s",
        retained_agent_ids={"d_ret"}, inflight_agent_ids=set(),
        launch=lambda **kw: None, release=release,
    )
    # Libera solo el excedente libre (d_free); no al persistente ni al retenido.
    assert result["released"] == ["d_free"]
    assert "a1" not in result["released"]
    assert "d_ret" not in result["released"]


def test_autonomous_scale_deshabilitado_no_hace_nada():
    session = _session_with(_agent("developer", "idle", False, _id="d1"))
    config = config_from_preferences({"enabled": False})
    result = autonomous_scale(
        session, config=config, pending=10, agents=list(session.agents),
        project_path="/p", socket_name="s",
        launch=lambda **kw: (_ for _ in ()).throw(AssertionError("no debe lanzar")),
        release=lambda a, s: (_ for _ in ()).throw(AssertionError("no debe liberar")),
    )
    assert result == {"launched": [], "released": []}