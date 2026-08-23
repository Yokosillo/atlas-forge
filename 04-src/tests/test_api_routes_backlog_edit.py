"""Tests de `PUT /backlog/{item_id}/priority` y `PUT /backlog/{item_id}/state`
(T-AF036-US08-01, US-AF036-08 · "Editar prioridad y estado de una User
Story o Task desde su línea de título, sin desplegar").

Backlog real escrito a un `tmp_path` aislado, formato frontmatter YAML
vigente — mismo patrón que `test_api_routes_dispatch_queue.py`."""

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


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _epic(backlog: Path, epic_id: str, state: str = "READY") -> None:
    _write(
        backlog / "epics" / f"{epic_id}.md",
        f"---\nid: {epic_id}\ntype: epic\ntitle: {epic_id}\nstate: {state}\n"
        "dependencies: []\n---\n\n## Objetivo\n\nTest.\n",
    )


def _story(backlog: Path, us_id: str, epic_id: str, state: str = "READY", priority: str = "Alta") -> None:
    _write(
        backlog / "user-stories" / f"{us_id}.md",
        f"---\nid: {us_id}\ntype: user_story\ntitle: {us_id}\nstate: {state}\n"
        f"dependencies: []\nepic: {epic_id}\npriority: {priority}\n---\n\n## Historia\n\nTest.\n",
    )


def _task(backlog: Path, task_id: str, epic_id: str, us_id: str, state: str = "READY", priority: str = "Alta") -> None:
    _write(
        backlog / "tasks" / f"{task_id}.md",
        f"---\nid: {task_id}\ntype: task\ntitle: {task_id}\nstate: {state}\n"
        f"dependencies: []\nepic: {epic_id}\nuser_story: {us_id}\npriority: {priority}\n---\n\n"
        "## Objetivo\n\nTest.\n",
    )


def _field(path: Path, field: str) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{field}:"):
            return line.split(":", 1)[1].strip()
    raise AssertionError(f"no {field} field in {path}")


def test_put_priority_cambia_el_fichero_real(tmp_path: Path, monkeypatch) -> None:
    project_path = _active_project(tmp_path, monkeypatch)
    backlog = project_path / "02-backlog"
    _epic(backlog, "AF-100")
    _task(backlog, "T-AF100-US01-01", "AF-100", "US-AF100-01", priority="Alta")
    _story(backlog, "US-AF100-01", "AF-100")

    client = TestClient(create_app())
    response = client.put("/backlog/T-AF100-US01-01/priority", json={"priority": "Baja"})

    assert response.status_code == 200
    assert response.json()["priority"] == "Baja"
    assert _field(backlog / "tasks" / "T-AF100-US01-01.md", "priority") == "Baja"


def test_put_priority_valor_invalido_devuelve_400_sin_tocar_el_fichero(tmp_path: Path, monkeypatch) -> None:
    project_path = _active_project(tmp_path, monkeypatch)
    backlog = project_path / "02-backlog"
    _epic(backlog, "AF-100")
    _story(backlog, "US-AF100-01", "AF-100")
    _task(backlog, "T-AF100-US01-01", "AF-100", "US-AF100-01", priority="Alta")
    path = backlog / "tasks" / "T-AF100-US01-01.md"
    original = path.read_text(encoding="utf-8")

    client = TestClient(create_app())
    response = client.put("/backlog/T-AF100-US01-01/priority", json={"priority": "Urgentísima"})

    assert response.status_code == 400
    assert "Urgentísima" in response.json()["detail"]
    assert path.read_text(encoding="utf-8") == original


def test_put_priority_sobre_epic_devuelve_400(tmp_path: Path, monkeypatch) -> None:
    project_path = _active_project(tmp_path, monkeypatch)
    backlog = project_path / "02-backlog"
    _epic(backlog, "AF-100")

    client = TestClient(create_app())
    response = client.put("/backlog/AF-100/priority", json={"priority": "Baja"})

    assert response.status_code == 400
    assert "Epic" in response.json()["detail"]


