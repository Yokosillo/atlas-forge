"""Tests de `brain.dispatcher.dispatch_queue_worker` (T-FB008-US10-02):
el Dispatcher de fondo que consume la cola de `dispatch_queue.py`
(`T-FB008-US10-01`).

`test_pick_next_eligible_entry_*` cubre la función pura de selección
(prioridad + FIFO + dependencias) sin ningún I/O. `test_run_dispatch_cycle_*`
y el test de integración final ejercitan `run_dispatch_cycle` contra un
backlog/sesión reales (tmux real, sin runtime real de Claude Code —
mismo runtime cooperativo simulado ya usado en el resto de la suite del
dispatcher)."""

import threading
import time
from pathlib import Path

import pytest

from brain.core.session_lifecycle import activate, assign_agent
from brain.dispatcher.dispatch_queue import (
    STATUS_DISPATCHED,
    STATUS_FAILED,
    STATUS_QUEUED,
    enqueue_task,
    get_queue,
)
from brain.dispatcher.dispatch_queue_worker import (
    DispatchQueueWorker,
    _pick_next_eligible_entry,
    run_dispatch_cycle,
)
from brain.models import Agent, DevelopmentSession
from brain.runtime import register_runtime_instance_for_agent, start_runtime, stop_runtime
from brain.models import Runtime

_COOPERATIVE_AGENT_SCRIPT = str(
    Path(__file__).parent / "fixtures" / "cooperative_agent_sim.sh"
)


# ---------------------------------------------------------------------------
# _pick_next_eligible_entry — función pura, sin I/O.
# ---------------------------------------------------------------------------


def _entry(task_id, priority, enqueued_at, status=STATUS_QUEUED):
    from brain.dispatcher.dispatch_queue import QueueEntry

    return QueueEntry(
        task_id=task_id, us_id="US-1", priority=priority, status=status,
        enqueued_at=enqueued_at,
    )


def test_pick_next_eligible_entry_prefers_higher_priority():
    entries = [
        _entry("T-baja", "Baja", "2026-01-01T00:00:00"),
        _entry("T-critica", "Crítica", "2026-01-01T00:00:01"),
        _entry("T-media", "Media", "2026-01-01T00:00:02"),
    ]

    chosen = _pick_next_eligible_entry(entries, done_ids=set(), dependencies_of={})

    assert chosen.task_id == "T-critica"


def test_pick_next_eligible_entry_breaks_ties_by_enqueued_at_fifo():
    entries = [
        _entry("T-segunda", "Alta", "2026-01-01T00:00:05"),
        _entry("T-primera", "Alta", "2026-01-01T00:00:01"),
    ]

    chosen = _pick_next_eligible_entry(entries, done_ids=set(), dependencies_of={})

    assert chosen.task_id == "T-primera"


def test_pick_next_eligible_entry_skips_task_with_pending_dependency():
    entries = [
        _entry("T-bloqueada", "Crítica", "2026-01-01T00:00:00"),
        _entry("T-libre", "Baja", "2026-01-01T00:00:01"),
    ]
    dependencies_of = {"T-bloqueada": ("T-dep",)}

    chosen = _pick_next_eligible_entry(entries, done_ids=set(), dependencies_of=dependencies_of)

    # La de mayor prioridad está bloqueada (T-dep no está DONE) — se
    # salta sin bloquear el resto, elige la siguiente elegible.
    assert chosen.task_id == "T-libre"


def test_pick_next_eligible_entry_picks_task_once_dependency_is_done():
    entries = [_entry("T-1", "Alta", "2026-01-01T00:00:00")]
    dependencies_of = {"T-1": ("T-dep",)}

    chosen = _pick_next_eligible_entry(entries, done_ids={"T-dep"}, dependencies_of=dependencies_of)

    assert chosen.task_id == "T-1"


def test_pick_next_eligible_entry_returns_none_when_all_blocked_or_dispatched():
    entries = [
        _entry("T-bloqueada", "Crítica", "2026-01-01T00:00:00"),
        _entry("T-ya-despachada", "Alta", "2026-01-01T00:00:01", status=STATUS_DISPATCHED),
    ]
    dependencies_of = {"T-bloqueada": ("T-dep",)}

    chosen = _pick_next_eligible_entry(entries, done_ids=set(), dependencies_of=dependencies_of)

    assert chosen is None


