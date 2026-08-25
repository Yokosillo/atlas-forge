"""Tests deterministas de T-AF004-US04-02 (US-AF004-04 · "Detectar y
recuperar automáticamente un runtime caído"): la decisión de relanzamiento
automático con límite de reintentos configurable, reutilizando
`RecoveryRetryTracker`. Sin tmux real: la liveness y el relanzamiento se
inyectan.

Cubre los criterios de aceptación:
- Ante un runtime caído se intenta el relanzamiento automáticamente.
- El número de reintentos está limitado y es configurable (default 3).
- Un relanzamiento con éxito (runtime vuelve a vivo) resetea el contador.
- Al superar el límite se deja de reintentar y el estado pasa a `failed`
  (sin descartar al agente en silencio).
"""

from __future__ import annotations

from atlas_forge.agents.recovery import (
    RETRY_STATUS_FAILED,
    RETRY_STATUS_OK,
    RETRY_STATUS_RECOVERING,
)
from atlas_forge.agents.runtime_death_watcher import run_runtime_death_cycle
from atlas_forge.agents.runtime_relaunch import (
    RuntimeRelaunchTrackers,
    decide_auto_relaunch,
    max_retries_of,
)
from atlas_forge.models import Agent, DevelopmentSession


def _agent(_id: str, status: str = "idle", role: str = "developer") -> Agent:
    return Agent(id=_id, name=_id, role=role, prompt="", runtime_id="r", status=status)


def test_default_max_retries_es_configurable() -> None:
    assert RuntimeRelaunchTrackers().max_retries == 3
    assert max_retries_of(RuntimeRelaunchTrackers(max_retries=5)) == 5


def test_runtime_caido_intenta_relaunch_y_reporta_recovering() -> None:
    trackers = RuntimeRelaunchTrackers(max_retries=3)
    relaunched: list[int] = []

    status = decide_auto_relaunch(
        "a1", alive=False, trackers=trackers,
        relaunch=lambda: relaunched.append(1) or True,
    )

    assert len(relaunched) == 1  # se intentó el relanzamiento
    assert status == RETRY_STATUS_RECOVERING
    assert trackers.tracker_for("a1").consecutive_retries == 1


def test_relanzamiento_con_exito_resetea_el_contador() -> None:
    trackers = RuntimeRelaunchTrackers(max_retries=3)
    relaunched: list[int] = []
    relaunch = lambda: relaunched.append(1) or True

    # Dos ciclos fallidos (runtime muerto) -> 2 reintentos.
    decide_auto_relaunch("a1", alive=False, trackers=trackers, relaunch=relaunch)
    decide_auto_relaunch("a1", alive=False, trackers=trackers, relaunch=relaunch)
    assert trackers.tracker_for("a1").consecutive_retries == 2

    # El runtime vuelve a vivo -> contador reseteado a `ok`.
    status = decide_auto_relaunch("a1", alive=True, trackers=trackers)
    assert status == RETRY_STATUS_OK
    assert trackers.tracker_for("a1").consecutive_retries == 0


def test_superado_el_limite_se_deja_de_reintentar_y_pasa_a_failed() -> None:
    trackers = RuntimeRelaunchTrackers(max_retries=3)
    relaunched: list[int] = []
    exhausted: list[int] = []
    relaunch = lambda: relaunched.append(1) or True

    # 3 ciclos con runtime muerto -> 3 relanzamientos; el tercero agota.
    for _ in range(3):
        status = decide_auto_relaunch(
            "a1", alive=False, trackers=trackers,
            relaunch=relaunch, on_failed=lambda: exhausted.append(1),
        )
    assert len(relaunched) == 3
    assert status == RETRY_STATUS_FAILED
    assert trackers.tracker_for("a1").should_retry() is False

    # Ciclo extra: límite superado -> NO se relanza y se invoca `on_failed`.
    status = decide_auto_relaunch(
        "a1", alive=False, trackers=trackers,
        relaunch=relaunch, on_failed=lambda: exhausted.append(1),
    )
    assert status == RETRY_STATUS_FAILED
    assert len(relaunched) == 3  # sin reintento adicional
    assert len(exhausted) == 1  # se señala el agotamiento (no silencioso)


def test_ciclo_del_watcher_integrado_intenta_relaunch_y_marca_unavailable() -> None:
    """Integración: `run_runtime_death_cycle` con liveness inyectada intenta
    el relanzamiento del agente muerto y marca `unavailable`; el agente vivo
    resetea su contador."""
    session = DevelopmentSession(
        id="s", project_id="/tmp/proj", status="active",
        agents=[_agent("a1"), _agent("a2")],
    )
    relaunched: list[str] = []
    trackers = RuntimeRelaunchTrackers(max_retries=3)

    def relaunch(agent, _socket):
        relaunched.append(agent.id)
        return True

    changed = run_runtime_death_cycle(
        session, alive_check=lambda agent, _sn: agent.id != "a1",
        relaunch=relaunch, retry_policy=trackers,
    )

    assert changed == ["a1"]
    assert relaunched == ["a1"]  # se relanzó al caído
    by_id = {a.id: a for a in session.agents}
    assert by_id["a1"].status == "unavailable"  # visible, no descartado
    assert by_id["a2"].status == "idle"
    assert trackers.tracker_for("a1").consecutive_retries == 1


def test_ciclo_no_relanza_agente_stopped() -> None:
    session = DevelopmentSession(
        id="s", project_id="/tmp/proj", status="active",
        agents=[_agent("a1", status="stopped")],
    )
    relaunched: list[str] = []

    changed = run_runtime_death_cycle(
        session, alive_check=lambda _a, _sn: False,
        relaunch=lambda a, _sn: relaunched.append(a.id) or True,
        retry_policy=RuntimeRelaunchTrackers(),
    )

    assert changed == []
    assert relaunched == []
    assert session.agents[0].status == "stopped"  # parada intencional, intacta