def test_put_priority_item_inexistente_devuelve_404(tmp_path: Path, monkeypatch) -> None:
    project_path = _active_project(tmp_path, monkeypatch)
    (project_path / "02-backlog").mkdir()

    client = TestClient(create_app())
    response = client.put("/backlog/T-AF999-US01-01/priority", json={"priority": "Baja"})

    assert response.status_code == 404


def test_put_state_cambia_el_fichero_real(tmp_path: Path, monkeypatch) -> None:
    project_path = _active_project(tmp_path, monkeypatch)
    backlog = project_path / "02-backlog"
    _epic(backlog, "AF-100")
    _story(backlog, "US-AF100-01", "AF-100")
    _task(backlog, "T-AF100-US01-01", "AF-100", "US-AF100-01", state="READY")

    client = TestClient(create_app())
    response = client.put("/backlog/T-AF100-US01-01/state", json={"state": "TO_DEVELOP"})

    assert response.status_code == 200
    assert response.json()["state"] == "TO_DEVELOP"
    assert _field(backlog / "tasks" / "T-AF100-US01-01.md", "state") == "TO_DEVELOP"


def test_put_state_valor_invalido_devuelve_400(tmp_path: Path, monkeypatch) -> None:
    project_path = _active_project(tmp_path, monkeypatch)
    backlog = project_path / "02-backlog"
    _epic(backlog, "AF-100")
    _story(backlog, "US-AF100-01", "AF-100")
    _task(backlog, "T-AF100-US01-01", "AF-100", "US-AF100-01", state="READY")

    client = TestClient(create_app())
    response = client.put("/backlog/T-AF100-US01-01/state", json={"state": "CANCELADA"})

    assert response.status_code == 400


def test_put_state_transicion_ilegal_devuelve_400_y_no_escribe(
    tmp_path: Path, monkeypatch
) -> None:
    """T-AF036-US22-01: una transición ilegal (Task `READY -> DONE`) responde
    400 con `detail` verbatim y no toca disco."""
    project_path = _active_project(tmp_path, monkeypatch)
    backlog = project_path / "02-backlog"
    _epic(backlog, "AF-100")
    _story(backlog, "US-AF100-01", "AF-100")
    _task(backlog, "T-AF100-US01-01", "AF-100", "US-AF100-01", state="READY")

    client = TestClient(create_app())
    response = client.put("/backlog/T-AF100-US01-01/state", json={"state": "DONE"})

    assert response.status_code == 400
    assert "ilegal" in response.json()["detail"]
    assert _field(backlog / "tasks" / "T-AF100-US01-01.md", "state") == "READY"


def test_put_state_done_en_user_story_dispara_promocion_de_epic(tmp_path: Path, monkeypatch) -> None:
    project_path = _active_project(tmp_path, monkeypatch)
    backlog = project_path / "02-backlog"
    _epic(backlog, "AF-100")
    # `IN_REVIEW -> DONE` es la única vía legal de una US a DONE (la máquina
    # canónica no permite `IN_PROGRESS -> DONE`).
    _story(backlog, "US-AF100-01", "AF-100", state="IN_REVIEW")
    _task(backlog, "T-AF100-US01-01", "AF-100", "US-AF100-01", state="DONE")

    client = TestClient(create_app())
    response = client.put("/backlog/US-AF100-01/state", json={"state": "DONE"})

    assert response.status_code == 200
    body = response.json()
    assert body["promoted_epics"] == ["AF-100"]
    assert _field(backlog / "user-stories" / "US-AF100-01.md", "state") == "DONE"
    assert _field(backlog / "epics" / "AF-100.md", "state") == "DONE"


def test_put_state_done_en_user_story_sin_epic_completa_no_promociona(tmp_path: Path, monkeypatch) -> None:
    project_path = _active_project(tmp_path, monkeypatch)
    backlog = project_path / "02-backlog"
    _epic(backlog, "AF-100")
    _story(backlog, "US-AF100-01", "AF-100", state="IN_REVIEW")
    _task(backlog, "T-AF100-US01-01", "AF-100", "US-AF100-01", state="READY")
    _story(backlog, "US-AF100-02", "AF-100", state="READY")

    client = TestClient(create_app())
    response = client.put("/backlog/US-AF100-01/state", json={"state": "DONE"})

    assert response.status_code == 200
    assert response.json()["promoted_epics"] == []
    assert _field(backlog / "epics" / "AF-100.md", "state") == "READY"


