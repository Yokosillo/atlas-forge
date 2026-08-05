"""Tests de `BacklogScreen`/`BacklogEpicScreen`/`BacklogItemScreen`
(T-FB020-US01-02): mismo patrón que `test_plan_screen.py` — backend real
de prueba (`running_backend`), `FactoryBrainApp.run_test()`/`Pilot`, y
ficheros `.md` reales escritos a `tmp_path` (nunca un backlog mockeado,
mismo criterio que `test_api_routes_backlog.py`)."""

import sys
from pathlib import Path

import pytest
from textual.widgets import Button, Select, Static

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
from backend_server import running_backend  # noqa: E402

from brain.core.session_registry import (
    _reset_registry_for_tests,
    resolve_startup_session,
    shutdown_current_session,
)
from brain.dispatcher.job_history_registry import (
    _reset_registry_for_tests as _reset_job_history_registry_for_tests,
)
from brain.runtime.agent_runtime_registry import (
    _reset_registry_for_tests as _reset_runtime_registry_for_tests,
)
from brain.tui.app import FactoryBrainApp
from brain.tui.backend_client import BackendClient
from brain.tui.screens import BacklogEpicScreen, BacklogItemScreen, BacklogScreen
from brain.workspace.active_project import select_active_project
from brain.workspace.discovery import discover_projects


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
def backend(tmp_path: Path):
    with running_backend(
        workspace_root=tmp_path / "workspace", state_dir=tmp_path / "state"
    ) as base_url:
        yield BackendClient(base_url=base_url)


def _make_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()


def _select_project_and_start_backend_session(workspace_root: Path, state_dir: Path) -> Path:
    repo_path = workspace_root / "my-project"
    _make_git_repo(repo_path)
    discovered = discover_projects(workspace_root)
    select_active_project(discovered[0], discovered=discovered, state_dir=state_dir)
    resolve_startup_session(workspace_root=workspace_root, state_dir=state_dir)
    return repo_path


def _write_epic_file(path: Path, epic_id: str, *, objetivo: str = "Objetivo de la Epic.") -> None:
    """Fiel al formato real de `02-backlog/epics/*.md` (mismo fixture que
    `test_api_routes_backlog.py`, tras la corrección del hallazgo del
    Crítico en T-FB020-US01-01): secciones internas en `#`, no `##`."""
    path.write_text(
        f"# {epic_id} Epic de prueba\n\n"
        f"## Objetivo\n\n{objetivo}\n\n"
        "---\n\n"
        "# Contexto\n\nInvestigación previa.\n",
        encoding="utf-8",
    )


def _write_user_story(
    path: Path,
    item_id: str,
    *,
    epic: str,
    state: str,
    historia: str = "Como usuario quiero X para lograr Y.",
    criterios: str = "- Criterio uno.\n- Criterio dos.",
) -> None:
    path.write_text(
        f"# {item_id}\n"
        f"**Epic:** {epic}\n\n"
        f"## Historia\n\n{historia}\n\n"
        f"## Criterios de aceptación\n\n{criterios}\n\n"
        f"## Estado\n\n{state}\n\n"
        "## Dependencias\n\nNinguna.\n\n"
        "## Prioridad\n\nAlta.\n",
        encoding="utf-8",
    )


def _write_task(
    path: Path,
    item_id: str,
    *,
    epic: str,
    state: str,
    dependencies: str = "Ninguna.",
    objetivo: str = "Objetivo de la Task.",
) -> None:
    path.write_text(
        f"# {item_id}\n"
        f"**Epic:** {epic}\n\n"
        f"## Objetivo\n\n{objetivo}\n\n"
        "## Criterios de aceptación\n\n- Criterio único.\n\n"
        f"## Estado\n\n{state}\n\n"
        f"## Dependencias\n\n{dependencies}\n\n"
        "## Prioridad\n\nAlta.\n",
        encoding="utf-8",
    )


