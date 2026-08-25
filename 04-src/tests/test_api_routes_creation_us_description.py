"""Tests de `POST /backlog/epic/{epic_id}/from-description-us`
(T-AF036-US20-02, US-AF036-20): punto de entrada que recibe una descripción
en lenguaje natural y **encola** una petición de creación de User Story en la
cola persistente (`creation_queue`, T-AF036-US20-06) — sin interpretar nada de
forma síncrona ni escribir ficheros de backlog en la petición web.

Criterios de aceptación cubiertos:
- descripción real + `epic_id` existente → 202 con `{request_id, tipo, status}`,
  y una entrada `pending` en la cola con `epic_id` de contexto;
- `epic_id` inexistente → 404;
- descripción vacía → 400;
- no se escribe ningún fichero de backlog ni se invoca el pipeline de
  interpretación en la petición (se comprueba que no aparecen EPICs/US nuevas
  y que la entrada queda `pending`, no `in_flight`/`done`).

Backlog real escrito a `tmp_path` aislado; mismo patrón que
`test_api_routes_backlog_create.py`."""

from pathlib import Path

from fastapi.testclient import TestClient

import atlas_forge.api.routes as routes_module
from atlas_forge.api import create_app
from atlas_forge.dispatcher.creation_queue import (
    STATUS_IN_FLIGHT,
    STATUS_PENDING,
    get_creation_requests,
)


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


def _write_epic(project_path: Path, epic_id: str) -> None:
    epic_dir = project_path / "02-backlog" / "epics"
    epic_dir.mkdir(parents=True, exist_ok=True)
    (epic_dir / f"{epic_id}.md").write_text(
        "---\n"
        f"id: {epic_id}\ntype: epic\ntitle: {epic_id}\nstate: READY\n"
        "dependencies: []\n"
        "---\n\n## Objetivo\n\nO.\n",
        encoding="utf-8",
    )


def _requests(project_path: Path) -> list:
    return get_creation_requests(project_path, "project-a")


def test_encola_peticion_us_con_descripcion_real_y_epic_existente(
    tmp_path: Path, monkeypatch
) -> None:
    project_path = _active_project(tmp_path, monkeypatch)
    _write_epic(project_path, "AF-999")
    client = TestClient(create_app())

    response = client.post(
        "/backlog/epic/AF-999/from-description-us",
        json={"description": "Como usuario quiero poder filtrar por prioridad en el backlog."},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["tipo"] == "us"
    assert body["status"] == STATUS_PENDING
    assert body["request_id"]

    # La petición queda PENDING en la cola, con el epic_id de contexto.
    requests = _requests(project_path)
    assert len(requests) == 1
    entry = requests[0]
    assert entry.request_id == body["request_id"]
    assert entry.tipo == "us"
    assert entry.status == STATUS_PENDING
    assert entry.epic_id == "AF-999"
    assert "filtrar por prioridad" in entry.description

    # No se escribió ningún fichero de backlog nuevo ni se despachó (pending).
    assert not (project_path / "02-backlog" / "user-stories").exists()


def test_epic_inexistente_devuelve_404_sin_encolar(tmp_path: Path, monkeypatch) -> None:
    project_path = _active_project(tmp_path, monkeypatch)
    client = TestClient(create_app())

    response = client.post(
        "/backlog/epic/AF-000/from-description-us",
        json={"description": "Cualquiera."},
    )

    assert response.status_code == 404
    assert _requests(project_path) == []


def test_descripcion_vacia_devuelve_400_sin_encolar(tmp_path: Path, monkeypatch) -> None:
    project_path = _active_project(tmp_path, monkeypatch)
    _write_epic(project_path, "AF-999")
    client = TestClient(create_app())

    # Vacía literal y solo espacios.
    for empty in ("", "   ", "\n\t  "):
        response = client.post(
            "/backlog/epic/AF-999/from-description-us", json={"description": empty}
        )
        assert response.status_code == 400

    assert _requests(project_path) == []


def test_descripcion_omitida_devuelve_422(tmp_path: Path, monkeypatch) -> None:
    project_path = _active_project(tmp_path, monkeypatch)
    _write_epic(project_path, "AF-999")
    client = TestClient(create_app())

    response = client.post("/backlog/epic/AF-999/from-description-us", json={})

    assert response.status_code == 422  # falta el campo obligatorio
    assert _requests(project_path) == []


def test_varias_peticiones_se_encolan_fifo_sin_tocar_ficheros_de_backlog(
    tmp_path: Path, monkeypatch
) -> None:
    project_path = _active_project(tmp_path, monkeypatch)
    _write_epic(project_path, "AF-999")
    client = TestClient(create_app())

    r1 = client.post(
        "/backlog/epic/AF-999/from-description-us", json={"description": "Primera petición."}
    )
    r2 = client.post(
        "/backlog/epic/AF-999/from-description-us", json={"description": "Segunda petición."}
    )
    assert r1.status_code == 202 and r2.status_code == 202

    requests = _requests(project_path)
    assert len(requests) == 2
    assert [entry.description for entry in requests] == [
        "Primera petición.",
        "Segunda petición.",
    ]
    assert all(entry.status == STATUS_PENDING for entry in requests)
    # Nada se despachó: sin report_file ni ficheros de backlog nuevos.
    assert all(entry.report_file is None for entry in requests)
    assert not (project_path / "02-backlog" / "user-stories").exists()


# ---------------------------------------------------------------------------
# T-AF036-US20-04: endpoint web de la cola de peticiones de creación
# (`GET /backlog/creation-requests`) para el panel "Peticiones para el
# Arquitecto". Devuelve la cola (cualquier estado, orden de encolado) con los
# motivos verbatim de las peticiones `failed`.
# ---------------------------------------------------------------------------


def test_get_creation_requests_endpoint_expone_la_cola_con_errores(
    tmp_path: Path, monkeypatch
) -> None:
    from atlas_forge.dispatcher.creation_queue import (
        mark_creation_failed,
        mark_creation_in_flight,
    )

    project_path = _active_project(tmp_path, monkeypatch)
    _write_epic(project_path, "AF-999")
    client = TestClient(create_app())

    r1 = client.post(
        "/backlog/epic/AF-999/from-description-us", json={"description": "Primera."}
    )
    r2 = client.post(
        "/backlog/epic/from-description", json={"description": "Segunda epic."}
    )
    rq1, rq2 = r1.json()["request_id"], r2.json()["request_id"]

    # Estado variado: una en vuelo y una fallida con motivos verbatim.
    mark_creation_in_flight(project_path, "project-a", rq1, "/tmp/r1.txt")
    mark_creation_failed(project_path, "project-a", rq2, ["id duplicado: ya existe la Epic.", "prioridad inválida"])

    response = client.get("/backlog/creation-requests")
    assert response.status_code == 200
    body = response.json()
    by_id = {entry["request_id"]: entry for entry in body}
    assert by_id[rq1]["status"] == STATUS_IN_FLIGHT
    assert by_id[rq1]["tipo"] == "us"
    assert by_id[rq1]["epic_id"] == "AF-999"
    assert by_id[rq2]["status"] == "failed"
    assert by_id[rq2]["tipo"] == "epic"
    assert by_id[rq2]["errors"] == ["id duplicado: ya existe la Epic.", "prioridad inválida"]
    assert by_id[rq1]["description"] == "Primera."


def test_get_creation_requests_endpoint_404_sin_proyecto(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(routes_module, "get_active_project", lambda **_kwargs: None)
    client = TestClient(create_app())

    response = client.get("/backlog/creation-requests")

    assert response.status_code == 404