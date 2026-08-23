"""Tests de `atlas_forge.dispatcher.dispatch_queue_worker` (T-AF008-US10-02):
el Dispatcher de fondo que consume la cola de `dispatch_queue.py`
(`T-AF008-US10-01`).

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

from atlas_forge.core.session_lifecycle import activate, assign_agent
from atlas_forge.dispatcher.dispatch_queue import (
    STATUS_COMPLETED,
    STATUS_DISPATCHED,
    STATUS_FAILED,
    STATUS_QUEUED,
    enqueue_task,
    get_queue,
    mark_dispatched,
)
from atlas_forge.dispatcher.dispatch_queue_worker import (
    DispatchQueueWorker,
    _pick_next_eligible_entry,
    run_dispatch_cycle,
)
from atlas_forge.dispatcher.job_dispatch import (
    AgentNotReadyError,
    is_agent_ready_for_input,
)
from atlas_forge.models import Agent, DevelopmentSession, Job
from atlas_forge.runtime import register_runtime_instance_for_agent, start_runtime, stop_runtime
from atlas_forge.models import Runtime

_COOPERATIVE_AGENT_SCRIPT = str(
    Path(__file__).parent / "fixtures" / "cooperative_agent_sim.sh"
)
_OPENCODE_INIT_SIM_SCRIPT = str(
    Path(__file__).parent / "fixtures" / "opencode_init_sim.sh"
)


# ---------------------------------------------------------------------------
# _pick_next_eligible_entry — función pura, sin I/O.
# ---------------------------------------------------------------------------


def _entry(task_id, priority, enqueued_at, status=STATUS_QUEUED):
    from atlas_forge.dispatcher.dispatch_queue import QueueEntry

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
        f"dependencies: {dependencies}\nepic: AF-999\nuser_story: {us_id}\n"
        f"{priority_line}---\n\n"
        f"# {task_id}\n\n## Objetivo\n\nObjetivo.\n\n## Criterios de aceptación\n\n1. Y.\n",
        encoding="utf-8",
    )


def test_run_dispatch_cycle_returns_none_without_any_developer(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    _write_task_yaml(backlog / "tasks", "T-AF999-US01-01", "US-AF999-01", "TO_DEVELOP", priority="Alta")
    enqueue_task(tmp_path, "proj", task_id="T-AF999-US01-01", us_id="US-AF999-01", priority="Alta")

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
        backlog / "tasks", "T-AF999-US01-01", "US-AF999-01", "TO_DEVELOP", priority="Crítica",
        dependencies='["T-AF999-US01-99"]',
    )
    _write_task_yaml(backlog / "tasks", "T-AF999-US01-99", "US-AF999-01", "READY")
    enqueue_task(tmp_path, "proj", task_id="T-AF999-US01-01", us_id="US-AF999-01", priority="Crítica")

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

    name = f"atlas_forge-test-{uuid.uuid4().hex[:8]}"
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


def _await_task_resolved(worker: DispatchQueueWorker, task_id: str, timeout: float = 6.0) -> bool:
    """Espera (con timeout real) a que el Job en vuelo de `task_id` se
    resuelva vía `run_completion_poll_once` (T-AF022-US06-05): el Developer
    ya escribió su reporte, la Task pasó a `IN_REVIEW` y el Developer quedó
    libre. Devuelve `True` si se resolvió dentro de `timeout`."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resolved = worker.run_completion_poll_once()
        if task_id in resolved:
            return True
        time.sleep(0.05)
    return False


def _await_review_resolved(worker: DispatchQueueWorker, task_id: str, timeout: float = 6.0) -> bool:
    """Espera (con timeout real) a que la verificación en vuelo de
    `task_id` se resuelva vía `run_review_completion_once`
    (T-AF022-US06-06): el Tester ya emitió veredicto (EXITO->DONE,
    FALLO->redespacho) o expiró. Devuelve `True` si se resolvió."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resolved = worker.run_review_completion_once()
        if task_id in resolved:
            return True
        time.sleep(0.05)
    return False


def _await_architect_verdict_resolved(worker: DispatchQueueWorker, story_id: str, timeout: float = 6.0) -> bool:
    """Espera (con timeout real) a que el veredicto en vuelo de `story_id`
    se resuelva vía `run_architect_verdict_completion_once`
    (T-AF022-US06-06): el Arquitecto ya emitió su veredicto (se promovió
    la US y, en su caso, se encoló al Tester de UI) o expiró. Devuelve
    `True` si se resolvió."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resolved = worker.run_architect_verdict_completion_once()
        if story_id in resolved:
            return True
        time.sleep(0.05)
    return False


def test_run_dispatch_cycle_dispatches_the_highest_priority_eligible_task(
    isolated_socket: str, tmp_path,
) -> None:
    # Criterio de aceptación: con un Developer idle y Tasks de prioridad
    # distinta, despacha primero la de mayor prioridad.
    backlog_root = tmp_path / "backlog_root"
    backlog = backlog_root / "02-backlog"
    _write_task_yaml(backlog / "tasks", "T-AF999-US01-01", "US-AF999-01", "TO_DEVELOP", priority="Baja")
    _write_task_yaml(backlog / "tasks", "T-AF999-US01-02", "US-AF999-01", "TO_DEVELOP", priority="Crítica")
    enqueue_task(backlog_root, "proj", task_id="T-AF999-US01-01", us_id="US-AF999-01", priority="Baja")
    enqueue_task(backlog_root, "proj", task_id="T-AF999-US01-02", us_id="US-AF999-01", priority="Crítica")

    agent, runtime_instance = _launch_cooperative_developer(isolated_socket, tmp_path)
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    assign_agent(session, agent)

    worker = DispatchQueueWorker(backlog_root, "proj", session, socket_name=isolated_socket)
    try:
        # T-AF022-US06-05: el despacho es NO BLOQUEANTE — tras un ciclo la
        # Task queda IN_PROGRESS y el Developer working (la promoción a
        # IN_REVIEW la hace el nivel de completión, más abajo).
        dispatched_task_id = worker.run_once()
        assert dispatched_task_id == "T-AF999-US01-02"

        entries = get_queue(backlog_root, "proj")
        by_id = {e.task_id: e for e in entries}
        assert by_id["T-AF999-US01-02"].status == STATUS_DISPATCHED
        assert by_id["T-AF999-US01-02"].agent_id == agent.id
        assert by_id["T-AF999-US01-01"].status == STATUS_QUEUED

        task_text = (backlog / "tasks" / "T-AF999-US01-02.md").read_text(encoding="utf-8")
        assert "state: IN_PROGRESS" in task_text

        # Completión: el Developer reporta -> la Task pasa a IN_REVIEW y el
        # Developer vuelve a idle (T-AF008-US14-02: no DONE directo).
        assert _await_task_resolved(worker, "T-AF999-US01-02")
    finally:
        stop_runtime(runtime_instance, socket_name=isolated_socket)

    task_text = (backlog / "tasks" / "T-AF999-US01-02.md").read_text(encoding="utf-8")
    assert "state: IN_REVIEW" in task_text


def test_run_dispatch_cycle_marks_failed_without_blocking_the_queue_when_no_agent_id_matches(
    tmp_path,
) -> None:
    # Criterio de aceptación: una Task despachada que falla no bloquea
    # el resto — reproducido sin tmux, forzando el fallo real de
    # create_job (agente no perteneciente a la sesión activa).
    backlog_root = tmp_path
    backlog = backlog_root / "02-backlog"
    _write_task_yaml(backlog / "tasks", "T-AF999-US01-01", "US-AF999-01", "TO_DEVELOP", priority="Alta")
    enqueue_task(backlog_root, "proj", task_id="T-AF999-US01-01", us_id="US-AF999-01", priority="Alta")

    # Sesión SIN agentes asignados, pero con `_pick_developer_for_difficulty`
    # monkeypatcheado para forzar un agente "fantasma" CON runtime
    # registrado (para superar el guard de `runtime_instance is None`) —
    # `create_job` lo rechaza igualmente porque no pertenece a `session`
    # (`agent not in list_agents(session)`), mismo camino de error real
    # que un fallo de despacho genuino, sin necesitar tmux real para
    # este caso concreto.
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    phantom_agent = Agent(id="ghost", name="ghost", role="developer", prompt="p", runtime_id="r1")
    from atlas_forge.runtime import RuntimeInstance

    register_runtime_instance_for_agent(
        phantom_agent.id,
        RuntimeInstance(
            runtime=Runtime(id="r1", name="r", type="test", command="bash", args=[]),
            session_name="ghost-session",
        ),
    )

    import atlas_forge.dispatcher.dispatch_queue_worker as worker_module

    original = worker_module._pick_developer_for_difficulty
    worker_module._pick_developer_for_difficulty = lambda *a, **k: (phantom_agent, "test")
    try:
        dispatched_task_id = run_dispatch_cycle(backlog_root, "proj", session)
    finally:
        worker_module._pick_developer_for_difficulty = original

    assert dispatched_task_id == "T-AF999-US01-01"
    entries = get_queue(backlog_root, "proj")
    assert entries[0].status == STATUS_FAILED
    assert entries[0].result

    task_text = (backlog / "tasks" / "T-AF999-US01-01.md").read_text(encoding="utf-8")
    # Decisión 2026-08-19: tras un fallo la Task queda `TO_DEVELOP` (no
    # vuelve a `READY`) para que el siguiente ciclo la reintente sola.
    assert "state: TO_DEVELOP" in task_text


