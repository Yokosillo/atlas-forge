"""Tests de T-AF022-US07-03: persistencia de la cola de veredictos del
Arquitecto (`atlas_forge.dispatcher.architect_verdict_store`).

El ciclo de veredicto del Arquitecto era en memoria y no sobrevivía a un
reinicio de `atlas-forge-api`. Este módulo persiste el estado de la cola a
disco y lo reconcilia al arrancar. Los tests son deterministas (sin tmux):
simulan el reinicio escribiendo el estado de la cola en disco y volviendo a
leerlo/reconciliándolo con el backlog real, verificando que ninguna User
Story `IN_REVIEW` se pierde y que la US en vuelo vuelve a quedar pendiente.

Cobertura de criterios de aceptación:
- Criterio 1 (ninguna US se pierde ante reinicio, se retoman en orden):
  `test_reconcile_keeps_all_in_review_stories_in_order`,
  `test_restart_recovers_all_stories_no_loss`.
- Criterio 2 (veredicto en vuelo se reanuda o, como mínimo, la US vuelve a
  quedar pendiente): `test_reconcile_re_enqueues_the_inflight_story_first`,
  `test_restart_re_enqueues_inflight_story_for_re_dispatch`.
- Criterio 4 (tests deterministas sin tmux que simulan el reinicio y
  verifican la recuperación): todo este fichero.
"""

import json
from pathlib import Path

from atlas_forge.dispatcher.architect_verdict_store import (
    architect_verdict_queue_path,
    load_architect_verdict_queue,
    reconcile_architect_verdict_queue,
    save_architect_verdict_queue,
)
from atlas_forge.dispatcher.dispatch_queue_worker import DispatchQueueWorker


# ---------------------------------------------------------------------------
# Helpers — construcción de un backlog sintético con US en IN_REVIEW.
# ---------------------------------------------------------------------------


def _write_story(backlog: Path, story_id: str, state: str = "IN_REVIEW") -> Path:
    stories_dir = backlog / "user-stories"
    stories_dir.mkdir(parents=True, exist_ok=True)
    path = stories_dir / f"{story_id}-titulo.md"
    path.write_text(
        "---\n"
        f"id: {story_id}\ntype: user-story\ntitle: Titulo\nstate: {state}\n"
        "dependencies: []\nepic: AF-999\n"
        "---\n\n"
        f"# {story_id}\n\n## Contexto\n\nC.\n",
        encoding="utf-8",
    )
    return path


def _write_task(backlog: Path, task_id: str, us_id: str, state: str = "DONE") -> None:
    tasks_dir = backlog / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    (tasks_dir / f"{task_id}.md").write_text(
        "---\n"
        f"id: {task_id}\ntype: task\ntitle: Task\nstate: {state}\n"
        f"dependencies: []\nepic: AF-999\nuser_story: {us_id}\n"
        "---\n\n"
        f"# {task_id}\n\n## Objetivo\n\nObjetivo.\n",
        encoding="utf-8",
    )


def _build_backlog(tmp_path: Path, story_ids: list[str]) -> Path:
    """Crea `tmp_path/02-backlog` con una US por cada `story_ids`, todas en
    IN_REVIEW, cada una con su Task DONE (para que `derive_user_story_state`
    no contradiga el IN_REVIEW explícito). Devuelve la ruta del backlog."""
    backlog = tmp_path / "02-backlog"
    for i, sid in enumerate(story_ids, start=1):
        _write_story(backlog, sid)
        _write_task(backlog, f"T-AF999-US{i:02d}-01", sid, "DONE")
    return backlog


# ---------------------------------------------------------------------------
# save / load
# ---------------------------------------------------------------------------


def test_save_creates_file_and_directory_in_state_dir(tmp_path: Path) -> None:
    project_root = tmp_path / "proj"
    path = save_architect_verdict_queue(
        project_root, "proj", pending=["US-AF999-01"], inflight=None
    )
    assert path.is_file()
    assert path == (
        project_root / ".claude" / "state" / "proj" / "architect_verdict_queue.json"
    )


