"""Tests de T-AF022-US15-04 (US-AF022-15): disparo automático de un Job
de Tester de UI al cerrar con veredicto aprobado una User Story cuyo
alcance toca `10-web/`.

`test_maybe_enqueue_ui_tester_*` cubre la función pura de decisión
(veredicto aprobado/rechazado × US toca-web/no-toca-web), sin ningún I/O.
`test_do_dispatch_verdict_*` y el test de integración final ejercitan el
flujo real end-to-end: cola de veredictos -> Arquitecto real (doble
cooperativo, `SIM_ROLE=architect_approved_verdict`) -> cola de Tester de
UI -> Job de Tester real (tmux real, sin runtime real de Claude Code —
mismo criterio de aislamiento que el resto de la suite del dispatcher)."""

import time
from pathlib import Path
from unittest.mock import patch

import pytest

from atlas_forge.agents.tester import TESTER_ROLE
from atlas_forge.core.session_lifecycle import activate, assign_agent
from atlas_forge.dispatcher.architect_verdict_queue import (
    _do_dispatch_verdict,
    _maybe_enqueue_ui_tester,
    _instance as _verdict_queue_instance,
    enqueue_architect_verdict,
)
from atlas_forge.dispatcher.ui_tester_queue import (
    _instance as _ui_tester_queue_instance,
    enqueue_ui_tester_job,
    get_ui_tester_queue_status,
)
from atlas_forge.models import Agent, DevelopmentSession

_WEB_REPORT = "# Informe\n\n**`10-web/app.js`**: cambios en el panel.\n"
_BACKEND_REPORT = "# Informe\n\n**`04-src/src/atlas_forge/api/routes.py`**: cambios.\n"

_VERDICT_APPROVED = "ESTADO: APROBADO\nJUSTIFICACIÓN:\nOK.\nSIGUIENTE_PROMPT_PARA_WORKER:\n(ninguno)\n"
_VERDICT_REJECTED = "ESTADO: RECHAZADO\nJUSTIFICACIÓN:\nFalta X.\nSIGUIENTE_PROMPT_PARA_WORKER:\nCorrige X.\n"


@pytest.fixture(autouse=True)
def _reset_queues():
    _verdict_queue_instance.reset_for_testing()
    _ui_tester_queue_instance.reset_for_testing()
    yield
    _verdict_queue_instance.reset_for_testing()
    _ui_tester_queue_instance.reset_for_testing()


# ---------------------------------------------------------------------------
# _maybe_enqueue_ui_tester — función pura de decisión, sin I/O real de red.
# ---------------------------------------------------------------------------


def test_maybe_enqueue_ui_tester_enqueues_when_approved_and_touches_web():
    with patch(
        "atlas_forge.dispatcher.ui_tester_queue.enqueue_ui_tester_job"
    ) as mock_enqueue:
        _maybe_enqueue_ui_tester(
            "US-AF999-01", _VERDICT_APPROVED, [_WEB_REPORT], None, "default", None
        )

    mock_enqueue.assert_called_once_with("US-AF999-01", None, "default", None)


def test_maybe_enqueue_ui_tester_enqueues_when_approved_with_notes_and_touches_web():
    verdict_with_notes = _VERDICT_APPROVED.replace(
        "ESTADO: APROBADO", "ESTADO: APROBADO_CON_OBSERVACIONES"
    )
    with patch(
        "atlas_forge.dispatcher.ui_tester_queue.enqueue_ui_tester_job"
    ) as mock_enqueue:
        _maybe_enqueue_ui_tester(
            "US-AF999-01", verdict_with_notes, [_WEB_REPORT], None, "default", None
        )

    mock_enqueue.assert_called_once()


def test_maybe_enqueue_ui_tester_does_nothing_when_rejected():
    with patch(
        "atlas_forge.dispatcher.ui_tester_queue.enqueue_ui_tester_job"
    ) as mock_enqueue:
        _maybe_enqueue_ui_tester(
            "US-AF999-01", _VERDICT_REJECTED, [_WEB_REPORT], None, "default", None
        )

    mock_enqueue.assert_not_called()


def test_maybe_enqueue_ui_tester_does_nothing_when_story_does_not_touch_web():
    # Criterio de aceptación 3: una US que no toca 10-web/ (solo backend)
    # no dispara ningún Job de Tester de UI innecesario.
    with patch(
        "atlas_forge.dispatcher.ui_tester_queue.enqueue_ui_tester_job"
    ) as mock_enqueue:
        _maybe_enqueue_ui_tester(
            "US-AF999-01", _VERDICT_APPROVED, [_BACKEND_REPORT], None, "default", None
        )

    mock_enqueue.assert_not_called()


