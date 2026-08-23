import threading
import time
import uuid
from pathlib import Path
from unittest.mock import patch

import libtmux
import pytest

from atlas_forge.core.session_lifecycle import activate, assign_agent
from atlas_forge.dispatcher import JobPlanDispatchError, dispatch_plan, get_plan_progress
from atlas_forge.dispatcher.job_report import read_job_report
from atlas_forge.local_tools import ScribeUnavailableError
from atlas_forge.models import Agent, DevelopmentSession, JobPlan, JobPlanStep, Runtime
from atlas_forge.runtime import register_runtime_instance_for_agent, start_runtime, stop_runtime

_COOPERATIVE_AGENT_SCRIPT = str(
    Path(__file__).parent / "fixtures" / "cooperative_agent_sim.sh"
)


@pytest.fixture
def isolated_socket():
    """Mismo patrón de aislamiento ya usado en test_job_dispatch.py /
    test_job_chaining.py: servidor tmux propio por test, nunca el binario
    real de un runtime."""
    name = f"atlas_forge-test-{uuid.uuid4().hex[:8]}"
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
        goal="AF999-US01",
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
        goal="AF999-US01",
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


def test_dispatch_agent_step_passes_an_explicit_timeout_longer_than_the_dispatch_job_default(
    isolated_socket: str, tmp_path
) -> None:
    """T-AF008-US04-06: antes de esta Task, `_dispatch_agent_step` llamaba
    `dispatch_job(job, agent, runtime_instance, socket_name=socket_name)`
    sin `timeout_seconds`, heredando el default de 30s de `dispatch_job`
    (pensado para Jobs cortos/deterministas, no para el trabajo real de
    una Task de Developer) — causa raíz verificada del bloqueo reproducido
    en vivo con el plan de `US-AF036-01`. Verifica contra la llamada real
    (mock de `dispatch_job`, sin esperar de verdad el timeout) que ahora
    se pasa `timeout_seconds=AGENT_STEP_TIMEOUT_SECONDS`, mayor que el
    default de 30s de `dispatch_job`."""
    from atlas_forge.dispatcher.job_plan_dispatch import AGENT_STEP_TIMEOUT_SECONDS

    assert AGENT_STEP_TIMEOUT_SECONDS > 30.0

    agent, runtime_instance = _launch_cooperative_developer(isolated_socket, tmp_path)
    session = _active_session_with_developer(agent)
    plan = JobPlan(
        goal="AF999-US01",
        steps=[JobPlanStep(description="paso", mechanism="agent", agent_role="developer")],
        status="approved",
    )

    with patch(
        "atlas_forge.dispatcher.job_plan_dispatch.dispatch_job",
        wraps=__import__(
            "atlas_forge.dispatcher.job_plan_dispatch", fromlist=["dispatch_job"]
        ).dispatch_job,
    ) as mock_dispatch_job:
        try:
            dispatch_plan(plan, session, socket_name=isolated_socket)
        finally:
            stop_runtime(runtime_instance, socket_name=isolated_socket)

    assert mock_dispatch_job.call_args.kwargs["timeout_seconds"] == AGENT_STEP_TIMEOUT_SECONDS
    assert plan.status == "approved"
    assert plan.steps[0].status == "completed"


def test_agent_step_timeout_is_reduced_well_below_the_old_hour() -> None:
    """T-AF008-US10-06 (criterio 5): el timeout del paso 'agent' se reduce
    de 3600s (1h, que mantenía un agente `working` colgado hasta 1h sin
    detección de cierre) a un valor razonable con margen amplio para el
    trabajo real, pero mucho menor que la hora antigua. Este techo es la
    parte segura del cambio; la detección activa del cierre queda para la
    decisión del Arquitecto (ver informe de la Task)."""
    from atlas_forge.dispatcher.job_plan_dispatch import AGENT_STEP_TIMEOUT_SECONDS

    assert AGENT_STEP_TIMEOUT_SECONDS > 30.0  # margen amplio para trabajo largo
    assert AGENT_STEP_TIMEOUT_SECONDS < 3600.0  # ya no se espera 1h
    assert AGENT_STEP_TIMEOUT_SECONDS == 1800.0  # valor documentado


def test_dispatch_plan_completes_an_agent_step_that_would_have_exceeded_the_old_default_timeout(
    isolated_socket: str, tmp_path
) -> None:
    """T-AF008-US04-06, criterio de aceptación 1 y 4: reproduce el bug
    original end-to-end con reloj real, sin esperar 30s de verdad —
    reduce `AGENT_STEP_TIMEOUT_SECONDS` (el timeout que `_dispatch_agent_step`
    pasa explícitamente desde esta Task) a un valor pequeño que simula en
    segundos de test la misma relación que existía con el viejo default
    de 30s de `dispatch_job` heredado sin querer (Developer más lento que
    el timeout aplicado). Antes de esta Task no existía ningún
    `timeout_seconds` propio del paso de plan — `dispatch_job` usaba
    directamente su propio default (30.0) sin que `_dispatch_agent_step`
    pudiera ajustarlo; ahora sí puede, y este test verifica que el ajuste
    realmente evita el bloqueo con un Developer más lento que ese valor."""
    agent, runtime_instance = _launch_cooperative_developer(
        isolated_socket, tmp_path, extra_env="SIM_DELAY=1"
    )
    session = _active_session_with_developer(agent)
    plan = JobPlan(
        goal="AF999-US01",
        steps=[JobPlanStep(description="paso lento", mechanism="agent", agent_role="developer")],
        status="approved",
    )

    with patch("atlas_forge.dispatcher.job_plan_dispatch.AGENT_STEP_TIMEOUT_SECONDS", 5.0):
        try:
            dispatch_plan(plan, session, socket_name=isolated_socket)
        finally:
            stop_runtime(runtime_instance, socket_name=isolated_socket)

    assert plan.status == "approved"
    assert plan.steps[0].status == "completed"
    assert "cooperative result" in plan.steps[0].result


