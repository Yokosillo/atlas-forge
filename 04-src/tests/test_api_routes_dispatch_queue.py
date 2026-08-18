"""Tests de `POST /backlog/{task_id}/enqueue`,
`POST /backlog/{us_id}/enqueue-all`, `DELETE /backlog/{task_id}/enqueue`
y `GET /backlog/queue` (T-FB008-US10-01, US-FB008-10 · "Marcar Tasks
como listas para desarrollo y que un Dispatcher las asigne solo a un
Developer libre") — mecanismo de cola en sí, sin ningún Dispatcher real
(esa pieza es `T-FB008-US10-02`, aparte).

Backlog real escrito a un `tmp_path` aislado (formato frontmatter YAML
vigente, con `user_story:` real en cada Task — necesario para verificar
`POST /backlog/{us_id}/enqueue-all`, que filtra por ese campo, nunca por
prefijo de `task_id`), mismo patrón que `test_api_routes_backlog.py`."""

from pathlib import Path

from fastapi.testclient import TestClient

import brain.api.routes as routes_module
from brain.api import create_app


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


def _write_task_yaml(
    tasks_dir: Path,
    task_id: str,
    *,
    us_id: str,
    epic: str,
    state: str,
    priority: str | None = None,
) -> None:
    """Task en formato frontmatter YAML vigente (`FB-027`), con
    `user_story:` real — el campo que `POST /backlog/{us_id}/enqueue-all`
    usa para filtrar, no el prefijo del `task_id`."""
    priority_line = f"priority: {priority}\n" if priority else ""
    tasks_dir.mkdir(parents=True, exist_ok=True)
    (tasks_dir / f"{task_id}.md").write_text(
        "---\n"
        f"id: {task_id}\n"
        "type: task\n"
        f"title: {task_id} título de prueba\n"
        f"state: {state}\n"
        "dependencies: []\n"
        f"epic: {epic}\n"
        f"user_story: {us_id}\n"
        f"{priority_line}"
        "---\n\n"
        f"# {task_id} · título de prueba\n\n"
        "## Objetivo\n\nObjetivo de prueba.\n\n"
        "## Descripción\n\nDescripción de prueba.\n\n"
        "## Criterios de aceptación\n\n- Criterio uno.\n",
        encoding="utf-8",
    )


def _write_us_yaml(
    us_dir: Path, us_id: str, *, epic: str, state: str = "TODO", priority: str = "Alta"
) -> None:
    us_dir.mkdir(parents=True, exist_ok=True)
    (us_dir / f"{us_id}.md").write_text(
        "---\n"
        f"id: {us_id}\n"
        "type: user_story\n"
        f"title: {us_id} título de prueba\n"
        f"state: {state}\n"
        "dependencies: []\n"
        f"epic: {epic}\n"
        f"priority: {priority}\n"
        "---\n\n"
        f"# {us_id} · título de prueba\n\n"
        "## Historia\n\nComo usuario quiero X para lograr Y.\n\n"
        "## Criterios de aceptación\n\n- Criterio uno.\n",
        encoding="utf-8",
    )


def _seed_backlog(project_path: Path) -> None:
    backlog = project_path / "02-backlog"
    _write_us_yaml(backlog / "user-stories", "US-FB999-01", epic="FB-999")
    _write_task_yaml(
        backlog / "tasks", "T-FB999-US01-01", us_id="US-FB999-01", epic="FB-999",
        state="TODO", priority="Alta",
    )
    _write_task_yaml(
        backlog / "tasks", "T-FB999-US01-02", us_id="US-FB999-01", epic="FB-999",
        state="TODO", priority="Media",
    )
    _write_task_yaml(
        backlog / "tasks", "T-FB999-US01-03", us_id="US-FB999-01", epic="FB-999",
        state="DONE", priority="Baja",
    )


def test_post_enqueue_task_returns_404_for_unknown_task(tmp_path, monkeypatch) -> None:
    project_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog(project_path)
    client = TestClient(create_app())

    response = client.post("/backlog/T-FB999-US01-999/enqueue")

    assert response.status_code == 404


def test_post_enqueue_task_returns_400_when_not_todo(tmp_path, monkeypatch) -> None:
    project_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog(project_path)
    client = TestClient(create_app())

    # T-FB999-US01-03 está DONE en el fixture.
    response = client.post("/backlog/T-FB999-US01-03/enqueue")

    assert response.status_code == 400
    assert "TODO" in response.json()["detail"]