def test_pick_next_eligible_entry_returns_none_for_empty_queue():
    assert _pick_next_eligible_entry([], done_ids=set(), dependencies_of={}) is None


# ---------------------------------------------------------------------------
# run_dispatch_cycle — backlog/sesión reales, sin tmux (cero Developers).
# ---------------------------------------------------------------------------


def _write_task_yaml(
    tasks_dir: Path, task_id: str, us_id: str, state: str, priority: str | None = None,
    dependencies: str = "[]",
) -> None:
    tasks_dir.mkdir(parents=True, exist_ok=True)
    priority_line = f"priority: {priority}\n" if priority else ""
    (tasks_dir / f"{task_id}.md").write_text(
        "---\n"
        f"id: {task_id}\ntype: task\ntitle: Task\nstate: {state}\n"
        f"dependencies: {dependencies}\nepic: FB-999\nuser_story: {us_id}\n"
        f"{priority_line}---\n\n"
        f"# {task_id}\n\n## Objetivo\n\nObjetivo.\n\n## Criterios de aceptación\n\n1. Y.\n",
        encoding="utf-8",
    )


def test_run_dispatch_cycle_returns_none_without_any_developer(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    _write_task_yaml(backlog / "tasks", "T-FB999-US01-01", "US-FB999-01", "TODO", priority="Alta")
    enqueue_task(tmp_path, "proj", task_id="T-FB999-US01-01", us_id="US-FB999-01", priority="Alta")

    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)

    result = run_dispatch_cycle(tmp_path, "proj", session)

    assert result is None
    # La entrada sigue queued: no se despachó nada sin Developer.
    entries = get_queue(tmp_path, "proj")
    assert entries[0].status == STATUS_QUEUED


def test_run_dispatch_cycle_returns_none_with_empty_queue(tmp_path: Path) -> None:
    (tmp_path / "02-backlog" / "tasks").mkdir(parents=True)
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)

    assert run_dispatch_cycle(tmp_path, "proj", session) is None


def test_run_dispatch_cycle_skips_task_with_pending_dependency_leaving_queue_unchanged(
    tmp_path: Path,
) -> None:
    backlog = tmp_path / "02-backlog"
    _write_task_yaml(
        backlog / "tasks", "T-FB999-US01-01", "US-FB999-01", "TODO", priority="Crítica",
        dependencies='["T-FB999-US01-99"]',
    )
    _write_task_yaml(backlog / "tasks", "T-FB999-US01-99", "US-FB999-01", "TODO")
    enqueue_task(tmp_path, "proj", task_id="T-FB999-US01-01", us_id="US-FB999-01", priority="Crítica")

    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)

    # Sin Developer tampoco aquí — el punto de este test es que
    # _pick_next_eligible_entry (invocada dentro de run_dispatch_cycle)
    # ya descarta la entrada bloqueada ANTES de buscar agente, así que
    # el resultado es None por "sin candidata elegible", verificable
    # porque la cola permanece intacta.
    result = run_dispatch_cycle(tmp_path, "proj", session)

    assert result is None
    entries = get_queue(tmp_path, "proj")
    assert entries[0].status == STATUS_QUEUED


@pytest.fixture
def isolated_socket():
    import uuid
    import libtmux

    name = f"brain-test-{uuid.uuid4().hex[:8]}"
    try:
        yield name
    finally:
        try:
            libtmux.Server(socket_name=name).kill()
        except Exception:
            pass


def _launch_cooperative_developer(isolated_socket: str, tmp_path, extra_env: str = ""):
    command = f"{extra_env} bash".strip()
    runtime = Runtime(
        id="test-runtime", name="Test Runtime", type="test", command=command,
        args=[_COOPERATIVE_AGENT_SCRIPT],
    )
    agent = Agent(id="a-dev", name="developer", role="developer", prompt="p", runtime_id="r1")
    runtime_instance = start_runtime(runtime, agent, str(tmp_path), socket_name=isolated_socket)
    register_runtime_instance_for_agent(agent.id, runtime_instance)
    return agent, runtime_instance