def _seed_backlog(repo_path: Path) -> None:
    """Backlog sintético: Epic FB-999 con 1 US y 2 Tasks (una dependiente
    de la US), mismo escenario ya verificado en
    `test_api_routes_backlog.py`."""
    backlog = repo_path / "02-backlog"
    (backlog / "epics").mkdir(parents=True)
    (backlog / "user-stories").mkdir(parents=True)
    (backlog / "tasks").mkdir(parents=True)

    _write_epic_file(backlog / "epics" / "FB-999-epic-de-prueba.md", "FB-999")
    _write_user_story(
        backlog / "user-stories" / "US-FB999-01.md",
        "US-FB999-01",
        epic="FB-999 · Epic de prueba",
        state="TODO",
    )
    _write_task(
        backlog / "tasks" / "T-FB999-US01-01.md",
        "T-FB999-US01-01",
        epic="FB-999 · Epic de prueba (alcance v1)",
        state="DONE",
        dependencies="**US-FB999-01**",
    )
    _write_task(
        backlog / "tasks" / "T-FB999-US01-02.md",
        "T-FB999-US01-02",
        epic="FB-999 · Epic de prueba",
        state="TODO",
        dependencies="**US-FB999-01**",
    )


async def test_epic_list_shows_epics_with_their_user_story_and_task_counts(
    tmp_path, backend
) -> None:
    # Criterio de aceptación 1: "Desde la app Android y la TUI existe una
    # vista que lista las Epics del proyecto activo con el conteo de sus
    # User Stories por estado."
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    repo_path = _select_project_and_start_backend_session(workspace_root, state_dir)
    _seed_backlog(repo_path)

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        backlog_screen = BacklogScreen(
            workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
        )
        pilot.app.push_screen(backlog_screen)
        await pilot.pause()

        text = str(backlog_screen.query_one("#epic-list", Static).content)
        assert "FB-999 Epic de prueba" in text
        # T-FB020-US03-01: progreso agregado (DONE/total de US) visible
        # por defecto sin expandir — el desglose por estado (`TODO=1`)
        # solo aparece al expandir (ver
        # test_expanding_an_epic_shows_its_state_breakdown_in_place).
        assert "0/1 US DONE" in text
        assert len(backlog_screen.query("#open-epic-0").nodes) == 1


async def test_empty_backlog_shows_explicit_message_not_an_error(tmp_path, backend) -> None:
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _select_project_and_start_backend_session(workspace_root, state_dir)
    # Sin `_seed_backlog`: proyecto activo real, pero sin `02-backlog/`
    # todavía — `build_backlog_report` lo trata como backlog vacío
    # (`empty=True`), no como error (T-FB018-US02-02).

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        backlog_screen = BacklogScreen(
            workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
        )
        pilot.app.push_screen(backlog_screen)
        await pilot.pause()

        text = str(backlog_screen.query_one("#epic-list", Static).content)
        assert "vacío" in text.lower()
        assert len(backlog_screen.query("#backend-error").nodes) == 0


async def test_selecting_an_epic_shows_its_objective_and_user_stories(tmp_path, backend) -> None:
    # Criterio de aceptación 2: "Tocar/seleccionar una Epic muestra sus
    # User Stories con el mismo desglose."
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    repo_path = _select_project_and_start_backend_session(workspace_root, state_dir)
    _seed_backlog(repo_path)

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        backlog_screen = BacklogScreen(
            workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
        )
        pilot.app.push_screen(backlog_screen)
        await pilot.pause()

        await pilot.click("#open-epic-0")
        await pilot.pause()

        assert isinstance(pilot.app.screen, BacklogEpicScreen)
        text = str(pilot.app.screen.query_one("#epic-detail", Static).content)
        assert "FB-999" in text
        assert "Objetivo de la Epic." in text
        assert "User Stories:" in text
        # El id/estado de cada User Story viaja en la etiqueta de su botón
        # (mismo patrón que la lista de Epics), no en el bloque de texto.
        user_story_button = pilot.app.screen.query_one("#open-item-0", Button)
        assert "US-FB999-01" in str(user_story_button.label)
        assert "TODO" in str(user_story_button.label)
        assert "(TODO)" in str(user_story_button.label)


# ---------------------------------------------------------------------------
# T-FB020-US03-01: código de color por estado, progreso agregado por Epic,
# expandir/colapsar in-place — sin tocar los endpoints (mismos campos que
# GET /backlog/GET /backlog/{item_id} ya traían).
# ---------------------------------------------------------------------------


