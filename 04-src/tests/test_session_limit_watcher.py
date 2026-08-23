"""Test de integración real (T-AF024-US21-01, criterio de aceptación
explícito: "simular un pane con el patrón de límite y hora ya pasada,
confirmar que el siguiente ciclo del watcher hace el ping"):
`atlas_forge.agents.session_limit_watcher.run_session_limit_cycle` contra una
sesión tmux real (sin runtime real de Claude Code — mismo patrón de
aislamiento ya usado por `test_agent_liveness.py`/
`test_dispatch_queue_worker.py`: `DEFAULT_CLAUDE_CODE_COMMAND` parcheado a
un binario real inofensivo)."""

import uuid
from datetime import datetime, timedelta, timezone

import libtmux
import pytest

from atlas_forge.agents.launch import launch_agent
from atlas_forge.agents.session_limit_watcher import PING_MESSAGE, run_session_limit_cycle
from atlas_forge.core.session_lifecycle import activate
from atlas_forge.models import DevelopmentSession
from atlas_forge.tmux.manager import capture_pane_lines, run_command


@pytest.fixture(autouse=True)
def _no_real_runtime(monkeypatch):
    """Mismo patrón de aislamiento que `test_agent_liveness.py`: nunca
    invocar el binario real de Claude Code en tests. `sleep 300` deja la
    sesión viva el tiempo suficiente para todo el test sin terminar sola."""
    import atlas_forge.runtime.claude_code as claude_code_module
    import atlas_forge.runtime.opencode as opencode_module

    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_COMMAND", "sleep")
    monkeypatch.setattr(claude_code_module, "DEFAULT_CLAUDE_CODE_ARGS", ["300"])
    monkeypatch.setattr(opencode_module, "DEFAULT_OPENCODE_COMMAND", "sleep")
    monkeypatch.setattr(opencode_module, "DEFAULT_OPENCODE_ARGS", ["300"])


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


def _active_session() -> DevelopmentSession:
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    return session


def _write_pane_text(session_name: str, text: str, socket_name: str) -> None:
    # `printf` en vez de `echo`: evita cualquier ambigüedad de expansión
    # de `·`/paréntesis por el shell — el texto viaja como un único
    # argumento literal, tal como lo haría Claude Code imprimiéndolo por
    # su cuenta en el pane.
    run_command(session_name, f"printf '%s\\n' {_shell_quote(text)}", socket_name=socket_name)


def _shell_quote(text: str) -> str:
    return "'" + text.replace("'", "'\\''") + "'"


def test_watcher_marks_agent_limited_when_pane_shows_the_block_pattern(
    isolated_socket: str, tmp_path
) -> None:
    session = _active_session()
    agent, runtime_instance = launch_agent(
        "developer", "claude-code", None, session, str(tmp_path), socket_name=isolated_socket
    )
    assert agent.status == "idle"

    _write_pane_text(
        runtime_instance.session_name,
        "You've hit your session limit · resets 11:59pm (UTC)",
        isolated_socket,
    )

    now = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)  # antes del reset
    pinged = run_session_limit_cycle(session, socket_name=isolated_socket, now=now)

    assert pinged == []
    assert agent.status == "limited"
    assert agent.limited_until is not None
    assert "23:59" in agent.limited_until or "T23:59" in agent.limited_until


def test_watcher_pings_and_clears_status_once_reset_time_plus_margin_has_passed(
    isolated_socket: str, tmp_path
) -> None:
    session = _active_session()
    agent, runtime_instance = launch_agent(
        "developer", "claude-code", None, session, str(tmp_path), socket_name=isolated_socket
    )

    _write_pane_text(
        runtime_instance.session_name,
        "You've hit your session limit · resets 1:30am (UTC)",
        isolated_socket,
    )

    now_before_reset = datetime(2026, 8, 17, 0, 0, tzinfo=timezone.utc)
    run_session_limit_cycle(session, socket_name=isolated_socket, now=now_before_reset)
    assert agent.status == "limited"

    # El texto de límite sigue en el pane (Claude Code real seguiría
    # mostrándolo hasta que el ping lo saque de ese estado) — el watcher
    # debe, aun así, enviar el ping y limpiar el estado una vez pasado el
    # margen, sin esperar a que el patrón desaparezca del pane primero
    # (criterio 5 de la US: el ping se dispara por tiempo transcurrido).
    now_after_margin = datetime(2026, 8, 17, 1, 32, tzinfo=timezone.utc)
    pinged = run_session_limit_cycle(session, socket_name=isolated_socket, now=now_after_margin)

    assert pinged == [agent.id]
    assert agent.status == "idle"
    assert agent.limited_until is None

    # `capture_pane_lines` envuelve por ancho real de terminal — el
    # mensaje puede quedar partido a mitad de palabra entre dos líneas
    # (visto en la práctica: "...ya se ha reiniciado. Co" / "ntinúa con
    # el trabajo..."), así que se compara sin saltos de línea en vez de
    # buscar el string completo tal cual.
    pane_content = "".join(capture_pane_lines(runtime_instance.session_name, socket_name=isolated_socket))
    assert PING_MESSAGE in pane_content


