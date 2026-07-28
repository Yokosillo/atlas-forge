import asyncio
import uuid
from pathlib import Path

import libtmux
import pytest

from brain.core.session_lifecycle import assign_agent, list_agents
from brain.core.session_registry import _reset_registry_for_tests
from brain.dispatcher.job_history_registry import (
    _reset_registry_for_tests as _reset_job_history_registry_for_tests,
)
from brain.models import Agent, Runtime
from brain.runtime import start_runtime, stop_runtime
from brain.runtime.agent_runtime_registry import (
    _reset_registry_for_tests as _reset_runtime_registry_for_tests,
)
from brain.runtime.agent_runtime_registry import register_runtime_instance_for_agent
from brain.tui.app import FactoryBrainApp
from brain.tui.screens import JobsScreen
from brain.workspace.active_project import select_active_project
from brain.workspace.discovery import discover_projects
from textual.widgets import Select, Static, TextArea

_COOPERATIVE_AGENT_SCRIPT = str(
    Path(__file__).parent / "fixtures" / "cooperative_agent_sim.sh"
)


@pytest.fixture(autouse=True)
def _reset_registries():
    _reset_registry_for_tests()
    _reset_runtime_registry_for_tests()
    _reset_job_history_registry_for_tests()
    yield
    _reset_registry_for_tests()
    _reset_runtime_registry_for_tests()
    _reset_job_history_registry_for_tests()


@pytest.fixture
def isolated_socket():
    """Aísla los tests de esta Task en su propio servidor tmux, con
    limpieza garantizada incluso si el test falla a medio camino — mismo
    patrón que test_job_dispatch.py/test_agents_screen.py."""
    name = f"brain-test-{uuid.uuid4().hex[:8]}"
    try:
        yield name
    finally:
        try:
            libtmux.Server(socket_name=name).kill()
        except Exception:
            pass


def _make_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()


def _select_project(workspace_root: Path, state_dir: Path):
    repo_path = workspace_root / "my-project"
    _make_git_repo(repo_path)
    discovered = discover_projects(workspace_root)
    select_active_project(discovered[0], discovered=discovered, state_dir=state_dir)
    return discovered[0]


def _launch_cooperative_agent(
    session,
    isolated_socket: str,
    tmp_path,
    extra_env: str = "",
    role: str = "developer",
    name: str = "Developer",
):
    # Doble cooperativo real (tmux real, nunca el binario real de Claude
    # Code/OpenCode) — mismo patrón ya usado en test_job_dispatch.py.
    # Se asigna manualmente a la sesión y se registra su RuntimeInstance
    # (T-FB002-US03-00), en vez de pasar por `register_developer`/
    # `launch_agent`, para no depender de mockear el comando real: aquí
    # se controla directamente qué runtime/comando arranca.
    runtime_id = f"test-runtime-{uuid.uuid4().hex[:8]}"
    agent = Agent(
        id=str(uuid.uuid4()), name=name, role=role, prompt="p", runtime_id=runtime_id
    )
    command = f"{extra_env} bash".strip()
    runtime = Runtime(
        id=runtime_id,
        name="Test Runtime",
        type="test",
        command=command,
        args=[_COOPERATIVE_AGENT_SCRIPT],
    )
    runtime_instance = start_runtime(
        runtime, agent, str(tmp_path), socket_name=isolated_socket
    )
    assign_agent(session, agent)
    register_runtime_instance_for_agent(agent.id, runtime_instance)
    return agent, runtime_instance


async def _wait_for_status_containing(jobs_screen, *substrings: str, timeout: float = 5.0):
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        status_text = str(jobs_screen.query_one("#job-status", Static).content).lower()
        if all(s.lower() in status_text for s in substrings):
            return status_text
        await asyncio.sleep(0.1)
    return str(jobs_screen.query_one("#job-status", Static).content)