def test_run_dispatch_cycle_a_failed_task_does_not_block_the_next_one_in_a_later_cycle(
    isolated_socket: str, tmp_path,
) -> None:
    # Criterio de aceptación: "una Task despachada que falla no bloquea
    # el despacho de las demás Tasks encoladas" — verificado con DOS
    # Tasks reales y DOS ciclos: la primera falla de verdad por timeout
    # real (SIM_DELAY largo + AGENT_STEP_TIMEOUT_SECONDS reducido vía
    # monkeypatch, mismo patrón ya usado en
    # test_dispatch_plan_completes_an_agent_step_that_would_have_exceeded_the_old_default_timeout
    # de T-AF008-US04-06 — Job.status queda "failed" de verdad, no
    # simulado con un mock), el Developer vuelve a `idle` al terminar ese
    # Job (igual que cualquier Job real, completado o no).
    #
    # Decisión de producto 2026-08-19: tras el fallo la Task 01 NO vuelve
    # a `READY` — queda en `TO_DEVELOP` para reintento automático. Por
    # prioridad (Alta > Media), el segundo ciclo la reintenta a ella
    # primero; la Task 02 (Media) queda pendiente y se despacha en un
    # ciclo posterior, demostrando que el fallo de una no bloquea el
    # despacho de las demás (que siguen encoladas y elegibles).
    from unittest.mock import patch

    backlog_root = tmp_path / "backlog_root"
    backlog = backlog_root / "02-backlog"
    _write_task_yaml(backlog / "tasks", "T-AF999-US01-01", "US-AF999-01", "TO_DEVELOP", priority="Alta")
    _write_task_yaml(backlog / "tasks", "T-AF999-US01-02", "US-AF999-01", "TO_DEVELOP", priority="Media")
    enqueue_task(backlog_root, "proj", task_id="T-AF999-US01-01", us_id="US-AF999-01", priority="Alta")
    enqueue_task(backlog_root, "proj", task_id="T-AF999-US01-02", us_id="US-AF999-01", priority="Media")

    agent, runtime_instance = _launch_cooperative_developer(
        isolated_socket, tmp_path, extra_env="SIM_DELAY=3"
    )
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    assign_agent(session, agent)

    worker = DispatchQueueWorker(backlog_root, "proj", session, socket_name=isolated_socket)
    try:
        # T-AF022-US06-05: el despacho es NO BLOQUEANTE — el timeout de la
        # primera Task (SIM_DELAY=3 > timeout 0.5) ya NO ocurre dentro del
        # ciclo de despacho, sino en el nivel de completión.
        with patch("atlas_forge.dispatcher.dispatch_queue_worker.AGENT_STEP_TIMEOUT_SECONDS", 0.5):
            first_result = worker.run_once()
        assert first_result == "T-AF999-US01-01"

        entries = get_queue(backlog_root, "proj")
        by_id = {e.task_id: e for e in entries}
        assert by_id["T-AF999-US01-01"].status == STATUS_DISPATCHED
        assert by_id["T-AF999-US01-02"].status == STATUS_QUEUED

        # Completión por timeout: el Developer (SIM_DELAY=3) no reporta en
        # 0.5s -> Job failed, Task 01 vuelve a TO_DEVELOP, Developer a idle.
        deadline = time.monotonic() + 0.7
        resolved = []
        while time.monotonic() < deadline:
            resolved = worker.run_completion_poll_once(timeout_seconds=0.5)
            if "T-AF999-US01-01" in resolved:
                break
            time.sleep(0.05)
        assert "T-AF999-US01-01" in resolved

        entries = get_queue(backlog_root, "proj")
        by_id = {e.task_id: e for e in entries}
        assert by_id["T-AF999-US01-01"].status == STATUS_FAILED
        assert by_id["T-AF999-US01-02"].status == STATUS_QUEUED
        task1_text = (backlog / "tasks" / "T-AF999-US01-01.md").read_text(encoding="utf-8")
        assert "state: TO_DEVELOP" in task1_text

        # El agente vuelve a `idle` en cuanto el nivel de completión marca
        # el Job `failed` por timeout — pequeña espera de reloj real para
        # que el script cooperativo, que sigue "trabajando" en segundo
        # plano tras el timeout, no interfiera con el segundo despacho.
        deadline = time.monotonic() + 5.0
        while agent.status != "idle" and time.monotonic() < deadline:
            time.sleep(0.05)
        assert agent.status == "idle"

        # Segundo ciclo: la Task 01 sigue `TO_DEVELOP` (Alta) — se
        # reintenta ella primero (reintento automático tras fallo). La 02
        # (Media) queda `queued`, NO bloqueada: se despachará en un ciclo
        # posterior cuando la 01 no sea elegible.
        second_result = worker.run_once()
        assert second_result == "T-AF999-US01-01"
        entries = get_queue(backlog_root, "proj")
        by_id = {e.task_id: e for e in entries}
        # La entrada `failed` previa de la 01 se reutiliza al re-despachar:
        # vuelve a `dispatched` (una sola entrada, sin acumular).
        assert by_id["T-AF999-US01-01"].status == STATUS_DISPATCHED
        assert by_id["T-AF999-US01-02"].status == STATUS_QUEUED
    finally:
        stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_dispatch_queue_worker_run_once_matches_run_dispatch_cycle(
    isolated_socket: str, tmp_path,
) -> None:
    backlog_root = tmp_path / "backlog_root"
    backlog = backlog_root / "02-backlog"
    _write_task_yaml(backlog / "tasks", "T-AF999-US01-01", "US-AF999-01", "TO_DEVELOP", priority="Alta")
    enqueue_task(backlog_root, "proj", task_id="T-AF999-US01-01", us_id="US-AF999-01", priority="Alta")

    agent, runtime_instance = _launch_cooperative_developer(isolated_socket, tmp_path)
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    assign_agent(session, agent)

    worker = DispatchQueueWorker(backlog_root, "proj", session, socket_name=isolated_socket)
    try:
        result = worker.run_once()
    finally:
        stop_runtime(runtime_instance, socket_name=isolated_socket)

    assert result == "T-AF999-US01-01"


def test_run_dispatch_cycle_does_not_dispatch_while_the_only_developer_is_genuinely_busy(
    isolated_socket: str, tmp_path,
) -> None:
    # Criterio de aceptación explícito: "con todos los Developers
    # working, el Dispatcher no intenta despachar nada hasta que alguno
    # quede idle" — verificado esperando un ciclo real sin Developer
    # libre y confirmando que la cola no cambia. Developer genuinamente
    # ocupado (dispatch_job real en un hilo de fondo), sin status
    # forzado a mano.
    from atlas_forge.dispatcher.job_creation import create_job
    from atlas_forge.dispatcher.job_dispatch import dispatch_job

    backlog_root = tmp_path / "backlog_root"
    backlog = backlog_root / "02-backlog"
    _write_task_yaml(backlog / "tasks", "T-AF999-US01-01", "US-AF999-01", "TO_DEVELOP", priority="Alta")
    enqueue_task(backlog_root, "proj", task_id="T-AF999-US01-01", us_id="US-AF999-01", priority="Alta")

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
# de T-AF008-US04-08.
# ---------------------------------------------------------------------------


def test_dispatcher_worker_picks_the_idle_developer_while_the_other_is_genuinely_busy(
    isolated_socket: str, tmp_path,
) -> None:
    from atlas_forge.dispatcher.job_creation import create_job
    from atlas_forge.dispatcher.job_dispatch import dispatch_job

    backlog_root = tmp_path / "backlog_root"
    backlog = backlog_root / "02-backlog"
    _write_task_yaml(backlog / "tasks", "T-AF999-US01-01", "US-AF999-01", "TO_DEVELOP", priority="Alta")
    enqueue_task(backlog_root, "proj", task_id="T-AF999-US01-01", us_id="US-AF999-01", priority="Alta")

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

    assert dispatched_task_id == "T-AF999-US01-01"
    entries = get_queue(backlog_root, "proj")
    assert entries[0].status == STATUS_DISPATCHED
    assert entries[0].agent_id == "dev-idle"
    assert busy_job.status == "completed"


# ---------------------------------------------------------------------------
# T-AF022-US06-05: despacho NO BLOQUEANTE del Dispatcher para paralelismo
# real de Developers.
# ---------------------------------------------------------------------------