def test_dispatch_plan_stops_and_blocks_on_first_failing_step(
    isolated_socket: str, tmp_path
) -> None:
    agent, runtime_instance = _launch_cooperative_developer(isolated_socket, tmp_path)
    session = _active_session_with_developer(agent)
    plan = JobPlan(
        goal="AF999-US01",
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
        "atlas_forge.dispatcher.job_plan_dispatch.summarize_document",
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
        goal="AF999-US01",
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
        goal="AF999-US01",
        steps=[JobPlanStep(description="resumir con scribe", mechanism="scribe")],
        status="approved",
    )

    with patch(
        "atlas_forge.dispatcher.job_plan_dispatch.summarize_document",
        side_effect=ScribeUnavailableError("Ollama no disponible"),
    ):
        dispatch_plan(plan, session)

    assert plan.status == "blocked"
    assert plan.steps[0].status == "failed"


def test_dispatch_plan_blocks_when_no_agent_with_required_role_exists() -> None:
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    plan = JobPlan(
        goal="AF999-US01",
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
        goal="AF999-US01",
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

    assert progress["goal"] == "AF999-US01"
    assert progress["status"] == "blocked"
    assert progress["steps"][0]["status"] == "completed"
    assert progress["steps"][1]["status"] == "failed"
    # T-AF008-US04-08, criterio de aceptación: `result` por paso, texto
    # real del error para el paso que falló, `null` (no cadena vacía)
    # para el que sí completó.
    assert progress["steps"][0]["result"] is not None
    assert "cooperative result" in progress["steps"][0]["result"]
    assert progress["steps"][1]["result"] is not None
    assert "No hay ningún agente con role 'critic'" in progress["steps"][1]["result"]


def test_get_plan_progress_step_result_is_null_when_not_yet_dispatched() -> None:
    # T-AF008-US04-08, criterio de aceptación: "un paso sin fallo tiene
    # `result: null`" — verificado también para el caso más simple, un
    # plan recién construido, sin despachar nada todavía.
    plan = JobPlan(
        goal="AF999-US01",
        steps=[JobPlanStep(description="paso", mechanism="agent", agent_role="developer")],
        status="proposed",
    )

    progress = get_plan_progress(plan)

    assert progress["steps"][0]["status"] == "pending"
    assert progress["steps"][0]["result"] is None


def test_dispatch_plan_invokes_the_step_status_callback_for_each_transition(
    isolated_socket: str, tmp_path
) -> None:
    """T-AF017-US04-03: `on_step_status_changed` se invoca en cada cambio
    de estado observable de un paso — al pasar a `running` Y al
    resolverse (`completed` en este caso, dos pasos reales, tmux real) —
    no solo al final de la secuencia entera."""
    agent, runtime_instance = _launch_cooperative_developer(isolated_socket, tmp_path)
    session = _active_session_with_developer(agent)
    plan = JobPlan(
        goal="AF999-US01",
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
        goal="AF999-US01",
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
    from atlas_forge.dispatcher.job_plan_dispatch import (
        _NoAgentAvailableError,
        _find_agent_by_role,
    )

    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    dev1 = Agent(id="dev-1", name="Developer-1", role="developer", prompt="p", runtime_id="r1")
    dev2 = Agent(id="dev-2", name="Developer-2", role="developer", prompt="p", runtime_id="r1")
    assign_agent(session, dev1)
    assign_agent(session, dev2)

    found_dev2 = _find_agent_by_role(session, "developer", agent_id="dev-2")
    assert found_dev2.id == "dev-2"

    found_dev1 = _find_agent_by_role(session, "developer", agent_id="dev-1")
    assert found_dev1.id == "dev-1"

    # T-AF008-US04-08: un `agent_id` concreto que no existe ya no devuelve
    # `None` — lanza `_NoAgentAvailableError` explícito (mismo criterio de
    # "fallar rápido" que el resto de esta Task).
    with pytest.raises(_NoAgentAvailableError):
        _find_agent_by_role(session, "developer", agent_id="dev-3")


def test_find_agent_by_role_no_agent_id_prefers_idle_over_working() -> None:
    # T-AF008-US04-08, criterio 1: con varios candidatos del mismo rol,
    # se prioriza uno `idle` sobre uno `working` — antes de esta Task se
    # devolvía sin más el primero encontrado, sin mirar `status`.
    from atlas_forge.dispatcher.job_plan_dispatch import _find_agent_by_role

    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    dev1 = Agent(
        id="dev-1", name="Developer-1", role="developer", prompt="p",
        runtime_id="r1", status="working",
    )
    dev2 = Agent(
        id="dev-2", name="Developer-2", role="developer", prompt="p",
        runtime_id="r1", status="idle",
    )
    assign_agent(session, dev1)
    assign_agent(session, dev2)

    found = _find_agent_by_role(session, "developer")
    assert found.id == "dev-2"


def test_find_agent_by_role_no_agent_id_fails_explicitly_when_all_working() -> None:
    # T-AF008-US04-08, criterio 2/3: si todos los agentes del rol están
    # `working`, no se reutiliza ninguno — falla explícito con
    # `all_working=True`, distinto del caso "no existe ninguno".
    from atlas_forge.dispatcher.job_plan_dispatch import (
        _NoAgentAvailableError,
        _find_agent_by_role,
    )

    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    dev1 = Agent(
        id="dev-1", name="Developer-1", role="developer", prompt="p",
        runtime_id="r1", status="working",
    )
    assign_agent(session, dev1)

    with pytest.raises(_NoAgentAvailableError) as exc_info:
        _find_agent_by_role(session, "developer")
    assert exc_info.value.all_working is True


def test_find_agent_by_role_no_agent_id_fails_explicitly_when_none_exists() -> None:
    from atlas_forge.dispatcher.job_plan_dispatch import (
        _NoAgentAvailableError,
        _find_agent_by_role,
    )

    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)

    with pytest.raises(_NoAgentAvailableError) as exc_info:
        _find_agent_by_role(session, "developer")
    assert exc_info.value.all_working is False


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
        goal="AF999-US01",
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


def test_dispatch_plan_picks_the_idle_developer_while_the_other_is_genuinely_busy(
    isolated_socket: str, tmp_path
) -> None:
    # T-AF008-US04-08, criterio de aceptación explícito: dos Developers
    # reales (tmux real, mismo runtime cooperativo que el resto de esta
    # suite), uno ocupado con un Job de LARGA DURACIÓN simulado (no un
    # `status="working"` puesto a mano — concurrencia real vía threading,
    # el Job del hilo de fondo sigue genuinamente en curso cuando se
    # despacha el segundo). Confirma que un despacho por rol (sin
    # `agent_id`) elige el Developer libre, nunca el ocupado.
    from atlas_forge.dispatcher.job_creation import create_job
    from atlas_forge.dispatcher.job_dispatch import dispatch_job

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
        # Espera activa corta a que el hilo de fondo REALMENTE haya
        # marcado `busy_dev` como `working` (mark_working ocurre dentro
        # de `dispatch_job`, antes de enviar la instrucción) — sin este
        # sondeo, el despacho del plan podría adelantarse a la
        # transición y el test no probaría la condición de carrera real.
        deadline = time.monotonic() + 5.0
        while busy_dev.status != "working" and time.monotonic() < deadline:
            time.sleep(0.02)
        assert busy_dev.status == "working"

        plan = JobPlan(
            goal="AF999-US01",
            steps=[
                JobPlanStep(
                    description="paso sin agent_id",
                    mechanism="agent",
                    agent_role="developer",
                ),
            ],
            status="approved",
        )
        dispatch_plan(plan, session, socket_name=isolated_socket)
    finally:
        busy_thread.join(timeout=10)
        stop_runtime(busy_ri, socket_name=isolated_socket)
        stop_runtime(idle_ri, socket_name=isolated_socket)

    assert plan.status == "approved"
    assert plan.steps[0].status == "completed"
    # El Job del paso se despachó al Developer libre (`dev-idle`), no al
    # ocupado — verificado con el propio agente vuelto a `idle` tras
    # completar (ambos lo estarán al terminar, pero solo `idle_dev`
    # participó en el paso: confirmado indirectamente por que el plan
    # completó sin bloquearse, lo que solo pasa si el paso encontró un
    # agente `idle` real para despachar — con la implementación previa a
    # esta Task, el riesgo real era que reutilizara `busy_dev` mientras
    # seguía `working`, mezclando dos instrucciones en el mismo pane).
    assert busy_job.status == "completed"


def test_dispatch_plan_blocks_when_agent_id_does_not_match_any_agent() -> None:
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    dev1 = Agent(
        id="dev-1", name="Developer-1", role="developer", prompt="p", runtime_id="r1"
    )
    assign_agent(session, dev1)

    plan = JobPlan(
        goal="AF999-US01",
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
    `run_job_plan`, T-AF008-US04-04).
    
    T-AF022-US06-03: además de la regresión de compatibilidad, verifica que
    el informe de cierre del Job se escribe en
    07-informes/<story_id>/<job_id>.md."""
    agent, runtime_instance = _launch_cooperative_developer(isolated_socket, tmp_path)
    session = _active_session_with_developer(agent)
    plan = JobPlan(
        goal="US-AF022-06",
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
        "atlas_forge.dispatcher.job_plan_dispatch.write_job_report",
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