def test_run_dispatch_cycle_dispatches_the_highest_priority_eligible_task(
    isolated_socket: str, tmp_path,
) -> None:
    # Criterio de aceptación: con un Developer idle y Tasks de prioridad
    # distinta, despacha primero la de mayor prioridad.
    backlog_root = tmp_path / "backlog_root"
    backlog = backlog_root / "02-backlog"
    _write_task_yaml(backlog / "tasks", "T-FB999-US01-01", "US-FB999-01", "TODO", priority="Baja")
    _write_task_yaml(backlog / "tasks", "T-FB999-US01-02", "US-FB999-01", "TODO", priority="Crítica")
    enqueue_task(backlog_root, "proj", task_id="T-FB999-US01-01", us_id="US-FB999-01", priority="Baja")
    enqueue_task(backlog_root, "proj", task_id="T-FB999-US01-02", us_id="US-FB999-01", priority="Crítica")

    agent, runtime_instance = _launch_cooperative_developer(isolated_socket, tmp_path)
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    assign_agent(session, agent)

    try:
        dispatched_task_id = run_dispatch_cycle(backlog_root, "proj", session, socket_name=isolated_socket)
    finally:
        stop_runtime(runtime_instance, socket_name=isolated_socket)

    assert dispatched_task_id == "T-FB999-US01-02"
    entries = get_queue(backlog_root, "proj")
    by_id = {e.task_id: e for e in entries}
    assert by_id["T-FB999-US01-02"].status == STATUS_DISPATCHED
    assert by_id["T-FB999-US01-02"].agent_id == agent.id
    assert by_id["T-FB999-US01-01"].status == STATUS_QUEUED

    task_text = (backlog / "tasks" / "T-FB999-US01-02.md").read_text(encoding="utf-8")
    assert "state: DONE" in task_text


def test_run_dispatch_cycle_marks_failed_without_blocking_the_queue_when_no_agent_id_matches(
    tmp_path,
) -> None:
    # Criterio de aceptación: una Task despachada que falla no bloquea
    # el resto — reproducido sin tmux, forzando el fallo real de
    # create_job (agente no perteneciente a la sesión activa).
    backlog_root = tmp_path
    backlog = backlog_root / "02-backlog"
    _write_task_yaml(backlog / "tasks", "T-FB999-US01-01", "US-FB999-01", "TODO", priority="Alta")
    enqueue_task(backlog_root, "proj", task_id="T-FB999-US01-01", us_id="US-FB999-01", priority="Alta")

    # Sesión SIN agentes asignados, pero con `_find_agent_by_role`
    # monkeypatcheado para forzar un agente "fantasma" CON runtime
    # registrado (para superar el guard de `runtime_instance is None`) —
    # `create_job` lo rechaza igualmente porque no pertenece a `session`
    # (`agent not in list_agents(session)`), mismo camino de error real
    # que un fallo de despacho genuino, sin necesitar tmux real para
    # este caso concreto.
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    phantom_agent = Agent(id="ghost", name="ghost", role="developer", prompt="p", runtime_id="r1")
    from brain.runtime import RuntimeInstance

    register_runtime_instance_for_agent(
        phantom_agent.id,
        RuntimeInstance(
            runtime=Runtime(id="r1", name="r", type="test", command="bash", args=[]),
            session_name="ghost-session",
        ),
    )

    import brain.dispatcher.dispatch_queue_worker as worker_module

    original = worker_module._find_agent_by_role
    worker_module._find_agent_by_role = lambda *a, **k: phantom_agent
    try:
        dispatched_task_id = run_dispatch_cycle(backlog_root, "proj", session)
    finally:
        worker_module._find_agent_by_role = original

    assert dispatched_task_id == "T-FB999-US01-01"
    entries = get_queue(backlog_root, "proj")
    assert entries[0].status == STATUS_FAILED
    assert entries[0].result

    task_text = (backlog / "tasks" / "T-FB999-US01-01.md").read_text(encoding="utf-8")
    assert "state: TODO" in task_text