def test_two_cycles_dispatch_two_tasks_to_two_idle_developers_in_parallel(
    isolated_socket: str, tmp_path,
) -> None:
    # Criterio 1/2 de la Task: con 2 Developers idle y ≥2 Tasks TO_DEVELOP
    # elegibles, dos ciclos consecutivos dejan 2 Tasks IN_PROGRESS (una por
    # Developer), en paralelo real — el worker NO bloquea esperando al
    # primero mientras despacha al segundo.
    backlog_root = tmp_path / "backlog_root"
    backlog = backlog_root / "02-backlog"
    _write_task_yaml(backlog / "tasks", "T-AF999-US01-01", "US-AF999-01", "TO_DEVELOP", priority="Alta")
    _write_task_yaml(backlog / "tasks", "T-AF999-US01-02", "US-AF999-01", "TO_DEVELOP", priority="Alta")
    enqueue_task(backlog_root, "proj", task_id="T-AF999-US01-01", us_id="US-AF999-01", priority="Alta")
    enqueue_task(backlog_root, "proj", task_id="T-AF999-US01-02", us_id="US-AF999-01", priority="Alta")

    dev_a, ri_a = _launch_cooperative_developer(isolated_socket, tmp_path, extra_env="SIM_DELAY=2")
    dev_a.id = "dev-a"
    dev_a.name = "Developer-a"
    register_runtime_instance_for_agent(dev_a.id, ri_a)

    dev_b, ri_b = _launch_cooperative_developer(isolated_socket, tmp_path, extra_env="SIM_DELAY=2")
    dev_b.id = "dev-b"
    dev_b.name = "Developer-b"
    register_runtime_instance_for_agent(dev_b.id, ri_b)

    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    assign_agent(session, dev_a)
    assign_agent(session, dev_b)

    worker = DispatchQueueWorker(backlog_root, "proj", session, socket_name=isolated_socket)
    try:
        first = worker.run_once()
        assert first in ("T-AF999-US01-01", "T-AF999-US01-02")
        # Tras el primer ciclo no bloqueante, exactamente un Developer
        # quedó `working` y el otro sigue `idle`.
        assert (dev_a.status, dev_b.status).count("working") == 1

        # Segundo ciclo: despacha la segunda Task al otro Developer idle
        # SIN esperar a que el primero termine.
        second = worker.run_once()
        assert {first, second} == {"T-AF999-US01-01", "T-AF999-US01-02"}

        # Paralelismo REAL: ambos Developers working a la vez y ambas Tasks
        # IN_PROGRESS (el primer Developer sigue sin haber reportado).
        assert dev_a.status == "working" and dev_b.status == "working"
        for task_id in (first, second):
            text = (backlog / "tasks" / f"{task_id}.md").read_text(encoding="utf-8")
            assert "state: IN_PROGRESS" in text
        entries = get_queue(backlog_root, "proj")
        assert {e.task_id for e in entries if e.status == STATUS_DISPATCHED} == {first, second}
    finally:
        stop_runtime(ri_a, socket_name=isolated_socket)
        stop_runtime(ri_b, socket_name=isolated_socket)


def test_completion_poll_marks_task_in_review_and_frees_developer(
    isolated_socket: str, tmp_path,
) -> None:
    # Criterio 3: cuando el reporte de un Job en vuelo aparece con el
    # marcador ___ATLAS_FORGE_JOB_DONE___, la Task pasa a IN_REVIEW y su
    # Developer vuelve a idle en un ciclo de completión posterior, sin
    # bloquear el resto del bucle.
    backlog_root = tmp_path / "backlog_root"
    backlog = backlog_root / "02-backlog"
    _write_task_yaml(backlog / "tasks", "T-AF999-US01-01", "US-AF999-01", "TO_DEVELOP", priority="Alta")
    enqueue_task(backlog_root, "proj", task_id="T-AF999-US01-01", us_id="US-AF999-01", priority="Alta")

    agent, runtime_instance = _launch_cooperative_developer(isolated_socket, tmp_path)
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    assign_agent(session, agent)

    worker = DispatchQueueWorker(backlog_root, "proj", session, socket_name=isolated_socket)
    try:
        dispatched = worker.run_once()
        assert dispatched == "T-AF999-US01-01"
        # Tras despachar (no bloqueante), el Developer sigue working y la
        # Task en IN_PROGRESS — todavía sin completar.
        assert agent.status == "working"
        text = (backlog / "tasks" / "T-AF999-US01-01.md").read_text(encoding="utf-8")
        assert "state: IN_PROGRESS" in text

        # Completión en un ciclo posterior: reporte presente -> IN_REVIEW y
        # Developer a idle.
        assert _await_task_resolved(worker, "T-AF999-US01-01")
        assert agent.status == "idle"
        text = (backlog / "tasks" / "T-AF999-US01-01.md").read_text(encoding="utf-8")
        assert "state: IN_REVIEW" in text
    finally:
        stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_completion_poll_timeout_marks_task_failed_and_ready(
    isolated_socket: str, tmp_path,
) -> None:
    # Criterio 4: un Job en vuelo sin reporte dentro de su timeout queda
    # `failed` y su Task vuelve a `TO_DEVELOP` (decisión 2026-08-19: tras
    # un fallo la Task no vuelve a `READY`, solo un humano la revierte) —
    # detectado por el nivel de completión, no dentro del ciclo de despacho
    # (no bloqueante).
    backlog_root = tmp_path / "backlog_root"
    backlog = backlog_root / "02-backlog"
    _write_task_yaml(backlog / "tasks", "T-AF999-US01-01", "US-AF999-01", "TO_DEVELOP", priority="Alta")
    enqueue_task(backlog_root, "proj", task_id="T-AF999-US01-01", us_id="US-AF999-01", priority="Alta")

    agent, runtime_instance = _launch_cooperative_developer(
        isolated_socket, tmp_path, extra_env="SIM_DELAY=3"
    )
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    assign_agent(session, agent)

    worker = DispatchQueueWorker(backlog_root, "proj", session, socket_name=isolated_socket)
    try:
        dispatched = worker.run_once()
        assert dispatched == "T-AF999-US01-01"

        # El Developer (SIM_DELAY=3) no reporta en 0.5s -> timeout.
        deadline = time.monotonic() + 0.7
        resolved = []
        while time.monotonic() < deadline:
            resolved = worker.run_completion_poll_once(timeout_seconds=0.5)
            if "T-AF999-US01-01" in resolved:
                break
            time.sleep(0.05)
        assert "T-AF999-US01-01" in resolved

        assert agent.status == "idle"
        text = (backlog / "tasks" / "T-AF999-US01-01.md").read_text(encoding="utf-8")
        assert "state: TO_DEVELOP" in text
        entries = get_queue(backlog_root, "proj")
        assert entries[0].status == STATUS_FAILED
    finally:
        stop_runtime(runtime_instance, socket_name=isolated_socket)


# ---------------------------------------------------------------------------
# T-AF022-US06-07: entregas de Job perdidas durante la inicialización del
# opencode de un agente recién registrado/reconciliado — gate de readiness.
# ---------------------------------------------------------------------------


def _launch_opencode_initializing_developer(isolated_socket: str, tmp_path, init_seconds: str = "0.3"):
    """Lanza un Developer simulado con runtime tipo `opencode` cuyo pane NO
    muestra la barra de estado `"Build · "` durante la inicialización
    ("Build auto") y solo la muestra tras un retardo configurable — el doble
    determinista del caso real del bug (2026-08-18): despachar a ese agente
    antes de la barra perdía la orden y lo dejaba `working` hasta el
    timeout."""
    command = "bash"
    runtime = Runtime(
        id="opencode-runtime", name="OpenCode", type="opencode", command=command,
        args=[_OPENCODE_INIT_SIM_SCRIPT],
    )
    agent = Agent(id="a-op", name="developer", role="developer", prompt="", runtime_id="opencode-runtime")
    runtime_instance = start_runtime(runtime, agent, str(tmp_path), socket_name=isolated_socket)
    register_runtime_instance_for_agent(agent.id, runtime_instance)
    return agent, runtime_instance


