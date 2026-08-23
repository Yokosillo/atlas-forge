"""Tests de `POST /backlog/epic` (T-AF036-US02-01),
`POST /backlog/epic/{epic_id}/us` (T-AF036-US02-02) y
`POST /backlog/us/{us_id}/task` (T-AF036-US02-03), los tres bajo
US-AF036-02 · "Crear una Epic, User Story o Task nueva sin salir de la
pantalla Backlog".

Backlog real escrito a un `tmp_path` aislado, formato frontmatter YAML
vigente — mismo patrón que `test_api_routes_backlog_edit.py`."""

from pathlib import Path

from fastapi.testclient import TestClient

import atlas_forge.api.routes as routes_module
from atlas_forge.api import create_app
from atlas_forge.backlog.validator_v2 import validate_backlog_file_v2


def _active_project(tmp_path: Path, monkeypatch) -> Path:
    project_path = tmp_path / "workspace" / "project-a"
    project_path.mkdir(parents=True, exist_ok=True)

    from atlas_forge.models import Project

    project = Project(
        id=str(project_path),
        name="project-a",
        path=str(project_path),
        repository="",
        workspace_id="ws-test",
    )
    monkeypatch.setattr(routes_module, "get_active_project", lambda **_kwargs: project)
    return project_path


def test_post_backlog_epic_with_valid_fields_creates_the_real_file_and_returns_201(
    tmp_path: Path, monkeypatch
) -> None:
    """Criterio de aceptación central de la Task: POST real seguido de
    lectura del fichero creado en disco, confirmando frontmatter y
    secciones correctas — sin condición de carrera, la respuesta HTTP y
    el fichero real deben coincidir de punta a punta."""
    project_path = _active_project(tmp_path, monkeypatch)

    client = TestClient(create_app())
    response = client.post(
        "/backlog/epic",
        json={
            "id": "AF-900",
            "title": "Epic de prueba",
            "objetivo": "Objetivo real de prueba end to end.",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == "AF-900"
    assert body["title"] == "Epic de prueba"

    created_path = Path(body["path"])
    assert created_path.is_file()
    assert created_path == project_path / "02-backlog" / "epics" / "AF-900-epic-de-prueba.md"

    content = created_path.read_text(encoding="utf-8")
    assert "id: AF-900" in content
    assert "type: epic" in content
    assert "title: Epic de prueba" in content
    assert "state: TO_DO" in content
    assert "dependencies: []" in content
    # T-AF036-US18-01: la Epic se versiona — `version` y no `fase`.
    assert "version:" in content
    assert "fase:" not in content
    assert "## Objetivo" in content
    assert "Objetivo real de prueba end to end." in content

    result = validate_backlog_file_v2(created_path)
    assert result.valid, result.errors


def test_post_backlog_epic_without_fase_still_passes_the_validator(
    tmp_path: Path, monkeypatch
) -> None:
    _active_project(tmp_path, monkeypatch)

    client = TestClient(create_app())
    response = client.post(
        "/backlog/epic",
        json={"id": "AF-901", "title": "Epic sin fase", "objetivo": "Objetivo real."},
    )

    assert response.status_code == 201
    created_path = Path(response.json()["path"])
    result = validate_backlog_file_v2(created_path)
    assert result.valid, result.errors


def test_post_backlog_epic_duplicate_id_returns_409_without_overwriting(
    tmp_path: Path, monkeypatch
) -> None:
    project_path = _active_project(tmp_path, monkeypatch)

    client = TestClient(create_app())
    first = client.post(
        "/backlog/epic",
        json={"id": "AF-900", "title": "Primera epic", "objetivo": "Objetivo primero."},
    )
    assert first.status_code == 201
    created_path = Path(first.json()["path"])
    original_content = created_path.read_text(encoding="utf-8")

    second = client.post(
        "/backlog/epic",
        json={"id": "AF-900", "title": "Segunda epic con mismo id", "objetivo": "Otro objetivo."},
    )

    assert second.status_code == 409
    assert "AF-900" in second.json()["detail"]
    assert created_path.read_text(encoding="utf-8") == original_content


def test_post_backlog_epic_invalid_id_format_returns_400_even_without_client_validation(
    tmp_path: Path, monkeypatch
) -> None:
    """Criterio de aceptación explícito: el servidor nunca confía
    únicamente en la validación de cliente — un id que un cliente mal
    implementado (o curl a mano) mandara sin validar debe rechazarse
    igual en servidor."""
    project_path = _active_project(tmp_path, monkeypatch)

    client = TestClient(create_app())
    response = client.post(
        "/backlog/epic",
        json={"id": "AF-9", "title": "Titulo", "objetivo": "Objetivo."},
    )

    assert response.status_code == 400
    assert "AF-9" in response.json()["detail"]
    assert not (project_path / "02-backlog" / "epics").exists()


def test_post_backlog_epic_title_with_colon_does_not_break_the_generated_yaml(
    tmp_path: Path, monkeypatch
) -> None:
    """Regresión del bug real detectado al escribir esta misma Task: un
    `title` con `:` sin comillas rompe el frontmatter YAML generado a
    mano — corregido serializando con `yaml.safe_dump`."""
    _active_project(tmp_path, monkeypatch)

    client = TestClient(create_app())
    response = client.post(
        "/backlog/epic",
        json={
            "id": "AF-900",
            "title": "Gestión de Backlog: Crear/Editar",
            "objetivo": "Objetivo con acentos: ción, áéíóú.",
        },
    )

    assert response.status_code == 201
    created_path = Path(response.json()["path"])
    result = validate_backlog_file_v2(created_path)
    assert result.valid, result.errors


# ---------------------------------------------------------------------
# POST /backlog/epic/{epic_id}/us (T-AF036-US02-02)
# ---------------------------------------------------------------------


def test_post_backlog_epic_us_with_valid_fields_and_existing_epic_creates_the_real_file(
    tmp_path: Path, monkeypatch
) -> None:
    """Criterio de aceptación central de la Task: crear una Epic real
    (fixture vía el propio endpoint ya cerrado, T-AF036-US02-01), crear
    una US sobre ella vía este endpoint, confirmar el fichero en disco
    con `epic_id` correcto."""
    project_path = _active_project(tmp_path, monkeypatch)

    client = TestClient(create_app())
    epic_response = client.post(
        "/backlog/epic",
        json={"id": "AF-900", "title": "Epic real de prueba", "objetivo": "Objetivo real."},
    )
    assert epic_response.status_code == 201

    response = client.post(
        "/backlog/epic/AF-900/us",
        json={
            "id": "US-AF900-01",
            "title": "US de prueba",
            "objetivo": "Como usuario quiero X para lograr Y.",
            "criterios_aceptacion": "- Criterio uno.\n- Criterio dos.",
            "priority": "Alta",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == "US-AF900-01"
    assert body["title"] == "US de prueba"
    assert body["epic_id"] == "AF-900"

    created_path = Path(body["path"])
    assert created_path.is_file()
    assert created_path == project_path / "02-backlog" / "user-stories" / "US-AF900-01-us-de-prueba.md"

    content = created_path.read_text(encoding="utf-8")
    assert "id: US-AF900-01" in content
    assert "type: user_story" in content
    assert "epic: AF-900" in content
    assert "priority: Alta" in content
    assert "## Historia" in content
    assert "## Criterios de aceptación" in content

    result = validate_backlog_file_v2(created_path)
    assert result.valid, result.errors


def test_post_backlog_epic_us_fase_fuera_del_conjunto_rechaza_400_sin_escribir(
    tmp_path: Path, monkeypatch
) -> None:
    """T-AF036-US14-05: crear una US con `fase` fuera del conjunto cerrado
    responde 400 con rechazo explícito y no escribe nada en disco."""
    project_path = _active_project(tmp_path, monkeypatch)

    client = TestClient(create_app())
    epic_response = client.post(
        "/backlog/epic",
        json={"id": "AF-900", "title": "Epic real", "objetivo": "Objetivo real."},
    )
    assert epic_response.status_code == 201

    response = client.post(
        "/backlog/epic/AF-900/us",
        json={
            "id": "US-AF900-01",
            "title": "US inválida",
            "objetivo": "Como usuario quiero X.",
            "criterios_aceptacion": "- Criterio.",
            "fase": "Fase 0.1",
        },
    )

    assert response.status_code == 400
    assert "no es una fase válida" in response.json()["detail"]
    assert not (project_path / "02-backlog" / "user-stories").exists()


def test_post_backlog_epic_us_nonexistent_epic_returns_404_without_writing_anything(
    tmp_path: Path, monkeypatch
) -> None:
    project_path = _active_project(tmp_path, monkeypatch)

    client = TestClient(create_app())
    response = client.post(
        "/backlog/epic/AF-999/us",
        json={
            "id": "US-AF999-01",
            "title": "US huerfana",
            "objetivo": "Historia.",
            "criterios_aceptacion": "Criterios.",
        },
    )

    assert response.status_code == 404
    assert "AF-999" in response.json()["detail"]
    assert not (project_path / "02-backlog" / "user-stories").exists()


def test_post_backlog_epic_us_duplicate_id_returns_409_without_overwriting(
    tmp_path: Path, monkeypatch
) -> None:
    _active_project(tmp_path, monkeypatch)

    client = TestClient(create_app())
    client.post("/backlog/epic", json={"id": "AF-900", "title": "Epic", "objetivo": "Objetivo."})
    first = client.post(
        "/backlog/epic/AF-900/us",
        json={"id": "US-AF900-01", "title": "Primera US", "objetivo": "H.", "criterios_aceptacion": "C."},
    )
    assert first.status_code == 201
    created_path = Path(first.json()["path"])
    original_content = created_path.read_text(encoding="utf-8")

    second = client.post(
        "/backlog/epic/AF-900/us",
        json={"id": "US-AF900-01", "title": "Segunda US mismo id", "objetivo": "H2.", "criterios_aceptacion": "C2."},
    )

    assert second.status_code == 409
    assert "US-AF900-01" in second.json()["detail"]
    assert created_path.read_text(encoding="utf-8") == original_content


def test_post_backlog_epic_us_epic_id_from_url_never_overridden_by_body(
    tmp_path: Path, monkeypatch
) -> None:
    """Criterio de aceptación explícito: el `epic_id` del fichero creado
    coincide siempre con el de la URL, nunca con un valor distinto que
    el cliente pudiera enviar en el body — el propio `CreateUserStoryRequest`
    no tiene campo `epic_id`, así que un cliente que lo mande de todos
    modos (payload con un campo extra no declarado) debe ser ignorado,
    no aceptado como override."""
    _active_project(tmp_path, monkeypatch)

    client = TestClient(create_app())
    client.post("/backlog/epic", json={"id": "AF-900", "title": "Epic real", "objetivo": "Objetivo."})
    client.post("/backlog/epic", json={"id": "AF-901", "title": "Otra epic", "objetivo": "Otro objetivo."})

    response = client.post(
        "/backlog/epic/AF-900/us",
        json={
            "id": "US-AF900-01",
            "title": "US",
            "objetivo": "H.",
            "criterios_aceptacion": "C.",
            "epic_id": "AF-901",  # campo extra no declarado — debe ignorarse
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["epic_id"] == "AF-900"
    content = Path(body["path"]).read_text(encoding="utf-8")
    assert "epic: AF-900" in content
    assert "epic: AF-901" not in content


def test_post_backlog_epic_us_invalid_priority_returns_400(
    tmp_path: Path, monkeypatch
) -> None:
    _active_project(tmp_path, monkeypatch)

    client = TestClient(create_app())
    client.post("/backlog/epic", json={"id": "AF-900", "title": "Epic", "objetivo": "Objetivo."})

    response = client.post(
        "/backlog/epic/AF-900/us",
        json={
            "id": "US-AF900-01", "title": "US", "objetivo": "H.", "criterios_aceptacion": "C.",
            "priority": "Urgentísima",
        },
    )

    assert response.status_code == 400
    assert "Urgentísima" in response.json()["detail"]


# ---------------------------------------------------------------------
# POST /backlog/us/{us_id}/task (T-AF036-US02-03)
# ---------------------------------------------------------------------


def test_post_backlog_us_task_with_valid_fields_and_existing_us_creates_the_real_file(
    tmp_path: Path, monkeypatch
) -> None:
    """Criterio de aceptación central de la Task: crear una US real
    (vía los dos endpoints ya cerrados, T-AF036-US02-01/-02), crear una
    Task sobre ella vía este endpoint, confirmar el fichero en disco con
    `user_story`/`epic` correctos."""
    project_path = _active_project(tmp_path, monkeypatch)

    client = TestClient(create_app())
    client.post("/backlog/epic", json={"id": "AF-900", "title": "Epic real", "objetivo": "Objetivo."})
    us_response = client.post(
        "/backlog/epic/AF-900/us",
        json={"id": "US-AF900-01", "title": "US real", "objetivo": "H.", "criterios_aceptacion": "C."},
    )
    assert us_response.status_code == 201

    response = client.post(
        "/backlog/us/US-AF900-01/task",
        json={
            "id": "T-AF900-US01-01",
            "title": "Task de prueba",
            "objetivo": "Objetivo real.",
            "descripcion": "Descripción real.",
            "criterios_aceptacion": "- Criterio uno.",
            "priority": "Alta",
            "dependencies": ["T-AF900-US01-02"],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == "T-AF900-US01-01"
    assert body["title"] == "Task de prueba"
    assert body["us_id"] == "US-AF900-01"
    assert body["epic_id"] == "AF-900"

    created_path = Path(body["path"])
    assert created_path.is_file()
    assert created_path == project_path / "02-backlog" / "tasks" / "T-AF900-US01-01-task-de-prueba.md"

    content = created_path.read_text(encoding="utf-8")
    assert "id: T-AF900-US01-01" in content
    assert "type: task" in content
    assert "user_story: US-AF900-01" in content
    assert "epic: AF-900" in content
    assert "priority: Alta" in content
    assert "- T-AF900-US01-02" in content
    assert "## Objetivo" in content
    assert "## Descripción" in content
    assert "## Criterios de aceptación" in content
    assert "## Bugs encontrados" in content

    result = validate_backlog_file_v2(created_path)
    assert result.valid, result.errors


def test_post_backlog_us_task_nonexistent_us_returns_404_without_writing_anything(
    tmp_path: Path, monkeypatch
) -> None:
    project_path = _active_project(tmp_path, monkeypatch)

    client = TestClient(create_app())
    response = client.post(
        "/backlog/us/US-AF999-01/task",
        json={
            "id": "T-AF999-US01-01", "title": "Task huerfana", "objetivo": "O.",
            "descripcion": "D.", "criterios_aceptacion": "C.",
        },
    )

    assert response.status_code == 404
    assert "US-AF999-01" in response.json()["detail"]
    assert not (project_path / "02-backlog" / "tasks").exists()


def test_post_backlog_us_task_under_orphan_user_story_returns_null_epic_id(
    tmp_path: Path, monkeypatch
) -> None:
    """Criterio de aceptación explícito: una Task creada bajo una US
    huérfana (sin `epic` en su frontmatter) se crea igualmente, con
    `epic_id: null` en la respuesta."""
    project_path = _active_project(tmp_path, monkeypatch)
    stories_dir = project_path / "02-backlog" / "user-stories"
    stories_dir.mkdir(parents=True)
    (stories_dir / "US-AF901-01-huerfana.md").write_text(
        "---\nid: US-AF901-01\ntype: user_story\ntitle: US huerfana\nstate: READY\n"
        "dependencies: []\npriority: Alta\n---\n\n## Historia\n\nHistoria.\n",
        encoding="utf-8",
    )

    client = TestClient(create_app())
    response = client.post(
        "/backlog/us/US-AF901-01/task",
        json={
            "id": "T-AF901-US01-01", "title": "Task huerfana", "objetivo": "O.",
            "descripcion": "D.", "criterios_aceptacion": "C.",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["epic_id"] is None
    content = Path(body["path"]).read_text(encoding="utf-8")
    assert "epic: null" in content
    result = validate_backlog_file_v2(Path(body["path"]))
    assert result.valid, result.errors


def test_post_backlog_us_task_duplicate_id_returns_409_without_overwriting(
    tmp_path: Path, monkeypatch
) -> None:
    _active_project(tmp_path, monkeypatch)

    client = TestClient(create_app())
    client.post("/backlog/epic", json={"id": "AF-900", "title": "Epic", "objetivo": "Objetivo."})
    client.post(
        "/backlog/epic/AF-900/us",
        json={"id": "US-AF900-01", "title": "US", "objetivo": "H.", "criterios_aceptacion": "C."},
    )
    first = client.post(
        "/backlog/us/US-AF900-01/task",
        json={"id": "T-AF900-US01-01", "title": "Primera Task", "objetivo": "O.", "descripcion": "D.", "criterios_aceptacion": "C."},
    )
    assert first.status_code == 201
    created_path = Path(first.json()["path"])
    original_content = created_path.read_text(encoding="utf-8")

    second = client.post(
        "/backlog/us/US-AF900-01/task",
        json={"id": "T-AF900-US01-01", "title": "Segunda Task mismo id", "objetivo": "O2.", "descripcion": "D2.", "criterios_aceptacion": "C2."},
    )

    assert second.status_code == 409
    assert "T-AF900-US01-01" in second.json()["detail"]
    assert created_path.read_text(encoding="utf-8") == original_content


def test_post_backlog_us_task_us_id_from_url_never_overridden_by_body(
    tmp_path: Path, monkeypatch
) -> None:
    """Análogo al test de `epic_id` inmutable de `POST /backlog/epic/{epic_id}/us`:
    el `us_id` del fichero creado coincide siempre con el de la URL,
    nunca con un valor distinto que el cliente pudiera enviar en el
    body — el propio `CreateTaskRequest` no tiene campo `us_id`."""
    _active_project(tmp_path, monkeypatch)

    client = TestClient(create_app())
    client.post("/backlog/epic", json={"id": "AF-900", "title": "Epic", "objetivo": "Objetivo."})
    client.post(
        "/backlog/epic/AF-900/us",
        json={"id": "US-AF900-01", "title": "US uno", "objetivo": "H.", "criterios_aceptacion": "C."},
    )
    client.post(
        "/backlog/epic/AF-900/us",
        json={"id": "US-AF900-02", "title": "US dos", "objetivo": "H.", "criterios_aceptacion": "C."},
    )

    response = client.post(
        "/backlog/us/US-AF900-01/task",
        json={
            "id": "T-AF900-US01-01",
            "title": "Task",
            "objetivo": "O.",
            "descripcion": "D.",
            "criterios_aceptacion": "C.",
            "us_id": "US-AF900-02",  # campo extra no declarado — debe ignorarse
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["us_id"] == "US-AF900-01"
    content = Path(body["path"]).read_text(encoding="utf-8")
    assert "user_story: US-AF900-01" in content
    assert "user_story: US-AF900-02" not in content


def test_post_backlog_us_task_invalid_id_format_returns_400(
    tmp_path: Path, monkeypatch
) -> None:
    _active_project(tmp_path, monkeypatch)

    client = TestClient(create_app())
    client.post("/backlog/epic", json={"id": "AF-900", "title": "Epic", "objetivo": "Objetivo."})
    client.post(
        "/backlog/epic/AF-900/us",
        json={"id": "US-AF900-01", "title": "US", "objetivo": "H.", "criterios_aceptacion": "C."},
    )

    response = client.post(
        "/backlog/us/US-AF900-01/task",
        json={"id": "T-AF900-01-01", "title": "T", "objetivo": "O.", "descripcion": "D.", "criterios_aceptacion": "C."},
    )

    assert response.status_code == 400
    assert "T-AF900-01-01" in response.json()["detail"]