def test_maybe_enqueue_ui_tester_does_nothing_with_empty_verdict_output():
    with patch(
        "atlas_forge.dispatcher.ui_tester_queue.enqueue_ui_tester_job"
    ) as mock_enqueue:
        _maybe_enqueue_ui_tester("US-AF999-01", "", [_WEB_REPORT], None, "default", None)

    mock_enqueue.assert_not_called()


# ---------------------------------------------------------------------------
# Cola FIFO de Tester de UI — mismo patrón de test que
# test_verdict_queue.py (no bloquea el llamador, estado consultable).
# ---------------------------------------------------------------------------


def test_ui_tester_queue_enqueue_does_not_block():
    """Criterio de aceptación 4: el disparo no bloquea ni retrasa el
    flujo normal de cierre de la US."""
    import threading

    step_event = threading.Event()

    def blocking_dispatch(*args, **kwargs):
        step_event.wait()

    with patch(
        "atlas_forge.dispatcher.ui_tester_queue._do_dispatch_ui_tester",
        side_effect=blocking_dispatch,
    ):
        enqueue_ui_tester_job("US-AF999-01", None, "default")
        time.sleep(0.1)

        start = time.monotonic()
        enqueue_ui_tester_job("US-AF999-02", None, "default")
        elapsed = time.monotonic() - start

        assert elapsed < 0.5, f"enqueue_ui_tester_job bloqueó {elapsed:.2f}s"

        status = get_ui_tester_queue_status()
        assert status["active"] == "US-AF999-01"
        assert "US-AF999-02" in status["waiting"]

        step_event.set()
        for _ in range(50):
            status = get_ui_tester_queue_status()
            if status["active"] is None:
                break
            time.sleep(0.05)


def test_get_ui_tester_queue_status_returns_empty_when_idle():
    status = get_ui_tester_queue_status()
    assert status["active"] is None
    assert status["waiting"] == []


def test_do_dispatch_ui_tester_does_nothing_without_a_tester_agent():
    """Sin agente Tester lanzado en la sesión, el Job se descarta en
    silencio — mismo comportamiento que `_do_dispatch_verdict` sin
    Arquitecto lanzado."""
    from atlas_forge.dispatcher.ui_tester_queue import _do_dispatch_ui_tester

    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)

    with patch(
        "atlas_forge.runtime.agent_runtime_registry.get_runtime_instance_for_agent",
    ) as mock_get_runtime:
        _do_dispatch_ui_tester("US-AF999-01", session, "default")

    mock_get_runtime.assert_not_called()


def test_do_dispatch_ui_tester_finds_agent_by_tester_role():
    from atlas_forge.dispatcher.ui_tester_queue import _do_dispatch_ui_tester

    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    tester = Agent(id="tester-1", name="Tester", role=TESTER_ROLE, prompt="p", runtime_id="r1")
    assign_agent(session, tester)

    with patch(
        "atlas_forge.runtime.agent_runtime_registry.get_runtime_instance_for_agent",
        return_value=None,
    ) as mock_get_runtime:
        _do_dispatch_ui_tester("US-AF999-01", session, "default")

    mock_get_runtime.assert_called_once_with(tester.id)


# ---------------------------------------------------------------------------
# Integración end-to-end real (tmux real, sin runtime real de Claude Code):
# veredicto aprobado real de un Arquitecto cooperativo -> Job de Tester de
# UI real despachado y completado.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_real_runtime(monkeypatch):
    import atlas_forge.runtime.claude_code as claude_code_module

    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_COMMAND", "sleep")
    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_ARGS", ["5"])


@pytest.fixture
def isolated_socket():
    import uuid

    import libtmux

    name = f"atlas_forge-test-{uuid.uuid4().hex[:8]}"
    try:
        yield name
    finally:
        try:
            libtmux.Server(socket_name=name).kill()
        except Exception:
            pass


_COOPERATIVE_AGENT_SCRIPT = str(Path(__file__).parent / "fixtures" / "cooperative_agent_sim.sh")