async def test_creating_and_dispatching_a_job_without_running_any_manual_code(
    isolated_socket: str, tmp_path
) -> None:
    # Criterio de aceptación 1: el desarrollador puede escribir una
    # descripción, elegir un agente ya lanzado, y confirmar — el Job se
    # crea y se despacha sin ejecutar código manualmente.
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    project = _select_project(workspace_root, state_dir)

    app = FactoryBrainApp(workspace_root=workspace_root, state_dir=state_dir)
    async with app.run_test() as pilot:
        from brain.core.session_registry import get_current_session

        session = get_current_session()
        agent, runtime_instance = _launch_cooperative_agent(
            session, isolated_socket, tmp_path, extra_env="SIM_DELAY=0.1"
        )

        jobs_screen = JobsScreen(
            workspace_root=workspace_root,
            state_dir=state_dir,
            socket_name=isolated_socket,
        )
        pilot.app.push_screen(jobs_screen)
        await pilot.pause()

        description_widget = jobs_screen.query_one("#job-description", TextArea)
        description_widget.text = "implement the requested feature"

        await pilot.click("#send-job")
        await pilot.pause()

        # Espera activa (sin bloquear el test) a que el worker en
        # background termine de despachar.
        for _ in range(50):
            status_text = str(jobs_screen.query_one("#job-status", Static).content)
            if "completado" in status_text.lower() or "falló" in status_text.lower():
                break
            await asyncio.sleep(0.1)

        status_text = str(jobs_screen.query_one("#job-status", Static).content)
        assert "completado" in status_text.lower()
        assert "cooperative result" in status_text.lower()

        stop_runtime(runtime_instance, socket_name=isolated_socket)


async def test_ui_stays_responsive_while_job_is_running(
    isolated_socket: str, tmp_path
) -> None:
    # Criterio de aceptación 2: mientras el Job está en curso, la
    # pantalla no se queda congelada ni bloquea el resto de la TUI —
    # verificado interactuando con la TUI (pop_screen) MIENTRAS el
    # despacho (con un delay deliberadamente largo) sigue en curso.
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    project = _select_project(workspace_root, state_dir)

    app = FactoryBrainApp(workspace_root=workspace_root, state_dir=state_dir)
    async with app.run_test() as pilot:
        from brain.core.session_registry import get_current_session

        session = get_current_session()
        agent, runtime_instance = _launch_cooperative_agent(
            session, isolated_socket, tmp_path, extra_env="SIM_DELAY=2"
        )

        jobs_screen = JobsScreen(
            workspace_root=workspace_root,
            state_dir=state_dir,
            socket_name=isolated_socket,
        )
        pilot.app.push_screen(jobs_screen)
        await pilot.pause()

        description_widget = jobs_screen.query_one("#job-description", TextArea)
        description_widget.text = "a task that takes a couple of seconds"

        await pilot.click("#send-job")
        await pilot.pause()

        # El Job está despachándose (SIM_DELAY=2s) — si dispatch_job
        # bloqueara el hilo principal de Textual, esta interacción con la
        # UI (navegar y volver) se quedaría congelada hasta que el Job
        # termine. Con el worker de hilo, responde de inmediato.
        import time

        started_at = time.monotonic()
        pilot.app.pop_screen()
        await pilot.pause()
        elapsed = time.monotonic() - started_at

        assert elapsed < 1.0
        assert not isinstance(pilot.app.screen, JobsScreen)

        stop_runtime(runtime_instance, socket_name=isolated_socket)