def test_save_load_round_trip_preserves_pending_order_and_inflight(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "proj"
    pending = ["US-AF999-02", "US-AF999-03"]
    save_architect_verdict_queue(
        project_root, "proj", pending=pending, inflight="US-AF999-01"
    )

    loaded = load_architect_verdict_queue(project_root, "proj")
    assert loaded == {"pending": pending, "inflight": "US-AF999-01"}


def test_load_returns_empty_queue_when_file_does_not_exist(tmp_path: Path) -> None:
    assert load_architect_verdict_queue(tmp_path / "never", "proj") == {
        "pending": [],
        "inflight": None,
    }


def test_load_tolerates_corrupt_file(tmp_path: Path) -> None:
    project_root = tmp_path / "proj"
    path = architect_verdict_queue_path(project_root, "proj")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{esto no es json valido", encoding="utf-8")

    assert load_architect_verdict_queue(project_root, "proj") == {
        "pending": [],
        "inflight": None,
    }


def test_save_write_is_atomic_and_single_json_object(tmp_path: Path) -> None:
    project_root = tmp_path / "proj"
    save_architect_verdict_queue(
        project_root, "proj", pending=["US-AF999-01"], inflight=None
    )
    data = json.loads(
        architect_verdict_queue_path(project_root, "proj").read_text(encoding="utf-8")
    )
    assert data == {"pending": ["US-AF999-01"], "inflight": None}


# ---------------------------------------------------------------------------
# reconcile
# ---------------------------------------------------------------------------


def test_reconcile_with_empty_stored_keeps_all_in_review_in_order(
    tmp_path: Path,
) -> None:
    """Criterio 1: al arrancar sin estado persistido, toda US IN_REVIEW del
    backlog queda pendiente de veredicto (ninguna se pierde)."""
    project_root = tmp_path / "proj"
    backlog = _build_backlog(tmp_path, ["US-AF999-03", "US-AF999-01", "US-AF999-02"])

    state = reconcile_architect_verdict_queue(project_root, "proj", backlog)

    assert state["inflight"] is None
    assert state["pending"] == ["US-AF999-01", "US-AF999-02", "US-AF999-03"]
    # El estado reconciliado queda persistido.
    assert load_architect_verdict_queue(project_root, "proj") == state


def test_reconcile_preserves_persisted_pending_order_and_adds_new(
    tmp_path: Path,
) -> None:
    """Criterio 1: el orden FIFO persistido se conserva para las US que
    siguen IN_REVIEW, y una US promovida mientras el proceso estaba caído se
    añade al final."""
    project_root = tmp_path / "proj"
    backlog = _build_backlog(
        tmp_path, ["US-AF999-01", "US-AF999-02", "US-AF999-03"]
    )
    save_architect_verdict_queue(
        project_root, "proj",
        pending=["US-AF999-02", "US-AF999-03"], inflight=None,
    )
    # US-AF999-01 llegó a IN_REVIEW después de la última persistencia.

    state = reconcile_architect_verdict_queue(project_root, "proj", backlog)

    assert state["pending"] == ["US-AF999-02", "US-AF999-03", "US-AF999-01"]


def test_reconcile_drops_pending_stories_that_left_in_review(tmp_path: Path) -> None:
    """Una US en `pending` que ya pasó a DONE se descarta (no se re-revisa)."""
    project_root = tmp_path / "proj"
    backlog = _build_backlog(tmp_path, ["US-AF999-02", "US-AF999-03"])
    save_architect_verdict_queue(
        project_root, "proj",
        pending=["US-AF999-01", "US-AF999-02"], inflight=None,
    )
    # US-AF999-01 ya no existe / ya no está IN_REVIEW.

    state = reconcile_architect_verdict_queue(project_root, "proj", backlog)

    # US-AF999-01 (ya no IN_REVIEW) se descarta; US-AF999-02 y US-AF999-03
    # siguen IN_REVIEW y quedan pendientes.
    assert "US-AF999-01" not in state["pending"]
    assert state["pending"] == ["US-AF999-02", "US-AF999-03"]


def test_reconcile_re_enqueues_the_inflight_story_first(tmp_path: Path) -> None:
    """Criterio 2: una US en vuelo persistida que sigue IN_REVIEW vuelve a
    quedar pendiente (al frente de la cola) y deja de estar en vuelo — el
    Job no puede reanudarse tras el reinicio, pero la US nunca queda
    bloqueada ni incoherente."""
    project_root = tmp_path / "proj"
    backlog = _build_backlog(
        tmp_path, ["US-AF999-01", "US-AF999-02", "US-AF999-03"]
    )
    save_architect_verdict_queue(
        project_root, "proj",
        pending=["US-AF999-02", "US-AF999-03"], inflight="US-AF999-01",
    )

    state = reconcile_architect_verdict_queue(project_root, "proj", backlog)

    assert state["inflight"] is None
    # La US en vuelo vuelve al frente para ser re-despachada primero.
    assert state["pending"] == ["US-AF999-01", "US-AF999-02", "US-AF999-03"]


def test_reconcile_drops_inflight_story_that_is_no_longer_in_review(
    tmp_path: Path,
) -> None:
    """Una US en vuelo que ya pasó a DONE (veredicto aplicado justo antes
    del reinicio) no se re-encola."""
    project_root = tmp_path / "proj"
    backlog = _build_backlog(tmp_path, ["US-AF999-02"])
    _write_story(backlog, "US-AF999-01", state="DONE")
    save_architect_verdict_queue(
        project_root, "proj", pending=["US-AF999-02"], inflight="US-AF999-01",
    )

    state = reconcile_architect_verdict_queue(project_root, "proj", backlog)

    assert state["inflight"] is None
    assert state["pending"] == ["US-AF999-02"]


# ---------------------------------------------------------------------------
# Simulación de reinicio completa (criterios 1 y 2)
# ---------------------------------------------------------------------------


def test_restart_recovers_all_stories_no_loss(tmp_path: Path) -> None:
    """Criterio 1: con varias US IN_REVIEW esperando veredicto (y varias más
    en cola), un reinicio no pierde ninguna: todas se retoman tras el arranque
    en orden."""
    project_root = tmp_path / "proj"
    backlog = _build_backlog(
        tmp_path,
        ["US-AF999-01", "US-AF999-02", "US-AF999-03", "US-AF999-04", "US-AF999-05"],
    )
    # Antes del "reinicio": US-AF999-01 en vuelo, el resto en cola.
    save_architect_verdict_queue(
        project_root, "proj",
        pending=["US-AF999-02", "US-AF999-03", "US-AF999-04", "US-AF999-05"],
        inflight="US-AF999-01",
    )

    # "Reinicio": se arranca de nuevo (reconcile) con un backlog idéntico.
    state = reconcile_architect_verdict_queue(project_root, "proj", backlog)

    assert set(state["pending"]) == {
        "US-AF999-01", "US-AF999-02", "US-AF999-03", "US-AF999-04", "US-AF999-05"
    }
    assert len(state["pending"]) == 5  # ninguna perdida


def test_restart_re_enqueues_inflight_story_for_re_dispatch(tmp_path: Path) -> None:
    """Criterio 2: un veredicto en vuelo en el momento del reinicio hace que
    la US vuelva a quedar pendiente de revisión (nunca bloqueada)."""
    project_root = tmp_path / "proj"
    backlog = _build_backlog(tmp_path, ["US-AF999-01", "US-AF999-02"])
    save_architect_verdict_queue(
        project_root, "proj", pending=["US-AF999-02"], inflight="US-AF999-01",
    )

    state = reconcile_architect_verdict_queue(project_root, "proj", backlog)

    # Al frente de la cola pendiente, lista para que el ciclo la re-despache.
    assert state["pending"][0] == "US-AF999-01"
    assert state["inflight"] is None


# ---------------------------------------------------------------------------
# Integración con DispatchQueueWorker (persistencia sin tmux)
# ---------------------------------------------------------------------------


def test_worker_start_restores_and_persists_reconciled_state(tmp_path: Path) -> None:
    """El arranque del worker (que es lo que hace `atlas-forge-api` al
    levantar) restaura la cola desde disco y deja el estado reconciliado
    persistido."""
    from atlas_forge.core.session_lifecycle import activate
    from atlas_forge.models import DevelopmentSession

    project_root = tmp_path / "proj"
    backlog = _build_backlog(project_root, ["US-AF999-01", "US-AF999-02"])
    save_architect_verdict_queue(
        project_root, "proj", pending=["US-AF999-02"], inflight="US-AF999-01",
    )

    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    worker = DispatchQueueWorker(project_root, "proj", session)
    try:
        worker.start()
        # Tras arrancar, el estado persistido ya está reconciliado: la US en
        # vuelo volvió a pending.
        state = load_architect_verdict_queue(project_root, "proj")
        assert state["inflight"] is None
        assert set(state["pending"]) == {"US-AF999-01", "US-AF999-02"}
    finally:
        worker.stop()


def test_worker_persists_pending_state_even_without_architect(tmp_path: Path) -> None:
    """El worker persiste el estado corriente de la cola tras cada ciclo de
    veredicto (sin arquitecto, no despacha nada pero `pending` queda en
    disco)."""
    from atlas_forge.core.session_lifecycle import activate
    from atlas_forge.models import DevelopmentSession

    project_root = tmp_path / "proj"
    backlog = _build_backlog(project_root, ["US-AF999-01", "US-AF999-02"])

    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    worker = DispatchQueueWorker(project_root, "proj", session)
    try:
        worker.start()
        result = worker.run_architect_verdict_once()
        assert result is None  # sin arquitecto no despacha
        state = load_architect_verdict_queue(project_root, "proj")
        assert state["inflight"] is None
        assert state["pending"] == ["US-AF999-01", "US-AF999-02"]
    finally:
        worker.stop()