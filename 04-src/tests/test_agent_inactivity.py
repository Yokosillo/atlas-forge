"""Tests de T-AF023-US01-01: detección determinista de inactividad (cuelgue)
de un agente a partir de una secuencia de timestamps y un umbral configurable
— capa de dominio pura, sin infraestructura externa."""

from atlas_forge.agents.inactivity import (
    DEFAULT_INACTIVITY_THRESHOLD_SECONDS,
    VERDICT_ALIVE,
    VERDICT_HUNG,
    VERDICT_PROCESSING,
    detect_agent_activity,
)

_NOW = 1_000_000.0


def test_recent_activity_is_alive() -> None:
    """Criterio: un agente cuya última actividad es reciente (dentro del
    umbral) se reporta `vivo`."""
    last_activity = [_NOW - 5.0, _NOW - 5.0, _NOW - 5.0]
    assert detect_agent_activity(last_activity, threshold_seconds=120.0, now=_NOW) == VERDICT_ALIVE


def test_no_activity_change_beyond_threshold_is_hung() -> None:
    """Criterio: varias lecturas seguidas sin cambio de la última actividad
    superando el umbral se reporta `colgado`."""
    last_activity = [_NOW - 300.0, _NOW - 300.0, _NOW - 300.0]
    assert detect_agent_activity(last_activity, threshold_seconds=120.0, now=_NOW) == VERDICT_HUNG


def test_spaced_but_real_activity_is_not_hung() -> None:
    """Criterio (sin falsos positivos): un agente con actividad espaciada pero
    real (la última actividad avanzó en la última lectura) se reporta
    `procesando`, nunca `colgado`."""
    last_activity = [_NOW - 500.0, _NOW - 400.0, _NOW - 250.0]
    assert detect_agent_activity(last_activity, threshold_seconds=120.0, now=_NOW) == VERDICT_PROCESSING


def test_not_enough_consecutive_reads_is_processing() -> None:
    """Con una o dos lecturas antiguas sin cambio no se declara aún el cuelgue
    (falta confirmar varias lecturas consecutivas) — `procesando`."""
    last_activity = [_NOW - 500.0, _NOW - 500.0]
    assert detect_agent_activity(last_activity, threshold_seconds=120.0, now=_NOW) == VERDICT_PROCESSING


def test_empty_sequence_is_processing() -> None:
    """Sin datos todavía no se puede declarar un cuelgue."""
    assert detect_agent_activity([], threshold_seconds=120.0, now=_NOW) == VERDICT_PROCESSING


def test_threshold_is_configurable() -> None:
    """Criterio: el umbral es configurable (no hardcodeado) — con un umbral
    muy corto una actividad que con el umbral por defecto sería `vivo` se
    convierte en candidata a `colgado`; con un umbral muy largo la misma
    secuencia antigua sigue `vivo`."""
    recent_but_slow = [_NOW - 60.0, _NOW - 60.0, _NOW - 60.0]
    # Con umbral 30s: actividad a 60s es antigua y sin cambio -> colgado.
    assert detect_agent_activity(recent_but_slow, threshold_seconds=30.0, now=_NOW) == VERDICT_HUNG
    # Con umbral 120s: actividad a 60s es reciente -> vivo.
    assert detect_agent_activity(recent_but_slow, threshold_seconds=120.0, now=_NOW) == VERDICT_ALIVE


def test_default_threshold_is_documented_and_120s() -> None:
    """El umbral por defecto está documentado y vale 120 segundos (sesión de
    origen) — y es invocable sin pasarlo."""
    assert DEFAULT_INACTIVITY_THRESHOLD_SECONDS == 120.0
    # Sin `now` explícito usa time.time(); con actividad muy reciente es vivo.
    import time

    assert detect_agent_activity([time.time()]) == VERDICT_ALIVE


def test_deterministic_with_injected_now() -> None:
    """Criterio: la lógica es pura y determinista — misma entrada + mismo
    `now` produce siempre el mismo veredicto."""
    a = detect_agent_activity([_NOW - 900.0] * 4, threshold_seconds=120.0, now=_NOW)
    b = detect_agent_activity([_NOW - 900.0] * 4, threshold_seconds=120.0, now=_NOW)
    assert a == b == VERDICT_HUNG