def test_run_dispatch_cycle_does_not_dispatch_to_a_not_ready_newly_registered_agent(
    isolated_socket: str, tmp_path,
) -> None:
    """T-AF022-US06-07, criterios 1-3: un agente recién registrado cuyo
    opencode aún no muestra la barra de estado (inicialización "Build
    auto") NO recibe la orden: el ciclo de despacho no lo marca `working`
    ni mueve la cola; cuando la barra aparece, el siguiente ciclo sí
    despacha y el Job se completa sin quedar huérfano."""
    backlog_root = tmp_path / "backlog_root"
    backlog = backlog_root / "02-backlog"
    _write_task_yaml(backlog / "tasks", "T-AF999-US01-01", "US-AF999-01", "TO_DEVELOP", priority="Alta")
    enqueue_task(backlog_root, "proj", task_id="T-AF999-US01-01", us_id="US-AF999-01", priority="Alta")

    agent, runtime_instance = _launch_opencode_initializing_developer(isolated_socket, tmp_path)
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    assign_agent(session, agent)

    worker = DispatchQueueWorker(backlog_root, "proj", session, socket_name=isolated_socket)
    try:
        # Ciclo 1: agente aún inicializando -> NO despacha.
        result = worker.run_once()
        assert result is None
        # El agente nunca quedó `working` sin orden (criterio 3).
        assert agent.status == "idle"
        entries = get_queue(backlog_root, "proj")
        assert entries[0].status == STATUS_QUEUED
        text = (backlog / "tasks" / "T-AF999-US01-01.md").read_text(encoding="utf-8")
        assert "state: TO_DEVELOP" in text

        # Espera a que la barra de estado aparezca (readiness real del
        # pane, señal determinista — sin esperas arbitrarias).
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if is_agent_ready_for_input(
                agent, socket_name=isolated_socket, runtime_instance=runtime_instance
            ):
                break
            time.sleep(0.1)
        else:
            pytest.fail("el agente simulado nunca alcanzó el estado ready")

        # Ciclo 2: ya listo -> despacha y completa (la orden llega).
        dispatched = worker.run_once()
        assert dispatched == "T-AF999-US01-01"
        assert agent.status == "working"
        assert _await_task_resolved(worker, "T-AF999-US01-01")
        assert agent.status == "idle"
        text = (backlog / "tasks" / "T-AF999-US01-01.md").read_text(encoding="utf-8")
        assert "state: IN_REVIEW" in text
    finally:
        stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_run_dispatch_cycle_prefers_a_ready_developer_over_a_not_ready_one(
    isolated_socket: str, tmp_path,
) -> None:
    """T-AF022-US06-07: si el primer Developer idle no está listo (recién
    lanzado, opencode inicializando) pero hay otro Developer idle listo, el
    ciclo despacha al que SÍ puede recibir la orden — un agente no listo no
    bloquea la cola para el resto."""
    backlog_root = tmp_path / "backlog_root"
    backlog = backlog_root / "02-backlog"
    _write_task_yaml(backlog / "tasks", "T-AF999-US01-01", "US-AF999-01", "TO_DEVELOP", priority="Alta")
    enqueue_task(backlog_root, "proj", task_id="T-AF999-US01-01", us_id="US-AF999-01", priority="Alta")

    not_ready, not_ready_ri = _launch_opencode_initializing_developer(
        isolated_socket, tmp_path, init_seconds="60"
    )
    ready, ready_ri = _launch_cooperative_developer(isolated_socket, tmp_path)

    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    assign_agent(session, not_ready)
    assign_agent(session, ready)

    worker = DispatchQueueWorker(backlog_root, "proj", session, socket_name=isolated_socket)
    try:
        # El único ciclo debe elegir al Developer LISTO (el no listo queda
        # excluido por el gate de readiness sin bloquear la cola).
        dispatched = worker.run_once()
        assert dispatched == "T-AF999-US01-01"
        assert ready.status == "working"
        assert not_ready.status == "idle"
        entries = get_queue(backlog_root, "proj")
        assert entries[0].status == STATUS_DISPATCHED
        assert entries[0].agent_id == ready.id
    finally:
        stop_runtime(not_ready_ri, socket_name=isolated_socket)
        stop_runtime(ready_ri, socket_name=isolated_socket)


def test_dispatch_job_send_to_not_ready_opencode_agent_fails_job_and_keeps_agent_idle(
    isolated_socket: str, tmp_path,
) -> None:
    """T-AF022-US06-07, criterio 2: si la entrega no puede realizarse
    porque el agente no está listo (opencode aún inicializando), el Job
    queda `failed` con el motivo y el agente NUNCA llega a `working` — no
    queda huérfano en `working` sin orden."""
    from atlas_forge.dispatcher.job_dispatch import dispatch_job_send

    agent, runtime_instance = _launch_opencode_initializing_developer(
        isolated_socket, tmp_path, init_seconds="60"
    )
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    assign_agent(session, agent)

    job = Job(id="j1", session_id="s1", agent_id=agent.id, description="test job")

    try:
        with pytest.raises(AgentNotReadyError):
            dispatch_job_send(job, agent, runtime_instance, socket_name=isolated_socket)

        assert job.status == "failed"
        assert "no está listo" in job.result
        assert agent.status == "idle"
    finally:
        stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_dispatch_job_blocks_without_propagating_when_agent_not_ready(
    isolated_socket: str, tmp_path,
) -> None:
    """T-AF022-US06-07: el camino bloqueante (`dispatch_job`) no propaga la
    excepción ante un agente no listo — deja el Job `failed` con el motivo y
    el agente `idle` (contrato histórico de la función: nunca propaga un
    fallo de despacho)."""
    from atlas_forge.dispatcher.job_dispatch import dispatch_job

    agent, runtime_instance = _launch_opencode_initializing_developer(
        isolated_socket, tmp_path, init_seconds="60"
    )
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    assign_agent(session, agent)

    job = Job(id="j1", session_id="s1", agent_id=agent.id, description="test job")

    try:
        dispatch_job(job, agent, runtime_instance, socket_name=isolated_socket)

        assert job.status == "failed"
        assert "no está listo" in job.result
        assert agent.status == "idle"
    finally:
        stop_runtime(runtime_instance, socket_name=isolated_socket)


# ---------------------------------------------------------------------------
# T-AF036-US13-01: el worker del Dispatcher escribe `updated_at` al cambiar
# el estado de una Task en disco (`_update_task_file_state`).
# ---------------------------------------------------------------------------


def test_update_task_file_state_escribe_updated_at(tmp_path: Path) -> None:
    """Criterio: el worker, al cambiar una Task a TO_DEVELOP/IN_REVIEW o en
    redespacho, escribe/actualiza `updated_at` en el frontmatter."""
    from atlas_forge.dispatcher.dispatch_queue_worker import _update_task_file_state

    backlog = tmp_path / "02-backlog"
    tasks_dir = backlog / "tasks"
    _write_task_yaml(tasks_dir, "T-AF999-US01-01", "US-AF999-01", "TO_DEVELOP", priority="Alta")
    task_path = tasks_dir / "T-AF999-US01-01.md"

    _update_task_file_state(tasks_dir, "T-AF999-US01-01", "IN_PROGRESS")

    text = task_path.read_text(encoding="utf-8")
    assert "state: IN_PROGRESS" in text
    assert "updated_at:" in text
    # Un segundo cambio no duplica la línea.
    _update_task_file_state(tasks_dir, "T-AF999-US01-01", "IN_REVIEW")
    assert task_path.read_text(encoding="utf-8").count("updated_at:") == 1


# ---------------------------------------------------------------------------
# T-AF022-US06-06: ciclo de revisión del Tester NO BLOQUEANTE — con el
# Tester verificando, los demás Developers idle continúan recibiendo Tasks.
# ---------------------------------------------------------------------------


def test_review_in_flight_does_not_block_dispatch_to_other_developers(
    isolated_socket: str, tmp_path, monkeypatch,
) -> None:
    # Criterio 1/2 de la Task: con el Tester `working` en una verificación
    # (nivel 2) y un Developer idle no retenido + una Task TO_DEVELOP, el
    # ciclo de despacho (nivel 1) sigue asignando Tasks a los Developers no
    # retenidos — el bucle del worker NO se congela por la revisión.
    from atlas_forge.agents.launch import launch_agent
    import atlas_forge.runtime.claude_code as claude_code_module

    backlog_root = tmp_path / "backlog_root"
    backlog = backlog_root / "02-backlog"
    _write_task_yaml(backlog / "tasks", "T-AF999-US01-01", "US-AF999-01", "IN_REVIEW", priority="Alta")
    _write_task_yaml(backlog / "tasks", "T-AF999-US01-02", "US-AF999-01", "TO_DEVELOP", priority="Media")
    enqueue_task(backlog_root, "proj", task_id="T-AF999-US01-01", us_id="US-AF999-01", priority="Alta")
    enqueue_task(backlog_root, "proj", task_id="T-AF999-US01-02", us_id="US-AF999-01", priority="Media")

    dev_a, ri_a = _launch_cooperative_developer(isolated_socket, tmp_path, extra_env="SIM_DELAY=2")
    dev_a.id = "dev-retained"
    dev_a.name = "Developer-retenido"
    register_runtime_instance_for_agent(dev_a.id, ri_a)

    dev_b, ri_b = _launch_cooperative_developer(isolated_socket, tmp_path, extra_env="SIM_DELAY=2")
    dev_b.id = "dev-other"
    dev_b.name = "Developer-otro"
    register_runtime_instance_for_agent(dev_b.id, ri_b)

    # T-01 la cerró dev_a -> quedará retenido mientras esté en IN_REVIEW.
    mark_dispatched(backlog_root, "proj", "T-AF999-US01-01",
                    agent_id="dev-retained", agent_name="Developer-retenido", dispatch_reason="test")

    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    assign_agent(session, dev_a)
    assign_agent(session, dev_b)

    monkeypatch.setattr(
        claude_code_module, "DEFAULT_CLAUDE_CODE_COMMAND",
        "SIM_ROLE=tester_failed_verdict SIM_DELAY=2 bash",
    )
    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_ARGS", [_COOPERATIVE_AGENT_SCRIPT])
    tester, tester_runtime = launch_agent(
        "tester", "claude-code", None, session, str(tmp_path), socket_name=isolated_socket
    )
    assign_agent(session, tester)

    worker = DispatchQueueWorker(backlog_root, "proj", session, socket_name=isolated_socket)
    try:
        # Nivel 2 no bloqueante: T-01 en revisión -> el Tester queda working,
        # la verificación en vuelo.
        review = worker.run_review_once()
        assert review == "T-AF999-US01-01"
        assert tester.status == "working"

        # Nivel 1: con el Tester working (y dev_a retenido), el ciclo de
        # despacho sigue asignando T-02 a dev_b (no retenido).
        dispatched = worker.run_once()
        assert dispatched == "T-AF999-US01-02"
        assert dev_b.status == "working"
        assert dev_a.status == "idle"  # retenido, no recibe trabajo nuevo
        text = (backlog / "tasks" / "T-AF999-US01-02.md").read_text(encoding="utf-8")
        assert "state: IN_PROGRESS" in text
    finally:
        stop_runtime(ri_a, socket_name=isolated_socket)
        stop_runtime(ri_b, socket_name=isolated_socket)
        stop_runtime(tester_runtime, socket_name=isolated_socket)