def test_watcher_does_not_ping_before_the_margin_has_passed(
    isolated_socket: str, tmp_path
) -> None:
    session = _active_session()
    agent, runtime_instance = launch_agent(
        "developer", "claude-code", None, session, str(tmp_path), socket_name=isolated_socket
    )

    _write_pane_text(
        runtime_instance.session_name,
        "You've hit your session limit · resets 1:30am (UTC)",
        isolated_socket,
    )

    now_before_reset = datetime(2026, 8, 17, 0, 0, tzinfo=timezone.utc)
    run_session_limit_cycle(session, socket_name=isolated_socket, now=now_before_reset)
    assert agent.status == "limited"

    # Justo en el instante del reset, sin margen todavía — criterio
    # explícito: nunca reintentar en el segundo exacto.
    now_at_reset = datetime(2026, 8, 17, 1, 30, tzinfo=timezone.utc)
    pinged = run_session_limit_cycle(session, socket_name=isolated_socket, now=now_at_reset)

    assert pinged == []
    assert agent.status == "limited"


def test_watcher_clears_status_when_pattern_disappears_without_needing_a_ping(
    isolated_socket: str, tmp_path
) -> None:
    session = _active_session()
    agent, runtime_instance = launch_agent(
        "developer", "claude-code", None, session, str(tmp_path), socket_name=isolated_socket
    )

    _write_pane_text(
        runtime_instance.session_name,
        "You've hit your session limit · resets 1:30am (UTC)",
        isolated_socket,
    )
    now = datetime(2026, 8, 17, 0, 0, tzinfo=timezone.utc)
    run_session_limit_cycle(session, socket_name=isolated_socket, now=now)
    assert agent.status == "limited"

    # El agente recuperó actividad normal por su cuenta (el patrón ya no
    # está en pantalla) — criterio 7: la etiqueta debe desaparecer sin
    # necesitar el ping.
    run_command(runtime_instance.session_name, "clear", socket_name=isolated_socket)
    _write_pane_text(runtime_instance.session_name, "trabajando en T-X...", isolated_socket)

    run_session_limit_cycle(session, socket_name=isolated_socket, now=now)

    assert agent.status == "idle"
    assert agent.limited_until is None


def test_watcher_ignores_the_previous_percentage_warning_variant(
    isolated_socket: str, tmp_path
) -> None:
    session = _active_session()
    agent, runtime_instance = launch_agent(
        "developer", "claude-code", None, session, str(tmp_path), socket_name=isolated_socket
    )

    _write_pane_text(
        runtime_instance.session_name,
        "You've used 92% of your session limit · resets 8am (UTC)",
        isolated_socket,
    )

    run_session_limit_cycle(session, socket_name=isolated_socket, now=datetime(2026, 8, 17, 0, 0, tzinfo=timezone.utc))

    # Decisión de producto explícita: el aviso previo NO transiciona el
    # estado operativo — el agente sigue disponible para el Dispatcher.
    assert agent.status == "idle"
    assert agent.limited_until is None


def test_watcher_skips_agents_with_a_different_runtime_type(isolated_socket: str, tmp_path) -> None:
    session = _active_session()
    agent, runtime_instance = launch_agent(
        "developer", "opencode", None, session, str(tmp_path), socket_name=isolated_socket
    )

    # No debe fallar ni intentar interpretar el pane de un runtime que no
    # es Claude Code (fuera de alcance explícito de la US).
    pinged = run_session_limit_cycle(session, socket_name=isolated_socket, now=datetime(2026, 8, 17, 0, 0, tzinfo=timezone.utc))

    assert pinged == []
    assert agent.status == "idle"
