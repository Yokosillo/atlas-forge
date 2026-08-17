"""Tests de `POST /backlog/epic` (T-FB036-US02-01, US-FB036-02 · "Crear
una Epic, User Story o Task nueva sin salir de la pantalla Backlog").

Backlog real escrito a un `tmp_path` aislado, formato frontmatter YAML
vigente — mismo patrón que `test_api_routes_backlog_edit.py`."""

from pathlib import Path

from fastapi.testclient import TestClient

import brain.api.routes as routes_module
from brain.api import create_app
from brain.backlog.validator_v2 import validate_backlog_file_v2


def _active_project(tmp_path: Path, monkeypatch) -> Path:
    project_path = tmp_path / "workspace" / "project-a"
    project_path.mkdir(parents=True, exist_ok=True)

    from brain.models import Project

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
            "id": "FB-900",
            "title": "Epic de prueba",
            "objetivo": "Objetivo real de prueba end to end.",
            "fase": "Fase 1.0",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == "FB-900"
    assert body["title"] == "Epic de prueba"

    created_path = Path(body["path"])
    assert created_path.is_file()
    assert created_path == project_path / "02-backlog" / "epics" / "FB-900-epic-de-prueba.md"

    content = created_path.read_text(encoding="utf-8")
    assert "id: FB-900" in content
    assert "type: epic" in content
    assert "title: Epic de prueba" in content
    assert "state: TODO" in content
    assert "dependencies: []" in content
    assert "fase: Fase 1.0" in content
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
        json={"id": "FB-901", "title": "Epic sin fase", "objetivo": "Objetivo real."},
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
        json={"id": "FB-900", "title": "Primera epic", "objetivo": "Objetivo primero."},
    )
    assert first.status_code == 201
    created_path = Path(first.json()["path"])
    original_content = created_path.read_text(encoding="utf-8")

    second = client.post(
        "/backlog/epic",
        json={"id": "FB-900", "title": "Segunda epic con mismo id", "objetivo": "Otro objetivo."},
    )

    assert second.status_code == 409
    assert "FB-900" in second.json()["detail"]
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
        json={"id": "FB-9", "title": "Titulo", "objetivo": "Objetivo."},
    )

    assert response.status_code == 400
    assert "FB-9" in response.json()["detail"]
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
            "id": "FB-900",
            "title": "Gestión de Backlog: Crear/Editar",
            "objetivo": "Objetivo con acentos: ción, áéíóú.",
        },
    )

    assert response.status_code == 201
    created_path = Path(response.json()["path"])
    result = validate_backlog_file_v2(created_path)
    assert result.valid, result.errors
