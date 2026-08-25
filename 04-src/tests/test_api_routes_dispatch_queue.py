"""Tests de `POST /backlog/{task_id}/enqueue`,
`POST /backlog/{us_id}/enqueue-all`, `DELETE /backlog/{task_id}/enqueue`
y `GET /backlog/queue` (T-AF008-US10-01, US-AF008-10 · "Marcar Tasks
como listas para desarrollo y que un Dispatcher las asigne solo a un
Developer libre") — mecanismo de cola en sí, sin ningún Dispatcher real
(esa pieza es `T-AF008-US10-02`, aparte).

Backlog real escrito a un `tmp_path` aislado (formato frontmatter YAML
vigente, con `user_story:` real en cada Task — necesario para verificar
`POST /backlog/{us_id}/enqueue-all`, que filtra por ese campo, nunca por
prefijo de `task_id`), mismo patrón que `test_api_routes_backlog.py`."""

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


def _write_task_yaml(
    tasks_dir: Path,
    task_id: str,
    *,
    us_id: str,
    epic: str,
    state: str,
    priority: str | None = None,
) -> None:
    """Task en formato frontmatter YAML vigente (`AF-027`), con
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
    us_dir: Path, us_id: str, *, epic: str, state: str = "READY", priority: str = "Alta"
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
    _write_us_yaml(backlog / "user-stories", "US-AF999-01", epic="AF-999")
    _write_task_yaml(
        backlog / "tasks", "T-AF999-US01-01", us_id="US-AF999-01", epic="AF-999",
        state="READY", priority="Alta",
    )
    _write_task_yaml(
        backlog / "tasks", "T-AF999-US01-02", us_id="US-AF999-01", epic="AF-999",
        state="READY", priority="Media",
    )
    _write_task_yaml(
        backlog / "tasks", "T-AF999-US01-03", us_id="US-AF999-01", epic="AF-999",
        state="DONE", priority="Baja",
    )


def test_post_enqueue_task_returns_404_for_unknown_task(tmp_path, monkeypatch) -> None:
    project_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog(project_path)
    client = TestClient(create_app())

    response = client.post("/backlog/T-AF999-US01-999/enqueue")

    assert response.status_code == 404


def test_post_enqueue_task_returns_400_when_not_to_do(tmp_path, monkeypatch) -> None:
    project_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog(project_path)
    client = TestClient(create_app())

    # T-AF999-US01-03 está DONE en el fixture.
    response = client.post("/backlog/T-AF999-US01-03/enqueue")

    assert response.status_code == 400
    assert "READY" in response.json()["detail"]


def test_post_enqueue_task_reflects_in_queue(tmp_path, monkeypatch) -> None:
    # Criterio de aceptación: "Encolar una Task real vía el endpoint la
    # refleja en GET /backlog/queue."
    project_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog(project_path)
    client = TestClient(create_app())

    response = client.post("/backlog/T-AF999-US01-01/enqueue")
    assert response.status_code == 201
    body = response.json()
    assert body["task_id"] == "T-AF999-US01-01"
    assert body["us_id"] == "US-AF999-01"
    assert body["priority"] == "Alta"
    assert body["status"] == "queued"

    queue = client.get("/backlog/queue").json()
    assert [e["task_id"] for e in queue["queued"]] == ["T-AF999-US01-01"]


def test_post_enqueue_task_twice_is_rejected(tmp_path, monkeypatch) -> None:
    """T-AF008-US14-01: el primer POST /enqueue escribe `state: TO_DEVELOP`
    en el fichero real — el segundo intento ahora se rechaza con 400
    ("no está en estado TODO", motivo real más claro que antes) en vez
    de 409 (`TaskAlreadyQueuedError`, que solo se alcanzaba comparando
    contra `dispatch_queue.json`, ya inalcanzable porque el guard de
    `state` lo intercepta antes)."""
    project_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog(project_path)
    client = TestClient(create_app())

    client.post("/backlog/T-AF999-US01-01/enqueue")
    response = client.post("/backlog/T-AF999-US01-01/enqueue")

    assert response.status_code == 400
    assert "TO_DEVELOP" in response.json()["detail"]


def test_post_enqueue_all_adds_every_to_do_task_of_the_story(tmp_path, monkeypatch) -> None:
    # Criterio de aceptación: "Encolar todas las Tasks TODO de una US
    # real las añade todas a la cola de una sola llamada."
    project_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog(project_path)
    client = TestClient(create_app())

    response = client.post("/backlog/US-AF999-01/enqueue-all")

    assert response.status_code == 201
    body = response.json()
    # Solo las dos TODO (T-AF999-US01-01/-02) — la -03 está DONE, no se
    # encola (mismo criterio que POST .../enqueue individual).
    assert sorted(body["enqueued"]) == ["T-AF999-US01-01", "T-AF999-US01-02"]

    queue = client.get("/backlog/queue").json()
    assert sorted(e["task_id"] for e in queue["queued"]) == [
        "T-AF999-US01-01",
        "T-AF999-US01-02",
    ]


def test_post_enqueue_all_returns_404_for_unknown_story(tmp_path, monkeypatch) -> None:
    project_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog(project_path)
    client = TestClient(create_app())

    response = client.post("/backlog/US-AF999-99/enqueue-all")

    assert response.status_code == 404


def test_post_enqueue_all_skips_tasks_already_en_cola(tmp_path, monkeypatch) -> None:
    """T-AF008-US14-01: una Task ya encolada individualmente ya tiene
    `state: TO_DEVELOP` en el fichero real — `enqueue-all` la filtra de
    `pending_tasks` (solo mira `state == "READY"`) antes de intentar
    encolarla, así que ya no llega ni a `enqueued` ni a
    `skipped_already_queued` (ese campo solo capturaba el caso, ahora
    inalcanzable por esta vía, de una entrada JSON duplicada con el
    `state` real todavía en `TODO`)."""
    project_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog(project_path)
    client = TestClient(create_app())

    client.post("/backlog/T-AF999-US01-01/enqueue")
    response = client.post("/backlog/US-AF999-01/enqueue-all")

    assert response.status_code == 201
    body = response.json()
    assert body["skipped_already_queued"] == []
    assert body["enqueued"] == ["T-AF999-US01-02"]


def test_delete_dequeue_removes_task_without_side_effects(tmp_path, monkeypatch) -> None:
    # Criterio de aceptación: "Desencolar una Task antes de ser
    # despachada la retira de GET /backlog/queue sin ningún efecto
    # secundario."
    project_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog(project_path)
    client = TestClient(create_app())

    client.post("/backlog/T-AF999-US01-01/enqueue")
    client.post("/backlog/T-AF999-US01-02/enqueue")

    response = client.delete("/backlog/T-AF999-US01-01/enqueue")
    assert response.status_code == 200

    queue = client.get("/backlog/queue").json()
    task_ids = [e["task_id"] for e in queue["queued"]]
    assert "T-AF999-US01-01" not in task_ids
    assert "T-AF999-US01-02" in task_ids


def test_put_state_en_desarrollo_on_user_story_enqueues_its_to_do_tasks(tmp_path, monkeypatch) -> None:
    """T-AF008-US14-04: marcar una User Story como TO_DEVELOP desde
    `PUT /backlog/{item_id}/state` (selector genérico de US-AF036-08) es
    un atajo del mismo efecto que `POST /backlog/{us_id}/enqueue-all` —
    mismas Tasks TODO encoladas, mismo criterio de filtro."""
    project_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog(project_path)
    client = TestClient(create_app())

    response = client.put("/backlog/US-AF999-01/state", json={"state": "TO_DEVELOP"})

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "TO_DEVELOP"
    assert sorted(body["enqueued"]) == ["T-AF999-US01-01", "T-AF999-US01-02"]
    assert body["skipped_already_queued"] == []

    queue = client.get("/backlog/queue").json()
    assert sorted(e["task_id"] for e in queue["queued"]) == [
        "T-AF999-US01-01",
        "T-AF999-US01-02",
    ]


def test_put_state_en_desarrollo_on_user_story_is_idempotent(tmp_path, monkeypatch) -> None:
    """Repetir el cambio de estado sobre una Story ya parcialmente
    encolada no falla — salta las Tasks que ya estaban en TO_DEVELOP,
    mismo criterio de idempotencia que enqueue-all."""
    project_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog(project_path)
    client = TestClient(create_app())

    client.post("/backlog/T-AF999-US01-01/enqueue")
    response = client.put("/backlog/US-AF999-01/state", json={"state": "TO_DEVELOP"})

    assert response.status_code == 200
    body = response.json()
    assert body["enqueued"] == ["T-AF999-US01-02"]
    assert body["skipped_already_queued"] == []


def test_put_state_en_desarrollo_on_task_does_not_trigger_enqueue_all(tmp_path, monkeypatch) -> None:
    """El atajo solo aplica a User Story — marcar una Task individual
    como TO_DEVELOP sigue siendo el cambio de estado simple ya
    existente, sin efecto secundario de "encolar toda la Story"."""
    project_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog(project_path)
    client = TestClient(create_app())

    response = client.put("/backlog/T-AF999-US01-01/state", json={"state": "TO_DEVELOP"})

    assert response.status_code == 200
    body = response.json()
    assert "enqueued" not in body

    queue = client.get("/backlog/queue").json()
    assert queue["queued"] == []


def test_delete_dequeue_returns_404_when_never_queued(tmp_path, monkeypatch) -> None:
    project_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog(project_path)
    client = TestClient(create_app())

    response = client.delete("/backlog/T-AF999-US01-01/enqueue")

    assert response.status_code == 404


def test_get_queue_orders_queued_entries_by_priority(tmp_path, monkeypatch) -> None:
    # Criterio de aceptación explícito: test de integración que encola 3
    # Tasks de prioridades distintas y confirma que GET /backlog/queue
    # las devuelve ordenadas por prioridad — Crítica primero, luego
    # Alta, Media y Baja/sin prioridad al final.
    project_path = _active_project(tmp_path, monkeypatch)
    backlog = project_path / "02-backlog"
    _write_us_yaml(backlog / "user-stories", "US-AF999-01", epic="AF-999")
    _write_task_yaml(
        backlog / "tasks", "T-AF999-US01-01", us_id="US-AF999-01", epic="AF-999",
        state="READY", priority="Baja",
    )
    _write_task_yaml(
        backlog / "tasks", "T-AF999-US01-02", us_id="US-AF999-01", epic="AF-999",
        state="READY", priority="Crítica",
    )
    _write_task_yaml(
        backlog / "tasks", "T-AF999-US01-03", us_id="US-AF999-01", epic="AF-999",
        state="READY", priority="Media",
    )
    client = TestClient(create_app())

    # Encoladas deliberadamente en un orden distinto al esperado, para
    # que el test verifique el REORDENAMIENTO por prioridad, no solo el
    # orden de inserción.
    client.post("/backlog/T-AF999-US01-01/enqueue")  # Baja
    client.post("/backlog/T-AF999-US01-02/enqueue")  # Crítica
    client.post("/backlog/T-AF999-US01-03/enqueue")  # Media

    queue = client.get("/backlog/queue").json()

    assert [e["task_id"] for e in queue["queued"]] == [
        "T-AF999-US01-02",  # Crítica
        "T-AF999-US01-03",  # Media
        "T-AF999-US01-01",  # Baja
    ]
    assert [e["priority"] for e in queue["queued"]] == ["Crítica", "Media", "Baja"]


def test_get_queue_persists_across_a_fresh_process_read(tmp_path, monkeypatch) -> None:
    # Requisito explícito del mecanismo de persistencia elegido: la cola
    # debe ser consultable tras un "reinicio del proceso" — simulado
    # aquí leyendo directamente del módulo de cola (sin pasar por el
    # TestClient/proceso HTTP que la escribió), como haría un proceso
    # `atlas-forge-api` nuevo tras un restart.
    from atlas_forge.dispatcher.dispatch_queue import get_queue

    project_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog(project_path)
    client = TestClient(create_app())

    client.post("/backlog/T-AF999-US01-01/enqueue")

    entries = get_queue(str(project_path), "project-a")
    assert [e.task_id for e in entries] == ["T-AF999-US01-01"]


# ---------------------------------------------------------------------------
# T-AF008-US10-04: GET /backlog/queue deriva el estado mostrado cruzando la
# entrada con el estado REAL del fichero de la Task (fuente de verdad).
# ---------------------------------------------------------------------------


def test_get_queue_shows_in_progress_as_dispatched_and_in_review_as_awaiting_tester(
    tmp_path, monkeypatch,
) -> None:
    """Criterio 2: una Task `IN_REVIEW` (con entrada `dispatched` residual)
    aparece como "esperando al Tester" (con el Developer retenido), nunca
    como "En curso"; solo la Task realmente `IN_PROGRESS` aparece en
    `dispatched`."""
    from atlas_forge.dispatcher.dispatch_queue import mark_dispatched

    project_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog(project_path)
    backlog = project_path / "02-backlog"
    client = TestClient(create_app())

    client.post("/backlog/US-AF999-01/enqueue-all")  # T-01 y T-02 queued

    for task_id in ("T-AF999-US01-01", "T-AF999-US01-02"):
        mark_dispatched(str(project_path), "project-a", task_id, agent_id="a-1", agent_name="Developer-1")
    _write_task_yaml(
        backlog / "tasks", "T-AF999-US01-01", us_id="US-AF999-01", epic="AF-999",
        state="IN_PROGRESS", priority="Alta",
    )
    _write_task_yaml(
        backlog / "tasks", "T-AF999-US01-02", us_id="US-AF999-01", epic="AF-999",
        state="IN_REVIEW", priority="Media",
    )

    queue = client.get("/backlog/queue").json()

    assert [e["task_id"] for e in queue["dispatched"]] == ["T-AF999-US01-01"]
    assert [e["task_id"] for e in queue["awaiting_tester"]] == ["T-AF999-US01-02"]
    assert queue["awaiting_tester"][0]["agent_name"] == "Developer-1"
    assert queue["awaiting_tester"][0]["effective_status"] == "awaiting_tester"
    assert queue["dispatched"][0]["effective_status"] == "dispatched"
    # La entrada almacenada sigue siendo `dispatched` (registro auxiliar) —
    # solo el derivado distingue la retención.
    assert queue["awaiting_tester"][0]["status"] == "dispatched"
    assert queue["completed"] == []
    assert queue["queued"] == []
    assert queue["failed"] == []


def test_get_queue_never_shows_a_done_task_as_en_curso(tmp_path, monkeypatch) -> None:
    """Criterio 1/4: una Task `DONE` con entrada `dispatched` residual
    aparece en `completed` (efectivo), nunca en `dispatched`."""
    from atlas_forge.dispatcher.dispatch_queue import mark_dispatched

    project_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog(project_path)
    backlog = project_path / "02-backlog"
    client = TestClient(create_app())

    client.post("/backlog/T-AF999-US01-01/enqueue")
    mark_dispatched(str(project_path), "project-a", "T-AF999-US01-01", agent_id="a-1", agent_name="Developer-1")
    _write_task_yaml(
        backlog / "tasks", "T-AF999-US01-01", us_id="US-AF999-01", epic="AF-999",
        state="DONE", priority="Alta",
    )

    queue = client.get("/backlog/queue").json()

    assert [e["task_id"] for e in queue["completed"]] == ["T-AF999-US01-01"]
    assert queue["dispatched"] == []
    assert queue["completed"][0]["effective_status"] == "completed"
    # La entrada almacenada no se mutó por la derivación — sigue siendo el
    # registro de orden/auditoría (`dispatched`), solo el derivado cambia.
    assert queue["completed"][0]["status"] == "dispatched"


def test_get_queue_orphan_readystate_entry_is_not_en_curso(tmp_path, monkeypatch) -> None:
    """Criterio 3: una Task `READY` con entrada `dispatched` residual
    (huérfana de reinicio) no aparece como "En curso" — cae al grupo
    `failed` con el motivo derivado, y `dispatched` queda vacío."""
    from atlas_forge.dispatcher.dispatch_queue import mark_dispatched

    project_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog(project_path)
    backlog = project_path / "02-backlog"
    client = TestClient(create_app())

    client.post("/backlog/T-AF999-US01-01/enqueue")
    mark_dispatched(str(project_path), "project-a", "T-AF999-US01-01", agent_id="a-1", agent_name="Developer-1")
    # Huérfana: el fichero real vuelve a READY (p. ej. tras un reinicio),
    # la entrada `dispatched` residual queda sin justificar.
    _write_task_yaml(
        backlog / "tasks", "T-AF999-US01-01", us_id="US-AF999-01", epic="AF-999",
        state="READY", priority="Alta",
    )

    queue = client.get("/backlog/queue").json()

    assert queue["dispatched"] == []
    assert [e["task_id"] for e in queue["failed"]] == ["T-AF999-US01-01"]
    assert queue["failed"][0]["effective_status"] == "failed"
    assert queue["failed"][0]["status"] == "dispatched"


def test_get_queue_includes_effective_status_on_queued_entries(tmp_path, monkeypatch) -> None:
    """Las entradas `queued` conservan su grupo y ahora serializan también
    su `effective_status` (compatibilidad hacia delante de la UI)."""
    project_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog(project_path)
    client = TestClient(create_app())

    client.post("/backlog/T-AF999-US01-01/enqueue")

    queue = client.get("/backlog/queue").json()

    assert [e["task_id"] for e in queue["queued"]] == ["T-AF999-US01-01"]
    assert queue["queued"][0]["effective_status"] == "queued"
    assert queue["dispatched"] == []
    assert queue["awaiting_tester"] == []
    assert queue["completed"] == []
    assert queue["failed"] == []


def test_queue_exposes_finished_at_on_terminal_entry(tmp_path, monkeypatch) -> None:
    """T-AF036-US17-01: `GET /backlog/queue` expone `finished_at` (además de
    `enqueued_at`/`dispatched_at`) en una entrada terminal `completed`."""
    from atlas_forge.dispatcher.dispatch_queue import mark_completed, mark_dispatched

    project_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog(project_path)
    client = TestClient(create_app())

    assert client.post("/backlog/T-AF999-US01-01/enqueue").status_code == 201
    mark_dispatched(
        project_path, "project-a", "T-AF999-US01-01",
        agent_id="a1", agent_name="Developer-1",
    )
    mark_completed(project_path, "project-a", "T-AF999-US01-01", result="ok")

    queue = client.get("/backlog/queue").json()
    entry = next(e for e in queue["completed"] if e["task_id"] == "T-AF999-US01-01")
    assert entry["enqueued_at"] is not None
    assert entry["dispatched_at"] is not None
    assert entry["finished_at"] is not None


def test_delete_queue_history_removes_terminal_and_keeps_active(
    tmp_path, monkeypatch
) -> None:
    """T-AF036-US17-02: `DELETE /backlog/queue/history` borra las entradas
    `completed`/`failed`, conserva las en curso y devuelve cuántas borró."""
    from atlas_forge.dispatcher.dispatch_queue import mark_completed, mark_dispatched

    project_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog(project_path)
    client = TestClient(create_app())

    # T-...-01 -> completed (se borrará)
    assert client.post("/backlog/T-AF999-US01-01/enqueue").status_code == 201
    mark_dispatched(project_path, "project-a", "T-AF999-US01-01", agent_id="a1", agent_name="D1")
    mark_completed(project_path, "project-a", "T-AF999-US01-01", result="ok")
    # T-...-02 -> queued (se conserva)
    assert client.post("/backlog/T-AF999-US01-02/enqueue").status_code == 201

    resp = client.delete("/backlog/queue/history")

    assert resp.status_code == 200
    assert resp.json()["removed"] == 1

    queue = client.get("/backlog/queue").json()
    assert any(e["task_id"] == "T-AF999-US01-02" for e in queue["queued"])  # conservada
    assert not any(e["task_id"] == "T-AF999-US01-01" for e in queue["completed"])  # borrada


# ---------------------------------------------------------------------------
# T-AF036-US17-07: borrado individual de una sola entrada terminal.
# ---------------------------------------------------------------------------


def test_delete_queue_entry_removes_only_that_terminal_entry(
    tmp_path, monkeypatch
) -> None:
    """`DELETE /backlog/queue/entry/{task_id}` borra SOLO la entrada terminal
    de `task_id` y conserva el resto de la cola, devolviendo cuántas borró."""
    from atlas_forge.dispatcher.dispatch_queue import mark_completed, mark_dispatched

    project_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog(project_path)
    client = TestClient(create_app())

    # T-...-01 -> completed (se borra)
    assert client.post("/backlog/T-AF999-US01-01/enqueue").status_code == 201
    mark_dispatched(project_path, "project-a", "T-AF999-US01-01", agent_id="a1", agent_name="D1")
    mark_completed(project_path, "project-a", "T-AF999-US01-01", result="ok")
    # T-...-02 -> queued (se conserva)
    assert client.post("/backlog/T-AF999-US01-02/enqueue").status_code == 201

    resp = client.delete("/backlog/queue/entry/T-AF999-US01-01")

    assert resp.status_code == 200
    assert resp.json() == {"task_id": "T-AF999-US01-01", "removed": 1}

    queue = client.get("/backlog/queue").json()
    assert any(e["task_id"] == "T-AF999-US01-02" for e in queue["queued"])  # conservada
    assert not any(e["task_id"] == "T-AF999-US01-01" for e in queue["completed"])  # borrada


def test_delete_queue_entry_returns_404_when_task_not_in_queue(
    tmp_path, monkeypatch
) -> None:
    """404 si `task_id` no tiene ninguna entrada en la cola, con detail."""
    from atlas_forge.dispatcher.dispatch_queue import mark_completed, mark_dispatched

    project_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog(project_path)
    client = TestClient(create_app())

    assert client.post("/backlog/T-AF999-US01-01/enqueue").status_code == 201
    mark_dispatched(project_path, "project-a", "T-AF999-US01-01", agent_id="a1", agent_name="D1")
    mark_completed(project_path, "project-a", "T-AF999-US01-01", result="ok")

    resp = client.delete("/backlog/queue/entry/T-AF999-US01-999")

    assert resp.status_code == 404
    assert "T-AF999-US01-999" in resp.json()["detail"]
    # La cola no cambia.
    queue = client.get("/backlog/queue").json()
    assert any(e["task_id"] == "T-AF999-US01-01" for e in queue["completed"])


def test_delete_queue_entry_returns_409_when_entry_is_in_flight(
    tmp_path, monkeypatch
) -> None:
    """409 si la entrada existe pero está en curso (`queued`/`dispatched`) —
    no es borrable por esta vía, con detail del motivo."""
    from atlas_forge.dispatcher.dispatch_queue import mark_dispatched

    project_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog(project_path)
    client = TestClient(create_app())

    assert client.post("/backlog/T-AF999-US01-01/enqueue").status_code == 201
    mark_dispatched(project_path, "project-a", "T-AF999-US01-01", agent_id="a1", agent_name="D1")

    resp = client.delete("/backlog/queue/entry/T-AF999-US01-01")

    assert resp.status_code == 409
    assert "no es terminal" in resp.json()["detail"]
    # La entrada sigue en la cola.
    queue = client.get("/backlog/queue").json()
    assert any(e["task_id"] == "T-AF999-US01-01" for e in queue["dispatched"])


def test_delete_queue_entry_persists_and_does_not_affect_task_state(
    tmp_path, monkeypatch
) -> None:
    """El borrado persiste en `dispatch_queue.json` y no toca el estado real
    de la Task en el backlog."""
    from atlas_forge.dispatcher.dispatch_queue import (
        mark_completed,
        mark_dispatched,
    )

    project_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog(project_path)
    client = TestClient(create_app())

    assert client.post("/backlog/T-AF999-US01-01/enqueue").status_code == 201
    mark_dispatched(project_path, "project-a", "T-AF999-US01-01", agent_id="a1", agent_name="D1")
    mark_completed(project_path, "project-a", "T-AF999-US01-01", result="ok")

    resp = client.delete("/backlog/queue/entry/T-AF999-US01-01")
    assert resp.status_code == 200

    # La entrada desapareció del fichero persistente.
    from atlas_forge.dispatcher.dispatch_queue import get_queue

    entries = get_queue(project_path, "project-a")
    assert not any(e.task_id == "T-AF999-US01-01" for e in entries)
    # El estado real de la Task (que era READY) no cambia.
    task_text = (
        project_path / "02-backlog" / "tasks" / "T-AF999-US01-01.md"
    ).read_text(encoding="utf-8")
    assert "state: READY" in task_text