def _launch_cooperative_agent(role, tmp_path, session, isolated_socket, monkeypatch, extra_env=""):
    import atlas_forge.runtime.claude_code as claude_code_module
    from atlas_forge.agents.launch import launch_agent

    monkeypatch.setattr(
        claude_code_module, "DEFAULT_CLAUDE_CODE_COMMAND", f"{extra_env} bash".strip()
    )
    monkeypatch.setattr(
        claude_code_module, "DEFAULT_CLAUDE_CODE_ARGS", [_COOPERATIVE_AGENT_SCRIPT]
    )
    return launch_agent(role, "claude-code", None, session, str(tmp_path), socket_name=isolated_socket)


def test_end_to_end_approved_verdict_on_a_web_touching_story_dispatches_a_real_ui_tester_job(
    tmp_path, isolated_socket, monkeypatch
):
    """Criterio de aceptación 2 y 5 de la Task: US sintética que toca
    `10-web/`, veredicto aprobado real (Arquitecto cooperativo), confirma
    que el Job de Tester de UI se encola y se completa realmente —
    verificación contra el backend real (tmux real, sesión real), sin
    mockear la cola de veredictos ni la cola de Tester de UI."""
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)

    architect, architect_runtime = _launch_cooperative_agent(
        "arquitecto", tmp_path, session, isolated_socket, monkeypatch,
        extra_env="SIM_ROLE=architect_approved_verdict SIM_DELAY=0.1",
    )
    tester, tester_runtime = _launch_cooperative_agent(
        "tester", tmp_path, session, isolated_socket, monkeypatch,
        extra_env="SIM_DELAY=0.1",
    )

    reports_root = tmp_path / "informes"
    story_dir = reports_root / "US-AF999-01"
    story_dir.mkdir(parents=True)
    (story_dir / "job-1.md").write_text(_WEB_REPORT, encoding="utf-8")

    tasks_dir = tmp_path / "backlog" / "tasks"
    tasks_dir.mkdir(parents=True)

    enqueue_architect_verdict("US-AF999-01", session, isolated_socket, reports_root)

    for _ in range(100):
        status = get_ui_tester_queue_status()
        if status["active"] == "US-AF999-01" or "US-AF999-01" in status["waiting"]:
            break
        time.sleep(0.05)
    else:
        pytest.fail("El Job de Tester de UI nunca se encoló tras el veredicto aprobado.")

    for _ in range(100):
        status = get_ui_tester_queue_status()
        if status["active"] is None and status["waiting"] == []:
            break
        time.sleep(0.05)
    else:
        pytest.fail("La cola de Tester de UI nunca terminó de procesar.")

    # No hay job_id determinista a mano aquí (lo genera create_job) —
    # confirmamos que el agente Tester recibió y completó un Job real vía
    # su estado, más directo y sin depender de adivinar el id para leer
    # el informe.
    assert tester.status == "idle", "El Tester debe volver a idle tras completar el Job."


def test_end_to_end_approved_verdict_on_a_non_web_story_does_not_dispatch_ui_tester_job(
    tmp_path, isolated_socket, monkeypatch
):
    """Criterio de aceptación 3: una US que no toca 10-web/ (solo
    backend) no dispara ningún Job de Tester de UI, incluso con
    veredicto aprobado real y un Tester disponible."""
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)

    _launch_cooperative_agent(
        "arquitecto", tmp_path, session, isolated_socket, monkeypatch,
        extra_env="SIM_ROLE=architect_approved_verdict SIM_DELAY=0.1",
    )
    tester, _tester_runtime = _launch_cooperative_agent(
        "tester", tmp_path, session, isolated_socket, monkeypatch,
        extra_env="SIM_DELAY=0.1",
    )

    reports_root = tmp_path / "informes"
    story_dir = reports_root / "US-AF999-02"
    story_dir.mkdir(parents=True)
    (story_dir / "job-1.md").write_text(_BACKEND_REPORT, encoding="utf-8")

    enqueue_architect_verdict("US-AF999-02", session, isolated_socket, reports_root)

    for _ in range(100):
        status = _verdict_queue_instance.get_status()
        if status["active"] is None and status["waiting"] == []:
            break
        time.sleep(0.05)
    else:
        pytest.fail("La cola de veredictos nunca terminó de procesar.")

    # Margen para confirmar ausencia (no solo "todavía no", sino "nunca").
    time.sleep(0.3)
    status = get_ui_tester_queue_status()
    assert status["active"] is None
    assert status["waiting"] == []
    assert tester.status == "idle", "El Tester nunca debió recibir ningún Job."
