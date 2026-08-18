"""Tests de `brain.agents.session_limit` (T-FB024-US21-01): parseo puro
del patrón textual de límite de sesión de Claude Code, sin ningún I/O —
las dos variantes reales verbatim citadas en la Task/US
(`02-backlog/tasks/T-FB024-US21-01-detectar-limite-de-sesion-y-reintentar.md`)."""

from datetime import datetime, timezone

from brain.agents.session_limit import (
    detect_session_limit_block,
    parse_reset_time,
    should_ping_now,
)

_NOW_MIDNIGHT = datetime(2026, 8, 17, 0, 0, tzinfo=timezone.utc)


def test_detects_total_block_variant_and_parses_reset_time():
    text = "You've hit your session limit · resets 1:30am (UTC)"

    reset_at = detect_session_limit_block(text, now=_NOW_MIDNIGHT)

    assert reset_at is not None
    assert (reset_at.hour, reset_at.minute) == (1, 30)


def test_ignores_the_previous_percentage_warning_variant():
    # Decisión de producto explícita (2026-08-17): el aviso previo NO
    # transiciona el estado operativo del agente — solo el bloqueo total.
    text = "You've used 92% of your session limit · resets 8am (UTC) · /upgrade to keep …"

    reset_at = detect_session_limit_block(text, now=_NOW_MIDNIGHT)

    assert reset_at is None


def test_ignores_pane_text_without_any_session_limit_pattern():
    reset_at = detect_session_limit_block("Working on T-FB001-US01-01...", now=_NOW_MIDNIGHT)

    assert reset_at is None


def test_parses_reset_time_without_minutes():
    text = "You've hit your session limit · resets 8am (UTC)"

    reset_at = detect_session_limit_block(text, now=_NOW_MIDNIGHT)

    assert (reset_at.hour, reset_at.minute) == (8, 0)


def test_resolves_reset_time_already_past_today_as_tomorrow():
    # Visto a las 23:00, "resets 1:30am" ya pasó hoy — debe interpretarse
    # como la ocurrencia de mañana, nunca como si ya hubiera pasado hace
    # horas.
    now = datetime(2026, 8, 17, 23, 0, tzinfo=timezone.utc)
    text = "You've hit your session limit · resets 1:30am (UTC)"

    reset_at = detect_session_limit_block(text, now=now)

    assert reset_at.date().day == 18
    assert (reset_at.hour, reset_at.minute) == (1, 30)


def test_resolves_reset_time_still_in_the_future_today_as_today():
    now = datetime(2026, 8, 17, 0, 0, tzinfo=timezone.utc)
    text = "You've hit your session limit · resets 8am (UTC)"

    reset_at = detect_session_limit_block(text, now=now)

    assert reset_at.date().day == 17


def test_parses_pm_hour_correctly():
    text = "You've hit your session limit · resets 3:15pm (UTC)"

    reset_at = detect_session_limit_block(text, now=_NOW_MIDNIGHT)

    assert (reset_at.hour, reset_at.minute) == (15, 15)


def test_parse_reset_time_returns_none_without_match():
    assert parse_reset_time("nada relevante aquí", now=_NOW_MIDNIGHT) is None


def test_should_ping_now_true_once_margin_has_passed():
    reset_at = datetime(2026, 8, 17, 1, 30, tzinfo=timezone.utc)

    # Justo en el instante del reset: todavía no (criterio explícito,
    # margen de 1 minuto).
    assert should_ping_now(reset_at, now=reset_at) is False

    # Pasado el margen de 1 minuto: sí.
    now_after_margin = datetime(2026, 8, 17, 1, 31, tzinfo=timezone.utc)
    assert should_ping_now(reset_at, now=now_after_margin) is True