async def test_epic_list_shows_progress_bar_reflecting_done_over_total_user_stories(
    tmp_path, backend
) -> None:
    # Criterio de aceptación 2: "Cada Epic en el listado muestra progreso
    # agregado (proporción DONE/total), no solo el conteo numérico."
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    repo_path = _select_project_and_start_backend_session(workspace_root, state_dir)
    backlog = repo_path / "02-backlog"
    (backlog / "epics").mkdir(parents=True)
    (backlog / "user-stories").mkdir(parents=True)
    (backlog / "tasks").mkdir(parents=True)
    _write_epic_file(backlog / "epics" / "FB-998-progreso.md", "FB-998")
    _write_user_story(
        backlog / "user-stories" / "US-FB998-01.md", "US-FB998-01", epic="FB-998 · Progreso", state="DONE"
    )
    _write_user_story(
        backlog / "user-stories" / "US-FB998-02.md", "US-FB998-02", epic="FB-998 · Progreso", state="DONE"
    )
    _write_user_story(
        backlog / "user-stories" / "US-FB998-03.md", "US-FB998-03", epic="FB-998 · Progreso", state="TODO"
    )
    _write_user_story(
        backlog / "user-stories" / "US-FB998-04.md", "US-FB998-04", epic="FB-998 · Progreso", state="TODO"
    )

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        backlog_screen = BacklogScreen(
            workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
        )
        pilot.app.push_screen(backlog_screen)
        await pilot.pause()

        text = str(backlog_screen.query_one("#epic-list", Static).content)
        # 2/4 DONE -> mitad de la barra rellena (ancho fijo de 10
        # caracteres, `_PROGRESS_BAR_WIDTH`).
        assert "█████░░░░░ 2/4 US DONE" in text


async def test_expanding_an_epic_shows_its_state_breakdown_in_place(tmp_path, backend) -> None:
    # Criterio de aceptación 3: "Es posible expandir/colapsar el desglose
    # de una Epic sin abandonar la pantalla de listado."
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    repo_path = _select_project_and_start_backend_session(workspace_root, state_dir)
    _seed_backlog(repo_path)

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        backlog_screen = BacklogScreen(
            workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
        )
        pilot.app.push_screen(backlog_screen)
        await pilot.pause()

        # Colapsado por defecto: el desglose por estado no está visible.
        collapsed_text = str(backlog_screen.query_one("#epic-list", Static).content)
        assert "US:" not in collapsed_text
        toggle_button = backlog_screen.query_one("#toggle-epic-0", Button)
        assert str(toggle_button.label) == "Expandir"

        await pilot.click("#toggle-epic-0")
        await pilot.pause()

        # Sigue siendo la MISMA pantalla de listado (nunca navegó) — con
        # el desglose ahora visible in-place.
        assert isinstance(pilot.app.screen, BacklogScreen)
        expanded_text = str(backlog_screen.query_one("#epic-list", Static).content)
        assert "US: [dark_orange]TODO[/]=1" in expanded_text
        assert str(backlog_screen.query_one("#toggle-epic-0", Button).label) == "Colapsar"

        # Colapsar de nuevo oculta el desglose sin abandonar el listado.
        # Textual mantiene la clase `-active` del clic anterior durante
        # `Button.active_effect_duration` (0.2s) — un segundo `pilot.click`
        # sobre el MISMO botón antes de ese margen se ignora en silencio
        # (mismo hallazgo ya documentado en `test_jobs_screen.py` para
        # "Cancelar Job"/"segunda pulsación").
        import asyncio

        await asyncio.sleep(0.25)
        await pilot.click("#toggle-epic-0")
        await pilot.pause()
        recollapsed_text = str(backlog_screen.query_one("#epic-list", Static).content)
        assert "US:" not in recollapsed_text
        assert str(backlog_screen.query_one("#toggle-epic-0", Button).label) == "Expandir"

        # El drill-down original (T-FB020-US01-02) sigue disponible como
        # alternativa — "Ver {epic}" todavía navega al detalle completo.
        assert len(backlog_screen.query("#open-epic-0").nodes) == 1


