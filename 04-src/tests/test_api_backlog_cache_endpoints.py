"""Tests de aplicación de la caché del BacklogGraph a los endpoints de
lectura (T-AF048-US01-02, US-AF048-01): `GET /backlog/{item_id}` (detalle),
`GET /backlog` (informe) y `GET /backlog/queue` (cola) usan el loader memoizado
(`load_backlog_cached`) y NO re-parsean el backlog completo en cada
request/poll sin cambios; tras una escritura real, la siguiente lectura
devuelve el dato nuevo; las respuestas son idénticas a las de sin-caché.

La no-re-parseada se demuestra a nivel del loader (`test_backlog_cache.py`,
contador de `parse_backlog_item`: 2ª lectura sin cambios → count constante);
a nivel de endpoints se verifica el contrato observable de esta Task: respuestas
idénticas entre lecturas sin cambios y refresco tras escritura real (sin
reiniciar la API).

Determinista, sin tmux, contra `TestClient(create_app())` con proyecto activo
aislado en `tmp_path`."""
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
        "---\nid: AF-999\ntype: epic\ntitle: Epic\n"
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
    """Cuenta las invocaciones de `parse_backlog_item` (cada una parsea un
    fichero): un endpoint que re-parsea en cada lectura hace crecer el
    contador; uno que usa la caché no."""
    counter = {"n": 0}
    original = parser_module.parse_backlog_item

    def counting(item_path):
        counter["n"] += 1
        return original(item_path)

    monkeypatch.setattr(parser_module, "parse_backlog_item", counting)
    return counter


def test_get_backlog_no_reparsea_en_segunda_lectura(tmp_path, monkeypatch) -> None:
    """Criterio principal: `GET /backlog` (el INFORME) NO re-parsea en la
    2ª+ lectura sin cambios — el contador de `parse_backlog_item` queda
    estable tras la primera. (Antes del fix re-parseaba cada vez: 2 → 4 → 6.)"""
    _active_project(tmp_path, monkeypatch)
    counter = _parse_counter(monkeypatch)
    client = TestClient(create_app())

    r1 = client.get("/backlog")
    assert r1.status_code == 200
    first = counter["n"]
    assert first >= 2  # af-999 + us-af999-01

    r2 = client.get("/backlog")
    assert r2.status_code == 200
    assert counter["n"] == first, "GET /backlog re-parseó en la 2ª lectura"

    r3 = client.get("/backlog")
    assert r3.status_code == 200
    assert counter["n"] == first, "GET /backlog re-parseó en la 3ª lectura"
    assert r1.json() == r2.json() == r3.json()


def test_informe_y_detalle_identicos_en_lecturas_sin_cambios(tmp_path, monkeypatch) -> None:
    """Contrato sin cambios (criterio de "diff JSON idéntico"): la 2ª y 3ª
    lectura de GET /backlog y GET /backlog/{item_id} devuelven exactamente lo
    mismo que la 1ª — la caché no altera el valor servido."""
    _active_project(tmp_path, monkeypatch)
    client = TestClient(create_app())

    report1 = client.get("/backlog")
    assert report1.status_code == 200
    report2 = client.get("/backlog")
    assert report2.status_code == 200
    assert report2.json() == report1.json()

    detail1 = client.get("/backlog/AF-999")
    assert detail1.status_code == 200
    detail2 = client.get("/backlog/AF-999")
    assert detail2.status_code == 200
    assert detail2.json() == detail1.json()

    # El detalle de una US también es estable entre lecturas.
    us1 = client.get("/backlog/US-AF999-01")
    assert us1.status_code == 200
    us2 = client.get("/backlog/US-AF999-01")
    assert us2.status_code == 200
    assert us2.json() == us1.json()


def test_queue_identico_en_polls_consecutivos_sin_cambios(tmp_path, monkeypatch) -> None:
    """GET /backlog/queue se ejecuta por polling ~5s: en polls consecutivos
    sin cambios la respuesta es idéntica (no cambia el estado derivado) — la
    caché no introduce inestabilidad."""
    _active_project(tmp_path, monkeypatch)
    client = TestClient(create_app())

    q1 = client.get("/backlog/queue")
    assert q1.status_code == 200
    q2 = client.get("/backlog/queue")
    assert q2.status_code == 200
    q3 = client.get("/backlog/queue")
    assert q3.status_code == 200
    assert q2.json() == q1.json()
    assert q3.json() == q1.json()


