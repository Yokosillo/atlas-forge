"""Tests HTTP de `GET /backlog/epic/{epic_id}/coverage` (T-AF036-US05-01).

La Task pide el endpoint (no solo la función `compute_epic_coverage`), por
eso este fichero verifica a nivel HTTP que la ruta produce los tres casos
de los criterios de aceptación:

- Criterio 3: Epic sin fichero propio -> 404 con el mensaje verbatim
  `No existe ningún fichero de Epic con id '<id>' en el backlog activo.`
  (hueco real: `test_backlog_coverage.py` solo prueba que
  `compute_epic_coverage` devuelve `None`, nunca que la ruta lo traduzca
  a 404 verbatim).
- Criterio 2: Epic sin sección "Alcance v1" -> 200 con
  `declared_alcance: null` y el mensaje explícito "no se puede calcular
  cobertura".
- Criterio 1: Epic con sección y un punto sin id -> 200 con `points`,
  `gaps` y `approximate: true`."""

from pathlib import Path

from fastapi.testclient import TestClient

import atlas_forge.api.routes as routes_module
from atlas_forge.api import create_app


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


_EPIC = (
    "---\n"
    "id: AF-999\n"
    "type: epic\n"
    "title: Epic de prueba\n"
    "state: IN_PROGRESS\n"
    "dependencies: []\n"
    "---\n\n"
    "# AF-999 · Epic de prueba\n\n"
)


def test_coverage_returns_404_verbatim_when_epic_has_no_own_file(
    tmp_path: Path, monkeypatch
) -> None:
    """Criterio 3: Epic sin fichero propio -> 404 con mensaje verbatim."""
    _active_project(tmp_path, monkeypatch)
    client = TestClient(create_app())

    response = client.get("/backlog/epic/AF-NOPE/coverage")

    assert response.status_code == 404
    assert (
        response.json()["detail"]
        == "No existe ningún fichero de Epic con id 'AF-NOPE' en el backlog activo."
    )


def test_coverage_returns_explicit_message_when_epic_has_no_alcance_section(
    tmp_path: Path, monkeypatch
) -> None:
    """Criterio 2: Epic sin sección -> 200 con mensaje explícito, nunca un
    resultado vacío ambiguo."""
    project_path = _active_project(tmp_path, monkeypatch)
    epics_dir = project_path / "02-backlog" / "epics"
    epics_dir.mkdir(parents=True, exist_ok=True)
    (epics_dir / "AF-999-epic.md").write_text(_EPIC, encoding="utf-8")
    client = TestClient(create_app())

    response = client.get("/backlog/epic/AF-999/coverage")

    assert response.status_code == 200
    body = response.json()
    assert body["declared_alcance"] is None
    assert "no se puede calcular cobertura" in body["message"]
    assert body["gaps"] == []


def test_coverage_returns_200_with_points_gaps_and_approximate_flag(
    tmp_path: Path, monkeypatch
) -> None:
    """Criterio 1: Epic con sección -> 200 con `points`, `gaps` y
    `approximate: true` (aviso de aproximación)."""
    project_path = _active_project(tmp_path, monkeypatch)
    backlog = project_path / "02-backlog"
    epics_dir = backlog / "epics"
    epics_dir.mkdir(parents=True, exist_ok=True)
    (epics_dir / "AF-999-epic.md").write_text(
        _EPIC
        + "## Alcance v1 (mínimo)\n\n"
        + "- **US-AF999-01**: gestionar los workspaces desde la interfaz.\n"
        + "- **US-AF999-99**: capacidad que nadie ha aterrizado todavia.\n",
        encoding="utf-8",
    )
    us_dir = backlog / "user-stories"
    us_dir.mkdir(parents=True, exist_ok=True)
    (us_dir / "US-AF999-01-gestionar.md").write_text(
        "---\n"
        "id: US-AF999-01\n"
        "type: user_story\n"
        "title: Gestionar workspaces\n"
        "state: TODO\n"
        "dependencies: []\n"
        "epic: AF-999\n"
        "priority: Media\n"
        "---\n\n"
        "# US-AF999-01 · Gestionar workspaces\n\n"
        "## Historia\n\nGestionar workspaces.\n",
        encoding="utf-8",
    )
    client = TestClient(create_app())

    response = client.get("/backlog/epic/AF-999/coverage")

    assert response.status_code == 200
    body = response.json()
    assert body["approximate"] is True
    assert body["declared_alcance"] is not None
    assert len(body["points"]) == 2
    assert len(body["gaps"]) == 1
    assert body["gaps"][0].startswith("US-AF999-99")
    assert "aproximada" in body["message"]