async def test_task_and_user_story_states_are_color_coded(tmp_path, backend) -> None:
    # Criterio de aceptación 1: "Cada fila de Epic/User Story/Task en
    # ambos clientes muestra un indicador de color junto a su texto de
    # estado... equivalente semántico en TUI."
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    repo_path = _select_project_and_start_backend_session(workspace_root, state_dir)
    _seed_backlog(repo_path)

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        item_screen = BacklogItemScreen(
            item_id="US-FB999-01",
            workspace_root=workspace_root,
            state_dir=state_dir,
            backend_client=backend,
        )
        pilot.app.push_screen(item_screen)
        await pilot.pause()

        text = str(item_screen.query_one("#item-detail", Static).content)
        # Estado de la propia US (TODO) coloreado en la cabecera.
        assert "Estado: [dark_orange]TODO[/]" in text
        # Sus dos Tasks, cada una con su color real (una DONE, una TODO).
        assert "T-FB999-US01-01 ([green]DONE[/])" in text
        assert "T-FB999-US01-02 ([dark_orange]TODO[/])" in text


async def test_unrecognized_state_uses_the_neutral_color_never_done_or_todo(
    tmp_path, backend
) -> None:
    # Criterio de aceptación 4: "Un estado no reconocido usa un color
    # neutro explícito, nunca se confunde visualmente con DONE o TODO."
    # Caso real verificado sobre el backlog de este proyecto:
    # "DESCARTADA (en principio)" (FB-015), "SUPERADA (ver ...)" (FB-017).
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    repo_path = _select_project_and_start_backend_session(workspace_root, state_dir)
    backlog = repo_path / "02-backlog"
    (backlog / "user-stories").mkdir(parents=True)
    (backlog / "tasks").mkdir(parents=True)
    _write_user_story(
        backlog / "user-stories" / "US-FB997-01.md",
        "US-FB997-01",
        epic="FB-997 · Epic descartada",
        state="DESCARTADA (en principio)",
    )

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        item_screen = BacklogItemScreen(
            item_id="US-FB997-01",
            workspace_root=workspace_root,
            state_dir=state_dir,
            backend_client=backend,
        )
        pilot.app.push_screen(item_screen)
        await pilot.pause()

        text = str(item_screen.query_one("#item-detail", Static).content)
        assert "[bright_black]DESCARTADA (en principio)[/]" in text
        assert "[green]" not in text
        assert "[dark_orange]" not in text


async def test_selecting_a_user_story_shows_objective_criteria_and_its_tasks(
    tmp_path, backend
) -> None:
    # Criterio de aceptación 3: "Tocar/seleccionar una User Story muestra
    # su detalle completo: objetivo, criterios de aceptación, Tasks con
    # estado."
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    repo_path = _select_project_and_start_backend_session(workspace_root, state_dir)
    _seed_backlog(repo_path)

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        backlog_screen = BacklogScreen(
            workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
        )
        pilot.app.push_screen(backlog_screen)
        await pilot.pause()

        await pilot.click("#open-epic-0")
        await pilot.pause()
        await pilot.click("#open-item-0")
        await pilot.pause()

        assert isinstance(pilot.app.screen, BacklogItemScreen)
        text = str(pilot.app.screen.query_one("#item-detail", Static).content)
        assert "US-FB999-01" in text
        assert "Como usuario quiero X para lograr Y." in text
        assert "Criterio uno." in text
        # Sus dos Tasks (una DONE, una TODO), ambas declaran esta US en
        # `## Dependencias` — derivado del grafo, sin releer ficheros.
        assert "T-FB999-US01-01" in text
        assert "T-FB999-US01-02" in text
        # T-FB020-US03-01: el estado va coloreado con marcado Rich
        # (verde=DONE, ámbar=TODO) — verificado con más detalle en
        # test_task_and_user_story_states_are_color_coded.
        assert "[green]DONE[/]" in text
        assert "[dark_orange]TODO[/]" in text


