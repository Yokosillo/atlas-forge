"""Tests deterministas del watcher de auto-liberación "working sin Job en
vuelo" (T-AF008-US18-04, US-AF008-18). Sin tmux: se construye una sesión
falsa con `Agent` reales, se siembra `dispatch_queue.json` y ficheros de
Task sintéticos, y se ejecuta `run_stuck_working_cycle`/`run_once` con
`now` y umbral inyectados.

Criterios cubiertos:
1. Existe la regla determinista: agente `working` sin entrada en la señal de
   vuelo y con `last_command_at` congelado más del umbral -> `failed` con
   motivo consultable en `failure_reason`.
2. Su Task (entrada `dispatched` con su `agent_id`) vuelve a `TO_DEVELOP`
   y la entrada de la cola queda `failed` (sin residuo `dispatched`).
3. Un agente `working` CON Job en vuelo legítimo NO se libera (sin falsos
   positivos).
4. La regla es configurable (`threshold_seconds`) y vive en un ciclo
   periódico (método `run_once` del `StuckWorkingWatcher`).
6. Tests deterministas sin tmux (este fichero).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from atlas_forge.agents.lifecycle import (
    InvalidAgentTransitionError,
    mark_failed,
    mark_idle,
    mark_working,
)
from atlas_forge.agents.runtime_death_watcher import run_runtime_death_cycle
from atlas_forge.agents.stuck_working_watcher import (
    DEFAULT_STUCK_WORKING_THRESHOLD_SECONDS,
    StuckWorkingWatcher,
    run_stuck_working_cycle,
)
from atlas_forge.dispatcher.dispatch_queue import (
    STATUS_DISPATCHED,
    enqueue_task,
    get_queue,
    mark_dispatched,
)
from atlas_forge.dispatcher.dispatch_queue_worker import (
    DispatchQueueWorker,
    InFlightJob,
    InFlightReviewJob,
)
from atlas_forge.models import Agent, Job

NOW = datetime(2026, 8, 24, 12, 0, 0, tzinfo=timezone.utc)


@dataclass
class _Session:
    agents: list = field(default_factory=list)


def _agent(_id: str, status: str = "working", last_command_at: str | None = None) -> Agent:
    return Agent(
        id=_id,
        name=_id,
        role="developer",
        prompt="",
        runtime_id="r",
        status=status,
        last_command_at=last_command_at if last_command_at is not None else "",
    )


STALE = "2026-08-24T00:00:00+00:00"  # 12h antes de NOW


def _write_task(project_root: Path, task_id: str, state: str) -> Path:
    tasks_dir = project_root / "02-backlog" / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    path = tasks_dir / f"{task_id}-test.md"
    path.write_text(
        "---\n"
        f"id: {task_id}\ntype: task\ntitle: {task_id}\nstate: {state}\n"
        "dependencies: []\nepic: AF-900\npriority: Alta\n"
        "---\n\n## Objetivo\n\nO.\n",
        encoding="utf-8",
    )
    return path


def _seed_dispatched(project_root: Path, project_name: str, task_id: str, agent_id: str) -> None:
    enqueue_task(project_root, project_name, task_id=task_id, us_id="US-AF900-01", priority="Alta")
    mark_dispatched(project_root, project_name, task_id, agent_id=agent_id, agent_name=agent_id)


def _state_of(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("state:"):
            return line.split(":", 1)[1].strip()
    return ""


# ---------------------------------------------------------------------------
# Criterios 1 y 2: working sin Job en vuelo y congelado -> failed + motivo
# consultable + Task a TO_DEVELOP (+ entrada de cola sin residuo).
# ---------------------------------------------------------------------------


def test_working_sin_job_y_congelado_se_libera_con_task_a_to_develop(tmp_path: Path):
    project_root = tmp_path / "p"
    task_path = _write_task(project_root, "T-AF900-01", "IN_PROGRESS")
    session = _Session(agents=[_agent("a1", last_command_at=STALE)])
    _seed_dispatched(project_root, "p", "T-AF900-01", "a1")

    released = run_stuck_working_cycle(
        session, set(),
        project_root=project_root, project_name="p",
        threshold_seconds=60.0, now=NOW,
    )

    assert released == [{"agent_id": "a1", "task_ids": ["T-AF900-01"]}]
    agent = session.agents[0]
    assert agent.status == "failed", "El agente debe marcarse failed."
    assert "working sin Job en vuelo" in (agent.failure_reason or "")
    # Criterio 2: la Task vuelve a TO_DEVELOP (re-despachable) sin bloqueo.
    assert _state_of(task_path) == "TO_DEVELOP"
    # Criterio 5 de la US: la entrada dispatched queda clara (failed).
    entry = next(e for e in get_queue(project_root, "p") if e.task_id == "T-AF900-01")
    assert entry.status == "failed"


def test_working_sin_job_y_sin_task_asociada_se_libera_solo_su_estado(tmp_path: Path):
    session = _Session(agents=[_agent("a1", last_command_at=STALE)])
    released = run_stuck_working_cycle(
        session, set(),
        project_root=tmp_path, project_name="p",
        threshold_seconds=60.0, now=NOW,
    )
    assert released == [{"agent_id": "a1", "task_ids": []}]
    assert session.agents[0].status == "failed"


# ---------------------------------------------------------------------------
# Criterio 3: un agente `working` CON Job en vuelo legítimo NO se libera.
# ---------------------------------------------------------------------------


def test_working_con_job_en_vuelo_legitimo_no_se_libera():
    session = _Session(agents=[_agent("a1", last_command_at=STALE)])
    released = run_stuck_working_cycle(
        session, {"a1"}, threshold_seconds=60.0, now=NOW,
    )
    assert released == []
    assert session.agents[0].status == "working"


# ---------------------------------------------------------------------------
# Criterio 1/4: los trabajadores legítimos y recientes tampoco se liberan;
# el umbral es configurable; sin evidencia temporal no se actúa.
# ---------------------------------------------------------------------------


def test_working_reciente_no_se_libera():
    recent = NOW.isoformat()
    session = _Session(agents=[_agent("a1", last_command_at=recent)])
    released = run_stuck_working_cycle(
        session, set(), threshold_seconds=60.0, now=NOW,
    )
    assert released == []
    assert session.agents[0].status == "working"


def test_umbral_configurable_bloquea_o_libera_segun_el_valor():
    # Con un umbral enorme, el agente congelado 12h sigue sin liberarse.
    session = _Session(agents=[_agent("a1", last_command_at=STALE)])
    released = run_stuck_working_cycle(
        session, set(), threshold_seconds=10 * 24 * 3600, now=NOW,
    )
    assert released == []
    assert session.agents[0].status == "working"
    # Con un umbral inferior al retraso, se libera.
    session2 = _Session(agents=[_agent("a1", last_command_at=STALE)])
    released2 = run_stuck_working_cycle(
        session2, set(), threshold_seconds=60.0, now=NOW,
    )
    assert released2 == [{"agent_id": "a1", "task_ids": []}]


def test_sin_evidencia_temporal_no_se_libera():
    session = _Session(agents=[_agent("a1", last_command_at="")])
    released = run_stuck_working_cycle(session, set(), threshold_seconds=1.0, now=NOW)
    assert released == []
    assert session.agents[0].status == "working"


def test_no_working_no_se_toca():
    session = _Session(
        agents=[
            _agent("a1", status="idle", last_command_at=STALE),
            _agent("a2", status="stopped", last_command_at=STALE),
            _agent("a3", status="unavailable", last_command_at=STALE),
            _agent("a4", status="limited", last_command_at=STALE),
        ]
    )
    released = run_stuck_working_cycle(session, set(), threshold_seconds=1.0, now=NOW)
    assert released == []
    assert [a.status for a in session.agents] == ["idle", "stopped", "unavailable", "limited"]


# ---------------------------------------------------------------------------
# Ciclo de vida del estado `failed`: motivo consultable, limpieza al volver
# a `idle` y recuperación automática por el RuntimeDeathWatcher (runtime vivo
# -> failed vuelve a idle). Criterio 1 (motivo consultable) + auto-reparación.
# ---------------------------------------------------------------------------


def test_mark_failed_registra_motivo_consultable():
    agent = Agent(id="a1", name="a1", role="developer", prompt="", runtime_id="r", status="working")
    mark_failed(agent, "working sin Job en vuelo: ...")
    assert agent.status == "failed"
    assert agent.failure_reason == "working sin Job en vuelo: ..."


def test_mark_idle_limpia_el_motivo_de_fallo():
    agent = Agent(id="a1", name="a1", role="developer", prompt="", runtime_id="r", status="working")
    mark_failed(agent, "motivo")
    mark_idle(agent)
    assert agent.status == "idle"
    assert agent.failure_reason is None


def test_failed_no_es_transicion_desde_idle_sin_marcar_trabajo():
    agent = Agent(id="a1", name="a1", role="developer", prompt="", runtime_id="r", status="idle")
    mark_working(agent)
    mark_failed(agent, "ok")  # working -> failed permitido.
    assert agent.status == "failed"


def test_runtime_death_watcher_recupera_failed_a_idle_si_runtime_vivo():
    session = _Session(agents=[_agent("a1", status="failed", last_command_at=STALE)])
    detected = run_runtime_death_cycle(session, alive_check=lambda _a, _s: True)
    assert detected == ["a1"]
    assert session.agents[0].status == "idle"
    assert session.agents[0].failure_reason is None


# ---------------------------------------------------------------------------
# Worker: la señal de vuelo para el watcher es la unión de sus registros.
# ---------------------------------------------------------------------------


def _job(_id: str, agent_id: str) -> Job:
    return Job(id=_id, session_id="s", agent_id=agent_id, description="d", status="running")


def _worker(tmp_path: Path) -> DispatchQueueWorker:
    return DispatchQueueWorker(tmp_path, "p", _Session(agents=[]))


def test_worker_get_inflight_agent_ids_es_union_de_registros(tmp_path: Path):
    worker = _worker(tmp_path)
    worker._inflight["j1"] = InFlightJob(
        task_id="T-AF900-01", agent_id="a1",
        report_file=tmp_path / "r1", job=_job("j1", "a1"), dispatched_at=0.0,
    )
    worker._inflight_review["T-AF900-02"] = InFlightReviewJob(
        task_id="T-AF900-02", tester_agent_id="a2",
        report_file=tmp_path / "r2", job=_job("j2", "a2"), dispatched_at=0.0,
        task_item=None,
    )
    assert worker.get_inflight_agent_ids() == {"a1", "a2"}


def test_worker_get_inflight_agent_ids_vacio_sin_registros(tmp_path: Path):
    assert _worker(tmp_path).get_inflight_agent_ids() == set()


# ---------------------------------------------------------------------------
# El watcher como ciclo periódico (patrón SessionLimitWatcher/RuntimeDeathWatcher):
# `run_once` con la señal de vuelo viva, y el default del umbral.
# ---------------------------------------------------------------------------


def test_stuck_working_watcher_run_once_y_umbral_configurado(tmp_path: Path):
    session = _Session(agents=[_agent("a1", last_command_at=STALE)])
    project_root = tmp_path / "p"
    _write_task(project_root, "T-AF900-01", "IN_PROGRESS")
    _seed_dispatched(project_root, "p", "T-AF900-01", "a1")

    watcher = StuckWorkingWatcher(
        session,
        inflight_agent_ids_provider=lambda: set(),
        threshold_seconds=60.0,
        project_root=project_root,
        project_name="p",
    )
    assert watcher.threshold_seconds() == 60.0
    released = watcher.run_once()
    assert released == [{"agent_id": "a1", "task_ids": ["T-AF900-01"]}]
    assert session.agents[0].status == "failed"


def test_umbral_por_defecto_documentado():
    assert DEFAULT_STUCK_WORKING_THRESHOLD_SECONDS == 1800.0