"""T-AF036-US13-02: exponer `updated_at` (y confirmar `fase`) en la API del
backlog — detalle (`build_item_detail`) y resumen por item
(`build_backlog_report`/`_summary`), leyéndolo del frontmatter YAML vía el
parser (`BacklogItem.updated_at`).

Retrocompatibilidad: si el fichero no declara `updated_at`, el campo se
devuelve `null`/`None`, nunca rompe el esquema ni a los clientes.
"""

from __future__ import annotations

from pathlib import Path

from atlas_forge.backlog.detail import build_item_detail
from atlas_forge.backlog.parser import load_backlog, parse_backlog_item
from atlas_forge.backlog.report import build_backlog_report

_TS = "2026-08-19T16:21:15.962347+00:00"


def _write(path: Path, subdir: str, filename: str, content: str) -> None:
    directory = path / subdir
    directory.mkdir(parents=True, exist_ok=True)
    (directory / filename).write_text(content, encoding="utf-8")


def _task_with(
    task_id: str,
    story_id: str,
    state: str = "READY",
    updated_at: str | None = None,
    fase: str | None = None,
) -> str:
    updated_line = f"updated_at: {updated_at}\n" if updated_at is not None else ""
    fase_line = f"fase: {fase}\n" if fase is not None else ""
    return (
        "---\n"
        f"id: {task_id}\n"
        "type: task\n"
        "title: Task de ejemplo\n"
        f"state: {state}\n"
        "dependencies: []\n"
        "epic: AF-999\n"
        f"user_story: {story_id}\n"
        "priority: Alta\n"
        f"{fase_line}"
        f"{updated_line}"
        "---\n\n"
        f"# {task_id} · Task de ejemplo\n\n"
        "## Objetivo\n\nHacer algo.\n\n"
        "## Criterios de aceptación\n\n1. Hecho.\n"
    )


def _us_with(
    us_id: str,
    state: str = "READY",
    updated_at: str | None = None,
    fase: str | None = None,
) -> str:
    updated_line = f"updated_at: {updated_at}\n" if updated_at is not None else ""
    fase_line = f"fase: {fase}\n" if fase is not None else ""
    return (
        "---\n"
        f"id: {us_id}\n"
        "type: user_story\n"
        "title: Historia de ejemplo\n"
        f"state: {state}\n"
        "dependencies: []\n"
        "epic: AF-999\n"
        "priority: Alta\n"
        f"{fase_line}"
        f"{updated_line}"
        "---\n\n"
        f"# {us_id} · Historia de ejemplo\n\n"
        "## Historia\n\nComo usuario quiero X.\n\n"
        "## Criterios de aceptación\n\n1. Y.\n"
    )


# ---------------------------------------------------------------------------
# Parser: BacklogItem.updated_at leído del frontmatter (igual que `fase`)
# ---------------------------------------------------------------------------


def test_parse_backlog_item_reads_updated_at_from_frontmatter(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "tasks",
        "T-AF999-US01-01.md",
        _task_with("T-AF999-US01-01", "US-AF999-01", updated_at=_TS, fase="Fase 1.0"),
    )

    item = parse_backlog_item(tmp_path / "tasks" / "T-AF999-US01-01.md")

    assert item.updated_at == _TS
    assert item.fase == "Fase 1.0"


def test_parse_backlog_item_updated_at_none_when_absent(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "tasks",
        "T-AF999-US01-01.md",
        _task_with("T-AF999-US01-01", "US-AF999-01"),
    )

    item = parse_backlog_item(tmp_path / "tasks" / "T-AF999-US01-01.md")

    assert item.updated_at is None


# ---------------------------------------------------------------------------
# Detalle: build_item_detail expone updated_at y fase para US y Task
# ---------------------------------------------------------------------------


def test_build_item_detail_exposes_updated_at_and_fase_for_task(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "user-stories",
        "US-AF999-01.md",
        _us_with("US-AF999-01"),
    )
    _write(
        tmp_path,
        "tasks",
        "T-AF999-US01-01.md",
        _task_with("T-AF999-US01-01", "US-AF999-01", updated_at=_TS, fase="Fase 1.0"),
    )

    graph = load_backlog(tmp_path)
    detail = build_item_detail(graph, "T-AF999-US01-01")

    assert detail is not None
    assert detail["updated_at"] == _TS
    assert detail["fase"] == "Fase 1.0"


def test_build_item_detail_exposes_updated_at_and_fase_for_user_story(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "user-stories",
        "US-AF999-01.md",
        _us_with("US-AF999-01", updated_at=_TS, fase="Fase 2.0"),
    )

    graph = load_backlog(tmp_path)
    detail = build_item_detail(graph, "US-AF999-01")

    assert detail is not None
    assert detail["updated_at"] == _TS
    assert detail["fase"] == "Fase 2.0"


def test_build_item_detail_updated_at_none_when_absent(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "user-stories",
        "US-AF999-01.md",
        _us_with("US-AF999-01"),
    )

    graph = load_backlog(tmp_path)
    detail = build_item_detail(graph, "US-AF999-01")

    assert detail is not None
    assert detail["updated_at"] is None
    assert detail["fase"] is None


# ---------------------------------------------------------------------------
# Resumen por item: _summary incluye updated_at (items_lista/items_bloqueada)
# ---------------------------------------------------------------------------


def _report_backlog(tmp_path: Path) -> Path:
    _write(
        tmp_path,
        "user-stories",
        "US-AF999-01.md",
        _us_with("US-AF999-01", updated_at=_TS, fase="Fase 1.0"),
    )
    _write(
        tmp_path,
        "tasks",
        "T-AF999-US01-01.md",
        _task_with("T-AF999-US01-01", "US-AF999-01", updated_at=_TS, fase="Fase 1.0"),
    )
    _write(
        tmp_path,
        "tasks",
        "T-AF999-US01-02.md",
        _task_with("T-AF999-US01-02", "US-AF999-01"),
    )
    return tmp_path


def test_report_summary_includes_updated_at_and_fase(tmp_path: Path) -> None:
    report = build_backlog_report(_report_backlog(tmp_path))

    lista = report["items_lista"]
    # Sin fase/updated_at explícito -> null (retrocompatibilidad).
    without = next(item for item in lista if item["id"] == "T-AF999-US01-02")
    assert without["updated_at"] is None
    assert without["fase"] is None
    # Con fase/updated_at presentes -> se exponen.
    with_meta = next(item for item in lista if item["id"] == "T-AF999-US01-01")
    assert with_meta["updated_at"] == _TS
    assert with_meta["fase"] == "Fase 1.0"
    us_entry = next(item for item in lista if item["id"] == "US-AF999-01")
    assert us_entry["updated_at"] == _TS
    assert us_entry["fase"] == "Fase 1.0"