async def test_malformed_item_shows_explicit_warning_without_breaking_navigation(
    tmp_path, backend
) -> None:
    # Criterio de aceptación 4: "Un fichero mal formado se refleja como
    # aviso explícito en su entrada, sin romper la vista completa."
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    repo_path = _select_project_and_start_backend_session(workspace_root, state_dir)
    _seed_backlog(repo_path)
    # Task sin `## Objetivo` ni `## Criterios de aceptación` — provoca
    # `parse_warning` en `GET /backlog/{item_id}` (T-FB020-US01-01),
    # nunca un fallo del endpoint entero.
    (repo_path / "02-backlog" / "tasks" / "T-FB999-US01-03.md").write_text(
        "# T-FB999-US01-03\n"
        "**Epic:** FB-999 · Epic de prueba\n\n"
        "## Estado\n\nTODO\n\n"
        "## Dependencias\n\n**US-FB999-01**\n\n"
        "## Prioridad\n\nMedia.\n",
        encoding="utf-8",
    )

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        item_screen = BacklogItemScreen(
            item_id="T-FB999-US01-03",
            workspace_root=workspace_root,
            state_dir=state_dir,
            backend_client=backend,
        )
        pilot.app.push_screen(item_screen)
        await pilot.pause()

        text = str(item_screen.query_one("#item-detail", Static).content)
        assert "⚠" in text
        assert "sin objetivo declarado" in text.lower()
        # La navegación sigue disponible pese al aviso (botón "Volver"
        # presente, pantalla no rota).
        assert len(item_screen.query("#go-back").nodes) == 1


async def test_recontextualizes_on_active_project_change(tmp_path, backend) -> None:
    # Criterio de aceptación 5: "Cambiar el proyecto activo recarga la
    # vista con los datos del nuevo proyecto, no mezcla datos de ambos" —
    # mismo criterio ya aplicado en el resto de la app (US-FB017-03). La
    # TUI resuelve esto "gratis": cada navegación a Backlog crea una
    # instancia NUEVA de `BacklogScreen`, que pide `GET /backlog` fresco
    # (ver docstring de módulo de `brain/tui/screens/backlog.py`).
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    repo_a = _select_project_and_start_backend_session(workspace_root, state_dir)
    _seed_backlog(repo_a)

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        first_screen = BacklogScreen(
            workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
        )
        pilot.app.push_screen(first_screen)
        await pilot.pause()
        first_text = str(first_screen.query_one("#epic-list", Static).content)
        assert "FB-999" in first_text
        pilot.app.pop_screen()
        await pilot.pause()

        # Cambia el proyecto activo a uno NUEVO, con una Epic distinta —
        # mismo mecanismo que `post_project` (`brain/api/routes.py`) usa
        # al cambiar de proyecto en caliente: cerrar la sesión anterior
        # antes de arrancar la del proyecto nuevo.
        repo_b = workspace_root / "my-second-project"
        _make_git_repo(repo_b)
        discovered = discover_projects(workspace_root)
        second_project = next(p for p in discovered if p.path == str(repo_b))
        select_active_project(second_project, discovered=discovered, state_dir=state_dir)
        shutdown_current_session()
        resolve_startup_session(workspace_root=workspace_root, state_dir=state_dir)

        backlog_b = repo_b / "02-backlog"
        (backlog_b / "epics").mkdir(parents=True)
        (backlog_b / "user-stories").mkdir(parents=True)
        (backlog_b / "tasks").mkdir(parents=True)
        _write_epic_file(backlog_b / "epics" / "FB-777-otra-epic.md", "FB-777")
        _write_user_story(
            backlog_b / "user-stories" / "US-FB777-01.md",
            "US-FB777-01",
            epic="FB-777 · Otra Epic",
            state="DONE",
        )

        second_screen = BacklogScreen(
            workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
        )
        pilot.app.push_screen(second_screen)
        await pilot.pause()

        second_text = str(second_screen.query_one("#epic-list", Static).content)
        assert "FB-777" in second_text
        assert "FB-999" not in second_text


# ---------------------------------------------------------------------------
# T-FB020-US02-02: botón "Lanzar desarrollo" en `BacklogItemScreen`
# (consume `POST /backlog/{story_id}/launch-development`, T-FB020-US02-01).
# Agente cooperativo real vía tmux (mismo patrón que
# `test_api_routes_launch_development.py`/`test_plan_screen.py`), nunca
# mockeado.
# ---------------------------------------------------------------------------

