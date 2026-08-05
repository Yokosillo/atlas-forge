import uuid
from pathlib import Path
from unittest.mock import patch

import libtmux
import pytest

from brain.core.session_lifecycle import activate, assign_agent
from brain.dispatcher import JobPlanDispatchError, dispatch_plan, get_plan_progress
from brain.dispatcher.job_report import read_job_report
from brain.local_tools import ScribeUnavailableError
from brain.models import Agent, DevelopmentSession, JobPlan, JobPlanStep, Runtime
from brain.runtime import register_runtime_instance_for_agent, start_runtime, stop_runtime

_COOPERATIVE_AGENT_SCRIPT = str(
    Path(__file__).parent / "fixtures" / "cooperative_agent_sim.sh"
)


@pytest.fixture
def isolated_socket():
    """Mismo patrón de aislamiento ya usado en test_job_dispatch.py /
    test_job_chaining.py: servidor tmux propio por test, nunca el binario
    real de un runtime."""
    name = f"brain-test-{uuid.uuid4().hex[:8]}"
    try:
        yield name
    finally:
        try:
            libtmux.Server(socket_name=name).kill()
        except Exception:
            pass


def _active_session_with_developer(agent: Agent) -> DevelopmentSession:
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    assign_agent(session, agent)
    return session


def _launch_cooperative_developer(
    isolated_socket: str, tmp_path, extra_env: str = ""
) -> Agent:
    command = f"{extra_env} bash".strip()
    runtime = Runtime(
        id="test-runtime",
        name="Test Runtime",
        type="test",
        command=command,
        args=[_COOPERATIVE_AGENT_SCRIPT],
    )
    agent = Agent(
        id="a-dev", name="developer", role="developer", prompt="p", runtime_id="r1"
    )
    runtime_instance = start_runtime(runtime, agent, str(tmp_path), socket_name=isolated_socket)
    register_runtime_instance_for_agent(agent.id, runtime_instance)
    return agent, runtime_instance


def test_dispatch_plan_rejects_a_plan_that_is_not_approved() -> None:
    plan = JobPlan(
        goal="FB999-US01",
        steps=[JobPlanStep(description="paso", mechanism="agent", agent_role="developer")],
        status="proposed",
    )
    session = DevelopmentSession(id="s1", project_id="p1")

    with pytest.raises(JobPlanDispatchError):
        dispatch_plan(plan, session)

    assert plan.status == "proposed"
    assert plan.steps[0].status == "pending"


def test_dispatch_plan_executes_three_agent_steps_in_order_waiting_for_each(
    isolated_socket: str, tmp_path
) -> None:
    agent, runtime_instance = _launch_cooperative_developer(isolated_socket, tmp_path)
    session = _active_session_with_developer(agent)
    plan = JobPlan(
        goal="FB999-US01",
        steps=[
            JobPlanStep(description="paso 1", mechanism="agent", agent_role="developer"),
            JobPlanStep(description="paso 2", mechanism="agent", agent_role="developer"),
            JobPlanStep(description="paso 3", mechanism="agent", agent_role="developer"),
        ],
        status="approved",
    )

    try:
        dispatch_plan(plan, session, socket_name=isolated_socket)
    finally:
        stop_runtime(runtime_instance, socket_name=isolated_socket)

    assert plan.status == "approved"
    assert [step.status for step in plan.steps] == ["completed", "completed", "completed"]
    assert all("cooperative result" in step.result for step in plan.steps)