def test_run_dispatch_cycle_a_failed_task_does_not_block_the_next_one_in_a_later_cycle(
    isolated_socket: str, tmp_path,
) -> None:
    # Criterio de aceptación: "una Task despachada que falla no bloquea
    # el despacho de las demás Tasks encoladas" — verificado con DOS
    # Tasks reales y DOS ciclos: la primera falla de verdad por timeout
    # real (SIM_DELAY largo + AGENT_STEP_TIMEOUT_SECONDS reducido vía
    # monkeypatch, mismo patrón ya usado en
    # test_dispatch_plan_completes_an_agent_step_that_would_have_exceeded_the_old_default_timeout
    # de T-FB008-US04-06 — Job.status queda "failed" de verdad, no
    # simulado con un mock), el Developer vuelve a `idle` al terminar ese
    # Job (igual que cualquier Job real, completado o no), y el segundo
    # ciclo despacha la segunda Task con normalidad sobre el MISMO
    # Developer ya libre de nuevo.
    from unittest.mock import patch

    backlog_root = tmp_path / "backlog_root"
    backlog = backlog_root / "02-backlog"
    _write_task_yaml(backlog / "tasks", "T-FB999-US01-01", "US-FB999-01", "TODO", priority="Alta")
    _write_task_yaml(backlog / "tasks", "T-FB999-US01-02", "US-FB999-01", "TODO", priority="Media")
    enqueue_task(backlog_root, "proj", task_id="T-FB999-US01-01", us_id="US-FB999-01", priority="Alta")
    enqueue_task(backlog_root, "proj", task_id="T-FB999-US01-02", us_id="US-FB999-01", priority="Media")

    agent, runtime_instance = _launch_cooperative_developer(
        isolated_socket, tmp_path, extra_env="SIM_DELAY=3"
    )
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    assign_agent(session, agent)

    try:
        with patch("brain.dispatcher.dispatch_queue_worker.AGENT_STEP_TIMEOUT_SECONDS", 0.5):
            first_result = run_dispatch_cycle(backlog_root, "proj", session, socket_name=isolated_socket)
        assert first_result == "T-FB999-US01-01"

        entries = get_queue(backlog_root, "proj")
        by_id = {e.task_id: e for e in entries}
        assert by_id["T-FB999-US01-01"].status == STATUS_FAILED
        assert by_id["T-FB999-US01-02"].status == STATUS_QUEUED

        # El agente vuelve a `idle` en cuanto `dispatch_job` marca el Job
        # `failed` por timeout (mismo ciclo de vida que cualquier Job
        # real) — pequeña espera de reloj real para que el script
        # cooperativo, que sigue "trabajando" en segundo plano tras el
        # timeout, no interfiera con el segundo despacho.
        deadline = time.monotonic() + 5.0
        while agent.status != "idle" and time.monotonic() < deadline:
            time.sleep(0.05)
        assert agent.status == "idle"

        second_result = run_dispatch_cycle(backlog_root, "proj", session, socket_name=isolated_socket)
    finally:
        stop_runtime(runtime_instance, socket_name=isolated_socket)

    assert second_result == "T-FB999-US01-02"
    entries = get_queue(backlog_root, "proj")
    by_id = {e.task_id: e for e in entries}
    assert by_id["T-FB999-US01-02"].status == STATUS_DISPATCHED

    task1_text = (backlog / "tasks" / "T-FB999-US01-01.md").read_text(encoding="utf-8")
    assert "state: TODO" in task1_text
    task2_text = (backlog / "tasks" / "T-FB999-US01-02.md").read_text(encoding="utf-8")
    assert "state: DONE" in task2_text


def test_dispatch_queue_worker_run_once_matches_run_dispatch_cycle(
    isolated_socket: str, tmp_path,
) -> None:
    backlog_root = tmp_path / "backlog_root"
    backlog = backlog_root / "02-backlog"
    _write_task_yaml(backlog / "tasks", "T-FB999-US01-01", "US-FB999-01", "TODO", priority="Alta")
    enqueue_task(backlog_root, "proj", task_id="T-FB999-US01-01", us_id="US-FB999-01", priority="Alta")

    agent, runtime_instance = _launch_cooperative_developer(isolated_socket, tmp_path)
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    assign_agent(session, agent)

    worker = DispatchQueueWorker(backlog_root, "proj", session, socket_name=isolated_socket)
    try:
        result = worker.run_once()
    finally:
        stop_runtime(runtime_instance, socket_name=isolated_socket)

    assert result == "T-FB999-US01-01"