def test_review_timeout_keeps_task_in_review_without_blocking(
    isolated_socket: str, tmp_path, monkeypatch,
) -> None:
    # Criterio 4: un timeout de verificación no bloquea el resto del bucle —
    # la Task vuelve a IN_REVIEW (re-encolable), lista para reintento.
    from atlas_forge.agents.launch import launch_agent
    import atlas_forge.runtime.claude_code as claude_code_module

    backlog_root = tmp_path / "backlog_root"
    backlog = backlog_root / "02-backlog"
    _write_task_yaml(backlog / "tasks", "T-AF999-US01-01", "US-AF999-01", "IN_REVIEW", priority="Alta")

    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)

    monkeypatch.setattr(
        claude_code_module, "DEFAULT_CLAUDE_CODE_COMMAND",
        "SIM_ROLE=tester_passed_verdict SIM_DELAY=3 bash",
    )
    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_ARGS", [_COOPERATIVE_AGENT_SCRIPT])
    tester, tester_runtime = launch_agent(
        "tester", "claude-code", None, session, str(tmp_path), socket_name=isolated_socket
    )

    worker = DispatchQueueWorker(backlog_root, "proj", session, socket_name=isolated_socket)
    try:
        dispatched = worker.run_review_once()
        assert dispatched == "T-AF999-US01-01"
        assert tester.status == "working"

        # El Tester (SIM_DELAY=3) no veredicta en 0.5s -> timeout; la Task
        # se queda en IN_REVIEW.
        deadline = time.monotonic() + 0.7
        resolved = []
        while time.monotonic() < deadline:
            resolved = worker.run_review_completion_once(timeout_seconds=0.5)
            if "T-AF999-US01-01" in resolved:
                break
            time.sleep(0.05)
        assert "T-AF999-US01-01" in resolved

        assert tester.status == "idle"
        text = (backlog / "tasks" / "T-AF999-US01-01.md").read_text(encoding="utf-8")
        assert "state: IN_REVIEW" in text
    finally:
        stop_runtime(tester_runtime, socket_name=isolated_socket)


# ---------------------------------------------------------------------------
# T-AF008-US14-02: IN_REVIEW con dos niveles (Tester por Task, Arquitecto por
# US) — Developer retenido, ciclo de Tester, ciclo de veredicto de US.
# ---------------------------------------------------------------------------


def test_retained_developer_is_excluded_from_next_dispatch_until_tester_resolves(
    isolated_socket: str, tmp_path,
) -> None:
    # Criterio de aceptación: "sin bloquear al Developer que sigue en
    # otra Task" se lee en sentido inverso también — el MISMO Developer
    # que cerró una Task ahora en IN_REVIEW no debe coger una Task TO_DEVELOP
    # nueva (decisión de producto explícita: "el developer debe esperar
    # hasta que el tester le responda").
    backlog_root = tmp_path / "backlog_root"
    backlog = backlog_root / "02-backlog"
    _write_task_yaml(backlog / "tasks", "T-AF999-US01-01", "US-AF999-01", "TO_DEVELOP", priority="Alta")
    _write_task_yaml(backlog / "tasks", "T-AF999-US01-02", "US-AF999-01", "TO_DEVELOP", priority="Media")
    enqueue_task(backlog_root, "proj", task_id="T-AF999-US01-01", us_id="US-AF999-01", priority="Alta")
    enqueue_task(backlog_root, "proj", task_id="T-AF999-US01-02", us_id="US-AF999-01", priority="Media")

    agent, runtime_instance = _launch_cooperative_developer(isolated_socket, tmp_path)
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    assign_agent(session, agent)

    worker = DispatchQueueWorker(backlog_root, "proj", session, socket_name=isolated_socket)
    try:
        first_result = worker.run_once()
        assert first_result == "T-AF999-US01-01"

        # Completión no bloqueante: el Developer reporta -> Task IN_REVIEW,
        # Developer vuelve a idle (queda retenido por el Tester).
        assert _await_task_resolved(worker, "T-AF999-US01-01")
        assert agent.status == "idle"

        # El agente volvió a `idle` (mismo Job real terminado), pero la
        # Task quedó en IN_REVIEW — el segundo ciclo NO debe despacharle la
        # siguiente Task TO_DEVELOP a este mismo Developer.
        second_result = worker.run_once()
    finally:
        stop_runtime(runtime_instance, socket_name=isolated_socket)

    assert second_result is None
    task1_text = (backlog / "tasks" / "T-AF999-US01-01.md").read_text(encoding="utf-8")
    assert "state: IN_REVIEW" in task1_text
    entries = get_queue(backlog_root, "proj")
    by_id = {e.task_id: e for e in entries}
    assert by_id["T-AF999-US01-02"].status == STATUS_QUEUED


def test_review_dispatch_cycle_passed_verdict_marks_task_done(
    isolated_socket: str, tmp_path, monkeypatch,
) -> None:
    from atlas_forge.agents.launch import launch_agent
    import atlas_forge.runtime.claude_code as claude_code_module
    from atlas_forge.dispatcher.dispatch_queue_worker import run_review_dispatch_cycle

    backlog_root = tmp_path / "backlog_root"
    backlog = backlog_root / "02-backlog"
    _write_task_yaml(backlog / "tasks", "T-AF999-US01-01", "US-AF999-01", "IN_REVIEW", priority="Alta")

    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)

    monkeypatch.setattr(
        claude_code_module, "DEFAULT_CLAUDE_CODE_COMMAND",
        "SIM_ROLE=tester_passed_verdict SIM_DELAY=0.1 bash",
    )
    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_ARGS", [_COOPERATIVE_AGENT_SCRIPT])

    tester, tester_runtime = launch_agent(
        "tester", "claude-code", None, session, str(tmp_path), socket_name=isolated_socket
    )
    worker = DispatchQueueWorker(backlog_root, "proj", session, socket_name=isolated_socket)
    try:
        # T-AF022-US06-06: despacho NO BLOQUEANTE de la verificación.
        result = worker.run_review_once()
        assert result == "T-AF999-US01-01"
        # Completión: el Tester reporta EXITO -> Task DONE.
        assert _await_review_resolved(worker, "T-AF999-US01-01")
    finally:
        stop_runtime(tester_runtime, socket_name=isolated_socket)

    task_text = (backlog / "tasks" / "T-AF999-US01-01.md").read_text(encoding="utf-8")
    assert "state: DONE" in task_text


def test_review_dispatch_cycle_failed_verdict_redispatches_to_same_developer(
    isolated_socket: str, tmp_path,
) -> None:
    """Rediseño 2026-08-17 (decisión explícita del usuario, sustituye el
    diseño anterior de Task de corrección nueva): un veredicto FALLO del
    Tester devuelve la Task DIRECTAMENTE al mismo Developer que la
    cerró — sin crear ninguna Task nueva. Verificación end-to-end real:
    Developer despacha y cierra la Task (queda en IN_REVIEW con entrada
    `dispatched` real), el Tester falla, y se confirma que el segundo
    Job de corrección lo recibe el MISMO agente (`a-dev`), no uno nuevo."""
    from atlas_forge.agents.launch import launch_agent
    import atlas_forge.runtime.claude_code as claude_code_module
    from atlas_forge.dispatcher.dispatch_queue_worker import run_review_dispatch_cycle

    backlog_root = tmp_path / "backlog_root"
    backlog = backlog_root / "02-backlog"
    _write_task_yaml(backlog / "tasks", "T-AF999-US01-01", "US-AF999-01", "TO_DEVELOP", priority="Alta")
    enqueue_task(backlog_root, "proj", task_id="T-AF999-US01-01", us_id="US-AF999-01", priority="Alta")

    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)

    developer, developer_runtime = _launch_cooperative_developer(isolated_socket, tmp_path)
    assign_agent(session, developer)

    import atlas_forge.runtime.claude_code as claude_code_module_for_tester

    worker = DispatchQueueWorker(backlog_root, "proj", session, socket_name=isolated_socket)

    try:
        dispatch_result = worker.run_once()
        assert dispatch_result == "T-AF999-US01-01"

        # Completión no bloqueante: el Developer reporta -> Task IN_REVIEW,
        # Developer vuelve a idle.
        assert _await_task_resolved(worker, "T-AF999-US01-01")
        assert developer.status == "idle"

        task_text = (backlog / "tasks" / "T-AF999-US01-01.md").read_text(encoding="utf-8")
        assert "state: IN_REVIEW" in task_text

        claude_code_module_for_tester.DEFAULT_CLAUDE_CODE_COMMAND = "SIM_ROLE=tester_failed_verdict SIM_DELAY=0.1 bash"
        claude_code_module_for_tester.DEFAULT_CLAUDE_CODE_ARGS = [_COOPERATIVE_AGENT_SCRIPT]
        tester, tester_runtime = launch_agent(
            "tester", "claude-code", None, session, str(tmp_path), socket_name=isolated_socket
        )
        try:
            # T-AF022-US06-06: despacho NO BLOQUEANTE de la verificación.
            review_result = worker.run_review_once()
            assert review_result == "T-AF999-US01-01"
            # Completión: el Tester reporta FALLO -> la Task vuelve al MISMO
            # Developer (`_redispatch_task_to_retained_developer`, Job de
            # corrección registrado en vuelo de implementación).
            assert _await_review_resolved(worker, "T-AF999-US01-01")
            # Completión del Job de corrección: el Developer corrige y cierra
            # -> Task vuelve a IN_REVIEW, Developer a idle.
            assert _await_task_resolved(worker, "T-AF999-US01-01")
        finally:
            stop_runtime(tester_runtime, socket_name=isolated_socket)
    finally:
        stop_runtime(developer_runtime, socket_name=isolated_socket)

    assert review_result == "T-AF999-US01-01"
    assert developer.status == "idle"

    # Ningún fichero de corrección nuevo — la corrección vuelve al mismo
    # Developer, no genera una Task aparte.
    correction_files = list((backlog / "tasks").glob("T-AF999-US01-02-*.md"))
    assert correction_files == []

    task_text = (backlog / "tasks" / "T-AF999-US01-01.md").read_text(encoding="utf-8")
    # El script cooperativo, en su segunda invocación (sin SIM_ROLE
    # explícito para el Developer), cierra normal — la Task vuelve a
    # IN_REVIEW (el ciclo de corrección se comporta igual que el original).
    assert "state: IN_REVIEW" in task_text
    assert "## Corrección pendiente" in task_text
    assert "endpoint devuelve 500" in task_text