def test_dispatch_plan_stops_and_blocks_on_first_failing_step(
    isolated_socket: str, tmp_path
) -> None:
    agent, runtime_instance = _launch_cooperative_developer(isolated_socket, tmp_path)
    session = _active_session_with_developer(agent)
    plan = JobPlan(
        goal="FB999-US01",
        steps=[
            JobPlanStep(description="paso 1", mechanism="scribe"),
            # Sin ningún agente "critic" en la sesión: causa de fallo real y
            # verificable (ver nota en test_get_plan_progress... sobre por
            # qué SIM_FAIL=1 no sirve para simular un Job realmente failed).
            JobPlanStep(description="paso 2", mechanism="agent", agent_role="critic"),
            JobPlanStep(description="paso 3", mechanism="agent", agent_role="developer"),
        ],
        status="approved",
    )

    with patch(
        "brain.dispatcher.job_plan_dispatch.summarize_document",
        return_value="resumen ok",
    ):
        try:
            dispatch_plan(plan, session, socket_name=isolated_socket)
        finally:
            stop_runtime(runtime_instance, socket_name=isolated_socket)

    assert plan.status == "blocked"
    assert plan.steps[0].status == "completed"
    assert plan.steps[1].status == "failed"
    # El paso 3 no se despacha en absoluto tras el fallo del paso 2.
    assert plan.steps[2].status == "pending"


def test_dispatch_plan_marks_script_step_as_pending_without_blocking_the_rest(
    isolated_socket: str, tmp_path
) -> None:
    agent, runtime_instance = _launch_cooperative_developer(isolated_socket, tmp_path)
    session = _active_session_with_developer(agent)
    plan = JobPlan(
        goal="FB999-US01",
        steps=[
            JobPlanStep(description="ejecutar script de limpieza", mechanism="script"),
            JobPlanStep(description="paso agente", mechanism="agent", agent_role="developer"),
        ],
        status="approved",
    )

    try:
        dispatch_plan(plan, session, socket_name=isolated_socket)
    finally:
        stop_runtime(runtime_instance, socket_name=isolated_socket)

    assert plan.status == "approved"
    assert plan.steps[0].status == "pending"
    assert plan.steps[1].status == "completed"


def test_dispatch_plan_marks_plan_blocked_when_scribe_step_is_unavailable() -> None:
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    plan = JobPlan(
        goal="FB999-US01",
        steps=[JobPlanStep(description="resumir con scribe", mechanism="scribe")],
        status="approved",
    )

    with patch(
        "brain.dispatcher.job_plan_dispatch.summarize_document",
        side_effect=ScribeUnavailableError("Ollama no disponible"),
    ):
        dispatch_plan(plan, session)

    assert plan.status == "blocked"
    assert plan.steps[0].status == "failed"


def test_dispatch_plan_blocks_when_no_agent_with_required_role_exists() -> None:
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    plan = JobPlan(
        goal="FB999-US01",
        steps=[JobPlanStep(description="paso", mechanism="agent", agent_role="critic")],
        status="approved",
    )

    dispatch_plan(plan, session)

    assert plan.status == "blocked"
    assert plan.steps[0].status == "failed"


def test_get_plan_progress_reflects_step_states_after_partial_dispatch(
    isolated_socket: str, tmp_path
) -> None:
    agent, runtime_instance = _launch_cooperative_developer(isolated_socket, tmp_path)
    session = _active_session_with_developer(agent)
    plan = JobPlan(
        goal="FB999-US01",
        steps=[
            JobPlanStep(description="paso 1", mechanism="agent", agent_role="developer"),
            # No hay ningún agente con role "critic" en la sesión — causa de
            # fallo real y verificable sin depender de SIM_FAIL (que solo
            # simula un mensaje de fallo textual, no un Job realmente
            # `failed`: el auto-reporte cooperativo de dispatch_job marca
            # `completed` en cuanto recibe cualquier reporte con marcador de
            # fin, sea cual sea su contenido).
            JobPlanStep(description="paso 2", mechanism="agent", agent_role="critic"),
        ],
        status="approved",
    )

    try:
        dispatch_plan(plan, session, socket_name=isolated_socket)
    finally:
        stop_runtime(runtime_instance, socket_name=isolated_socket)

    progress = get_plan_progress(plan)

    assert progress["goal"] == "FB999-US01"
    assert progress["status"] == "blocked"
    assert progress["steps"][0]["status"] == "completed"
    assert progress["steps"][1]["status"] == "failed"


