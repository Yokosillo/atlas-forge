import asyncio
import sys
import time
from pathlib import Path

import pytest
from textual.widgets import Button, Select, Static, TextArea

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
from backend_server import running_backend  # noqa: E402

from brain.core.session_registry import (
    _reset_registry_for_tests,
    resolve_startup_session,
)
from brain.dispatcher.job_history_registry import (
    _reset_registry_for_tests as _reset_job_history_registry_for_tests,
)
from brain.runtime.agent_runtime_registry import (
    _reset_registry_for_tests as _reset_runtime_registry_for_tests,
)
from brain.tui.app import FactoryBrainApp
from brain.tui.backend_client import BackendClient
from brain.tui.screens import JobsScreen
from brain.workspace.active_project import select_active_project
from brain.workspace.discovery import discover_projects

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


@pytest.fixture(autouse=True)
def _no_real_runtime(monkeypatch):
    """Sustituye los comandos reales de Claude Code/OpenCode por `sleep`
    por defecto (los tests que necesitan el doble cooperativo real lo
    sobreescriben explícitamente vía `_launch_cooperative_agent`)."""
    import brain.runtime.claude_code as claude_code_module
    import brain.runtime.opencode as opencode_module

    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_COMMAND", "sleep")
    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_ARGS", ["5"])
    monkeypatch.setattr(opencode_module, "DEFAULT_OPENCODE_COMMAND", "sleep")
    monkeypatch.setattr(opencode_module, "DEFAULT_OPENCODE_AUTONOMY_FLAG", "5")


@pytest.fixture
def backend(tmp_path: Path):
    # T-FB016-US01-06: JobsScreen ahora consulta/crea/despacha Jobs vía
    # backend real (brain-api) en vez de invocar dominio directamente —
    # se arranca un backend de prueba real (mismo `create_app()` de
    # producción) en un hilo, mismo criterio de "test contra
    # comportamiento real" ya aplicado en el resto del proyecto (nunca se
    # mockea la llamada HTTP; el aislamiento del socket tmux ya lo
    # gestiona `running_backend`).
    #
    # `workspace_root`/`state_dir` aislados en `tmp_path`
    # (T-FB016-US01-11): evita que el `_lifespan` real resuelva el
    # proyecto activo REAL del usuario en esta máquina — ver docstring
    # equivalente en `test_dashboard_screen.py`.
    with running_backend(
        workspace_root=tmp_path / "workspace", state_dir=tmp_path / "state"
    ) as base_url:
        yield BackendClient(base_url=base_url)


def _make_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()


def _select_project_and_start_backend_session(workspace_root: Path, state_dir: Path):
    # Ver justificación completa en test_dashboard_screen.py: GET /session
    # solo consulta, nunca resuelve — se arranca aquí para que el backend
    # de prueba (mismo proceso Python que el test) tenga sesión activa
    # antes de que la TUI haga su primera petición.
    repo_path = workspace_root / "my-project"
    _make_git_repo(repo_path)
    discovered = discover_projects(workspace_root)
    select_active_project(discovered[0], discovered=discovered, state_dir=state_dir)
    resolve_startup_session(workspace_root=workspace_root, state_dir=state_dir)
    return discovered[0]


def _launch_cooperative_agent(
    backend: BackendClient,
    monkeypatch,
    tmp_path,
    extra_env: str = "",
    role: str = "developer",
) -> dict:
    # Doble cooperativo real (tmux real, nunca el binario real de Claude
    # Code/OpenCode) — mismo patrón ya usado en test_job_dispatch.py,
    # ahora lanzado a través del backend (POST /agents) en vez de
    # `start_runtime`/`assign_agent`/`register_runtime_instance_for_agent`
    # directos, para que el agente exista de verdad en el registro que la
    # TUI consulta vía HTTP.
    import brain.runtime.claude_code as claude_code_module

    monkeypatch.setattr(
        claude_code_module, "DEFAULT_CLAUDE_CODE_COMMAND", f"{extra_env} bash".strip()
    )
    monkeypatch.setattr(
        claude_code_module, "DEFAULT_CLAUDE_CODE_ARGS", [_COOPERATIVE_AGENT_SCRIPT]
    )
    return backend.launch_agent(role, "claude-code", None)


