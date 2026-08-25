"""Tests de aplicación de la caché del BacklogGraph a los endpoints de
lectura (T-AF048-US01-02, US-AF048-01): `GET /backlog/{item_id}` (detalle),
`GET /backlog` (informe) y `GET /backlog/queue` (cola) usan
`load_backlog_cached` y NO re-parsean el backlog completo en cada
request/poll sin cambios; tras una escritura real, la siguiente lectura
devuelve el dato nuevo; las respuestas son idénticas a las de sin-caché
(diff JSON aditivo).

Determinista, sin tmux, contra `TestClient(create_app())` con proyecto activo
aislado en `tmp_path` (mismo patrón que el resto de la suite de routes)."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import atlas_forge.api.routes as routes_module
import atlas_forge.backlog.parser as parser_module
from atlas_forge.api.app import create_app


def _active_project(tmp_path: Path, monkeypatch) -> Path:
    project_path = tmp_path / "workspace" / "project-a"
    (project_path / "02-backlog" / "epics").mkdir(parents=True, exist_ok=True)
    (project_path / "02-backlog" / "user-stories").mkdir(parents=True, exist_ok=True)
    (project_path / "02-backlog" / "tasks").mkdir(parents=True, exist_ok=True)
    (project_path / "02-backlog" / "epics" / "AF-999.md").write_text(
        "---\nid: AF-999\ntype: epic\ntitle: Epic\nya"
        "state: TO_DO\ndependencies: []\nversion: 0.9\n"
        "---\n\n# AF-999 · Epic\n\n## Objetivo\n\nO.\n",
        encoding="utf-8",
    )
    (project_path / "02-backlog" / "user-stories" / "US-AF999-01.md").write_text(
        "---\nid: US-AF999-01\ntype: user_story\ntitle: Historia\n"
        "state: NO_TASKS\ndependencies: []\nepic: AF-999\npriority: Alta\nversion: 0.9\n"
        "---\n\n## Historia\n\nComo usuario...\n\n## Criterios de aceptación\n\n1. Y.\n",
        encoding="utf-8",
    )

    from atlas_forge.models import Project

    project = Project(
        id=str(project_path), name="project-a", path=str(project_path),
        repository="", workspace_id="ws-test",
    )
    monkeypatch.setattr(routes_module, "get_active_project", lambda **_kwargs: project)
    return project_path


def _parse_counter(monkeypatch):
    """Cuenta las invocaciones de `parse_backlog_item` (cada una es parsear un
    fichero; un `load_backlog_cached` sin cambios no llama a ninguna)."""
    counter = {"n": 0}
    original = parser_module.parse_backlog_item

    def counting(item_path):
        counter["n"] += 1
        return original(item_path)

    monkeypatch.setattr(parser_module, "parse_backlog_item", counting)
    return counter


def test_endpoints_no_reparsean_en_lecturas_sin_cambios(tmp_path, monkeypatch) -> None:
    """GET /backlog, GET /backlog/{item_id} y GET /backlog/queue: la 2ª y 3ª
    lectura sin cambios no disparan parseoo (el contador solo crece en la
    primera)."""
    project = _active_project(tmp_path, monkeypatch)
    counter = _parse_counter(monkeypatch)
    client = TestClient(create_app())

    # Primera lectura: re-parsea todo.
    r1 = client.get("/backlog")
    assert r1.status_code == 200
    parsed_after_first = counter["n"]
    assert parsed_after_first >= 2  # af-999 + us-af999-01

    # GET /backlog/{item_id} (detalle Epic) y GET /backlog de nuevo: sin
    # cambios → no re-parsea.
    r_item = client.get("/backlog/AF-999")
    assert r_item.status_code == 200
    assert counter["n"] == parsed_after_first  # usa la caché

    r2 = client.get("/backlog")
    assert r2.status_code == 200
    assert counter["n"] == parsed_after_first  # 2ª sin cambios, sin re-parsear
    assert r2.json() == r1.json()  # informe idéntico

    # GET /backlog/queue (cola): tampoco re-parsea en polls consecutivos.
    rq1 = client.get("/backlog/queue")
    assert rq1.status_code == 200
    assert counter["n"] == parsed_after_first
    rq2 = client.get("/backlog/queue")
    assert rq2.status_code == 200
    assert counter["n"] == parsed_after_first  # el contador no crece en polls


def test_escritura_real_invalida_y_la_siguiente_lectura_devuelve_dato_nuevo(
    tmp_path, monkeypatch,
) -> None:
    """Tras una escritura real (crear una US nueva vía endpoint), PUT state o
    edición del fichero — la siguiente lectura devuelve el dato nuevo sin
    reiniciar la API (invalidación por mtime+size)."""
    project = _active_project(tmp_path, monkeypatch)
    counter = _parse_counter(monkeypatch)
    client = TestClient(create_app())

    client.get("/backlog")  # primera lectura, puebla la caché
    base = counter["n"]

    # Escritura real: crear una Epic nueva vía POST al backlog real.
    resp = client.post(
        "/backlog/epic",
        json={"id": "AF-998", "title": "Epic nueva", "objetivo": "Objetivo nuevo."},
    )
    assert resp.status_code == 201

    # La siguiente lectura re-parsea (contador sube) y refleja el item nuevo.
    report = client.get("/backlog")
    assert report.status_code == 200
    assert counter["n"] > base  # se re-parseó por el cambio en disco
    by_epic = {e["epic"]: e for e in report.json().get("by_epic", [])}
    assert "AF-998" in by_epic or any("AF-998" in str(e) for e in by_epic)


def test_respuestas_idénticas_con_y_sin_caché(tmp_path, monkeypatch) -> None:
    """Para un backlog inmutable, las respuestas de los tres endpoints son
    idénticas entre la 1ª (re-parsea) y la 2ª (caché) lectura (diff JSON
    vacío); y el detalle de un item no cambia el contrato."""
    _active_project(tmp_path, monkeypatch)
    client = TestClient(create_app())

    first = client.get("/backlog").json()
    second = client.get("/backlog").json()
    assert first == second

    item_a = client.get("/backlog/AF-999").json()
    item_b = client.get("/backlog/AF-999").json()
    assert item_a == item_b

    q_a = client.get("/backlog/queue").json()
    q_b = client.get("/backlog/queue").json()
    assert q_a == q_b