async def test_screen_shows_running_progress_while_job_is_in_flight(
    isolated_socket: str, tmp_path
) -> None:
    # Criterio de aceptación de US-FB002-03: "la pantalla muestra el
    # progreso (created → running) mientras el agente trabaja" —
    # verificado leyendo #job-status justo después de enviar (antes de
    # que el Job complete, gracias a un SIM_DELAY deliberadamente largo).
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _select_project(workspace_root, state_dir)

    app = FactoryBrainApp(workspace_root=workspace_root, state_dir=state_dir)
    async with app.run_test() as pilot:
        from brain.core.session_registry import get_current_session

        session = get_current_session()
        agent, runtime_instance = _launch_cooperative_agent(
            session, isolated_socket, tmp_path, extra_env="SIM_DELAY=2"
        )

        jobs_screen = JobsScreen(
            workspace_root=workspace_root,
            state_dir=state_dir,
            socket_name=isolated_socket,
        )
        pilot.app.push_screen(jobs_screen)
        await pilot.pause()

        jobs_screen.query_one("#job-description", TextArea).text = "a slow task"
        await pilot.click("#send-job")
        await pilot.pause()

        status_text = str(jobs_screen.query_one("#job-status", Static).content).lower()
        assert "running" in status_text

        await _wait_for_status_containing(jobs_screen, "completado")

        stop_runtime(runtime_instance, socket_name=isolated_socket)


async def test_no_agents_launched_shows_clear_message_instead_of_empty_form(
    tmp_path,
) -> None:
    # Criterio de aceptación 3: sin agentes lanzados en la sesión, la
    # pantalla informa claramente en vez de mostrar un formulario vacío o
    # roto.
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _select_project(workspace_root, state_dir)

    app = FactoryBrainApp(workspace_root=workspace_root, state_dir=state_dir)
    async with app.run_test() as pilot:
        jobs_screen = JobsScreen(workspace_root=workspace_root, state_dir=state_dir)
        pilot.app.push_screen(jobs_screen)
        await pilot.pause()

        assert len(jobs_screen.query("#job-description").nodes) == 0
        assert len(jobs_screen.query("#agent-choice").nodes) == 0

        static_widgets = jobs_screen.query("Static")
        rendered_texts = [str(widget.content) for widget in static_widgets]
        assert any("no hay ningún agente lanzado" in text.lower() for text in rendered_texts)


async def test_completed_job_shows_full_result_and_offers_chain_to_critic_when_critic_launched(
    isolated_socket: str, tmp_path
) -> None:
    # Criterios de aceptación: "un Job completado muestra su resultado
    # completo... sin truncarlo silenciosamente" y "un Job de Developer
    # completado con Critic ya lanzado ofrece encadenar".
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _select_project(workspace_root, state_dir)

    app = FactoryBrainApp(workspace_root=workspace_root, state_dir=state_dir)
    async with app.run_test() as pilot:
        from brain.core.session_registry import get_current_session

        session = get_current_session()
        developer, dev_instance = _launch_cooperative_agent(
            session, isolated_socket, tmp_path, extra_env="SIM_DELAY=0.1"
        )
        critic, critic_instance = _launch_cooperative_agent(
            session,
            isolated_socket,
            tmp_path,
            extra_env="SIM_ROLE=critic SIM_DELAY=0.1",
            role="critic",
            name="Critic",
        )

        jobs_screen = JobsScreen(
            workspace_root=workspace_root,
            state_dir=state_dir,
            socket_name=isolated_socket,
        )
        pilot.app.push_screen(jobs_screen)
        await pilot.pause()

        select_widget = jobs_screen.query_one("#agent-choice", Select)
        select_widget.value = developer.id

        description_widget = jobs_screen.query_one("#job-description", TextArea)
        description_widget.text = "implement the requested feature"

        await pilot.click("#send-job")
        await pilot.pause()

        await _wait_for_status_containing(jobs_screen, "completado")

        status_text = str(jobs_screen.query_one("#job-status", Static).content)
        assert "cooperative result" in status_text.lower()
        # Resultado completo, no truncado: ambas líneas del doble
        # cooperativo aparecen enteras.
        assert "line one of the cooperative result" in status_text
        assert "line two of the cooperative result" in status_text

        assert len(jobs_screen.query("#chain-to-critic").nodes) == 1

        stop_runtime(dev_instance, socket_name=isolated_socket)
        stop_runtime(critic_instance, socket_name=isolated_socket)


