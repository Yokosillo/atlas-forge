"""Tests de T-FB018-US02-02: comando `brain backlog-status` y su informe
estructurado (`brain.backlog.report`), sobre `02-backlog/` sintético y sobre
el real de este proyecto 006.

## Estrategia de fixtures

Igual que en T-FB018-US02-01: NINGÚN test usa números del estado actual del
backlog como valor esperado fijo (el backlog cambia constantemente). Los
tests de comportamiento usan un mini-backlog sintético en `tmp_path` con
resultado totalmente controlado. El único test sobre el `02-backlog/` real
es de NATURALEZA ESTRUCTURAL: verifica que la salida humana y la `--json`
del CLI muestran las MISMAS cifras (criterios 1 y 2), comparando ambas con
el informe `build_backlog_report` del propio `02-backlog/` actual — nunca
contra números fijos copiados de la Task.

El criterio 3 (backlog vacío/recién creado → "sin datos", no excepción) se
testea con un directorio `02-backlog/` vacío sintético."""

import json
from pathlib import Path

import pytest

from brain.backlog import (
    BACKLOG_STATUS_NO_DATA_TEXT,
    build_backlog_report,
    format_human_report,
    priority_rank,
    render_json_report,
)
from brain.cli.backlog_status import run_backlog_status

REAL_BACKLOG_PATH = (
    Path(__file__).resolve().parents[1].parent / "02-backlog"
)

_WELL_FORMED_TASK = (
    "# T-FB100-01 · Ejemplo\n\n"
    "**Epic:** FB-100 · Uno\n\n"
    "## Dependencias\n\nNinguna.\n\n"
    "## Estado\n\n"
    "TODO\n\n"
    "## Prioridad\n\n"
    "Alta.\n"
)


def _write(backlog_path: Path, subdir: str, filename: str, content: str) -> Path:
    directory = backlog_path / subdir
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / filename
    target.write_text(content, encoding="utf-8")
    return target


def _synthetic_backlog(tmp_path: Path) -> Path:
    """Mini-backlog sintético controlado por el test:

    - US-FB100-01  DONE, Alta., epic "FB-100 · Uno"
    - T-FB100-01   TODO LISTA (sin deps), Crítica., epic "FB-100 · Uno"
    - T-FB100-02   TODO LISTA (sin deps), Alta., epic "FB-100 · Uno"
    - US-FB101-01  TODO LISTA (sin deps), Baja — opcional., epic "FB-101 · Dos"
    - T-FB101-01   TODO BLOQUEADA, depende de T-FB100-01 (TODO), Media.,
                   epic "FB-101 · Dos"

    Resultados esperados:
    - total: 5 items · 0 errores; US: DONE=1, TODO=1; Task: TODO=3.
    - items_lista ordenados por prioridad: T-FB100-01 (Crítica) → T-FB100-02
      (Alta) → US-FB101-01 (Baja).
    - items_bloqueada: T-FB101-01 con dependencia pendiente T-FB100-01.
    - max_leverage_chain: T-FB100-01 → T-FB101-01.
    """
    backlog = tmp_path / "backlog"
    _write(
        backlog,
        "user-stories",
        "US-FB100-01-done.md",
        _WELL_FORMED_TASK.replace("T-FB100-01", "US-FB100-01").replace("TODO", "DONE"),
    )
    _write(
        backlog,
        "user-stories",
        "US-FB101-01-lista.md",
        _WELL_FORMED_TASK.replace("T-FB100-01", "US-FB101-01")
        .replace("**Epic:** FB-100 · Uno", "**Epic:** FB-101 · Dos")
        .replace("Alta.", "Baja — opcional."),
    )
    _write(
        backlog,
        "tasks",
        "T-FB100-01-lista.md",
        _WELL_FORMED_TASK.replace("T-FB100-01", "T-FB100-01").replace("Alta.", "Crítica."),
    )
    _write(
        backlog,
        "tasks",
        "T-FB100-02-lista.md",
        _WELL_FORMED_TASK.replace("T-FB100-01", "T-FB100-02"),
    )
    _write(
        backlog,
        "tasks",
        "T-FB101-01-bloqueada.md",
        _WELL_FORMED_TASK.replace("T-FB100-01", "T-FB101-01")
        .replace("**Epic:** FB-100 · Uno", "**Epic:** FB-101 · Dos")
        .replace("## Dependencias\n\nNinguna.\n\n", "## Dependencias\n\n**T-FB100-01** (sigue TODO).\n\n")
        .replace("Alta.", "Media."),
    )
    return backlog


def _run_cli(argv: list[str]) -> tuple[int, str]:
    import io
    import contextlib

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = run_backlog_status(argv)
    return code, buffer.getvalue()


# ---------------------------------------------------------------------------
# priority_rank (orden determinista)
# ---------------------------------------------------------------------------


def test_priority_rank_orders_critica_alta_media_baja_and_missing() -> None:
    assert priority_rank("Crítica.") == 0
    assert priority_rank("Crítica — urgente.") == 0
    assert priority_rank("Alta.") == 1
    assert priority_rank("Alta — hoy.") == 1
    assert priority_rank("Media.") == 2
    assert priority_rank("Baja...") == 3
    assert priority_rank("Baja — opcional.") == 3
    assert priority_rank(None) == 4
    assert priority_rank("Desconocida") == 4


# ---------------------------------------------------------------------------
# build_backlog_report (sintético, resultado controlado)
# ---------------------------------------------------------------------------


