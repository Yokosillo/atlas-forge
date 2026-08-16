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
        "epics": {},
        "user_stories": {"DONE": 1, "TODO": 1},
        "tasks": {"TODO": 3},
        "errors": 0,
    }
    assert report["by_epic"] == [
        {
            "epic": "FB-100",
            "epic_label": "FB-100",
            "user_stories": {"DONE": 1},
            "tasks": {"TODO": 2},
            "unblock_degree": 1.0,
        },
        {
            "epic": "FB-101",
            "epic_label": "FB-101",
            "user_stories": {"TODO": 1},
            "tasks": {"TODO": 1},
            "unblock_degree": 0.5,
        },
    ]


# T-FB018-US02-06: `epic_label` debía devolver el título real de la Epic
# (campo `title` del frontmatter YAML de su fichero), no el mismo `FB-NNN`
# ya presente en el campo `epic` — `_epic_label_from_file` leía la
# PRIMERA LÍNEA literal del fichero buscando `# Título`, formato Markdown
# antiguo previo a la migración a frontmatter YAML (`FB-027`,
# 2026-08-06); tras la migración esa primera línea es siempre `---`, así
# que la función caía siempre a su fallback (`epic_id`).
_EPIC_FRONTMATTER = (
    "---\n"
    "id: {epic_id}\n"
    "type: epic\n"
    "title: {title}\n"
    "state: TODO\n"
    "dependencies: []\n"
    "---\n\n"
    "# {epic_id} · {title}\n\n"
    "## Objetivo\n\n{title} — objetivo de prueba.\n"
)


def test_epic_label_from_file_reads_title_from_yaml_frontmatter(tmp_path: Path) -> None:
    # Criterio de aceptación 3: test de regresión con un fixture de Epic
    # en formato frontmatter YAML real.
    from brain.backlog.report import _epic_label_from_file

    backlog = tmp_path / "backlog"
    _write(
        backlog,
        "epics",
        "FB-500-epic-de-prueba.md",
        _EPIC_FRONTMATTER.format(epic_id="FB-500", title="Título Real De La Epic"),
    )

    assert _epic_label_from_file(backlog, "FB-500") == "Título Real De La Epic"


def test_epic_label_from_file_falls_back_to_epic_id_without_epic_file(tmp_path: Path) -> None:
    # Criterio de aceptación 2: Epic huérfana (sin fichero propio en
    # `02-backlog/epics/`) sigue devolviendo el `epic_id` como fallback,
    # sin lanzar.
    from brain.backlog.report import _epic_label_from_file

    backlog = tmp_path / "backlog"
    backlog.mkdir(parents=True, exist_ok=True)

    assert _epic_label_from_file(backlog, "FB-999") == "FB-999"


def test_epic_label_from_file_falls_back_to_epic_id_when_title_missing(tmp_path: Path) -> None:
    # Fichero de Epic real, con frontmatter válido, pero sin campo
    # `title` — mismo criterio de robustez (nunca lanza).
    from brain.backlog.report import _epic_label_from_file

    backlog = tmp_path / "backlog"
    _write(
        backlog,
        "epics",
        "FB-501-sin-titulo.md",
        "---\nid: FB-501\ntype: epic\nstate: TODO\ndependencies: []\n---\n\n## Objetivo\n\nSin título.\n",
    )

    assert _epic_label_from_file(backlog, "FB-501") == "FB-501"