def test_architect_verdict_dispatch_cycle_assigns_review_story_to_idle_architect(
    isolated_socket: str, tmp_path, monkeypatch,
) -> None:
    from atlas_forge.agents.launch import launch_agent
    import atlas_forge.runtime.claude_code as claude_code_module
    from atlas_forge.dispatcher.dispatch_queue_worker import run_architect_verdict_dispatch_cycle

    backlog_root = tmp_path / "backlog_root"
    backlog = backlog_root / "02-backlog"
    stories_dir = backlog / "user-stories"
    stories_dir.mkdir(parents=True)
    (stories_dir / "US-AF999-01-titulo.md").write_text(
        "---\nid: US-AF999-01\ntype: user-story\ntitle: Titulo\nstate: IN_REVIEW\n"
        "dependencies: []\nepic: AF-999\n---\n\n# US-AF999-01\n\n## Contexto\n\nC.\n",
        encoding="utf-8",
    )
    _write_task_yaml(backlog / "tasks", "T-AF999-US01-01", "US-AF999-01", "DONE", priority="Alta")

    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)

    monkeypatch.setattr(
        claude_code_module, "DEFAULT_CLAUDE_CODE_COMMAND",
        "SIM_ROLE=architect_approved_verdict SIM_DELAY=0.1 bash",
    )
    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_ARGS", [_COOPERATIVE_AGENT_SCRIPT])

    architect, architect_runtime = launch_agent(
        "arquitecto", "claude-code", None, session, str(tmp_path), socket_name=isolated_socket
    )
    worker = DispatchQueueWorker(backlog_root, "proj", session, socket_name=isolated_socket)
    try:
        reports_root = tmp_path / "informes_vacio"
        # T-AF022-US06-06: despacho NO BLOQUEANTE del veredicto.
        result = worker.run_architect_verdict_once()
        assert result == "US-AF999-01"
        # Completión: el Arquitecto reporta APROBADO -> US DONE.
        assert _await_architect_verdict_resolved(worker, "US-AF999-01")
    finally:
        stop_runtime(architect_runtime, socket_name=isolated_socket)

    story_text = (stories_dir / "US-AF999-01-titulo.md").read_text(encoding="utf-8")
    assert "state: DONE" in story_text


def test_architect_verdict_dispatch_cycle_enqueues_ui_tester_when_story_touches_web(
    isolated_socket: str, tmp_path, monkeypatch,
) -> None:
    """Regresión encontrada durante el refactor de T-AF008-US14-02
    (2026-08-17, "el flujo de trabajo debe estar encadenado en el
    dispatcher"): `trigger_architect_verdict` dejó de llamar a
    `enqueue_architect_verdict` (ahora solo marca la US en `IN_REVIEW`), así
    que el enganche de `T-AF022-US15-04` (Tester de UI tras veredicto
    aprobado sobre una Story que toca `10-web/`) se había quedado sin
    ningún camino vivo que lo alcanzara — `run_architect_verdict_dispatch_cycle`
    (el único disparador real del veredicto tras ese refactor) nunca lo
    invocaba. Verifica que el camino nuevo reengancha ese disparo, con un
    Tester de UI real lanzado (mismo patrón que
    `test_ui_tester_queue.py::test_end_to_end_approved_verdict_on_a_web_touching_story_dispatches_a_real_ui_tester_job`)
    para no depender de leer el estado de la cola en la ventana de una
    condición de carrera entre hilos."""
    from atlas_forge.agents.launch import launch_agent
    import atlas_forge.runtime.claude_code as claude_code_module
    from atlas_forge.dispatcher.ui_tester_queue import _instance as ui_tester_queue_instance
    from atlas_forge.dispatcher.ui_tester_queue import get_ui_tester_queue_status

    ui_tester_queue_instance.reset_for_testing()

    backlog_root = tmp_path / "backlog_root"
    backlog = backlog_root / "02-backlog"
    stories_dir = backlog / "user-stories"
    stories_dir.mkdir(parents=True)
    (stories_dir / "US-AF999-01-titulo.md").write_text(
        "---\nid: US-AF999-01\ntype: user-story\ntitle: Titulo\nstate: IN_REVIEW\n"
        "dependencies: []\nepic: AF-999\n---\n\n# US-AF999-01\n\n## Contexto\n\nC.\n",
        encoding="utf-8",
    )
    _write_task_yaml(backlog / "tasks", "T-AF999-US01-01", "US-AF999-01", "DONE", priority="Alta")

    reports_root = tmp_path / "informes"
    story_reports_dir = reports_root / "US-AF999-01"
    story_reports_dir.mkdir(parents=True)
    (story_reports_dir / "job-1.md").write_text(
        "# Informe de cierre\n\nCambios en `10-web/app.js` para el botón nuevo.\n",
        encoding="utf-8",
    )

    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)

    monkeypatch.setattr(
        claude_code_module, "DEFAULT_CLAUDE_CODE_COMMAND",
        "SIM_ROLE=architect_approved_verdict SIM_DELAY=0.1 bash",
    )
    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_ARGS", [_COOPERATIVE_AGENT_SCRIPT])

    architect, architect_runtime = launch_agent(
        "arquitecto", "claude-code", None, session, str(tmp_path), socket_name=isolated_socket
    )

    monkeypatch.setattr(
        claude_code_module, "DEFAULT_CLAUDE_CODE_COMMAND", "SIM_DELAY=0.1 bash",
    )
    tester, tester_runtime = launch_agent(
        "tester", "claude-code", None, session, str(tmp_path), socket_name=isolated_socket
    )

    worker = DispatchQueueWorker(backlog_root, "proj", session, socket_name=isolated_socket)
    try:
        # T-AF022-US06-06: despacho NO BLOQUEANTE del veredicto.
        result = worker.run_architect_verdict_once(reports_root=reports_root)
        assert result == "US-AF999-01"
        # Completión: el Arquitecto reporta APROBADO -> se promueve la US y
        # se encola el Tester de UI (story que toca 10-web/).
        assert _await_architect_verdict_resolved(worker, "US-AF999-01")

        for _ in range(100):
            status = get_ui_tester_queue_status()
            if status["active"] == "US-AF999-01" or "US-AF999-01" in status["waiting"]:
                break
            time.sleep(0.05)
        else:
            pytest.fail("El Job de Tester de UI nunca se encoló tras el veredicto aprobado.")

        for _ in range(100):
            status = get_ui_tester_queue_status()
            if status["active"] is None and status["waiting"] == []:
                break
            time.sleep(0.05)
        else:
            pytest.fail("La cola de Tester de UI nunca terminó de procesar.")

        assert tester.status == "idle"
    finally:
        stop_runtime(architect_runtime, socket_name=isolated_socket)
        stop_runtime(tester_runtime, socket_name=isolated_socket)

    assert result == "US-AF999-01"


def _mock_landing_send(tmp_path, monkeypatch, proposal_text=None):
    """Sustituye el envío no bloqueante del Job de aterrizaje (T-AF008-US16-01)
    por un doble determinista SIN tmux: `dispatch_job_send` devuelve un
    fichero de reporte (que opcionalmente ya contiene la propuesta +
    marcador, para los tests de flujo completo) y
    `get_runtime_instance_for_agent` entrega un runtime falso. Devuelve la
    ruta del fichero de reporte."""
    from atlas_forge.agents.lifecycle import mark_working
    from atlas_forge.dispatcher import dispatch_queue_worker as worker_module
    from atlas_forge.dispatcher.job_lifecycle import mark_running

    class _FakeRuntime:
        session_name = "test-session"

    monkeypatch.setattr(worker_module, "get_runtime_instance_for_agent", lambda agent_id: _FakeRuntime())

    report_path = tmp_path / "reporte-landing.txt"

    def _fake_send(job, agent, runtime_instance, socket_name=None):
        # Mismo efecto secundario que `dispatch_job_send` real: el Job pasa
        # a `running` y el Arquitecto a `working` (la completión los
        # finaliza). La propuesta (si se da) ya viaja escrita en el fichero
        # de reporte con el marcador de fin.
        mark_running(job)
        mark_working(agent)
        if proposal_text is not None:
            report_path.write_text(
                proposal_text + "\n___ATLAS_FORGE_JOB_DONE___\n", encoding="utf-8",
            )
        return report_path

    monkeypatch.setattr(worker_module, "dispatch_job_send", _fake_send)
    return report_path


