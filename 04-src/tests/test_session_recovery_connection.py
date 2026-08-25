"""Tests de T-AF003-US02-02 (US-AF003-02 · "Recuperar la sesión de desarrollo
al reabrir Atlas Forge"): la capa de dominio de `session_recovery` queda
CONECTADA a su contexto de uso — el registro de sesiones persiste el snapshot
recuperable al arrancar una sesión y lo recupera al volver a abrir sobre el
mismo proyecto, sin duplicar la lógica de negocio.

Cubre: el store de snapshot (round-trip a disco), la recuperación desde un
snapshot RECUPERABLE (status activo + evento `sesion_recuperada` en el
historial persistido) y el no-recupero desde un snapshot cerrado
(no-recuperable -> sesión de cero).
"""

from __future__ import annotations

from pathlib import Path

from atlas_forge.core.session_recovery import (
    SessionSnapshot,
    serialize_snapshot,
)
from atlas_forge.core.session_registry import _reset_registry_for_tests, focus_project_session
from atlas_forge.storage.session_snapshot_store import (
    load_session_snapshot,
    save_session_snapshot,
    session_snapshot_path,
)


def _project(tmp_path: Path) -> Path:
    p = tmp_path / "workspace" / "project-a"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _snapshot(project_id: str, status: str = "active") -> SessionSnapshot:
    return SessionSnapshot(
        session_id=f"session-{project_id}",
        project_id=project_id,
        status=status,
        created_at="2026-08-24T05:00:00+00:00",
        last_active_at="2026-08-24T05:10:00+00:00",
    )


def test_store_round_trip_persists_snapshot(tmp_path: Path) -> None:
    """El store escribe y lee el snapshot portable del proyecto a disco."""
    project = _project(tmp_path)
    data = {"session_id": "session-x", "project_id": str(project), "status": "active"}

    save_session_snapshot(project, data)

    path = session_snapshot_path(project)
    assert path.is_file()
    assert load_session_snapshot(project) == data


def test_store_returns_none_when_no_snapshot(tmp_path: Path) -> None:
    project = _project(tmp_path)
    assert load_session_snapshot(project) is None


def test_start_session_recovers_persisted_recoverable_snapshot(tmp_path: Path) -> None:
    """Al arrancar una sesión sobre un proyecto con snapshot RECUPERABLE, la
    sesión se reconstruye (activa) y el historial persistido registra el
    evento `sesion_recuperada` — la lógica de dominio es invocada desde el
    contexto de arranque sin duplicarla."""
    _reset_registry_for_tests()
    project = _project(tmp_path)
    save_session_snapshot(project, serialize_snapshot(_snapshot(str(project))))

    session = focus_project_session(str(project))

    assert session.project_id == str(project)
    assert session.status == "active"
    # El evento de recuperación quedó registrado en el snapshot persistido.
    data = load_session_snapshot(project)
    events = [e["event"] for e in data["activity"]]
    assert "sesion_recuperada" in events


def test_start_session_ignores_closed_non_recoverable_snapshot(tmp_path: Path) -> None:
    """Un snapshot de sesión CERRADA (no-recuperable) no se recupera: se
    arranca una sesión de cero y el historial persistido no registra
    `sesion_recuperada`."""
    _reset_registry_for_tests()
    project = _project(tmp_path)
    save_session_snapshot(project, serialize_snapshot(_snapshot(str(project), status="closed")))

    session = focus_project_session(str(project))

    assert session.project_id == str(project)
    assert session.status == "active"  # sesión nueva, no recuperada
    data = load_session_snapshot(project)
    events = [e["event"] for e in data["activity"]]
    assert "sesion_recuperada" not in events