def test_put_state_sobre_epic_devuelve_400(tmp_path: Path, monkeypatch) -> None:
    project_path = _active_project(tmp_path, monkeypatch)
    backlog = project_path / "02-backlog"
    _epic(backlog, "AF-100")

    client = TestClient(create_app())
    response = client.put("/backlog/AF-100/state", json={"state": "DONE"})

    assert response.status_code == 400


def test_put_fase_actualiza_campo_de_user_story(tmp_path: Path, monkeypatch) -> None:
    """Criterio: `PUT /backlog/{item_id}/fase` actualiza el frontmatter `fase`
    de una User Story y devuelve el nuevo valor."""
    project_path = _active_project(tmp_path, monkeypatch)
    backlog = project_path / "02-backlog"
    _epic(backlog, "AF-100")
    _story(backlog, "US-AF100-01", "AF-100")

    client = TestClient(create_app())
    response = client.put("/backlog/US-AF100-01/fase", json={"fase": "Fase 0.9.1"})

    assert response.status_code == 200
    assert response.json()["fase"] == "Fase 0.9.1"
    assert _field(backlog / "user-stories" / "US-AF100-01.md", "fase") == "Fase 0.9.1"


def test_put_fase_actualiza_campo_de_epic(tmp_path: Path, monkeypatch) -> None:
    """Criterio: funciona para Epic (`AF-xxx`)."""
    project_path = _active_project(tmp_path, monkeypatch)
    backlog = project_path / "02-backlog"
    _epic(backlog, "AF-100", state="TO_DO")

    client = TestClient(create_app())
    response = client.put("/backlog/AF-100/fase", json={"fase": "Fase 0.9.2"})

    assert response.status_code == 200
    assert response.json()["fase"] == "Fase 0.9.2"
    assert _field(backlog / "epics" / "AF-100.md", "fase") == "Fase 0.9.2"


def test_put_fase_none_escribe_null(tmp_path: Path, monkeypatch) -> None:
    """Con `fase: null` se limpia el campo (sin fase) sin romper el render."""
    project_path = _active_project(tmp_path, monkeypatch)
    backlog = project_path / "02-backlog"
    _story(backlog, "US-AF100-01", "AF-100")

    client = TestClient(create_app())
    response = client.put("/backlog/US-AF100-01/fase", json={"fase": None})

    assert response.status_code == 200
    assert _field(backlog / "user-stories" / "US-AF100-01.md", "fase") == "null"


def test_put_fase_fuera_del_conjunto_rechaza_400_y_no_escribe(
    tmp_path: Path, monkeypatch
) -> None:
    """T-AF036-US14-05: `PUT /backlog/{item_id}/fase` con una fase fuera del
    conjunto cerrado (p. ej. `Fase 0.1`) responde 400 listando las fases
    válidas y NO escribe nada en el fichero."""
    project_path = _active_project(tmp_path, monkeypatch)
    backlog = project_path / "02-backlog"
    _epic(backlog, "AF-100")
    _story(backlog, "US-AF100-01", "AF-100")

    client = TestClient(create_app())
    response = client.put("/backlog/US-AF100-01/fase", json={"fase": "Fase 0.1"})

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "no es una fase válida" in detail
    assert "Fase 0.9" in detail
    # El fichero no se tocó: la US no declara fase (no se insertó ninguna).
    content = (backlog / "user-stories" / "US-AF100-01.md").read_text(encoding="utf-8")
    assert "fase:" not in content


def test_put_fase_item_inexistente_devuelve_404(tmp_path: Path, monkeypatch) -> None:
    project_path = _active_project(tmp_path, monkeypatch)
    backlog = project_path / "02-backlog"
    _epic(backlog, "AF-100")

    client = TestClient(create_app())
    response = client.put("/backlog/AF-999/fase", json={"fase": "Fase 0.9.1"})

    assert response.status_code == 404