_COOPERATIVE_AGENT_SCRIPT = str(Path(__file__).parent / "fixtures" / "cooperative_agent_sim.sh")


def _launch_cooperative_developer(backend, monkeypatch, extra_env: str = ""):
    import brain.runtime.claude_code as claude_code_module

    monkeypatch.setattr(
        claude_code_module, "DEFAULT_CLAUDE_CODE_COMMAND", f"{extra_env} bash".strip()
    )
    monkeypatch.setattr(
        claude_code_module, "DEFAULT_CLAUDE_CODE_ARGS", [_COOPERATIVE_AGENT_SCRIPT]
    )
    return backend.launch_agent("developer", "claude-code", None)


async def test_launch_development_dispatches_a_real_job_visible_in_jobs_screen(
    tmp_path, backend, monkeypatch
) -> None:
    # Criterios de aceptación 1 y 3: "Desde el detalle de una User Story
    # con Tasks TODO, se puede elegir un agente Developer y lanzar su
    # desarrollo sin escribir ninguna descripción a mano" + "El Job
    # lanzado aparece en la pantalla de Jobs de la sesión sin cambios
    # adicionales en esa pantalla."
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    repo_path = _select_project_and_start_backend_session(workspace_root, state_dir)
    _seed_backlog(repo_path)
    developer = _launch_cooperative_developer(backend, monkeypatch)

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        item_screen = BacklogItemScreen(
            item_id="US-FB999-01",
            workspace_root=workspace_root,
            state_dir=state_dir,
            backend_client=backend,
        )
        pilot.app.push_screen(item_screen)
        await pilot.pause()

        select_widget = item_screen.query_one("#launch-development-agent-choice", Select)
        assert select_widget.value == developer["id"]

        await pilot.click("#launch-development")
        await pilot.pause()

        # `POST /backlog/{story_id}/launch-development` es bloqueante —
        # despachado en un worker de hilo (`@work(thread=True)`), esperar
        # a que el estado refleje el resultado final.
        import asyncio

        status_widget = item_screen.query_one("#launch-development-status", Static)
        deadline = asyncio.get_event_loop().time() + 10.0
        while (
            "despachado" not in str(status_widget.content).lower()
            and asyncio.get_event_loop().time() < deadline
        ):
            await asyncio.sleep(0.1)

        assert "despachado" in str(status_widget.content).lower()

        # "El Job aparece en la pantalla de Jobs... sin cambios
        # adicionales en esa pantalla" — verificado abriendo la pantalla
        # de Jobs REAL, sin construir nada nuevo ahí.
        from brain.tui.screens import JobsScreen

        jobs_screen = JobsScreen(
            workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
        )
        pilot.app.push_screen(jobs_screen)
        await pilot.pause()

        history_text = str(jobs_screen.query_one("#job-history-text", Static).content)
        assert developer["id"] in history_text
        assert "completed" in history_text
        assert "Lanzar desarrollo de US-FB999-01." in history_text

        # La `description` real generada por el backend (objetivo +
        # títulos de Tasks TODO) — verificada completa vía `GET /jobs`
        # (`JobsScreen` solo muestra la primera línea resumida en su
        # histórico, comportamiento ya existente que esta Task no toca,
        # ver criterio de aceptación 3: "sin ningún cambio en esa
        # pantalla").
        dispatched_job = next(
            job for job in backend.get_jobs() if job["agent_id"] == developer["id"]
        )
        assert "Como usuario quiero X para lograr Y." in dispatched_job["description"]
        # `_write_task` no incluye ` · <título>` en la cabecera (formato
        # `# {item_id}`, sin título separado) — `_read_task_title`
        # (`job_plan_builder.py`) cae al `fallback` (el propio id del
        # fichero) en ese caso, mismo criterio ya verificado en
        # `test_api_routes_launch_development.py`.
        assert "T-FB999-US01-02" in dispatched_job["description"]
        # La Task ya DONE (T-FB999-US01-01) nunca debe aparecer.
        assert "T-FB999-US01-01" not in dispatched_job["description"]