def test_build_backlog_report_counts_by_epic_and_state(tmp_path: Path) -> None:
    report = build_backlog_report(_synthetic_backlog(tmp_path))

    assert report["empty"] is False
    assert report["total"] == {
        "items": 5,
        "user_stories": {"DONE": 1, "TODO": 1},
        "tasks": {"TODO": 3},
        "errors": 0,
    }
    assert report["by_epic"] == [
        {
            "epic": "FB-100 · Uno",
            "user_stories": {"DONE": 1},
            "tasks": {"TODO": 2},
        },
        {
            "epic": "FB-101 · Dos",
            "user_stories": {"TODO": 1},
            "tasks": {"TODO": 1},
        },
    ]


def test_build_backlog_report_lists_lista_sorted_by_priority(tmp_path: Path) -> None:
    report = build_backlog_report(_synthetic_backlog(tmp_path))

    assert [entry["id"] for entry in report["items_lista"]] == [
        "T-FB100-01",
        "T-FB100-02",
        "US-FB101-01",
    ]


def test_build_backlog_report_lists_bloqueada_with_pending_dependency(
    tmp_path: Path,
) -> None:
    report = build_backlog_report(_synthetic_backlog(tmp_path))

    assert [entry["id"] for entry in report["items_bloqueada"]] == ["T-FB101-01"]
    assert report["items_bloqueada"][0]["blocking_dependencies"] == [
        {"id": "T-FB100-01", "state": "TODO"}
    ]
    assert [entry["id"] for entry in report["max_leverage_chain"]] == [
        "T-FB100-01",
        "T-FB101-01",
    ]


# ---------------------------------------------------------------------------
# CLI: salida humana y JSON sobre el backlog real (criterios 1 y 2)
# ---------------------------------------------------------------------------


def test_cli_human_and_json_show_the_same_figures_on_the_real_backlog() -> None:
    """Criterios 1 y 2 de la Task: `brain backlog-status` sobre el
    `02-backlog/` real produce una salida legible y la `--json` una salida
    estructurada parseable, ambas con las MISMAS cifras. Se compara cada
    salida contra el informe `build_backlog_report` del `02-backlog/`
    actual (nunca contra números fijos, que cambian con el estado del
    backlog)."""
    code_text, human = _run_cli([str(REAL_BACKLOG_PATH)])
    code_json, json_text = _run_cli([str(REAL_BACKLOG_PATH), "--json"])

    assert code_text == 0
    assert code_json == 0

    report = build_backlog_report(REAL_BACKLOG_PATH)

    # JSON: es una salida estructurada (dict parseable), no el texto
    # formateado, y reproduce el informe exacto.
    parsed = json.loads(json_text)
    assert isinstance(parsed, dict)
    assert parsed == report

    # Humana: no es un backlog vacío, y las cifras del texto son las mismas
    # que las del informe estructurado (mismas figuras por construcción y
    # verificado literalmente en el texto).
    assert report["empty"] is False
    assert BACKLOG_STATUS_NO_DATA_TEXT not in human
    assert f"Total: {report['total']['items']} items · {report['total']['errors']} errores" in human
    for entry in report["items_lista"]:
        assert entry["id"] in human
    for entry in report["items_bloqueada"]:
        assert entry["id"] in human
    if report["max_leverage_chain"]:
        chain_ids = " → ".join(entry["id"] for entry in report["max_leverage_chain"])
        assert chain_ids in human


def test_cli_json_output_is_structured_and_parseable() -> None:
    """Criterio 2: `--json` produce un dict estructurado (no el texto
    formateado) con las mismas secciones que el informe."""
    _, json_text = _run_cli([str(REAL_BACKLOG_PATH), "--json"])
    parsed = json.loads(json_text)

    assert set(parsed) == {
        "backlog_path",
        "empty",
        "total",
        "by_epic",
        "items_lista",
        "items_bloqueada",
        "max_leverage_chain",
        "errors",
    }


# ---------------------------------------------------------------------------
# CLI: backlog vacío/recién creado (criterio 3)
# ---------------------------------------------------------------------------


def test_cli_on_an_empty_backlog_reports_sin_datos_without_failing(
    tmp_path: Path,
) -> None:
    """Criterio 3: un backlog vacío/recién creado no es una excepción — el
    texto humano reporta "sin datos" y la salida `--json` sigue siendo un
    informe estructurado válido con `empty=True`."""
    empty_backlog = tmp_path / "02-backlog"
    (empty_backlog / "user-stories").mkdir(parents=True)
    (empty_backlog / "tasks").mkdir(parents=True)

    code_text, human = _run_cli([str(empty_backlog)])
    code_json, json_text = _run_cli([str(empty_backlog), "--json"])

    assert code_text == 0
    assert code_json == 0
    assert human.strip() == BACKLOG_STATUS_NO_DATA_TEXT
    assert json.loads(json_text)["empty"] is True


# ---------------------------------------------------------------------------
# Coherencia de renderizado (humano y JSON derivan del mismo dict)
# ---------------------------------------------------------------------------


def test_human_and_json_render_from_the_same_report(tmp_path: Path) -> None:
    report = build_backlog_report(_synthetic_backlog(tmp_path))
    human = format_human_report(report)

    assert "Sin datos" not in human
    assert "Total: 5 items · 0 errores de parseo" in human
    assert "FB-100 · Uno" in human
    assert "T-FB100-01 → T-FB101-01" in human
    assert json.loads(render_json_report(report)) == report