def test_dispatch_plan_invokes_the_step_status_callback_for_each_transition(
    isolated_socket: str, tmp_path
) -> None:
    """T-FB017-US04-03: `on_step_status_changed` se invoca en cada cambio
    de estado observable de un paso — al pasar a `running` Y al
    resolverse (`completed` en este caso, dos pasos reales, tmux real) —
    no solo al final de la secuencia entera."""
    agent, runtime_instance = _launch_cooperative_developer(isolated_socket, tmp_path)
    session = _active_session_with_developer(agent)
    plan = JobPlan(
        goal="FB999-US01",
        steps=[
            JobPlanStep(description="paso 1", mechanism="agent", agent_role="developer"),
            JobPlanStep(description="paso 2", mechanism="agent", agent_role="developer"),
        ],
        status="approved",
    )

    observed_step_statuses: list[list[str]] = []

    def _record(dispatched_plan: JobPlan) -> None:
        observed_step_statuses.append([step.status for step in dispatched_plan.steps])

    try:
        dispatch_plan(
            plan, session, socket_name=isolated_socket, on_step_status_changed=_record
        )
    finally:
        stop_runtime(runtime_instance, socket_name=isolated_socket)

    # 4 notificaciones: paso1->running, paso1->completed, paso2->running,
    # paso2->completed — visibilidad real de cada paso individual, no solo
    # un evento al final de toda la secuencia.
    assert observed_step_statuses == [
        ["running", "pending"],
        ["completed", "pending"],
        ["completed", "running"],
        ["completed", "completed"],
    ]


def test_dispatch_plan_completes_normally_even_if_the_callback_raises(
    isolated_socket: str, tmp_path
) -> None:
    """El callback es una notificación de mejor esfuerzo — un fallo suyo
    (p. ej. un error real al publicar en el WebSocket) no debe interrumpir
    el despacho real del plan."""
    agent, runtime_instance = _launch_cooperative_developer(isolated_socket, tmp_path)
    session = _active_session_with_developer(agent)
    plan = JobPlan(
        goal="FB999-US01",
        steps=[JobPlanStep(description="paso 1", mechanism="agent", agent_role="developer")],
        status="approved",
    )

    def _broken_callback(_dispatched_plan: JobPlan) -> None:
        raise RuntimeError("fallo simulado al publicar en el WebSocket")

    try:
        dispatch_plan(
            plan, session, socket_name=isolated_socket, on_step_status_changed=_broken_callback
        )
    finally:
        stop_runtime(runtime_instance, socket_name=isolated_socket)

    assert plan.status == "approved"
    assert plan.steps[0].status == "completed"


def test_find_agent_by_role_disambiguates_by_agent_id() -> None:
    from brain.dispatcher.job_plan_dispatch import _find_agent_by_role

    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    dev1 = Agent(id="dev-1", name="Developer-1", role="developer", prompt="p", runtime_id="r1")
    dev2 = Agent(id="dev-2", name="Developer-2", role="developer", prompt="p", runtime_id="r1")
    assign_agent(session, dev1)
    assign_agent(session, dev2)

    found_dev2 = _find_agent_by_role(session, "developer", agent_id="dev-2")
    assert found_dev2 is not None
    assert found_dev2.id == "dev-2"

    found_dev1 = _find_agent_by_role(session, "developer", agent_id="dev-1")
    assert found_dev1 is not None
    assert found_dev1.id == "dev-1"

    found_nonexistent = _find_agent_by_role(session, "developer", agent_id="dev-3")
    assert found_nonexistent is None


def test_find_agent_by_role_no_agent_id_returns_first_match() -> None:
    from brain.dispatcher.job_plan_dispatch import _find_agent_by_role

    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    dev1 = Agent(id="dev-1", name="Developer-1", role="developer", prompt="p", runtime_id="r1")
    dev2 = Agent(id="dev-2", name="Developer-2", role="developer", prompt="p", runtime_id="r1")
    assign_agent(session, dev1)
    assign_agent(session, dev2)

    found = _find_agent_by_role(session, "developer")
    assert found is not None
    assert found.id == "dev-1"


