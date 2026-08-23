import uuid
from pathlib import Path
from unittest.mock import patch

import libtmux
import pytest

from atlas_forge.core.session_lifecycle import activate, assign_agent
from atlas_forge.dispatcher import get_plan_progress, run_job_plan
from atlas_forge.local_tools import ScribeUnavailableError
from atlas_forge.models import Agent, DevelopmentSession, Runtime
from atlas_forge.runtime import register_runtime_instance_for_agent, start_runtime, stop_runtime

_COOPERATIVE_AGENT_SCRIPT = str(
    Path(__file__).parent / "fixtures" / "cooperative_agent_sim.sh"
)


@pytest.fixture
def isolated_socket():
    """Mismo patrón de aislamiento ya usado en el resto de tests de
    despacho real (test_job_dispatch.py, test_job_plan_dispatch.py):
    servidor tmux propio por test, nunca el binario real de un runtime."""
    name = f"atlas_forge-test-{uuid.uuid4().hex[:8]}"
    try:
        yield name
    finally:
        try:
            libtmux.Server(socket_name=name).kill()
        except Exception:
            pass


def _write_task(
    tasks_dir: Path, story_id: str, correlative: str, slug: str, title: str, body: str
) -> None:
    content = (
        "---\n"
        f"id: T-{story_id}-{correlative}\n"
        "type: task\n"
        f"title: {title}\n"
        "epic: AF-999\n"
        f"user_story: {story_id}\n"
        "state: READY\n"
        "dependencies: []\n"
        "priority: Crítica\n"
        "---\n\n"
        "## Objetivo\n\n"
        f"{body}\n\n"
        "## Descripción\n\n"
        f"{body}\n\n"
        "## Criterios de aceptación\n\n- CR1: La Task cierra la User Story.\n"
    )
    (tasks_dir / f"T-{story_id}-{correlative}-{slug}.md").write_text(
        content, encoding="utf-8"
    )


def _active_session_with_developer(agent: Agent) -> DevelopmentSession:
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    assign_agent(session, agent)
    return session


def _launch_cooperative_developer(isolated_socket: str, tmp_path: Path) -> Agent:
    runtime = Runtime(
        id="test-runtime",
        name="Test Runtime",
        type="test",
        command="bash",
        args=[_COOPERATIVE_AGENT_SCRIPT],
    )
    agent = Agent(
        id="a-dev", name="developer", role="developer", prompt="p", runtime_id="r1"
    )
    runtime_instance = start_runtime(
        runtime, agent, str(tmp_path / "project"), socket_name=isolated_socket
    )
    register_runtime_instance_for_agent(agent.id, runtime_instance)
    return agent, runtime_instance


def test_run_job_plan_end_to_end_mixed_steps_all_succeed(
    isolated_socket: str, tmp_path: Path
) -> None:
    story_id = "AF999-US01"
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    _write_task(
        tasks_dir,
        story_id,
        "01",
        "paso-script",
        "Ejecutar el script de limpieza",
        body="Reutiliza un script determinista ya existente.",
    )
    _write_task(
        tasks_dir,
        story_id,
        "02",
        "paso-scribe",
        "Resumir el contexto",
        body="Invoca a Scribe para resumir el documento.",
    )
    _write_task(
        tasks_dir,
        story_id,
        "03",
        "paso-agente",
        "Implementar la nueva pantalla",
        body="Requiere criterio de diseño e implementación real.",
    )

    agent, runtime_instance = _launch_cooperative_developer(isolated_socket, tmp_path)
    session = _active_session_with_developer(agent)

    try:
        # Scribe real (Ollama) no está garantizado disponible en el
        # entorno de test — se mockea para el camino feliz, igual que en
        # test_job_plan_dispatch.py (nunca se invoca Ollama real en tests).
        with patch(
            "atlas_forge.dispatcher.job_plan_dispatch.summarize_document",
            return_value="resumen ok",
        ):
            plan = run_job_plan(
                story_id,
                session,
                approved=True,
                socket_name=isolated_socket,
                tasks_dir=tasks_dir,
            )
    finally:
        stop_runtime(runtime_instance, socket_name=isolated_socket)

    # Construir: la heurística de -01 reflejó los tres mecanismos.
    assert [step.mechanism for step in plan.steps] == ["script", "scribe", "agent"]

    # Aprobar + despachar: el paso "script" (sin catálogo invocable) queda
    # pending sin bloquear, scribe y agent se completan.
    progress = get_plan_progress(plan)
    assert progress["status"] == "approved"
    assert [step["status"] for step in progress["steps"]] == [
        "pending",
        "completed",
        "completed",
    ]


def test_run_job_plan_end_to_end_rejected_plan_dispatches_nothing(
    tmp_path: Path,
) -> None:
    story_id = "AF999-US01"
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    _write_task(
        tasks_dir,
        story_id,
        "01",
        "paso-agente",
        "Implementar la nueva pantalla",
        body="Requiere criterio de diseño e implementación real.",
    )
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)

    plan = run_job_plan(
        story_id, session, approved=False, tasks_dir=tasks_dir
    )

    progress = get_plan_progress(plan)
    assert progress["status"] == "rejected"
    # El paso nunca se intentó: sigue pending, no completed ni failed.
    assert progress["steps"][0]["status"] == "pending"


def test_run_job_plan_end_to_end_intermediate_step_failure_blocks_the_rest(
    isolated_socket: str, tmp_path: Path
) -> None:
    story_id = "AF999-US01"
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    _write_task(
        tasks_dir,
        story_id,
        "01",
        "paso-agente-1",
        "Implementar la primera parte",
        body="Requiere criterio de diseño e implementación real.",
    )
    # Paso intermedio "scribe": se fuerza `ScribeUnavailableError` (mock,
    # ver más abajo) como causa de fallo real y determinista, sin depender
    # de SIM_FAIL=1 (ver nota en test_job_plan_dispatch.py sobre por qué
    # ese mecanismo del fixture no sirve para simular un Job realmente
    # `failed`: el auto-reporte cooperativo de dispatch_job marca
    # `completed` en cuanto recibe cualquier reporte con marcador de fin,
    # sea cual sea su contenido de texto).
    _write_task(
        tasks_dir,
        story_id,
        "02",
        "paso-scribe",
        "Resumir el resultado con Scribe",
        body="Invoca a Scribe para resumir el resultado anterior.",
    )
    _write_task(
        tasks_dir,
        story_id,
        "03",
        "paso-agente-3",
        "Implementar la tercera parte",
        body="Requiere criterio de diseño e implementación real.",
    )

    agent, runtime_instance = _launch_cooperative_developer(isolated_socket, tmp_path)
    session = _active_session_with_developer(agent)

    try:
        with patch(
            "atlas_forge.dispatcher.job_plan_dispatch.summarize_document",
            side_effect=ScribeUnavailableError("Ollama no disponible"),
        ):
            plan = run_job_plan(
                story_id,
                session,
                approved=True,
                socket_name=isolated_socket,
                tasks_dir=tasks_dir,
            )
    finally:
        stop_runtime(runtime_instance, socket_name=isolated_socket)

    progress = get_plan_progress(plan)

    # Bloqueado se distingue claramente de "en curso" y "completado".
    assert progress["status"] == "blocked"
    assert [step["status"] for step in progress["steps"]] == [
        "completed",
        "failed",
        "pending",
    ]