async def _wait_for_status_containing(jobs_screen, *substrings: str, timeout: float = 5.0):
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        status_text = str(jobs_screen.query_one("#job-status", Static).content).lower()
        if all(s.lower() in status_text for s in substrings):
            return status_text
        await asyncio.sleep(0.1)
    return str(jobs_screen.query_one("#job-status", Static).content)


async def test_creating_and_dispatching_a_job_without_running_any_manual_code(
    tmp_path, backend, monkeypatch
) -> None:
    # Criterio de aceptación 1: el desarrollador puede escribir una
    # descripción, elegir un agente ya lanzado, y confirmar — el Job se
    # crea y se despacha sin ejecutar código manualmente.
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _select_project_and_start_backend_session(workspace_root, state_dir)

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        _launch_cooperative_agent(backend, monkeypatch, tmp_path, extra_env="SIM_DELAY=0.1")

        jobs_screen = JobsScreen(
            workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
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


async def test_ui_stays_responsive_while_job_is_running(
    tmp_path, backend, monkeypatch
) -> None:
    # Criterio de aceptación 2: mientras el Job está en curso, la
    # pantalla no se queda congelada ni bloquea el resto de la TUI —
    # verificado interactuando con la TUI (pop_screen) MIENTRAS el
    # despacho (con un delay deliberadamente largo) sigue en curso.
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _select_project_and_start_backend_session(workspace_root, state_dir)

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        _launch_cooperative_agent(backend, monkeypatch, tmp_path, extra_env="SIM_DELAY=2")

        jobs_screen = JobsScreen(
            workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
        )
        pilot.app.push_screen(jobs_screen)
        await pilot.pause()

        description_widget = jobs_screen.query_one("#job-description", TextArea)
        description_widget.text = "a task that takes a couple of seconds"

        await pilot.click("#send-job")
        await pilot.pause()

        # El Job está despachándose (SIM_DELAY=2s) — si la llamada HTTP
        # bloqueante bloqueara el hilo principal de Textual, esta
        # interacción con la UI (navegar y volver) se quedaría congelada
        # hasta que el Job termine. Con el worker de hilo, responde de
        # inmediato.
        started_at = time.monotonic()
        pilot.app.pop_screen()
        await pilot.pause()
        elapsed = time.monotonic() - started_at

        assert elapsed < 1.0
        assert not isinstance(pilot.app.screen, JobsScreen)


async def test_screen_shows_running_progress_while_job_is_in_flight(
    tmp_path, backend, monkeypatch
) -> None:
    # Criterio de aceptación de US-FB002-03: "la pantalla muestra el
    # progreso (created → running) mientras el agente trabaja" —
    # verificado leyendo #job-status justo después de enviar (antes de
    # que el Job complete, gracias a un SIM_DELAY deliberadamente largo).
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _select_project_and_start_backend_session(workspace_root, state_dir)

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        _launch_cooperative_agent(backend, monkeypatch, tmp_path, extra_env="SIM_DELAY=2")

        jobs_screen = JobsScreen(
            workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
        )
        pilot.app.push_screen(jobs_screen)
        await pilot.pause()

        jobs_screen.query_one("#job-description", TextArea).text = "a slow task"
        await pilot.click("#send-job")
        await pilot.pause()

        status_text = str(jobs_screen.query_one("#job-status", Static).content).lower()
        assert "running" in status_text

        await _wait_for_status_containing(jobs_screen, "completado")


async def test_no_agents_launched_shows_clear_message_instead_of_empty_form(
    tmp_path, backend
) -> None:
    # Criterio de aceptación 3: sin agentes lanzados en la sesión, la
    # pantalla informa claramente en vez de mostrar un formulario vacío o
    # roto.
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _select_project_and_start_backend_session(workspace_root, state_dir)

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        jobs_screen = JobsScreen(
            workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
        )
        pilot.app.push_screen(jobs_screen)
        await pilot.pause()

        assert len(jobs_screen.query("#job-description").nodes) == 0
        assert len(jobs_screen.query("#agent-choice").nodes) == 0

        static_widgets = jobs_screen.query("Static")
        rendered_texts = [str(widget.content) for widget in static_widgets]
        assert any("no hay ningún agente lanzado" in text.lower() for text in rendered_texts)


async def test_completed_job_shows_full_result_and_offers_chain_to_critic_when_critic_launched(
    tmp_path, backend, monkeypatch
) -> None:
    # Criterios de aceptación: "un Job completado muestra su resultado
    # completo... sin truncarlo silenciosamente" y "un Job de Developer
    # completado con Critic ya lanzado ofrece encadenar".
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _select_project_and_start_backend_session(workspace_root, state_dir)

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        developer = _launch_cooperative_agent(
            backend, monkeypatch, tmp_path, extra_env="SIM_DELAY=0.1"
        )
        _launch_cooperative_agent(
            backend,
            monkeypatch,
            tmp_path,
            extra_env="SIM_ROLE=critic SIM_DELAY=0.1",
            role="critic",
        )

        jobs_screen = JobsScreen(
            workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
        )
        pilot.app.push_screen(jobs_screen)
        await pilot.pause()

        select_widget = jobs_screen.query_one("#agent-choice", Select)
        select_widget.value = developer["id"]

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


async def test_chaining_to_critic_creates_and_dispatches_job_with_developer_result(
    tmp_path, backend, monkeypatch
) -> None:
    # Criterio de aceptación: "hacerlo crea y despacha correctamente el
    # Job de Critic con el resultado de Developer incluido".
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _select_project_and_start_backend_session(workspace_root, state_dir)

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        developer = _launch_cooperative_agent(
            backend, monkeypatch, tmp_path, extra_env="SIM_DELAY=0.1"
        )
        critic = _launch_cooperative_agent(
            backend,
            monkeypatch,
            tmp_path,
            extra_env="SIM_ROLE=critic SIM_DELAY=0.1",
            role="critic",
        )

        jobs_screen = JobsScreen(
            workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
        )
        pilot.app.push_screen(jobs_screen)
        await pilot.pause()

        select_widget = jobs_screen.query_one("#agent-choice", Select)
        select_widget.value = developer["id"]
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
        assert critic_screen.query_one("#agent-choice", Select).value == critic["id"]

        await pilot.click("#send-job")
        await pilot.pause()
        await _wait_for_status_containing(critic_screen, "completado")

        critic_status_text = str(
            critic_screen.query_one("#job-status", Static).content
        )
        assert "critic verdict" in critic_status_text.lower()
        # Critic recibió el resultado real de Developer, no un texto fijo.
        assert "cooperative result" in critic_status_text.lower()


async def test_completed_developer_job_without_critic_launched_shows_clear_message(
    tmp_path, backend, monkeypatch
) -> None:
    # Criterio de aceptación: "sin Critic lanzado, la opción de encadenar
    # no está disponible, con mensaje claro".
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _select_project_and_start_backend_session(workspace_root, state_dir)

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        _launch_cooperative_agent(backend, monkeypatch, tmp_path, extra_env="SIM_DELAY=0.1")

        jobs_screen = JobsScreen(
            workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
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


async def test_failed_job_shows_reason_without_offering_chain(tmp_path, backend) -> None:
    # Criterio de aceptación: "un Job fallido muestra el motivo, sin
    # ofrecer encadenamiento". Runtime que nunca reporta (`sleep`, el
    # doble por defecto de `_no_real_runtime` — nunca escribe el fichero
    # pactado): el backend marca el Job `failed` por timeout.
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _select_project_and_start_backend_session(workspace_root, state_dir)

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        agent = backend.launch_agent("developer", "claude-code", None)

        jobs_screen = JobsScreen(
            workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
        )
        pilot.app.push_screen(jobs_screen)
        await pilot.pause()

        jobs_screen.query_one("#job-description", TextArea).text = "a task"
        select_widget = jobs_screen.query_one("#agent-choice", Select)
        select_widget.value = agent["id"]

        await pilot.click("#send-job")
        await pilot.pause()

        await _wait_for_status_containing(jobs_screen, "falló", timeout=35.0)

        status_text = str(jobs_screen.query_one("#job-status", Static).content)
        assert "falló" in status_text.lower()
        assert "timeout" in status_text.lower()
        assert len(jobs_screen.query("#chain-to-critic").nodes) == 0
        assert len(jobs_screen.query("#no-critic-message").nodes) == 0


async def test_multiple_jobs_all_appear_in_history_with_current_status(
    tmp_path, backend, monkeypatch
) -> None:
    # Criterio de aceptación: "tras crear y despachar varios Jobs, todos
    # aparecen en el histórico con su estado actual".
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _select_project_and_start_backend_session(workspace_root, state_dir)

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        _launch_cooperative_agent(backend, monkeypatch, tmp_path, extra_env="SIM_DELAY=0.1")

        jobs_screen = JobsScreen(
            workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
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


async def test_history_survives_navigating_away_and_back_to_jobs(
    tmp_path, backend, monkeypatch
) -> None:
    # Criterio de aceptación: "navegar a otra pantalla y volver a Jobs
    # conserva el histórico completo" — se verifica construyendo una
    # SEGUNDA instancia de JobsScreen (equivalente a "volver": Dashboard
    # construye una nueva `JobsScreen` al pulsar "Ver Jobs", no reutiliza
    # la anterior), sin pasar por la primera instancia en absoluto.
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _select_project_and_start_backend_session(workspace_root, state_dir)

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        _launch_cooperative_agent(backend, monkeypatch, tmp_path, extra_env="SIM_DELAY=0.1")

        first_jobs_screen = JobsScreen(
            workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
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
            workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
        )
        pilot.app.push_screen(second_jobs_screen)
        await pilot.pause()

        history_text = str(
            second_jobs_screen.query_one("#job-history-text", Static).content
        )
        assert "a task created before navigating away" in history_text
        assert "[completed]" in history_text


async def test_history_distinguishes_completed_failed_and_running_jobs(
    tmp_path, backend, monkeypatch
) -> None:
    # Criterio de aceptación: "el histórico distingue claramente Jobs
    # completed, failed, y running (si alguno sigue en curso)".
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _select_project_and_start_backend_session(workspace_root, state_dir)

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        developer = _launch_cooperative_agent(
            backend, monkeypatch, tmp_path, extra_env="SIM_DELAY=0.1"
        )

        jobs_screen = JobsScreen(
            workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
        )
        pilot.app.push_screen(jobs_screen)
        await pilot.pause()

        # Job completado.
        jobs_screen.query_one("#job-description", TextArea).text = "a completed task"
        await pilot.click("#send-job")
        await pilot.pause()
        await _wait_for_status_containing(jobs_screen, "completado")

        # Job en curso (running): se despacha con un delay largo en un
        # segundo hilo, sin esperar a que termine, para verificar que el
        # histórico distingue `running` de `completed`/`failed` mientras
        # el Job sigue en curso del lado del backend.
        _launch_cooperative_agent(
            backend, monkeypatch, tmp_path, extra_env="SIM_DELAY=5", role="arquitecto"
        )
        second_agent = next(
            a for a in backend.get_agents() if a["role"] == "arquitecto"
        )

        import threading

        def _dispatch_slow_job():
            backend.create_and_dispatch_job(second_agent["id"], "a running task")

        thread = threading.Thread(target=_dispatch_slow_job, daemon=True)
        thread.start()

        # Espera activa a que el Job "running" aparezca en el histórico
        # del backend (creado antes de que el thread bloquee 5s en
        # dispatch).
        deadline = asyncio.get_event_loop().time() + 3.0
        while asyncio.get_event_loop().time() < deadline:
            jobs = backend.get_jobs()
            if any(job["description"] == "a running task" for job in jobs):
                break
            await asyncio.sleep(0.05)

        jobs_screen._refresh_history()

        history_text = str(
            jobs_screen.query_one("#job-history-text", Static).content
        )
        assert "[completed]" in history_text
        assert "a completed task" in history_text
        assert "[running]" in history_text
        assert "a running task" in history_text

        thread.join(timeout=10.0)


async def test_cancel_job_button_appears_and_cancels_a_real_job_from_the_tui(
    tmp_path, backend, monkeypatch
) -> None:
    # Criterios de aceptación de T-FB019-US01-02: "Cancelar un Job en
    # curso desde la TUI lo refleja como cancelled también si se consulta
    # desde la app u otro cliente" y "El agente involucrado queda idle
    # tras cancelar, disponible para el siguiente Job, verificado desde la
    # propia TUI." tmux real, delay largo deliberado para que la
    # cancelación llegue mientras el Job sigue realmente en curso.
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _select_project_and_start_backend_session(workspace_root, state_dir)

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        agent = _launch_cooperative_agent(
            backend, monkeypatch, tmp_path, extra_env="SIM_DELAY=10"
        )

        jobs_screen = JobsScreen(
            workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
        )
        pilot.app.push_screen(jobs_screen)
        await pilot.pause()

        jobs_screen.query_one("#job-description", TextArea).text = "a cancellable task"
        await pilot.click("#send-job")
        await pilot.pause()

        # Espera a que el botón "Cancelar Job" aparezca (montado por
        # `_locate_dispatched_job_in_background` en cuanto localiza el
        # `job_id` real) — evidencia de que la localización sin
        # `POST /jobs` devolviendo el id de forma anticipada funciona de
        # verdad, no solo en teoría.
        deadline = asyncio.get_event_loop().time() + 5.0
        while asyncio.get_event_loop().time() < deadline:
            if len(jobs_screen.query("#cancel-job").nodes) == 1:
                break
            await asyncio.sleep(0.1)
        assert len(jobs_screen.query("#cancel-job").nodes) == 1

        # Primer clic: pide confirmación, no cancela todavía (patrón de
        # "segunda pulsación", ver docstring de módulo). La confirmación
        # se refleja en la ETIQUETA del propio botón (no en #job-status,
        # que vive en un VerticalScroll de altura variable — ver
        # comentario en `_handle_cancel_job_button` sobre por qué),
        # verificado aquí explícitamente para no reintroducir la
        # regresión de layout encontrada durante el desarrollo.
        await pilot.click("#cancel-job")
        await pilot.pause()
        cancel_button = jobs_screen.query_one("#cancel-job", Button)
        assert "seguro" in str(cancel_button.label).lower()

        # Textual mantiene la clase `-active` del primer clic durante
        # `Button.active_effect_duration` (0.2s, animación visual de
        # "pulsado") — un segundo clic real de un usuario nunca llega tan
        # rápido, pero `pilot.click` sí puede, y `Button._on_click`
        # ignora silenciosamente el clic mientras esa clase siga presente
        # (encontrado depurando esta Task: la confirmación no llegaba a
        # invocarse en absoluto en el segundo clic). Se espera a que pase
        # ese margen antes del segundo clic, igual que un clic humano real.
        await asyncio.sleep(0.25)

        # Segundo clic: confirma y cancela de verdad.
        await pilot.click("#cancel-job")
        await pilot.pause()

        await _wait_for_status_containing(jobs_screen, "cancelado")
        # `remove()` de Textual es asíncrono (`AwaitRemove`) — un
        # `pilot.pause()` extra da tiempo a que el árbol de widgets
        # refleje el desmontaje antes de comprobar su ausencia.
        await pilot.pause()

        assert len(jobs_screen.query("#cancel-job").nodes) == 0

        # "Otro cliente": una segunda instancia de BackendClient contra el
        # mismo backend de prueba, sin pasar por la instancia de la TUI.
        other_client = BackendClient(base_url=backend._base_url)
        jobs = other_client.get_jobs()
        cancelled_job = next(j for j in jobs if j["description"] == "a cancellable task")
        assert cancelled_job["status"] == "cancelled"

        agents = other_client.get_agents()
        cancelled_job_agent = next(a for a in agents if a["id"] == agent["id"])
        assert cancelled_job_agent["status"] == "idle"
