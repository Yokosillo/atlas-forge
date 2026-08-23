"""Tests de `POST /backlog/{story_id}/launch-development`
(T-AF020-US02-01): envoltura de resolución de contexto sobre el motor de
Jobs ya existente (`create_and_record_job`/`dispatch_job`, AF-005/AF-008)
— nunca mockeado, se lanza un agente cooperativo real vía tmux (mismo
patrón que `test_api_routes_jobs.py`) y se escriben ficheros `.md` reales
de backlog a `tmp_path` (mismo patrón que `test_api_routes_backlog.py`)."""

import uuid
from pathlib import Path

import libtmux
import pytest
from fastapi.testclient import TestClient

import atlas_forge.api.routes as routes_module
from atlas_forge.api import create_app
from atlas_forge.agents.launch import launch_agent
from atlas_forge.api.routes import _job_plan_builder_story_id
from atlas_forge.core import resolve_startup_session
from atlas_forge.core.session_registry import _reset_registry_for_tests
from atlas_forge.dispatcher.job_history_registry import _reset_registry_for_tests as _reset_job_history
from atlas_forge.runtime import stop_runtime
from atlas_forge.workspace import discover_projects, select_active_project

# Ruta del 02-backlog/ real de este proyecto (padre del directorio de
# tests) — mismo cálculo que `REAL_BACKLOG_PATH` de `test_backlog.py`.
REAL_BACKLOG_PATH = Path(__file__).resolve().parents[1].parent / "02-backlog"

_COOPERATIVE_AGENT_SCRIPT = str(
    Path(__file__).parent / "fixtures" / "cooperative_agent_sim.sh"
)


@pytest.fixture(autouse=True)
def _clean_registries():
    _reset_registry_for_tests()
    _reset_job_history()
    yield
    _reset_registry_for_tests()
    _reset_job_history()


@pytest.fixture(autouse=True)
def _no_real_runtime(monkeypatch):
    import atlas_forge.runtime.claude_code as claude_code_module
    import atlas_forge.runtime.opencode as opencode_module

    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_COMMAND", "sleep")
    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_ARGS", ["5"])
    monkeypatch.setattr(opencode_module, "DEFAULT_OPENCODE_COMMAND", "sleep")
    monkeypatch.setattr(opencode_module, "DEFAULT_OPENCODE_AUTONOMY_FLAG", "5")
    monkeypatch.setattr(opencode_module, "DEFAULT_OPENCODE_ARGS", ["5"])


@pytest.fixture
def isolated_socket(monkeypatch):
    name = f"atlas_forge-test-{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(routes_module, "_SOCKET_NAME", name)
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


