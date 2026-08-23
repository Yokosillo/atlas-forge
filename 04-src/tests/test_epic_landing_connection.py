"""Tests de la conexión de US-AF036-03 (T-AF036-US03-02): el endpoint
`POST /backlog/epic/{epic_id}/propose-stories` debe invocar el módulo de
dominio `plan_epic_landing` (T-AF036-US03-01) en vez de recomponer el
pipeline — la conexión no duplica lógica de negocio y el comportamiento
HTTP se preserva (criterios de aceptación 1 y 2).

Se ejercita la capa HTTP real (TestClient) contra un proyecto activo
aislado, y se comprueba que:
- Una Epic con alcance v1 produce sus User Stories y las escribe a disco
  (camino aprobado, via `can_approve_landing` + `write_approved_stories`).
- Una Epic sin alcance devuelve la propuesta rechazada sin escribir nada.
- Una Epic inexistente responde 404."""

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


def _write_epic(backlog: Path, epic_id: str, *, alcance: str) -> None:
    epics_dir = backlog / "epics"
    epics_dir.mkdir(parents=True, exist_ok=True)
    content = f"# {epic_id} Epic de prueba\n\n## Objetivo\n\nObjetivo real.\n\n"
    if alcance:
        content += f"## Alcance v1 (mínimo)\n\n{alcance}\n"
    (epics_dir / f"{epic_id}-epic-de-prueba.md").write_text(content, encoding="utf-8")


def test_propose_stories_lands_stories_via_domain_module(tmp_path, monkeypatch) -> None:
    """Camino feliz: la conexión invoca `plan_epic_landing` y escribe las
    User Stories aprobadas a disco (criterios 1 y 2)."""
    project_path = _active_project(tmp_path, monkeypatch)
    backlog = project_path / "02-backlog"
    (backlog / "user-stories").mkdir(parents=True)
    _write_epic(
        backlog,
        "AF-999",
        alcance="- Crear la cola de mensajes interna.\n- Desencolar mensajes.\n",
    )
    client = TestClient(create_app())

    response = client.post("/backlog/epic/AF-999/propose-stories")

    assert response.status_code == 200
    body = response.json()
    assert body["num_stories"] == 2
    assert body["validation_valid"] is True
    assert body["self_audit"] is not None
    assert body["self_audit"]["status"] == "APROBADO"

    # Las dos User Stories propuestas se escribieron a disco.
    written = sorted(p.name for p in (backlog / "user-stories").glob("US-AF999-*.md"))
    assert len(written) == 2, f"Esperaba 2 User Stories escritas, encontradas: {written}"
    assert any("US-AF999-01" in name for name in written)
    assert any("US-AF999-02" in name for name in written)


def test_propose_stories_without_alcance_rejects_and_writes_nothing(tmp_path, monkeypatch) -> None:
    """Epic sin alcance v1: la propuesta queda rechazada (RECHAZADO) y no
    se escribe ningún fichero — mismo criterio que el pipeline previo,
    ahora resuelto por `can_approve_landing`."""
    project_path = _active_project(tmp_path, monkeypatch)
    backlog = project_path / "02-backlog"
    _write_epic(backlog, "AF-999", alcance="")
    client = TestClient(create_app())

    response = client.post("/backlog/epic/AF-999/propose-stories")

    assert response.status_code == 200
    body = response.json()
    assert body["num_stories"] == 0
    assert body["self_audit"]["status"] == "RECHAZADO"
    assert list((backlog / "user-stories").glob("US-AF999-*.md")) == []


def test_propose_stories_returns_404_for_unknown_epic(tmp_path, monkeypatch) -> None:
    _active_project(tmp_path, monkeypatch)
    client = TestClient(create_app())

    response = client.post("/backlog/epic/AF-999/propose-stories")

    assert response.status_code == 404