def test_dispatch_plan_disambiguates_multiple_developers_by_agent_id(
    isolated_socket: str, tmp_path
) -> None:
    dev1, ri1 = _launch_cooperative_developer(isolated_socket, tmp_path)
    dev1.id = "dev-1"
    dev1.name = "Developer-1"
    register_runtime_instance_for_agent(dev1.id, ri1)

    dev2, ri2 = _launch_cooperative_developer(isolated_socket, tmp_path)
    dev2.id = "dev-2"
    dev2.name = "Developer-2"
    register_runtime_instance_for_agent(dev2.id, ri2)

    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    assign_agent(session, dev1)
    assign_agent(session, dev2)

    plan = JobPlan(
        goal="FB999-US01",
        steps=[
            JobPlanStep(
                description="paso dev-2",
                mechanism="agent",
                agent_role="developer",
                agent_id="dev-2",
            ),
            JobPlanStep(
                description="paso dev-1",
                mechanism="agent",
                agent_role="developer",
                agent_id="dev-1",
            ),
        ],
        status="approved",
    )

    try:
        dispatch_plan(plan, session, socket_name=isolated_socket)
    finally:
        stop_runtime(ri1, socket_name=isolated_socket)
        stop_runtime(ri2, socket_name=isolated_socket)

    assert plan.status == "approved"
    assert plan.steps[0].status == "completed"
    assert plan.steps[1].status == "completed"


def test_dispatch_plan_blocks_when_agent_id_does_not_match_any_agent() -> None:
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    dev1 = Agent(
        id="dev-1", name="Developer-1", role="developer", prompt="p", runtime_id="r1"
    )
    assign_agent(session, dev1)

    plan = JobPlan(
        goal="FB999-US01",
        steps=[
            JobPlanStep(
                description="paso",
                mechanism="agent",
                agent_role="developer",
                agent_id="dev-3",
            ),
        ],
        status="approved",
    )

    dispatch_plan(plan, session)

    assert plan.status == "blocked"
    assert plan.steps[0].status == "failed"


def test_dispatch_plan_without_callback_behaves_exactly_as_before(
    isolated_socket: str, tmp_path
) -> None:
    """`on_step_status_changed=None` (valor por defecto) no cambia el
    comportamiento ya existente — regresión explícita de compatibilidad
    hacia atrás para cualquier llamador que no lo use (p. ej.
    `run_job_plan`, T-FB008-US04-04).
    
    T-FB022-US06-03: además de la regresión de compatibilidad, verifica que
    el informe de cierre del Job se escribe en
    07-informes/<story_id>/<job_id>.md."""
    agent, runtime_instance = _launch_cooperative_developer(isolated_socket, tmp_path)
    session = _active_session_with_developer(agent)
    plan = JobPlan(
        goal="US-FB022-06",
        steps=[JobPlanStep(description="paso 1", mechanism="agent", agent_role="developer")],
        status="approved",
    )

    written_paths = []

    def _fake_write(job, reports_root=None):
        from pathlib import Path as _P

        root = _P(reports_root) if reports_root else _P(tmp_path)
        story_dir = root / (job.story_id or "_sin-story")
        story_dir.mkdir(parents=True, exist_ok=True)
        p = story_dir / f"{job.id}.md"
        p.write_text(f"Estado: {job.status}\nResultado: {job.result}\n", encoding="utf-8")
        written_paths.append(p)
        return p

    with patch(
        "brain.dispatcher.job_plan_dispatch.write_job_report",
        side_effect=_fake_write,
    ):
        try:
            dispatch_plan(plan, session, socket_name=isolated_socket)
        finally:
            stop_runtime(runtime_instance, socket_name=isolated_socket)

    assert plan.status == "approved"
    assert plan.steps[0].status == "completed"

    assert len(written_paths) == 1
    content = written_paths[0].read_text()
    assert "completed" in content
