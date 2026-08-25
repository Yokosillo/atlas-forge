"""Tests end-to-end deterministas de la reconciliación automática
(T-AF022-US18-05, US-AF022-18 criterio 2): el escenario del caso real
2026-08-20 —

    T-AF023-US03-01 IN_PROGRESS huérfana (sin entrada en `dispatch_queue.json`
    ni reporte en vuelo) → la reconciliación automática la revierte → deja de
    bloquear la cadena y el despacho puede retomarla; mismo flujo para
    T-AF005-US01-09 → T-AF024-US11-16.

Cubre además el criterio "la reconciliación se ejecuta en runtime sin
reiniciar el worker" (`run_reconciliation_once` de `DispatchQueueWorker`) y
que `_pick_next_eligible_task_id` vuelve a elegir la Task revertida cuando la
preferencia de reencolado automático está activa. Determinista, sin tmux."""
from __future__ import annotations

from pathlib import Path

from atlas_forge.backlog.parser import load_backlog
from atlas_forge.core.session_lifecycle import activate
from atlas_forge.dispatcher.dispatch_queue import (
    reconcile_orphaned_in_progress_tasks,
)
from atlas_forge.dispatcher.dispatch_queue_worker import (
    DispatchQueueWorker,
    _pick_next_eligible_task_id,
)
from atlas_forge.models import DevelopmentSession


def _write_task_deps(tasks_dir: Path, task_id: str, state: str, deps: list[str]) -> Path:
    tasks_dir.mkdir(parents=True, exist_ok=True)
    dep_section = (
        "dependencies:\n" + "".join(f"  - {d}\n" for d in deps)
        if deps else "dependencies: []\n"
    )
    target = tasks_dir / f"{task_id}.md"
    target.write_text(
        "---\n"
        f"id: {task_id}\ntype: task\ntitle: Task\nstate: {state}\n"
        f"{dep_section}"
        f"epic: AF-023\nuser_story: US-AF023-03\npriority: Alta\n"
        "---\n\n"
        f"# {task_id}\n\n## Objetivo\n\nObjetivo.\n\n## Criterios de aceptación\n\n1. Y.\n",
        encoding="utf-8",
    )
    return target


def _seed_real_scenario(backlog: Path) -> tuple[Path, Path]:
    """El caso real: T-AF023-US03-01 IN_PROGRESS huérfana (sin entrada ni
    reporte) y T-AF023-US03-02 TO_DEVELOP que depende de US03-01 (bloqueada
    mientras US03-01 no esté DONE)."""
    us03_01 = _write_task_deps(backlog / "tasks", "T-AF023-US03-01", "IN_PROGRESS", [])
    us03_02 = _write_task_deps(
        backlog / "tasks", "T-AF023-US03-02", "TO_DEVELOP", ["T-AF023-US03-01"]
    )
    return us03_01, us03_02


def _read_state(path: Path) -> str:
    import re

    text = path.read_text(encoding="utf-8")
    match = re.search(r"^state:\s*(\S+)$", text, re.MULTILINE)
    return match.group(1) if match else ""


def _write_state(path: Path, state: str) -> None:
    import re

    text = path.read_text(encoding="utf-8")
    updated, n = re.subn(r"^state:\s*\S+$", f"state: {state}", text, count=1, flags=re.MULTILINE)
    if n == 0:
        raise AssertionError(f"No se pudo reescribir el estado de {path.name}")
    path.write_text(updated, encoding="utf-8")


def _next_eligible(backlog: Path, entries, done_ids, deps) -> str | None:
    graph = load_backlog(backlog)
    return _pick_next_eligible_task_id(graph, entries, done_ids, deps)


def test_caso_real_af023_huerfana_se_revierte_y_la_siguiente_se_elige(tmp_path) -> None:
    """Escenario del caso real: con la preferencia de reencolado automático
    activa, la huérfana T-AF023-US03-01 vuelve a TO_DEVELOP (reintentable) y
    `_pick_next_eligible_task_id` la vuelve a elegir — deja de estar colgada
    en IN_PROGRESS y la cadena (incluida T-AF023-US03-02) deja de estar
    congelada."""
    project_root = tmp_path / "rep"
    backlog = project_root / "02-backlog"
    us03_01, _us03_02 = _seed_real_scenario(backlog)

    # Antes de reconciliar: ninguno de los dos es elegible (US03-01 IN_PROGRESS
    # no es TO_DEVELOP; US03-02 tiene su dependencia no DONE).
    graph0 = load_backlog(backlog)
    assert _pick_next_eligible_task_id(
        graph0, [], set(), dict(graph0.dependencies_of)
    ) is None

    # La reconciliación automática revierte la huérfana (runtime, sin reinicio).
    reconciled = reconcile_orphaned_in_progress_tasks(
        project_root, "proj", backlog, auto_reenqueue_orphaned=True
    )
    assert reconciled == ["T-AF023-US03-01"]
    assert _read_state(us03_01) == "TO_DEVELOP"

    # El despacho la retoma: ahora US03-01 es la candidata elegible.
    graph = load_backlog(backlog)
    picked = _pick_next_eligible_task_id(
        graph, [], set(), dict(graph.dependencies_of)
    )
    assert picked == "T-AF023-US03-01"


