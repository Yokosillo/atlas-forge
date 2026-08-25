"""Tests deterministas del watcher de muerte inesperada de runtime
(T-AF004-US04-01, US-AF004-04). Sin tmux real: se inyecta una fuente de
liveness falsa (`alive_check`) para simular la muerte del runtime."""

from dataclasses import dataclass, field

from atlas_forge.agents.runtime_death_watcher import (
    RuntimeDeathWatcher,
    run_runtime_death_cycle,
)
from atlas_forge.models import Agent, DevelopmentSession


@dataclass
class _Session:
    agents: list = field(default_factory=list)


def _agent(_id: str, role: str = "developer", status: str = "idle") -> Agent:
    return Agent(
        id=_id, name=_id, role=role, prompt="", runtime_id="r", status=status
    )


def test_agente_con_runtime_muerto_se_marca_unavailable():
    session = _Session(agents=[_agent("a1"), _agent("a2")])
    # a1 está muerto (alive=False), a2 vivo.
    detected = run_runtime_death_cycle(
        session, alive_check=lambda agent, _sn: agent.id != "a1"
    )
    assert detected == ["a1"]
    by_id = {a.id: a for a in session.agents}
    assert by_id["a1"].status == "unavailable"
    assert by_id["a2"].status == "idle"


def test_agente_stopped_nunca_se_reporta_caido():
    session = _Session(agents=[_agent("a1", status="stopped")])
    # Aunque alive=False (muerte), un agente `stopped` (parada intencional)
    # no se marca unavailable.
    detected = run_runtime_death_cycle(
        session, alive_check=lambda agent, _sn: False
    )
    assert detected == []
    assert session.agents[0].status == "stopped"


def test_agente_unavailable_no_se_vuelve_a_tocar():
    session = _Session(agents=[_agent("a1", status="unavailable")])
    detected = run_runtime_death_cycle(
        session, alive_check=lambda agent, _sn: False
    )
    assert detected == []
    assert session.agents[0].status == "unavailable"


def test_agente_vivo_no_se_toca():
    session = _Session(agents=[_agent("a1"), _agent("a2")])
    detected = run_runtime_death_cycle(
        session, alive_check=lambda agent, _sn: True
    )
    assert detected == []
    assert all(a.status == "idle" for a in session.agents)


def test_watcher_run_once_sincrono_usa_liveness_inyectada():
    session = _Session(agents=[_agent("a1"), _agent("a2", status="stopped")])
    watcher = RuntimeDeathWatcher(
        session, alive_check=lambda agent, _sn: agent.id != "a1"
    )
    detected = watcher.run_once()
    assert detected == ["a1"]
    by_id = {a.id: a for a in session.agents}
    assert by_id["a1"].status == "unavailable"
    assert by_id["a2"].status == "stopped"  # intocada


def test_watcher_start_stop_no_lanza_por_agentes_vivos():
    # Con un session real (DevelopmentSession) y alive_check que dice vivo,
    # arrancar y parar el hilo daemon no debe lanzar ni marcar nada.
    session = DevelopmentSession(id="s", project_id="p", status="active",
                                 agents=[_agent("a1")])
    watcher = RuntimeDeathWatcher(
        session, poll_interval_seconds=0.01, alive_check=lambda a, s: True
    )
    watcher.start()
    watcher.stop(timeout=2.0)
    assert session.agents[0].status == "idle"

# ── T-AF004-US04-04: recuperación del agente al volver el runtime ──

def test_agente_unavailable_vuelve_a_idle_cuando_el_runtime_se_recupera():
    session = _Session(agents=[_agent("a1", status="unavailable")])
    # El runtime vuelve a estar vivo (alive=True) -> el agente se recupera.
    changed = run_runtime_death_cycle(
        session, alive_check=lambda agent, _sn: True
    )
    assert changed == ["a1"]
    assert session.agents[0].status == "idle"


def test_agente_unavailable_permanece_si_el_runtime_sigue_caido():
    session = _Session(agents=[_agent("a1", status="unavailable")])
    changed = run_runtime_death_cycle(
        session, alive_check=lambda agent, _sn: False
    )
    assert changed == []
    assert session.agents[0].status == "unavailable"


