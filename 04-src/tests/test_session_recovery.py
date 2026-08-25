"""Tests deterministas de la lógica central de recuperación de sesión
(T-AF003-US02-01, US-AF003-02) — capa de dominio pura, sin infraestructura
(no usa HTTP, persistencia ni I/O real)."""

from datetime import datetime, timezone

from atlas_forge.core.session_recovery import (
    ActivityEvent,
    AgentSnapshot,
    SessionSnapshot,
    build_session_snapshot,
    deserialize_snapshot,
    is_recoverable,
    serialize_snapshot,
)
from atlas_forge.models import Agent, DevelopmentSession


def _session():
    return DevelopmentSession(
        id="sess-1",
        project_id="project-a",
        status="active",
        agents=[
            Agent(id="a1", name="Arquitecto", role="arquitecto", prompt="", runtime_id="r", persistent=True),
            Agent(id="a2", name="Developer-1", role="developer", prompt="", runtime_id="r", status="idle"),
        ],
    )


def test_build_snapshot_extrae_proyecto_y_agentes_sin_io():
    snap = build_session_snapshot(_session())
    assert snap.session_id == "sess-1"
    assert snap.project_id == "project-a"
    assert snap.status == "active"
    assert len(snap.agents) == 2
    # El Arquitecto es persistente; el Developer no.
    by_id = {a.id: a for a in snap.agents}
    assert by_id["a1"].persistent is True
    assert by_id["a2"].persistent is False
    assert by_id["a2"].role == "developer"


def test_is_recoverable_depende_del_estado():
    active = SessionSnapshot("s", "p", "active", "t0", "t0")
    created = SessionSnapshot("s", "p", "created", "t0", "t0")
    closed = SessionSnapshot("s", "p", "closed", "t0", "t0")
    destroyed = SessionSnapshot("s", "p", "destroyed", "t0", "t0")
    assert active.is_recoverable()
    assert is_recoverable(created)
    assert not closed.is_recoverable()
    assert not is_recoverable(destroyed)


def test_record_activity_anade_evento_y_actualiza_last_active():
    snap = build_session_snapshot(_session())
    updated = snap.record_activity("sesion_recuperada", detail="al reabrir")
    assert len(updated.activity) == 1
    ev = updated.activity[0]
    assert ev.event == "sesion_recuperada"
    assert ev.detail == "al reabrir"
    assert updated.last_active_at != snap.last_active_at or updated.last_active_at == ev.timestamp
    # La original (inmutable) no se modifica.
    assert len(snap.activity) == 0


def test_round_trip_serialize_deserialize_conserva_estado():
    snap = build_session_snapshot(_session()).record_activity("agente_lanzado", detail="a2")
    data = serialize_snapshot(snap)
    restored = deserialize_snapshot(data)
    assert restored.session_id == snap.session_id
    assert restored.project_id == snap.project_id
    assert restored.status == snap.status
    assert restored.last_active_at == snap.last_active_at
    assert [a.id for a in restored.agents] == [a.id for a in snap.agents]
    assert [(e.event, e.detail) for e in restored.activity] == [
        (e.event, e.detail) for e in snap.activity
    ]
    assert restored.is_recoverable()


def test_round_trip_con_sesion_cerrada_no_recuperable():
    snap = SessionSnapshot("s", "p", "closed", "t0", "t0", agents=(AgentSnapshot("a1", "A", "arquitecto", "idle", True),))
    restored = deserialize_snapshot(serialize_snapshot(snap))
    assert not restored.is_recoverable()
    assert restored.agents[0].persistent is True


def test_serialize_es_json_serializable():
    import json

    snap = build_session_snapshot(_session()).record_activity("x")
    payload = json.dumps(serialize_snapshot(snap))  # no debe lanzar
    assert "session_id" in payload


def test_timestamps_iso_utc():
    snap = build_session_snapshot(_session())
    # created_at/last_active_at son ISO con zona horaria.
    datetime.fromisoformat(snap.created_at)
    datetime.fromisoformat(snap.last_active_at)
    # activity event con timestamp ISO.
    ev = snap.record_activity("e", ts="2026-08-24T03:00:00+00:00").activity[0]
    datetime.fromisoformat(ev.timestamp)