def test_caso_real_af005_preferencia_default_revierte_a_ready(tmp_path) -> None:
    """Segundo caso real (T-AF005-US01-09 → T-AF024-US11-16), con la
    preferencia por defecto (sin auto-reencolado): la huérfana T-AF005-US01-09
    vuelve a READY — sale de IN_PROGRESS perpetuo y requiere humano — y la
    cadena deja de estar congelada (no queda bloqueando agentes forever)."""
    project_root = tmp_path / "rep"
    backlog = project_root / "02-backlog"
    us01_09 = _write_task_deps(backlog / "tasks", "T-AF005-US01-09", "IN_PROGRESS", [])
    _write_task_deps(
        backlog / "tasks", "T-AF024-US11-16", "TO_DEVELOP", ["T-AF005-US01-09"]
    )

    reconciled = reconcile_orphaned_in_progress_tasks(project_root, "proj", backlog)

    assert reconciled == ["T-AF005-US01-09"]
    assert _read_state(us01_09) == "READY"
    # Logueda (reconciliation_log.jsonl registra la huérfana reconciliada).
    from atlas_forge.core.reconciliation_log import reconciliation_log_path

    log_text = reconciliation_log_path(project_root, "proj").read_text(encoding="utf-8")
    assert "T-AF005-US01-09" in log_text
    assert "dispatched_orphan_reconciled" in log_text


def test_caso_real_af023_cadena_se_desbloquea_us03_02_eligble(tmp_path) -> None:
    """T-AF022-US18-05 (escenario completo): tras reconciliar la huérfana
    T-AF023-US03-01 y completarla (simulado), T-AF023-US03-02 (que depende
    de US03-01) deja de estar bloqueada y pasa a ser elegible para el
    despacho — el desbloqueo de la cadena completa, no solo el primer
    eslabón."""
    project_root = tmp_path / "rep"
    backlog = project_root / "02-backlog"
    us03_01, us03_02 = _seed_real_scenario(backlog)

    # Antes del arreglo: US03-01 IN_PROGRESS huérfana (no elegible) y
    # US03-02 bloqueada por su dependencia no DONE.
    graph0 = load_backlog(backlog)
    assert _pick_next_eligible_task_id(
        graph0, [], set(), dict(graph0.dependencies_of)
    ) is None

    # 1. La reconciliación automática revierte la huérfana.
    reconciled = reconcile_orphaned_in_progress_tasks(
        project_root, "proj", backlog, auto_reenqueue_orphaned=True
    )
    assert reconciled == ["T-AF023-US03-01"]
    assert _read_state(us03_01) == "TO_DEVELOP"

    # 2. US03-01 se despacha y se completa (DONE, simulado por el cierre).
    _write_state(us03_01, "DONE")

    # 3. US03-02 (dependía de US03-01) deja de estar bloqueada: la cola de
    #    despacho la retoma como siguiente candidata elegible.
    graph = load_backlog(backlog)
    picked = _pick_next_eligible_task_id(
        graph, [], {"T-AF023-US03-01"}, dict(graph.dependencies_of)
    )
    assert picked == "T-AF023-US03-02"


def test_caso_real_periodic_worker_reverts_without_restart(tmp_path) -> None:
    """La reconciliación periódica del worker (`run_reconciliation_once`)
    revierte la huérfana en runtime — sin reiniciar el worker — y no rompe el
    despacho (buen esfuerzo, no lanza)."""
    project_root = tmp_path / "rep"
    backlog = project_root / "02-backlog"
    us03_01, _ = _seed_real_scenario(backlog)

    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    worker = DispatchQueueWorker(project_root, "proj", session)

    # El ciclo periódico no debe lanzar ni romper el resto de la reconciliación.
    worker.run_reconciliation_once()

    # La huérfana fue tocada por el ciclo: ya no está IN_PROGRESS perpetuo.
    assert _read_state(us03_01) in ("READY", "TO_DEVELOP")