def test_us_landing_dispatch_registers_inflight_job_and_writes_no_tasks(
    tmp_path, monkeypatch,
) -> None:
    """T-AF008-US16-01/US16-03: `run_us_landing_dispatch_cycle` con una US
    en TO_PLAN y un Arquitecto idle DESPACHA un Job de aterrizaje al
    Arquitecto (registrado en `inflight_landing` con su fichero de reporte)
    y NO escribe Tasks en proceso ni invoca los generadores deterministas
    (`propose_tasks_from_user_story`/`plan_us_landing`/`run_task_pipeline`)."""
    from unittest.mock import patch

    import atlas_forge.architect.propose_tasks as propose_tasks_module
    import atlas_forge.architect.task_pipeline as task_pipeline_module
    import atlas_forge.architect.us_landing as us_landing_module
    from atlas_forge.dispatcher.dispatch_queue_worker import run_us_landing_dispatch_cycle

    backlog_root, backlog, stories_dir, us_path, _graph = _make_landing_backlog(tmp_path)
    report_path = _mock_landing_send(tmp_path, monkeypatch)

    architect = Agent(id="arch-1", name="Arquitecto", role="arquitecto", prompt="p", runtime_id="r1")
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    assign_agent(session, architect)

    inflight_landing = {}
    with patch.object(
        propose_tasks_module, "propose_tasks_from_user_story",
        side_effect=AssertionError("no se debe invocar en el ciclo del Dispatcher"),
    ), patch.object(
        us_landing_module, "plan_us_landing",
        side_effect=AssertionError("no se debe invocar en el ciclo del Dispatcher"),
    ), patch.object(
        task_pipeline_module, "run_task_pipeline",
        side_effect=AssertionError("no se debe invocar en el ciclo del Dispatcher"),
    ):
        result = run_us_landing_dispatch_cycle(
            backlog_root, "proj", session, inflight_landing=inflight_landing,
        )

    assert result == "US-AF999-01"

    # El aterrizaje queda registrado en vuelo con su fichero de reporte.
    assert set(inflight_landing) == {"US-AF999-01"}
    infl = inflight_landing["US-AF999-01"]
    assert infl.us_id == "US-AF999-01"
    assert infl.architect_agent_id == "arch-1"
    assert infl.report_file == report_path
    assert infl.job is not None
    assert infl.dispatched_at > 0
    assert infl.us_item.id == "US-AF999-01"

    # No se escribió ninguna Task en proceso ni se tocó la US.
    assert list((backlog / "tasks").glob("*.md")) == []
    assert "state: TO_PLAN" in us_path.read_text(encoding="utf-8")


def test_us_landing_dispatch_cycle_returns_none_without_idle_architect(tmp_path) -> None:
    """T-AF008-US16-01: sin Arquitecto idle el ciclo no despacha nada
    (None) y no escribe Tasks."""
    from atlas_forge.dispatcher.dispatch_queue_worker import run_us_landing_dispatch_cycle

    backlog_root, backlog, stories_dir, us_path, _graph = _make_landing_backlog(tmp_path)

    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)

    result = run_us_landing_dispatch_cycle(
        backlog_root, "proj", session, inflight_landing={},
    )

    assert result is None
    assert "state: TO_PLAN" in us_path.read_text(encoding="utf-8")
    assert list((backlog / "tasks").glob("*.md")) == []


def test_us_landing_dispatch_cycle_returns_none_without_to_plan_story(
    tmp_path, monkeypatch,
) -> None:
    """T-AF008-US16-01: sin US en TO_PLAN el ciclo no despacha nada (None)
    aunque haya Arquitecto idle y runtime."""
    from atlas_forge.dispatcher.dispatch_queue_worker import run_us_landing_dispatch_cycle

    backlog_root = tmp_path / "backlog_root"
    backlog = backlog_root / "02-backlog"
    stories_dir = backlog / "user-stories"
    stories_dir.mkdir(parents=True)
    (backlog / "tasks").mkdir(parents=True)
    (stories_dir / "US-AF999-01-titulo.md").write_text(
        "---\nid: US-AF999-01\ntype: user_story\ntitle: Titulo\nstate: READY\n"
        "dependencies: []\nepic: AF-999\npriority: Alta\n---\n\n## Historia\n\nH.\n",
        encoding="utf-8",
    )

    architect = Agent(id="arch-1", name="Arquitecto", role="arquitecto", prompt="p", runtime_id="r1")
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    assign_agent(session, architect)
    _mock_landing_send(tmp_path, monkeypatch)

    result = run_us_landing_dispatch_cycle(
        backlog_root, "proj", session, inflight_landing={},
    )

    assert result is None
    assert list((backlog / "tasks").glob("*.md")) == []


def test_us_landing_dispatch_never_produces_template_trio(tmp_path, monkeypatch) -> None:
    """T-AF008-US16-03 (guardián): el ciclo del Dispatcher NO produce el
    trío de plantillas genéricas ('implementar la logica central' /
    'conectar la logica a su contexto de uso' / 'validar el flujo completo').
    El aterrizaje solo despacha el Job al Arquitecto; la generación de Tasks
    es responsabilidad del agente (vía completión), nunca del generador
    determinista en proceso. Este guardián falla si alguien vuelve a llamar
    al generador de plantillas desde el ciclo del Dispatcher."""
    from unittest.mock import patch

    import atlas_forge.architect.propose_tasks as propose_tasks_module
    from atlas_forge.dispatcher.dispatch_queue_worker import run_us_landing_dispatch_cycle

    backlog_root, backlog, stories_dir, us_path, _graph = _make_landing_backlog(tmp_path)
    _mock_landing_send(tmp_path, monkeypatch)

    architect = Agent(id="arch-1", name="Arquitecto", role="arquitecto", prompt="p", runtime_id="r1")
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    assign_agent(session, architect)

    with patch.object(
        propose_tasks_module, "propose_tasks_from_user_story",
        side_effect=AssertionError("las plantillas genéricas no deben generarse desde el ciclo"),
    ) as spy:
        result = run_us_landing_dispatch_cycle(
            backlog_root, "proj", session, inflight_landing={},
        )

    assert result == "US-AF999-01"
    assert spy.call_count == 0

    # Ni rastro del trío de plantillas en el backlog de Tasks tras el ciclo.
    for task_file in (backlog / "tasks").glob("*.md"):
        content = task_file.read_text(encoding="utf-8")
        for plantilla in (
            "implementar la logica central",
            "conectar la logica a su contexto de uso",
            "validar el flujo completo",
        ):
            assert plantilla not in content


def test_us_landing_full_flow_via_worker_loop(tmp_path, monkeypatch) -> None:
    """T-AF008-US16-03: ejercita el camino real de invocación del aterrizaje
    — el hilo de polling del `DispatchQueueWorker` (`_run_loop`), no solo las
    funciones sueltas, SIN tmux. El envío real del Job se sustituye por un
    doble que ya entrega la propuesta válida + marcador en el fichero de
    reporte, así el ciclo de completión la valida y escribe las Tasks (US
    TO_PLAN -> READY) por el camino real de polling."""
    from atlas_forge.dispatcher.dispatch_queue_worker import DispatchQueueWorker

    backlog_root, backlog, stories_dir, us_path, _graph = _make_landing_backlog(tmp_path)
    _mock_landing_send(tmp_path, monkeypatch, proposal_text=_VALID_LANDING_PROPOSAL)

    architect = Agent(id="arch-1", name="Arquitecto", role="arquitecto", prompt="p", runtime_id="r1")
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    assign_agent(session, architect)

    worker = DispatchQueueWorker(
        backlog_root, "proj", session, poll_interval_seconds=0.05
    )
    try:
        worker.start()
        # El hilo real del worker recorre los 4 niveles + completiones; la
        # US en TO_PLAN se despacha en un ciclo y se completa en otro.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            story_text = (stories_dir / "US-AF999-01-titulo.md").read_text(encoding="utf-8")
            if "state: READY" in story_text:
                break
            time.sleep(0.1)
    finally:
        worker.stop()

    story_text = (stories_dir / "US-AF999-01-titulo.md").read_text(encoding="utf-8")
    assert "state: READY" in story_text, "La US debe quedar READY tras el aterrizaje en el hilo real."
    generated_tasks = list((backlog / "tasks").glob("T-AF999-US01-*.md"))
    assert len(generated_tasks) > 0, "La propuesta válida debe haberse escrito como Task real en el flujo completo."


def test_story_is_fully_done_true_only_when_every_task_is_done(tmp_path) -> None:
    from atlas_forge.backlog.parser import load_backlog
    from atlas_forge.dispatcher.dispatch_queue_worker import story_is_fully_done

    backlog = tmp_path / "02-backlog"
    _write_task_yaml(backlog / "tasks", "T-AF999-US01-01", "US-AF999-01", "DONE")
    _write_task_yaml(backlog / "tasks", "T-AF999-US01-02", "US-AF999-01", "IN_REVIEW")
    graph = load_backlog(backlog)

    assert story_is_fully_done(graph, "US-AF999-01") is False

    (backlog / "tasks" / "T-AF999-US01-02.md").write_text(
        (backlog / "tasks" / "T-AF999-US01-02.md").read_text(encoding="utf-8").replace(
            "state: IN_REVIEW", "state: DONE"
        ),
        encoding="utf-8",
    )
    graph = load_backlog(backlog)
    assert story_is_fully_done(graph, "US-AF999-01") is True