def test_post_enqueue_task_reflects_in_queue(tmp_path, monkeypatch) -> None:
    # Criterio de aceptación: "Encolar una Task real vía el endpoint la
    # refleja en GET /backlog/queue."
    project_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog(project_path)
    client = TestClient(create_app())

    response = client.post("/backlog/T-FB999-US01-01/enqueue")
    assert response.status_code == 201
    body = response.json()
    assert body["task_id"] == "T-FB999-US01-01"
    assert body["us_id"] == "US-FB999-01"
    assert body["priority"] == "Alta"
    assert body["status"] == "queued"

    queue = client.get("/backlog/queue").json()
    assert [e["task_id"] for e in queue["queued"]] == ["T-FB999-US01-01"]


def test_post_enqueue_task_twice_is_rejected(tmp_path, monkeypatch) -> None:
    """T-FB008-US14-01: el primer POST /enqueue escribe `state: EN_DESARROLLO`
    en el fichero real — el segundo intento ahora se rechaza con 400
    ("no está en estado TODO", motivo real más claro que antes) en vez
    de 409 (`TaskAlreadyQueuedError`, que solo se alcanzaba comparando
    contra `dispatch_queue.json`, ya inalcanzable porque el guard de
    `state` lo intercepta antes)."""
    project_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog(project_path)
    client = TestClient(create_app())

    client.post("/backlog/T-FB999-US01-01/enqueue")
    response = client.post("/backlog/T-FB999-US01-01/enqueue")

    assert response.status_code == 400
    assert "EN_DESARROLLO" in response.json()["detail"]


def test_post_enqueue_all_adds_every_todo_task_of_the_story(tmp_path, monkeypatch) -> None:
    # Criterio de aceptación: "Encolar todas las Tasks TODO de una US
    # real las añade todas a la cola de una sola llamada."
    project_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog(project_path)
    client = TestClient(create_app())

    response = client.post("/backlog/US-FB999-01/enqueue-all")

    assert response.status_code == 201
    body = response.json()
    # Solo las dos TODO (T-FB999-US01-01/-02) — la -03 está DONE, no se
    # encola (mismo criterio que POST .../enqueue individual).
    assert sorted(body["enqueued"]) == ["T-FB999-US01-01", "T-FB999-US01-02"]

    queue = client.get("/backlog/queue").json()
    assert sorted(e["task_id"] for e in queue["queued"]) == [
        "T-FB999-US01-01",
        "T-FB999-US01-02",
    ]


def test_post_enqueue_all_returns_404_for_unknown_story(tmp_path, monkeypatch) -> None:
    project_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog(project_path)
    client = TestClient(create_app())

    response = client.post("/backlog/US-FB999-99/enqueue-all")

    assert response.status_code == 404


def test_post_enqueue_all_skips_tasks_already_en_cola(tmp_path, monkeypatch) -> None:
    """T-FB008-US14-01: una Task ya encolada individualmente ya tiene
    `state: EN_DESARROLLO` en el fichero real — `enqueue-all` la filtra de
    `pending_tasks` (solo mira `state == "TODO"`) antes de intentar
    encolarla, así que ya no llega ni a `enqueued` ni a
    `skipped_already_queued` (ese campo solo capturaba el caso, ahora
    inalcanzable por esta vía, de una entrada JSON duplicada con el
    `state` real todavía en `TODO`)."""
    project_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog(project_path)
    client = TestClient(create_app())

    client.post("/backlog/T-FB999-US01-01/enqueue")
    response = client.post("/backlog/US-FB999-01/enqueue-all")

    assert response.status_code == 201
    body = response.json()
    assert body["skipped_already_queued"] == []
    assert body["enqueued"] == ["T-FB999-US01-02"]


def test_delete_dequeue_removes_task_without_side_effects(tmp_path, monkeypatch) -> None:
    # Criterio de aceptación: "Desencolar una Task antes de ser
    # despachada la retira de GET /backlog/queue sin ningún efecto
    # secundario."
    project_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog(project_path)
    client = TestClient(create_app())

    client.post("/backlog/T-FB999-US01-01/enqueue")
    client.post("/backlog/T-FB999-US01-02/enqueue")

    response = client.delete("/backlog/T-FB999-US01-01/enqueue")
    assert response.status_code == 200

    queue = client.get("/backlog/queue").json()
    task_ids = [e["task_id"] for e in queue["queued"]]
    assert "T-FB999-US01-01" not in task_ids
    assert "T-FB999-US01-02" in task_ids


def test_put_state_en_desarrollo_on_user_story_enqueues_its_todo_tasks(tmp_path, monkeypatch) -> None:
    """T-FB008-US14-04: marcar una User Story como EN_DESARROLLO desde
    `PUT /backlog/{item_id}/state` (selector genérico de US-FB036-08) es
    un atajo del mismo efecto que `POST /backlog/{us_id}/enqueue-all` —
    mismas Tasks TODO encoladas, mismo criterio de filtro."""
    project_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog(project_path)
    client = TestClient(create_app())

    response = client.put("/backlog/US-FB999-01/state", json={"state": "EN_DESARROLLO"})

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "EN_DESARROLLO"
    assert sorted(body["enqueued"]) == ["T-FB999-US01-01", "T-FB999-US01-02"]
    assert body["skipped_already_queued"] == []

    queue = client.get("/backlog/queue").json()
    assert sorted(e["task_id"] for e in queue["queued"]) == [
        "T-FB999-US01-01",
        "T-FB999-US01-02",
    ]


