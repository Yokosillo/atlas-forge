"""Tests de T-AF037-US02-01: `reconcile_session_agents` ahora devuelve
`(reconciled, ignored)` en vez de solo `reconciled` — `ignored` trae el
motivo de cada sesión tmux que no terminó reenganchada (criterio de
aceptación 2 de `US-AF037-02`). Llama a la función directamente (sin
pasar por `_lifespan`/`TestClient`), tmux real vía `create_session` —
mismo estilo de fixture que `test_session_reconciliation.py`, pero
enfocado en el segundo valor de retorno nuevo, no en qué se reengancha
(eso ya lo cubre ese fichero, sin cambios de comportamiento aquí)."""

import uuid
from pathlib import Path

import libtmux
import pytest

from atlas_forge.core.session_lifecycle import activate
from atlas_forge.core.session_reconciliation import reconcile_session_agents
from atlas_forge.models import DevelopmentSession
from atlas_forge.tmux.manager import create_session


@pytest.fixture
def isolated_socket():
    name = f"atlas_forge-test-{uuid.uuid4().hex[:8]}"
    try:
        yield name
    finally:
        try:
            libtmux.Server(socket_name=name).kill()
        except Exception:
            pass


def _active_session(project_path: Path) -> DevelopmentSession:
    # `assign_agent` (invocado dentro de `reconcile_session_agents` al
    # reenganchar) exige `session.status == "active"` — mismo estado que
    # `resolve_startup_session` ya deja tras `activate()` en el flujo
    # real de `_lifespan`, replicado aquí sin pasar por todo ese camino.
    session = DevelopmentSession(id="s1", project_id=str(project_path))
    activate(session)
    return session


def test_ignored_lists_reason_for_unrecognized_session_name(
    tmp_path: Path, isolated_socket: str
) -> None:
    project_path = tmp_path / "mi-proyecto"
    project_path.mkdir()
    session = _active_session(project_path)

    unrelated = "una-sesion-tmux-cualquiera-ajena"
    create_session(unrelated, str(tmp_path), socket_name=isolated_socket)

    reconciled, ignored = reconcile_session_agents(session, socket_name=isolated_socket)

    assert reconciled == []
    assert ignored == [{"session_name": unrelated, "reason": "nombre_no_reconocido"}]


def test_ignored_lists_reason_for_other_project_session(
    tmp_path: Path, isolated_socket: str
) -> None:
    project_path = tmp_path / "mi-proyecto"
    project_path.mkdir()
    session = _active_session(project_path)

    other_project_session = "arquitecto-otro-proyecto-distinto"
    create_session(other_project_session, str(tmp_path), socket_name=isolated_socket)

    reconciled, ignored = reconcile_session_agents(session, socket_name=isolated_socket)

    assert reconciled == []
    assert ignored == [{"session_name": other_project_session, "reason": "otro_proyecto"}]


def test_reconciled_session_is_not_listed_as_ignored(
    tmp_path: Path, isolated_socket: str
) -> None:
    project_path = tmp_path / "mi-proyecto"
    project_path.mkdir()
    session = _active_session(project_path)

    developer_session_name = f"developer-1-{project_path.name}"
    create_session(developer_session_name, str(tmp_path), socket_name=isolated_socket)

    reconciled, ignored = reconcile_session_agents(session, socket_name=isolated_socket)

    assert len(reconciled) == 1
    assert reconciled[0].name == "Developer-1"
    assert ignored == []


def test_no_sessions_at_all_returns_both_lists_empty(
    tmp_path: Path, isolated_socket: str
) -> None:
    project_path = tmp_path / "mi-proyecto"
    project_path.mkdir()
    session = _active_session(project_path)

    reconciled, ignored = reconcile_session_agents(session, socket_name=isolated_socket)

    assert reconciled == []
    assert ignored == []