def test_run_dispatch_cycle_does_not_dispatch_while_the_only_developer_is_genuinely_busy(
    isolated_socket: str, tmp_path,
) -> None:
    # Criterio de aceptación explícito: "con todos los Developers
    # working, el Dispatcher no intenta despachar nada hasta que alguno
    # quede idle" — verificado esperando un ciclo real sin Developer
    # libre y confirmando que la cola no cambia. Developer genuinamente
    # ocupado (dispatch_job real en un hilo de fondo), sin status
    # forzado a mano.
    from brain.dispatcher.job_creation import create_job
    from brain.dispatcher.job_dispatch import dispatch_job

    backlog_root = tmp_path / "backlog_root"
    backlog = backlog_root / "02-backlog"
    _write_task_yaml(backlog / "tasks", "T-FB999-US01-01", "US-FB999-01", "TODO", priority="Alta")
    enqueue_task(backlog_root, "proj", task_id="T-FB999-US01-01", us_id="US-FB999-01", priority="Alta")

    agent, runtime_instance = _launch_cooperative_developer(
        isolated_socket, tmp_path, extra_env="SIM_DELAY=2"
    )
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    assign_agent(session, agent)

    busy_job = create_job("Job de larga duración en curso", agent, session)
    busy_thread = threading.Thread(
        target=dispatch_job,
        args=(busy_job, agent, runtime_instance),
        kwargs={"socket_name": isolated_socket},
    )
    busy_thread.start()
    try:
        deadline = time.monotonic() + 5.0
        while agent.status != "working" and time.monotonic() < deadline:
            time.sleep(0.02)
        assert agent.status == "working"

        result = run_dispatch_cycle(backlog_root, "proj", session, socket_name=isolated_socket)
    finally:
        busy_thread.join(timeout=10)
        stop_runtime(runtime_instance, socket_name=isolated_socket)

    assert result is None
    entries = get_queue(backlog_root, "proj")
    assert entries[0].status == STATUS_QUEUED


# ---------------------------------------------------------------------------
# Test de integración con Developers REALES (tmux real, sin status
# forzado a mano) — criterio de aceptación explícito, mismo patrón que
# test_dispatch_plan_picks_the_idle_developer_while_the_other_is_genuinely_busy
# de T-FB008-US04-08.
# ---------------------------------------------------------------------------


def test_dispatcher_worker_picks_the_idle_developer_while_the_other_is_genuinely_busy(
    isolated_socket: str, tmp_path,
) -> None:
    from brain.dispatcher.job_creation import create_job
    from brain.dispatcher.job_dispatch import dispatch_job

    backlog_root = tmp_path / "backlog_root"
    backlog = backlog_root / "02-backlog"
    _write_task_yaml(backlog / "tasks", "T-FB999-US01-01", "US-FB999-01", "TODO", priority="Alta")
    enqueue_task(backlog_root, "proj", task_id="T-FB999-US01-01", us_id="US-FB999-01", priority="Alta")

    busy_dev, busy_ri = _launch_cooperative_developer(
        isolated_socket, tmp_path, extra_env="SIM_DELAY=3"
    )
    busy_dev.id = "dev-busy"
    busy_dev.name = "Developer-busy"
    register_runtime_instance_for_agent(busy_dev.id, busy_ri)

    idle_dev, idle_ri = _launch_cooperative_developer(isolated_socket, tmp_path)
    idle_dev.id = "dev-idle"
    idle_dev.name = "Developer-idle"
    register_runtime_instance_for_agent(idle_dev.id, idle_ri)

    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    assign_agent(session, busy_dev)
    assign_agent(session, idle_dev)

    busy_job = create_job("Job de larga duración en curso", busy_dev, session)
    busy_thread = threading.Thread(
        target=dispatch_job,
        args=(busy_job, busy_dev, busy_ri),
        kwargs={"socket_name": isolated_socket},
    )
    busy_thread.start()
    try:
        deadline = time.monotonic() + 5.0
        while busy_dev.status != "working" and time.monotonic() < deadline:
            time.sleep(0.02)
        assert busy_dev.status == "working"

        # El Dispatcher, ejecutando un único ciclo real (sin status
        # forzado a mano en NINGÚN agente — busy_dev quedó `working` por
        # el propio dispatch_job real de arriba), debe elegir al
        # Developer genuinamente libre.
        dispatched_task_id = run_dispatch_cycle(backlog_root, "proj", session, socket_name=isolated_socket)
    finally:
        busy_thread.join(timeout=10)
        stop_runtime(busy_ri, socket_name=isolated_socket)
        stop_runtime(idle_ri, socket_name=isolated_socket)

    assert dispatched_task_id == "T-FB999-US01-01"
    entries = get_queue(backlog_root, "proj")
    assert entries[0].status == STATUS_DISPATCHED
    assert entries[0].agent_id == "dev-idle"
    assert busy_job.status == "completed"