def test_ciclo_detecta_muerte_y_recuperacion_en_la_misma_corrida():
    session = _Session(agents=[_agent("a1", status="idle"), _agent("a2", status="unavailable")])
    # a1 muere (alive=False), a2 se recupera (alive=True).
    changed = run_runtime_death_cycle(
        session, alive_check=lambda agent, _sn: agent.id == "a2"
    )
    assert sorted(changed) == ["a1", "a2"]
    by_id = {a.id: a for a in session.agents}
    assert by_id["a1"].status == "unavailable"
    assert by_id["a2"].status == "idle"


def test_agente_stopped_no_se_recupera_ni_se_marca_unavailable():
    session = _Session(agents=[_agent("a1", status="stopped")])
    changed = run_runtime_death_cycle(
        session, alive_check=lambda agent, _sn: True
    )
    assert changed == []
    assert session.agents[0].status == "stopped"


# ── T-AF004-US04-03: notificación visible al agotar los reintentos ──

def test_notifica_failed_una_vez_al_agotar_reintentos():
    session = _Session(agents=[_agent("a1")])
    watcher = RuntimeDeathWatcher(
        session,
        alive_check=lambda agent, _sn: False,   # runtime siempre muerto
        relaunch=lambda agent, _sn: False,      # el relanzamiento siempre falla
        max_retries=3,
    )
    # Ciclos con runtime muerto: agota los 3 reintentos.
    watcher.run_once()  # 1er intento fallido (recovering)
    watcher.run_once()  # 2º
    watcher.run_once()  # 3º -> failed + notificación
    events = watcher.failed_events()
    assert len(events) == 1, "debe notificarse una vez al agotar el límite: " + repr(events)
    assert events[0]["agent_id"] == "a1"
    assert events[0]["error"]
    # Ciclos posteriores NO re-notifican (no bucle infinito de avisos).
    watcher.run_once()
    watcher.run_once()
    assert len(watcher.failed_events()) == 1


def test_no_notifica_si_el_runtime_se_recupera():
    session = _Session(agents=[_agent("a1")])
    alive = {"vivo": True}
    watcher = RuntimeDeathWatcher(
        session,
        alive_check=lambda agent, _sn: alive["vivo"],
        relaunch=lambda agent, _sn: True,
        max_retries=3,
    )
    # Runtime vivo -> no notifica nada.
    watcher.run_once()
    assert watcher.failed_events() == []


def test_runtime_failed_expone_estado_observable_por_watcher():
    session = _Session(agents=[_agent("a1")])
    watcher = RuntimeDeathWatcher(
        session,
        alive_check=lambda agent, _sn: False,
        relaunch=lambda agent, _sn: False,
        max_retries=2,
    )
    watcher.run_once()
    watcher.run_once()
    events = watcher.failed_events()
    assert len(events) == 1
    assert events[0]["agent_id"] == "a1"
    assert "ts" in events[0]
    # El agente queda `unavailable` (visible en GET /agents).
    assert session.agents[0].status == "unavailable"


def test_notify_inyectado_es_invocado_con_agente_y_error():
    session = _Session(agents=[_agent("a1")])
    captured = []
    watcher = RuntimeDeathWatcher(
        session,
        alive_check=lambda agent, _sn: False,
        relaunch=lambda agent, _sn: False,
        max_retries=1,
        notify=lambda agent_id, error: captured.append((agent_id, error)),
    )
    watcher.run_once()
    assert len(captured) == 1
    assert captured[0][0] == "a1"
    assert captured[0][1]


# ── T-AF004-US04-05: intervalo de polling configurable ──

def test_intervalo_de_polling_configurable_no_hardcodeado():
    session = _Session(agents=[_agent("a1")])
    watcher = RuntimeDeathWatcher(
        session, poll_interval_seconds=7.5, alive_check=lambda a, s: True
    )
    assert watcher.poll_interval_seconds() == 7.5
    # Default documentado también es consultable.
    from atlas_forge.agents.runtime_death_watcher import DEFAULT_POLL_INTERVAL_SECONDS
    default_watcher = RuntimeDeathWatcher(session)
    assert default_watcher.poll_interval_seconds() == DEFAULT_POLL_INTERVAL_SECONDS