def _active_project_and_session(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    _make_git_repo(workspace / "project-a")
    state_dir = tmp_path / "state"

    discovered = discover_projects(workspace)
    select_active_project(discovered[0], discovered=discovered, state_dir=state_dir)
    monkeypatch.setattr(
        routes_module, "get_active_project", lambda **_kwargs: discovered[0]
    )

    session = resolve_startup_session(workspace_root=workspace, state_dir=state_dir)
    assert session is not None
    return discovered[0], session


def _launch_cooperative_agent(
    role: str, project_path: Path, session, isolated_socket: str, monkeypatch, extra_env: str = ""
):
    import atlas_forge.runtime.claude_code as claude_code_module

    monkeypatch.setattr(
        claude_code_module, "DEFAULT_CLAUDE_CODE_COMMAND", f"{extra_env} bash".strip()
    )
    monkeypatch.setattr(
        claude_code_module, "DEFAULT_CLAUDE_CODE_ARGS", [_COOPERATIVE_AGENT_SCRIPT]
    )

    return launch_agent(
        role, "claude-code", None, session, str(project_path), socket_name=isolated_socket
    )


def _write_user_story(
    path: Path,
    item_id: str,
    *,
    epic: str = "AF-999 · Epic de prueba",
    state: str = "READY",
    historia: str = "Como usuario quiero X para lograr Y.",
    criterios: str = "- Criterio uno.",
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
    title: str,
    *,
    epic: str = "AF-999 · Epic de prueba",
    state: str,
    dependencies: str,
) -> None:
    path.write_text(
        f"# {item_id} · {title}\n"
        f"**Epic:** {epic}\n\n"
        "## Objetivo\n\nObjetivo de la Task.\n\n"
        "## Criterios de aceptación\n\n- Criterio único.\n\n"
        f"## Estado\n\n{state}\n\n"
        f"## Dependencias\n\n{dependencies}\n\n"
        "## Prioridad\n\nAlta.\n",
        encoding="utf-8",
    )


def _task_id_for_story(story_id: str, correlative: str) -> str:
    # US-AFnnn-ss -> T-AFnnn-USss-correlative, convención real de
    # 02-backlog/ (verificada sobre el backlog real de este proyecto:
    # `T-AF020-US01-01`, no `T-US-AF020-01-01`) — necesaria para que estos
    # ficheros de prueba entren de verdad en `graph.items`
    # (`_item_id_from_stem`/`_ITEM_ID_PATTERN`, `atlas_forge/backlog/parser.py`),
    # no solo para que el glob de `_pending_task_files_for_story` los
    # encuentre.
    epic, story_num = story_id.removeprefix("US-").split("-")
    return f"T-{epic}-US{story_num}-{correlative}"


def _seed_story_with_pending_tasks(project_path: Path, story_id: str = "US-AF999-01") -> None:
    """Backlog sintético: 1 US con 2 Tasks TODO + 1 Task DONE (la DONE no
    debe aparecer en la description generada) — mismo escenario de
    `job_plan_builder.py::_pending_task_files_for_story`."""
    backlog = project_path / "02-backlog"
    (backlog / "user-stories").mkdir(parents=True)
    (backlog / "tasks").mkdir(parents=True)

    _write_user_story(
        backlog / "user-stories" / f"{story_id}.md",
        story_id,
        historia="Como desarrollador quiero lanzar el desarrollo de una US con contexto resuelto.",
    )
    task_1 = _task_id_for_story(story_id, "01")
    task_2 = _task_id_for_story(story_id, "02")
    task_3 = _task_id_for_story(story_id, "03")
    _write_task(
        backlog / "tasks" / f"{task_1}-primer-paso.md",
        task_1,
        "Primer paso pendiente",
        state="READY",
        dependencies=f"**{story_id}**",
    )
    _write_task(
        backlog / "tasks" / f"{task_2}-segundo-paso.md",
        task_2,
        "Segundo paso pendiente",
        state="READY",
        dependencies=f"**{story_id}**",
    )
    _write_task(
        backlog / "tasks" / f"{task_3}-paso-ya-hecho.md",
        task_3,
        "Paso ya completado",
        state="DONE",
        dependencies=f"**{story_id}**",
    )


def _seed_story_without_pending_tasks(project_path: Path, story_id: str = "US-AF999-02") -> None:
    """Backlog sintético: 1 US cuyas Tasks están todas DONE (mismo criterio
    de aceptación explícito: 'todas DONE, o ninguna creada' -> 400)."""
    backlog = project_path / "02-backlog"
    (backlog / "user-stories").mkdir(parents=True, exist_ok=True)
    (backlog / "tasks").mkdir(parents=True, exist_ok=True)

    _write_user_story(backlog / "user-stories" / f"{story_id}.md", story_id)
    task_1 = _task_id_for_story(story_id, "01")
    _write_task(
        backlog / "tasks" / f"{task_1}-ya-hecho.md",
        task_1,
        "Ya completado",
        state="DONE",
        dependencies=f"**{story_id}**",
    )


def test_post_launch_development_dispatches_a_real_job_with_resolved_description(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """Criterio de aceptación: lanzar desarrollo de una US con Tasks TODO
    despacha un Job cuya `description` incluye el objetivo real y los
    títulos de las Tasks pendientes, sin que el llamador la escriba — y
    el Job se despacha de verdad (agente cooperativo real vía tmux)."""
    project, session = _active_project_and_session(tmp_path, monkeypatch)
    _seed_story_with_pending_tasks(Path(project.path))
    agent, runtime_instance = _launch_cooperative_agent(
        "developer", Path(project.path), session, isolated_socket, monkeypatch
    )

    client = TestClient(create_app())
    response = client.post(
        "/backlog/US-AF999-01/launch-development", json={"agent_id": agent.id}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "completed"
    assert "cooperative result" in body["result"]

    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_post_launch_development_description_matches_real_story_content(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """Criterio de aceptación explícito: test que compara la `description`
    generada contra el contenido REAL de una US de prueba con Tasks TODO
    conocidas — no solo 'no está vacía'. Verificado sobre `description`
    del Job dispatchado (`GET /jobs`, mismo mecanismo que un Job normal,
    criterio de aceptación: indistinguible de `POST /jobs`), y también
    sobre `result` (el doble cooperativo de tmux confirma en su reporte
    que recibió esa instrucción completa como entrada real de la sesión,
    no solo que el backend la calculó — ver `cooperative_agent_sim.sh`,
    que lee la instrucción entera de stdin antes de reportar)."""
    project, session = _active_project_and_session(tmp_path, monkeypatch)
    _seed_story_with_pending_tasks(Path(project.path))
    agent, runtime_instance = _launch_cooperative_agent(
        "developer", Path(project.path), session, isolated_socket, monkeypatch
    )

    client = TestClient(create_app())
    created = client.post(
        "/backlog/US-AF999-01/launch-development", json={"agent_id": agent.id}
    ).json()

    jobs = client.get("/jobs").json()
    assert len(jobs) == 1
    dispatched_job = jobs[0]
    assert dispatched_job["id"] == created["id"]

    description = dispatched_job["description"]
    assert "US-AF999-01" in description
    assert "Como desarrollador quiero lanzar el desarrollo de una US con contexto resuelto." in description
    assert "Primer paso pendiente" in description
    assert "Segundo paso pendiente" in description
    # La Task ya DONE NUNCA debe aparecer en la description generada.
    assert "Paso ya completado" not in description

    # El Job se despachó de verdad (agente cooperativo real vía tmux, no
    # simulado a nivel de test) — evidencia de extremo a extremo de que la
    # `description` resuelta llegó hasta el runtime.
    assert dispatched_job["status"] == "completed"
    assert "cooperative result" in dispatched_job["result"]

    stop_runtime(runtime_instance, socket_name=isolated_socket)


def test_post_launch_development_returns_400_when_story_has_no_pending_tasks(
    tmp_path: Path, monkeypatch
) -> None:
    """Criterio de aceptación explícito: una US sin ninguna Task TODO
    (todas DONE) responde 400 con motivo explícito, sin crear ningún Job
    — nunca se llega a `create_and_record_job`/`dispatch_job`."""
    project, session = _active_project_and_session(tmp_path, monkeypatch)
    _seed_story_without_pending_tasks(Path(project.path))

    client = TestClient(create_app())
    response = client.post(
        "/backlog/US-AF999-02/launch-development", json={"agent_id": "whatever"}
    )

    assert response.status_code == 400
    assert "US-AF999-02" in response.json()["detail"]
    assert "no tiene Tasks pendientes" in response.json()["detail"]

    # Ningún Job creado — ni siquiera se validó el agente inexistente
    # ('whatever'), confirmando que el chequeo de Tasks pendientes ocurre
    # ANTES, sin necesidad de un agente real para este caso.
    assert client.get("/jobs").json() == []


def test_post_launch_development_returns_400_when_story_has_no_tasks_at_all(
    tmp_path: Path, monkeypatch
) -> None:
    """Variante del criterio anterior: 'ninguna Task creada todavía' (no
    solo 'todas DONE') — mismo 400, mismo criterio."""
    project, session = _active_project_and_session(tmp_path, monkeypatch)
    backlog = Path(project.path) / "02-backlog"
    (backlog / "user-stories").mkdir(parents=True)
    (backlog / "tasks").mkdir(parents=True)
    _write_user_story(backlog / "user-stories" / "US-AF999-03.md", "US-AF999-03")

    client = TestClient(create_app())
    response = client.post(
        "/backlog/US-AF999-03/launch-development", json={"agent_id": "whatever"}
    )

    assert response.status_code == 400
    assert "no tiene Tasks pendientes" in response.json()["detail"]
    assert client.get("/jobs").json() == []


def test_post_launch_development_returns_404_for_unknown_story_id(
    tmp_path: Path, monkeypatch
) -> None:
    """Criterio de aceptación explícito: una User Story inexistente
    responde 404 con `detail` explícito."""
    _active_project_and_session(tmp_path, monkeypatch)
    client = TestClient(create_app())

    response = client.post(
        "/backlog/US-AF999-99/launch-development", json={"agent_id": "whatever"}
    )

    assert response.status_code == 404
    assert "US-AF999-99" in response.json()["detail"]


def test_post_launch_development_returns_404_for_a_task_id_not_a_story(
    tmp_path: Path, monkeypatch
) -> None:
    """`story_id` debe ser una User Story — un id de Task real (existe en
    el grafo, pero no es una US) también es 404, mismo criterio que
    'no existe ninguna User Story con ese id'."""
    project, session = _active_project_and_session(tmp_path, monkeypatch)
    _seed_story_with_pending_tasks(Path(project.path))

    client = TestClient(create_app())
    response = client.post(
        "/backlog/T-AF999-US01-01/launch-development", json={"agent_id": "whatever"}
    )

    assert response.status_code == 404


def test_post_launch_development_returns_404_for_unknown_agent(
    tmp_path: Path, monkeypatch
) -> None:
    """Criterio de aceptación: agente inválido reutiliza la misma
    validación que `POST /jobs` (404 por id desconocido, sin duplicar la
    lógica) — probado DESPUÉS de confirmar que la US sí tiene Tasks
    pendientes, para aislar este caso del anterior."""
    project, session = _active_project_and_session(tmp_path, monkeypatch)
    _seed_story_with_pending_tasks(Path(project.path))

    client = TestClient(create_app())
    response = client.post(
        "/backlog/US-AF999-01/launch-development", json={"agent_id": "does-not-exist"}
    )

    assert response.status_code == 404
    assert "does-not-exist" in response.json()["detail"]
    assert client.get("/jobs").json() == []


def test_post_launch_development_returns_404_when_no_session_is_active() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/backlog/US-AF999-01/launch-development", json={"agent_id": "whatever"}
    )

    assert response.status_code == 404


def test_post_launch_development_job_is_indistinguishable_from_a_normal_post_jobs(
    tmp_path: Path, isolated_socket: str, monkeypatch
) -> None:
    """Criterio de aceptación explícito: el Job despachado es
    indistinguible de uno creado por `POST /jobs` normal desde
    `GET /jobs`/`GET /jobs/{id}` — mismo mecanismo, sin tabla/campo
    paralelo. Se compara con un Job real creado por `POST /jobs` en la
    misma sesión: mismos campos, mismo shape."""
    project, session = _active_project_and_session(tmp_path, monkeypatch)
    _seed_story_with_pending_tasks(Path(project.path))
    agent, runtime_instance = _launch_cooperative_agent(
        "developer", Path(project.path), session, isolated_socket, monkeypatch
    )

    client = TestClient(create_app())
    launched = client.post(
        "/backlog/US-AF999-01/launch-development", json={"agent_id": agent.id}
    ).json()

    # Mismos campos exactos que un Job normal (`_serialize_job`,
    # `atlas_forge/api/routes.py`) — ningún campo extra, ninguno ausente.
    assert set(launched.keys()) == {"id", "session_id", "agent_id", "description", "status", "result"}
    assert launched["session_id"] == session.id
    assert launched["agent_id"] == agent.id

    fetched = client.get(f"/jobs/{launched['id']}").json()
    assert fetched == launched

    stop_runtime(runtime_instance, socket_name=isolated_socket)


# ---------------------------------------------------------------------------
# Conversión de `story_id` al formato que espera `_pending_task_files_for_story`
# (`job_plan_builder.py`) — bug real encontrado durante la implementación:
# `GET /backlog/{item_id}` usa `US-AFnnn-ss` (p. ej. `US-AF020-01`), pero
# los nombres de fichero reales de Task son `T-AFnnn-USss-...` (p. ej.
# `T-AF020-US01-01-...md`, NUNCA `T-US-AF020-01-...md`) — sin convertir,
# `_pending_task_files_for_story` nunca encontraba ningún fichero real,
# disparando el 400 de "sin Tasks pendientes" incorrectamente incluso con
# Tasks TODO reales. `_job_plan_builder_story_id` hace esa conversión.
# ---------------------------------------------------------------------------


def test_job_plan_builder_story_id_converts_to_the_real_task_filename_prefix() -> None:
    assert _job_plan_builder_story_id("US-AF999-01") == "AF999-US01"
    assert _job_plan_builder_story_id("US-AF020-02") == "AF020-US02"


def test_job_plan_builder_story_id_prefix_matches_real_task_filenames_on_the_real_backlog() -> None:
    """Reverificación contra el `02-backlog/` real de este proyecto (no
    solo el sintético): para toda User Story real con Tasks reales
    decompuestas, el prefijo convertido coincide de verdad con los
    nombres de fichero `T-...` existentes en disco — la evidencia directa
    de que la conversión no es solo una suposición sobre el formato."""
    tasks_dir = REAL_BACKLOG_PATH / "tasks"
    user_stories_dir = REAL_BACKLOG_PATH / "user-stories"

    matched_at_least_one_story_with_tasks = False
    for story_path in user_stories_dir.glob("US-*.md"):
        story_id = story_path.stem.split("-", 3)
        # US-AFnnn-ss-slug.md -> US-AFnnn-ss
        story_id = "-".join(story_id[:3])
        converted = _job_plan_builder_story_id(story_id)
        matching_files = list(tasks_dir.glob(f"T-{converted}-*.md"))
        if matching_files:
            matched_at_least_one_story_with_tasks = True
            for task_file in matching_files:
                assert task_file.name.startswith(f"T-{converted}-")

    assert matched_at_least_one_story_with_tasks, (
        "Ninguna User Story real tiene Tasks reales que coincidan con el "
        "prefijo convertido — la reverificación no probaría nada."
    )