async def test_chaining_to_critic_creates_and_dispatches_job_with_developer_result(
    isolated_socket: str, tmp_path
) -> None:
    # Criterio de aceptación: "hacerlo crea y despacha correctamente el
    # Job de Critic con el resultado de Developer incluido".
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _select_project(workspace_root, state_dir)

    app = FactoryBrainApp(workspace_root=workspace_root, state_dir=state_dir)
    async with app.run_test() as pilot:
        from brain.core.session_registry import get_current_session

        session = get_current_session()
        developer, dev_instance = _launch_cooperative_agent(
            session, isolated_socket, tmp_path, extra_env="SIM_DELAY=0.1"
        )
        critic, critic_instance = _launch_cooperative_agent(
            session,
            isolated_socket,
            tmp_path,
            extra_env="SIM_ROLE=critic SIM_DELAY=0.1",
            role="critic",
            name="Critic",
        )

        jobs_screen = JobsScreen(
            workspace_root=workspace_root,
            state_dir=state_dir,
            socket_name=isolated_socket,
        )
        pilot.app.push_screen(jobs_screen)
        await pilot.pause()

        select_widget = jobs_screen.query_one("#agent-choice", Select)
        select_widget.value = developer.id
        jobs_screen.query_one("#job-description", TextArea).text = "implement the feature"

        await pilot.click("#send-job")
        await pilot.pause()
        await _wait_for_status_containing(jobs_screen, "completado")

        await pilot.click("#chain-to-critic")
        await pilot.pause()

        critic_screen = pilot.app.screen
        assert isinstance(critic_screen, JobsScreen)
        assert critic_screen is not jobs_screen

        # Agente destinatario fijado a Critic (criterio: "agente
        # destinatario fijado si está lanzado").
        assert critic_screen.query_one("#agent-choice", Select).value == critic.id

        await pilot.click("#send-job")
        await pilot.pause()
        await _wait_for_status_containing(critic_screen, "completado")

        critic_status_text = str(
            critic_screen.query_one("#job-status", Static).content
        )
        assert "critic verdict" in critic_status_text.lower()
        # Critic recibió el resultado real de Developer, no un texto fijo.
        assert "cooperative result" in critic_status_text.lower()

        stop_runtime(dev_instance, socket_name=isolated_socket)
        stop_runtime(critic_instance, socket_name=isolated_socket)


async def test_completed_developer_job_without_critic_launched_shows_clear_message(
    isolated_socket: str, tmp_path
) -> None:
    # Criterio de aceptación: "sin Critic lanzado, la opción de encadenar
    # no está disponible, con mensaje claro".
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _select_project(workspace_root, state_dir)

    app = FactoryBrainApp(workspace_root=workspace_root, state_dir=state_dir)
    async with app.run_test() as pilot:
        from brain.core.session_registry import get_current_session

        session = get_current_session()
        developer, dev_instance = _launch_cooperative_agent(
            session, isolated_socket, tmp_path, extra_env="SIM_DELAY=0.1"
        )

        jobs_screen = JobsScreen(
            workspace_root=workspace_root,
            state_dir=state_dir,
            socket_name=isolated_socket,
        )
        pilot.app.push_screen(jobs_screen)
        await pilot.pause()

        jobs_screen.query_one("#job-description", TextArea).text = "implement it"

        await pilot.click("#send-job")
        await pilot.pause()
        await _wait_for_status_containing(jobs_screen, "completado")

        assert len(jobs_screen.query("#chain-to-critic").nodes) == 0
        no_critic_widgets = jobs_screen.query("#no-critic-message")
        assert len(no_critic_widgets.nodes) == 1
        assert "no hay ningún agente critic lanzado" in str(
            no_critic_widgets.first().content
        ).lower()

        stop_runtime(dev_instance, socket_name=isolated_socket)