async def test_launch_development_shows_the_real_400_detail_when_no_pending_tasks(
    tmp_path, backend, monkeypatch
) -> None:
    # Criterio de aceptación 2: "Si la User Story no tiene Tasks TODO, la
    # acción se rechaza con el motivo explícito del backend, sin lanzar
    # nada" — nunca un mensaje genérico tipo "not found".
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    repo_path = _select_project_and_start_backend_session(workspace_root, state_dir)
    backlog = repo_path / "02-backlog"
    (backlog / "user-stories").mkdir(parents=True)
    (backlog / "tasks").mkdir(parents=True)
    _write_user_story(
        backlog / "user-stories" / "US-FB998-01.md",
        "US-FB998-01",
        epic="FB-998 · Epic sin Tasks pendientes",
        state="TODO",
    )
    _write_task(
        backlog / "tasks" / "T-FB998-US01-01.md",
        "T-FB998-US01-01",
        epic="FB-998 · Epic sin Tasks pendientes",
        state="DONE",
        dependencies="**US-FB998-01**",
    )
    developer = _launch_cooperative_developer(backend, monkeypatch)

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        item_screen = BacklogItemScreen(
            item_id="US-FB998-01",
            workspace_root=workspace_root,
            state_dir=state_dir,
            backend_client=backend,
        )
        pilot.app.push_screen(item_screen)
        await pilot.pause()

        await pilot.click("#launch-development")
        await pilot.pause()

        import asyncio

        status_widget = item_screen.query_one("#launch-development-status", Static)
        deadline = asyncio.get_event_loop().time() + 10.0
        while (
            str(status_widget.content) in ("", "Lanzando desarrollo...")
            and asyncio.get_event_loop().time() < deadline
        ):
            await asyncio.sleep(0.1)

        status_text = str(status_widget.content)
        assert "US-FB998-01" in status_text
        assert "no tiene Tasks pendientes" in status_text
        # Nunca lanzado: sin Job en el histórico de la sesión.
        assert backend.get_jobs() == []


async def test_launch_development_double_click_does_not_dispatch_two_jobs(
    tmp_path, backend, monkeypatch
) -> None:
    # Criterio de aceptación 4: "Un doble clic en 'Lanzar desarrollo' no
    # despacha dos Jobs" — mismo criterio de `SingleFlightAction` en
    # Android, aquí el guard `_launch_in_flight` deshabilita el botón
    # antes de arrancar el worker de despacho.
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    repo_path = _select_project_and_start_backend_session(workspace_root, state_dir)
    _seed_backlog(repo_path)
    _launch_cooperative_developer(backend, monkeypatch, extra_env="SIM_DELAY=1")

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        item_screen = BacklogItemScreen(
            item_id="US-FB999-01",
            workspace_root=workspace_root,
            state_dir=state_dir,
            backend_client=backend,
        )
        pilot.app.push_screen(item_screen)
        await pilot.pause()

        await pilot.click("#launch-development")
        await pilot.pause()
        # El botón se deshabilita de inmediato, ANTES de que el despacho
        # bloqueante (SIM_DELAY=1) termine.
        assert item_screen.query_one("#launch-development", Button).disabled

        # Segundo clic mientras el primero sigue en vuelo.
        await pilot.click("#launch-development")
        await pilot.pause()

        import asyncio

        status_widget = item_screen.query_one("#launch-development-status", Static)
        deadline = asyncio.get_event_loop().time() + 10.0
        while (
            "despachado" not in str(status_widget.content).lower()
            and asyncio.get_event_loop().time() < deadline
        ):
            await asyncio.sleep(0.1)

        # Un único Job real despachado, no dos.
        assert len(backend.get_jobs()) == 1


async def test_navigating_from_dashboard_to_backlog_screen(tmp_path, backend) -> None:
    workspace_root = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _select_project_and_start_backend_session(workspace_root, state_dir)

    app = FactoryBrainApp(
        workspace_root=workspace_root, state_dir=state_dir, backend_client=backend
    )
    async with app.run_test() as pilot:
        await pilot.pause()

        await pilot.click("#go-to-backlog")
        await pilot.pause()

        assert isinstance(pilot.app.screen, BacklogScreen)