def test_build_backlog_report_by_epic_uses_real_title_from_frontmatter(
    tmp_path: Path,
) -> None:
    # Verificación end-to-end (no solo `_epic_label_from_file` en
    # aislamiento): `build_backlog_report` sobre un backlog sintético con
    # una Epic real (fichero propio en frontmatter YAML) y una Epic
    # huérfana (sin fichero) — confirma que `by_epic` refleja el título
    # real para la primera y el fallback para la segunda.
    from brain.backlog.report import build_backlog_report

    backlog = _synthetic_backlog(tmp_path)
    _write(
        backlog,
        "epics",
        "FB-100-epic-real.md",
        _EPIC_FRONTMATTER.format(epic_id="FB-100", title="Uno De Verdad"),
    )

    report = build_backlog_report(backlog)

    by_epic = {entry["epic"]: entry["epic_label"] for entry in report["by_epic"]}
    assert by_epic["FB-100"] == "Uno De Verdad"
    # FB-101 sigue sin fichero propio de Epic (huérfana en este fixture
    # sintético) — mismo fallback que antes de esta Task, sin cambios.
    assert by_epic["FB-101"] == "FB-101"


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
    formateado) con las mismas secciones que el informe.

    `drift` (T-FB022-US13-05) es opcional: solo aparece si el backlog
    real tiene algún padre DONE con un hijo reabierto — condición real
    hoy sobre `REAL_BACKLOG_PATH` (drift preexistente detectado en vivo,
    2026-08-16), así que se acepta con o sin la clave en vez de fijar un
    conjunto exacto que dependería del estado cambiante del backlog real."""
    _, json_text = _run_cli([str(REAL_BACKLOG_PATH), "--json"])
    parsed = json.loads(json_text)

    expected = {
        "backlog_path",
        "empty",
        "total",
        "by_epic",
        "items_lista",
        "items_bloqueada",
        "max_leverage_chain",
        "errors",
    }
    assert set(parsed) - {"drift"} == expected


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


# ---------------------------------------------------------------------------
# T-FB022-US13-05: GET /backlog (via build_backlog_report) nunca sirve un
# padre DONE con un hijo pendiente, sin escribir nada en disco.
# ---------------------------------------------------------------------------


def _yaml_us(path: Path, us_id: str, epic_id: str, state: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nid: {us_id}\ntype: user_story\ntitle: {us_id}\nstate: {state}\n"
        f"dependencies: []\nepic: {epic_id}\npriority: Alta\n---\n\n"
        f"## Historia\n\nHistoria de prueba.\n\n## Criterios de aceptación\n\n- Uno.\n",
        encoding="utf-8",
    )


def _yaml_task(path: Path, task_id: str, epic_id: str, us_id: str, state: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nid: {task_id}\ntype: task\ntitle: {task_id}\nstate: {state}\n"
        f"dependencies: []\nepic: {epic_id}\nuser_story: {us_id}\npriority: Alta\n---\n\n"
        f"## Objetivo\n\nObjetivo de prueba.\n\n## Criterios de aceptación\n\n- Uno.\n",
        encoding="utf-8",
    )


def test_build_backlog_report_reconciles_us_done_with_reopened_task(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    _yaml_us(backlog / "user-stories" / "US-FB900-01.md", "US-FB900-01", "FB-900", "DONE")
    _yaml_task(backlog / "tasks" / "T-FB900-US01-01.md", "T-FB900-US01-01", "FB-900", "US-FB900-01", "DONE")
    _yaml_task(backlog / "tasks" / "T-FB900-US01-02.md", "T-FB900-US01-02", "FB-900", "US-FB900-01", "TODO")

    report = build_backlog_report(backlog)

    # Ni el conteo agregado ni por-Epic cuentan la US como DONE (criterio 2).
    assert report["total"]["user_stories"].get("DONE", 0) == 0
    assert report["total"]["user_stories"]["IN_PROGRESS"] == 1
    epic_entry = next(e for e in report["by_epic"] if e["epic"] == "FB-900")
    assert epic_entry["user_stories"].get("DONE", 0) == 0
    assert report["drift"] == ["US-FB900-01"]


def test_build_backlog_report_no_drift_field_when_backlog_consistent(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    _yaml_us(backlog / "user-stories" / "US-FB900-01.md", "US-FB900-01", "FB-900", "DONE")
    _yaml_task(backlog / "tasks" / "T-FB900-US01-01.md", "T-FB900-US01-01", "FB-900", "US-FB900-01", "DONE")

    report = build_backlog_report(backlog)

    # Criterio 3: sin drift, no aparece el campo — mismo formato que antes.
    assert "drift" not in report


def test_build_backlog_report_does_not_write_any_file(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    us_path = backlog / "user-stories" / "US-FB900-01.md"
    _yaml_us(us_path, "US-FB900-01", "FB-900", "DONE")
    _yaml_task(backlog / "tasks" / "T-FB900-US01-01.md", "T-FB900-US01-01", "FB-900", "US-FB900-01", "TODO")

    before = us_path.read_text(encoding="utf-8")
    build_backlog_report(backlog)
    after = us_path.read_text(encoding="utf-8")

    assert before == after
    assert "state: DONE" in after