def test_put_state_en_desarrollo_on_user_story_is_idempotent(tmp_path, monkeypatch) -> None:
    """Repetir el cambio de estado sobre una Story ya parcialmente
    encolada no falla — salta las Tasks que ya estaban en EN_DESARROLLO,
    mismo criterio de idempotencia que enqueue-all."""
    project_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog(project_path)
    client = TestClient(create_app())

    client.post("/backlog/T-FB999-US01-01/enqueue")
    response = client.put("/backlog/US-FB999-01/state", json={"state": "EN_DESARROLLO"})

    assert response.status_code == 200
    body = response.json()
    assert body["enqueued"] == ["T-FB999-US01-02"]
    assert body["skipped_already_queued"] == []


def test_put_state_en_desarrollo_on_task_does_not_trigger_enqueue_all(tmp_path, monkeypatch) -> None:
    """El atajo solo aplica a User Story — marcar una Task individual
    como EN_DESARROLLO sigue siendo el cambio de estado simple ya
    existente, sin efecto secundario de "encolar toda la Story"."""
    project_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog(project_path)
    client = TestClient(create_app())

    response = client.put("/backlog/T-FB999-US01-01/state", json={"state": "EN_DESARROLLO"})

    assert response.status_code == 200
    body = response.json()
    assert "enqueued" not in body

    queue = client.get("/backlog/queue").json()
    assert queue["queued"] == []


def test_delete_dequeue_returns_404_when_never_queued(tmp_path, monkeypatch) -> None:
    project_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog(project_path)
    client = TestClient(create_app())

    response = client.delete("/backlog/T-FB999-US01-01/enqueue")

    assert response.status_code == 404


def test_get_queue_orders_queued_entries_by_priority(tmp_path, monkeypatch) -> None:
    # Criterio de aceptación explícito: test de integración que encola 3
    # Tasks de prioridades distintas y confirma que GET /backlog/queue
    # las devuelve ordenadas por prioridad — Crítica primero, luego
    # Alta, Media y Baja/sin prioridad al final.
    project_path = _active_project(tmp_path, monkeypatch)
    backlog = project_path / "02-backlog"
    _write_us_yaml(backlog / "user-stories", "US-FB999-01", epic="FB-999")
    _write_task_yaml(
        backlog / "tasks", "T-FB999-US01-01", us_id="US-FB999-01", epic="FB-999",
        state="TODO", priority="Baja",
    )
    _write_task_yaml(
        backlog / "tasks", "T-FB999-US01-02", us_id="US-FB999-01", epic="FB-999",
        state="TODO", priority="Crítica",
    )
    _write_task_yaml(
        backlog / "tasks", "T-FB999-US01-03", us_id="US-FB999-01", epic="FB-999",
        state="TODO", priority="Media",
    )
    client = TestClient(create_app())

    # Encoladas deliberadamente en un orden distinto al esperado, para
    # que el test verifique el REORDENAMIENTO por prioridad, no solo el
    # orden de inserción.
    client.post("/backlog/T-FB999-US01-01/enqueue")  # Baja
    client.post("/backlog/T-FB999-US01-02/enqueue")  # Crítica
    client.post("/backlog/T-FB999-US01-03/enqueue")  # Media

    queue = client.get("/backlog/queue").json()

    assert [e["task_id"] for e in queue["queued"]] == [
        "T-FB999-US01-02",  # Crítica
        "T-FB999-US01-03",  # Media
        "T-FB999-US01-01",  # Baja
    ]
    assert [e["priority"] for e in queue["queued"]] == ["Crítica", "Media", "Baja"]


def test_get_queue_persists_across_a_fresh_process_read(tmp_path, monkeypatch) -> None:
    # Requisito explícito del mecanismo de persistencia elegido: la cola
    # debe ser consultable tras un "reinicio del proceso" — simulado
    # aquí leyendo directamente del módulo de cola (sin pasar por el
    # TestClient/proceso HTTP que la escribió), como haría un proceso
    # `brain-api` nuevo tras un restart.
    from brain.dispatcher.dispatch_queue import get_queue

    project_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog(project_path)
    client = TestClient(create_app())

    client.post("/backlog/T-FB999-US01-01/enqueue")

    entries = get_queue(str(project_path), "project-a")
    assert [e.task_id for e in entries] == ["T-FB999-US01-01"]