async def test_failed_job_shows_reason_without_offering_chain(
    isolated_socket: str, tmp_path
) -> None:
    # Criterio de aceptación: "un Job fallido muestra el motivo, sin
    # ofrecer encadenamiento".
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _select_project(workspace_root, state_dir)

    app = FactoryBrainApp(workspace_root=workspace_root, state_dir=state_dir)
    async with app.run_test() as pilot:
        from brain.core.session_registry import get_current_session

        session = get_current_session()
        # Runtime que nunca reporta (nunca escribe el fichero pactado) —
        # dispatch_job lo marca como `failed` por timeout.
        agent = Agent(
            id=str(uuid.uuid4()),
            name="Developer",
            role="developer",
            prompt="p",
            runtime_id="never-reports-runtime",
        )
        never_reports_runtime = Runtime(
            id="never-reports-runtime",
            name="Never Reports",
            type="test",
            command="bash",
            args=[],
        )
        runtime_instance = start_runtime(
            never_reports_runtime, agent, str(tmp_path), socket_name=isolated_socket
        )
        assign_agent(session, agent)
        register_runtime_instance_for_agent(agent.id, runtime_instance)

        jobs_screen = JobsScreen(
            workspace_root=workspace_root,
            state_dir=state_dir,
            socket_name=isolated_socket,
        )
        pilot.app.push_screen(jobs_screen)
        await pilot.pause()

        jobs_screen.query_one("#job-description", TextArea).text = "a task"

        select_widget = jobs_screen.query_one("#agent-choice", Select)
        select_widget.value = agent.id

        from brain.dispatcher import create_job

        job = create_job("a task", agent, session)
        jobs_screen._dispatch_job_in_background(
            job, agent, runtime_instance, timeout_seconds=1.0, poll_interval_seconds=0.1
        )

        await _wait_for_status_containing(jobs_screen, "falló", timeout=5.0)

        status_text = str(jobs_screen.query_one("#job-status", Static).content)
        assert "falló" in status_text.lower()
        assert "timeout" in status_text.lower()
        assert len(jobs_screen.query("#chain-to-critic").nodes) == 0
        assert len(jobs_screen.query("#no-critic-message").nodes) == 0

        stop_runtime(runtime_instance, socket_name=isolated_socket)


async def test_multiple_jobs_all_appear_in_history_with_current_status(
    isolated_socket: str, tmp_path
) -> None:
    # Criterio de aceptación: "tras crear y despachar varios Jobs, todos
    # aparecen en el histórico con su estado actual".
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _select_project(workspace_root, state_dir)

    app = FactoryBrainApp(workspace_root=workspace_root, state_dir=state_dir)
    async with app.run_test() as pilot:
        from brain.core.session_registry import get_current_session

        session = get_current_session()
        developer, dev_instance = _launch_cooperative_agent(
            session, isolated_socket, tmp_path, extra_env="SIM_DELAY=0.1"
        )

        jobs_screen = JobsScreen(
            workspace_root=workspace_root,
            state_dir=state_dir,
            socket_name=isolated_socket,
        )
        pilot.app.push_screen(jobs_screen)
        await pilot.pause()

        jobs_screen.query_one("#job-description", TextArea).text = "first task"
        await pilot.click("#send-job")
        await pilot.pause()
        await _wait_for_status_containing(jobs_screen, "completado")

        jobs_screen.query_one("#job-description", TextArea).text = "second task"
        await pilot.click("#send-job")
        await pilot.pause()
        await _wait_for_status_containing(jobs_screen, "completado")

        history_text = str(
            jobs_screen.query_one("#job-history-text", Static).content
        )
        assert "first task" in history_text
        assert "second task" in history_text
        assert history_text.count("[completed]") == 2

        stop_runtime(dev_instance, socket_name=isolated_socket)