def test_escritura_real_invalida_y_la_siguiente_lectura_refleja_lo_nuevo(
    tmp_path, monkeypatch,
) -> None:
    """Tras una escritura real (crear una Epic nueva vía POST), la siguiente
    lectura de GET /backlog y GET /backlog/{item_id} refleja el item nuevo sin
    reiniciar la API (invalidación por mtime+size del loader memoizado)."""
    project = _active_project(tmp_path, monkeypatch)
    client = TestClient(create_app())

    before = client.get("/backlog").json()
    assert "AF-998" not in str(before)

    resp = client.post(
        "/backlog/epic",
        json={"id": "AF-998", "title": "Epic nueva", "objetivo": "Objetivo nuevo."},
    )
    assert resp.status_code == 201

    after = client.get("/backlog").json()
    assert "AF-998" in str(after)

    detail = client.get("/backlog/AF-998")
    assert detail.status_code == 200
    assert detail.json()["id"] == "AF-998"


def test_get_backlog_item_caliente_no_reparsea(tmp_path, monkeypatch) -> None:
    """Criterio (T-AF048-US01-03): GET /backlog/{item_id} EN CALIENTE (2ª y 3ª
    llamada sin cambios) no incrementa el contador de `parse_backlog_item` y
    devuelve el mismo item."""
    _active_project(tmp_path, monkeypatch)
    counter = _parse_counter(monkeypatch)
    client = TestClient(create_app())

    client.get("/backlog/AF-999").json()  # frío (1ª)
    cold = counter["n"]

    detail2 = client.get("/backlog/AF-999")
    assert detail2.status_code == 200
    assert counter["n"] == cold, "GET /backlog/{item_id} re-parseó en la 2ª llamada"

    us1 = client.get("/backlog/US-AF999-01")
    assert us1.status_code == 200
    us2 = client.get("/backlog/US-AF999-01")
    assert us2.status_code == 200
    after_us = counter["n"]
    assert us2.json() == us1.json()
    us3 = client.get("/backlog/US-AF999-01")
    assert counter["n"] == after_us, "GET /backlog/{item_id} re-parseó en la 3ª llamada"


def test_get_backlog_queue_caliente_no_reparsea(tmp_path, monkeypatch) -> None:
    """Criterio: GET /backlog/queue en polls consecutivos sin cambios no
    incrementa el contador de `parse_backlog_item`."""
    _active_project(tmp_path, monkeypatch)
    counter = _parse_counter(monkeypatch)
    client = TestClient(create_app())

    q1 = client.get("/backlog/queue")
    assert q1.status_code == 200
    cold = counter["n"]

    q2 = client.get("/backlog/queue")
    assert q2.status_code == 200
    assert counter["n"] == cold, "GET /backlog/queue re-parseó en un poll sin cambios"
    assert q2.json() == q1.json()


def test_edicion_de_priority_o_version_invalida_y_se_refleja(tmp_path, monkeypatch) -> None:
    """Criterio (b): modificar `priority` o `version` de un fichero de prueba →
    la siguiente lectura (misma ruta) devuelve el dato nuevo, sin borrar caché
    ni reiniciar."""
    project = _active_project(tmp_path, monkeypatch)
    us_path = project / "02-backlog" / "user-stories" / "US-AF999-01.md"
    client = TestClient(create_app())

    before = client.get("/backlog/US-AF999-01").json()
    # priority/version actuales del fichero de prueba ("Alta"/"0.9").
    assert before["priority"] == "Alta." or "Alta" in str(before.get("priority", ""))

    text = us_path.read_text(encoding="utf-8")
    us_path.write_text(
        text.replace("priority: Alta", "priority: Baja").replace("version: 0.9", "version: 0.9.2"),
        encoding="utf-8",
    )

    after = client.get("/backlog/US-AF999-01").json()
    # El detalle refleja el dato nuevo (invalidación por mtime+size).
    assert after is not before
    assert "Baja" in str(after.get("priority", ""))