# ---------------------------------------------------------------------------
# T-AF008-US16: aterrizaje US→Tasks vía Arquitecto — completión por polling
# (T-AF008-US16-02).
# ---------------------------------------------------------------------------

_VALID_LANDING_PROPOSAL = """tasks:
  - id: T-AF999-US01-01
    title: Implementar modulo central
    objective: Implementar la logica central
    description: Descripcion detallada.
    criteria:
      - La logica funciona.
    priority: Alta
    difficulty: Alta
    dependencies: []
    epic_id: AF-999
    us_id: US-AF999-01
"""

_INVALID_LANDING_PROPOSAL = """tasks:
  - id: not-a-valid-id
    title: Task invalida
    objective: Objetivo.
    description: Desc.
    criteria:
      - C1
    priority: Alta
    difficulty: Alta
    dependencies: []
    epic_id: AF-999
    us_id: US-AF999-01
"""


def _make_landing_backlog(tmp_path):
    from atlas_forge.backlog.parser import load_backlog

    backlog_root = tmp_path / "backlog_root"
    backlog = backlog_root / "02-backlog"
    stories_dir = backlog / "user-stories"
    stories_dir.mkdir(parents=True)
    (backlog / "tasks").mkdir(parents=True)
    us_path = stories_dir / "US-AF999-01-titulo.md"
    us_path.write_text(
        "---\nid: US-AF999-01\ntype: user_story\ntitle: Titulo\nstate: TO_PLAN\n"
        "dependencies: []\nepic: AF-999\npriority: Alta\n---\n\n"
        "## Historia\n\nConstruir cola de mensajes interna.\n\n"
        "## Criterios de aceptación\n\n- CR1: La cola encola y desencola.\n",
        encoding="utf-8",
    )
    return backlog_root, backlog, stories_dir, us_path, load_backlog(backlog)


def _inflight_landing(report_file, us_item, dispatched_at):
    from atlas_forge.agents.lifecycle import mark_working
    from atlas_forge.dispatcher.dispatch_queue_worker import InFlightLandingJob
    from atlas_forge.dispatcher.job_creation import create_job
    from atlas_forge.dispatcher.job_lifecycle import mark_running

    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    architect = Agent(id="arch-1", name="Arquitecto", role="arquitecto", prompt="p", runtime_id="r1")
    assign_agent(session, architect)
    job = create_job("Aterrizar US-AF999-01 en Tasks", architect, session)
    # Simula el envío no bloqueante de `dispatch_job_send` (T-AF008-US16-01):
    # el Job pasa a `running` y el Arquitecto a `working`.
    mark_running(job)
    mark_working(architect)
    return InFlightLandingJob(
        us_id="US-AF999-01", architect_agent_id="arch-1",
        report_file=report_file, job=job, dispatched_at=dispatched_at, us_item=us_item,
    )


def test_landing_completion_valid_proposal_writes_tasks_and_readies_us(tmp_path) -> None:
    """T-AF008-US16-02: una propuesta con Tasks válidas escribe las Tasks
    (validadas con `validate_backlog_file_v2`) y la US pasa a READY."""
    from atlas_forge.dispatcher.dispatch_queue_worker import poll_inflight_landing_completions

    backlog_root, backlog, stories_dir, us_path, graph = _make_landing_backlog(tmp_path)
    report_file = tmp_path / "propuesta.md"
    report_file.write_text(_VALID_LANDING_PROPOSAL + "\n___ATLAS_FORGE_JOB_DONE___\n", encoding="utf-8")

    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    inflight = {"US-AF999-01": _inflight_landing(report_file, graph.items["US-AF999-01"], time.monotonic())}

    resolved = poll_inflight_landing_completions(backlog_root, session, inflight)

    assert resolved == ["US-AF999-01"]
    assert inflight == {}
    assert "state: READY" in us_path.read_text(encoding="utf-8")
    written = list((backlog / "tasks").glob("*.md"))
    assert len(written) == 1
    assert written[0].exists()


def test_landing_completion_invalid_proposal_keeps_us_in_plan(tmp_path) -> None:
    """T-AF008-US16-02: una propuesta con alguna Task inválida NO escribe esa
    Task; si ninguna es válida, la US queda TO_PLAN sin cambios."""
    from atlas_forge.dispatcher.dispatch_queue_worker import poll_inflight_landing_completions

    backlog_root, backlog, stories_dir, us_path, graph = _make_landing_backlog(tmp_path)
    report_file = tmp_path / "propuesta.md"
    report_file.write_text(_INVALID_LANDING_PROPOSAL + "\n___ATLAS_FORGE_JOB_DONE___\n", encoding="utf-8")

    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    inflight = {"US-AF999-01": _inflight_landing(report_file, graph.items["US-AF999-01"], time.monotonic())}

    resolved = poll_inflight_landing_completions(backlog_root, session, inflight)

    assert resolved == ["US-AF999-01"]
    assert "state: TO_PLAN" in us_path.read_text(encoding="utf-8")
    assert list((backlog / "tasks").glob("*.md")) == []


def test_landing_completion_timeout_keeps_us_in_plan(tmp_path) -> None:
    """T-AF008-US16-02: timeout sin propuesta -> Job failed y US TO_PLAN
    re-encolable, sin bloquear."""
    from atlas_forge.dispatcher.dispatch_queue_worker import poll_inflight_landing_completions

    backlog_root, backlog, stories_dir, us_path, graph = _make_landing_backlog(tmp_path)
    missing_report = tmp_path / "no-existe.md"  # nunca se escribe

    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    inflight = {"US-AF999-01": _inflight_landing(
        missing_report, graph.items["US-AF999-01"], time.monotonic() - 1000.0,
    )}

    resolved = poll_inflight_landing_completions(
        backlog_root, session, inflight, timeout_seconds=0.5,
    )

    assert resolved == ["US-AF999-01"]
    assert inflight == {}
    assert "state: TO_PLAN" in us_path.read_text(encoding="utf-8")
    assert list((backlog / "tasks").glob("*.md")) == []


def test_review_completion_passed_verdict_terminalizes_queue_entry(tmp_path) -> None:
    """T-AF008-US10-04, criterio 1: un veredicto EXITO del Tester (Task ->
    DONE) terminaliza la entrada `dispatched` de `dispatch_queue.json` a
    `completed` — la UI deja de poder mostrarla como "En curso" y
    `GET /backlog/queue` la deriva a `completed` aunque el estado
    almacenado quedara desincronizado."""
    from atlas_forge.dispatcher.dispatch_queue_worker import (
        InFlightReviewJob,
        poll_inflight_review_completions,
    )
    from atlas_forge.dispatcher.job_creation import create_job
    from atlas_forge.dispatcher.job_lifecycle import mark_running
    from atlas_forge.agents.lifecycle import mark_working
    from atlas_forge.backlog.parser import load_backlog

    backlog_root = tmp_path / "backlog_root"
    backlog = backlog_root / "02-backlog"
    _write_task_yaml(backlog / "tasks", "T-AF999-US01-01", "US-AF999-01", "IN_REVIEW", priority="Alta")
    enqueue_task(backlog_root, "proj", task_id="T-AF999-US01-01", us_id="US-AF999-01", priority="Alta")
    mark_dispatched(backlog_root, "proj", "T-AF999-US01-01", agent_id="a-dev", agent_name="Developer-1")

    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    tester = Agent(id="t-1", name="Tester", role="tester", prompt="p", runtime_id="r1")
    assign_agent(session, tester)

    job = create_job("Verifica la Task T-AF999-US01-01", tester, session)
    mark_running(job)
    mark_working(tester)
    report_file = tmp_path / "veredicto.md"
    report_file.write_text(
        "RESULTADO: EXITO\n"
        "RESUMEN:\nTodos los criterios de aceptación se cumplen.\n"
        "SIGUIENTE_PASO:\n(sin correcciones pendientes)\n"
        "___ATLAS_FORGE_JOB_DONE___\n",
        encoding="utf-8",
    )

    graph = load_backlog(backlog)
    inflight_review = {
        "T-AF999-US01-01": InFlightReviewJob(
            task_id="T-AF999-US01-01",
            tester_agent_id="t-1",
            report_file=report_file,
            job=job,
            dispatched_at=time.monotonic(),
            task_item=graph.items["T-AF999-US01-01"],
        )
    }

    resolved = poll_inflight_review_completions(
        backlog_root, "proj", session, inflight_review, {}, timeout_seconds=5,
    )

    assert resolved == ["T-AF999-US01-01"]
    assert inflight_review == {}
    task_text = (backlog / "tasks" / "T-AF999-US01-01.md").read_text(encoding="utf-8")
    assert "state: DONE" in task_text
    entries = get_queue(backlog_root, "proj")
    assert entries[0].status == STATUS_COMPLETED
    assert entries[0].result == "Veredicto EXITO del Tester."