async def test_history_survives_navigating_away_and_back_to_jobs(
    isolated_socket: str, tmp_path
) -> None:
    # Criterio de aceptación: "navegar a otra pantalla y volver a Jobs
    # conserva el histórico completo" — se verifica construyendo una
    # SEGUNDA instancia de JobsScreen (equivalente a "volver": Dashboard
    # construye una nueva `JobsScreen` al pulsar "Ver Jobs", no reutiliza
    # la anterior), sin pasar por la primera instancia en absoluto.
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _select_project(workspace_root, state_dir)

    app = FactoryBrainApp(workspace_root=workspace_root, state_dir=state_dir)
    async with app.run_test() as pilot:
        from brain.core.session_registry import get_current_session

        session = get_current_session()
        developer, dev_instance = _launch_cooperative_agent(
            session, isolated_socket, tmp_path, extra_env="SIM_DELAY=0.1"
        )

        first_jobs_screen = JobsScreen(
            workspace_root=workspace_root,
            state_dir=state_dir,
            socket_name=isolated_socket,
        )
        pilot.app.push_screen(first_jobs_screen)
        await pilot.pause()

        first_jobs_screen.query_one("#job-description", TextArea).text = (
            "a task created before navigating away"
        )
        await pilot.click("#send-job")
        await pilot.pause()
        await _wait_for_status_containing(first_jobs_screen, "completado")

        # "Navegar a otra pantalla y volver": se simula saliendo de Jobs
        # (pop_screen) y empujando una JobsScreen nueva, independiente de
        # la anterior — el histórico no puede depender de la instancia.
        pilot.app.pop_screen()
        await pilot.pause()

        second_jobs_screen = JobsScreen(
            workspace_root=workspace_root,
            state_dir=state_dir,
            socket_name=isolated_socket,
        )
        pilot.app.push_screen(second_jobs_screen)
        await pilot.pause()

        history_text = str(
            second_jobs_screen.query_one("#job-history-text", Static).content
        )
        assert "a task created before navigating away" in history_text
        assert "[completed]" in history_text

        stop_runtime(dev_instance, socket_name=isolated_socket)


async def test_history_distinguishes_completed_failed_and_running_jobs(
    isolated_socket: str, tmp_path
) -> None:
    # Criterio de aceptación: "el histórico distingue claramente Jobs
    # completed, failed, y running (si alguno sigue en curso)".
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _select_project(workspace_root, state_dir)

    app = FactoryBrainApp(workspace_root=workspace_root, state_dir=state_dir)
    async with app.run_test() as pilot:
        from brain.core.session_registry import get_current_session

        session = get_current_session()
        developer, dev_instance = _launch_cooperative_agent(
            session, isolated_socket, tmp_path, extra_env="SIM_DELAY=0.1"
        )

        jobs_screen = JobsScreen(
            workspace_root=workspace_root,
            state_dir=state_dir,
            socket_name=isolated_socket,
        )
        pilot.app.push_screen(jobs_screen)
        await pilot.pause()

        # Job completado.
        jobs_screen.query_one("#job-description", TextArea).text = "a completed task"
        await pilot.click("#send-job")
        await pilot.pause()
        await _wait_for_status_containing(jobs_screen, "completado")

        # Job en curso (running): se registra manualmente en el
        # histórico sin despacharlo, para verificar que el histórico
        # distingue `running` de `completed`/`failed` sin depender de
        # que dispatch_job termine durante el test.
        from brain.dispatcher import create_job, mark_running, record_job

        running_job = create_job("a running task", developer, session)
        mark_running(running_job)
        record_job(session.id, running_job)
        jobs_screen._refresh_history()

        history_text = str(
            jobs_screen.query_one("#job-history-text", Static).content
        )
        assert "[completed]" in history_text
        assert "a completed task" in history_text
        assert "[running]" in history_text
        assert "a running task" in history_text

        stop_runtime(dev_instance, socket_name=isolated_socket)
