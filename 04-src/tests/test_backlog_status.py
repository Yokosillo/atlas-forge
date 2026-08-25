"""Tests de T-AF018-US02-02: comando `atlas_forge backlog-status` y su informe
estructurado (`atlas_forge.backlog.report`), sobre `02-backlog/` sintético y sobre
el real de este proyecto 006.

## Estrategia de fixtures

Igual que en T-AF018-US02-01: NINGÚN test usa números del estado actual del
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

from atlas_forge.backlog import (
    BACKLOG_STATUS_NO_DATA_TEXT,
    build_backlog_report,
    format_human_report,
    priority_rank,
    render_json_report,
)
from atlas_forge.cli.backlog_status import run_backlog_status

REAL_BACKLOG_PATH = (
    Path(__file__).resolve().parents[1].parent / "02-backlog"
)

_WELL_FORMED_TASK = (
    "# T-AF100-01 · Ejemplo\n\n"
    "**Epic:** AF-100 · Uno\n\n"
    "## Dependencias\n\nNinguna.\n\n"
    "## Estado\n\n"
    "READY\n\n"
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

    - US-AF100-01  DONE, Alta., epic "AF-100 · Uno"
    - T-AF100-01   READY LISTA (sin deps), Crítica., epic "AF-100 · Uno"
    - T-AF100-02   READY LISTA (sin deps), Alta., epic "AF-100 · Uno"
    - US-AF101-01  READY LISTA (sin deps), Baja — opcional., epic "AF-101 · Dos"
    - T-AF101-01   READY BLOQUEADA, depende de T-AF100-01 (READY), Media.,
                   epic "AF-101 · Dos"

    Resultados esperados:
    - total: 5 items · 0 errores; US: DONE=1, READY=1; Task: READY=3.
    - items_lista ordenados por prioridad: T-AF100-01 (Crítica) → T-AF100-02
      (Alta) → US-AF101-01 (Baja).
    - items_bloqueada: T-AF101-01 con dependencia pendiente T-AF100-01.
    - max_leverage_chain: T-AF100-01 → T-AF101-01.
    """
    backlog = tmp_path / "backlog"
    _write(
        backlog,
        "user-stories",
        "US-AF100-01-done.md",
        _WELL_FORMED_TASK.replace("T-AF100-01", "US-AF100-01").replace("READY", "DONE"),
    )
    _write(
        backlog,
        "user-stories",
        "US-AF101-01-lista.md",
        _WELL_FORMED_TASK.replace("T-AF100-01", "US-AF101-01")
        .replace("**Epic:** AF-100 · Uno", "**Epic:** AF-101 · Dos")
        .replace("Alta.", "Baja — opcional."),
    )
    _write(
        backlog,
        "tasks",
        "T-AF100-01-lista.md",
        _WELL_FORMED_TASK.replace("T-AF100-01", "T-AF100-01").replace("Alta.", "Crítica."),
    )
    _write(
        backlog,
        "tasks",
        "T-AF100-02-lista.md",
        _WELL_FORMED_TASK.replace("T-AF100-01", "T-AF100-02"),
    )
    _write(
        backlog,
        "tasks",
        "T-AF101-01-bloqueada.md",
        _WELL_FORMED_TASK.replace("T-AF100-01", "T-AF101-01")
        .replace("**Epic:** AF-100 · Uno", "**Epic:** AF-101 · Dos")
        .replace("## Dependencias\n\nNinguna.\n\n", "## Dependencias\n\n**T-AF100-01** (sigue READY).\n\n")
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


def test_build_backlog_report_exposes_fase_per_user_story_in_by_epic(tmp_path: Path) -> None:
    """T-AF036-US15-01: `by_epic` expone por Epic la lista de User Stories
    con su `fase` (`user_stories_detail`) — campo aditivo que no rompe los
    conteos existentes."""
    from atlas_forge.backlog.report import build_backlog_report

    backlog = tmp_path / "02-backlog"
    (backlog / "epics").mkdir(parents=True)
    (backlog / "user-stories").mkdir(parents=True)
    (backlog / "epics" / "AF-700.md").write_text(
        "---\nid: AF-700\ntype: epic\ntitle: Epic\nstate: READY\n"
        "dependencies: []\nfase: Fase 1.1\n---\n\n## Objetivo\n\nO.\n",
        encoding="utf-8",
    )
    _yaml_us(backlog / "user-stories" / "US-AF700-01.md", "US-AF700-01", "AF-700", "READY")
    # Añade `fase` a la US (el helper no lo incluye).
    us_path = backlog / "user-stories" / "US-AF700-01.md"
    us_path.write_text(
        us_path.read_text(encoding="utf-8").replace("epic: AF-700\n", "epic: AF-700\nfase: Fase 1.1\n"),
        encoding="utf-8",
    )
    _yaml_us(backlog / "user-stories" / "US-AF700-02.md", "US-AF700-02", "AF-700", "READY")

    report = build_backlog_report(backlog)

    entry = next(e for e in report["by_epic"] if e["epic"] == "AF-700")
    # Campo nuevo aditivo: detalle por US con su fase (None si no la declara).
    detail_by_id = {us["id"]: us for us in entry["user_stories_detail"]}
    assert detail_by_id["US-AF700-01"]["fase"] == "Fase 1.1"
    assert detail_by_id["US-AF700-01"]["state"] == "NO_TASKS"
    assert detail_by_id["US-AF700-02"]["fase"] is None
    assert detail_by_id["US-AF700-02"]["state"] == "NO_TASKS"
    # Los campos existentes siguen presentes (aditivo, no rompe consumidores).
    assert entry["user_stories"] == {"NO_TASKS": 2}
    assert "unblock_degree" in entry


def test_build_backlog_report_counts_by_epic_and_state(tmp_path: Path) -> None:
    report = build_backlog_report(_synthetic_backlog(tmp_path))

    assert report["empty"] is False
    assert report["total"] == {
        "items": 5,
        "epics": {},
        # T-AF022-US13-09: el backlog sintético es formato legacy (sin
        # `user_story:` en las Tasks), así que ambas US se ven sin Tasks
        # vinculadas y derivan a NO_TASKS.
        "user_stories": {"NO_TASKS": 2},
        "tasks": {"READY": 3},
        "errors": 0,
    }
    assert report["by_epic"] == [
        {
            "epic": "AF-100",
            "epic_label": "AF-100",
            "user_stories": {"NO_TASKS": 1},
            "tasks": {"READY": 2},
            # T-AF036-US15-01: detalle por US con su fase (legacy sin fase -> None).
            "user_stories_detail": [
                {"id": "US-AF100-01", "fase": None, "state": "NO_TASKS"}
            ],
            "unblock_degree": 1.0,
        },
        {
            "epic": "AF-101",
            "epic_label": "AF-101",
            "user_stories": {"NO_TASKS": 1},
            "tasks": {"READY": 1},
            "user_stories_detail": [
                {"id": "US-AF101-01", "fase": None, "state": "NO_TASKS"}
            ],
            "unblock_degree": 0.5,
        },
    ]


# T-AF018-US02-06: `epic_label` debía devolver el título real de la Epic
# (campo `title` del frontmatter YAML de su fichero), no el mismo `AF-NNN`
# ya presente en el campo `epic` — `_epic_label_from_file` leía la
# PRIMERA LÍNEA literal del fichero buscando `# Título`, formato Markdown
# antiguo previo a la migración a frontmatter YAML (`AF-027`,
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
    from atlas_forge.backlog.report import _epic_label_from_file

    backlog = tmp_path / "backlog"
    _write(
        backlog,
        "epics",
        "AF-500-epic-de-prueba.md",
        _EPIC_FRONTMATTER.format(epic_id="AF-500", title="Título Real De La Epic"),
    )

    assert _epic_label_from_file(backlog, "AF-500") == "Título Real De La Epic"


def test_epic_label_from_file_falls_back_to_epic_id_without_epic_file(tmp_path: Path) -> None:
    # Criterio de aceptación 2: Epic huérfana (sin fichero propio en
    # `02-backlog/epics/`) sigue devolviendo el `epic_id` como fallback,
    # sin lanzar.
    from atlas_forge.backlog.report import _epic_label_from_file

    backlog = tmp_path / "backlog"
    backlog.mkdir(parents=True, exist_ok=True)

    assert _epic_label_from_file(backlog, "AF-999") == "AF-999"


def test_epic_label_from_file_falls_back_to_epic_id_when_title_missing(tmp_path: Path) -> None:
    # Fichero de Epic real, con frontmatter válido, pero sin campo
    # `title` — mismo criterio de robustez (nunca lanza).
    from atlas_forge.backlog.report import _epic_label_from_file

    backlog = tmp_path / "backlog"
    _write(
        backlog,
        "epics",
        "AF-501-sin-titulo.md",
        "---\nid: AF-501\ntype: epic\nstate: TODO\ndependencies: []\n---\n\n## Objetivo\n\nSin título.\n",
    )

    assert _epic_label_from_file(backlog, "AF-501") == "AF-501"


def test_build_backlog_report_by_epic_uses_real_title_from_frontmatter(
    tmp_path: Path,
) -> None:
    # Verificación end-to-end (no solo `_epic_label_from_file` en
    # aislamiento): `build_backlog_report` sobre un backlog sintético con
    # una Epic real (fichero propio en frontmatter YAML) y una Epic
    # huérfana (sin fichero) — confirma que `by_epic` refleja el título
    # real para la primera y el fallback para la segunda.
    from atlas_forge.backlog.report import build_backlog_report

    backlog = _synthetic_backlog(tmp_path)
    _write(
        backlog,
        "epics",
        "AF-100-epic-real.md",
        _EPIC_FRONTMATTER.format(epic_id="AF-100", title="Uno De Verdad"),
    )

    report = build_backlog_report(backlog)

    by_epic = {entry["epic"]: entry["epic_label"] for entry in report["by_epic"]}
    assert by_epic["AF-100"] == "Uno De Verdad"
    # AF-101 sigue sin fichero propio de Epic (huérfana en este fixture
    # sintético) — mismo fallback que antes de esta Task, sin cambios.
    assert by_epic["AF-101"] == "AF-101"


# ---------------------------------------------------------------------------
# T-AF036-US02-04: Epics sin hijos (recién creadas) en el listado agrupado
# ---------------------------------------------------------------------------


def test_build_backlog_report_includes_an_epic_without_children(tmp_path: Path) -> None:
    """Bug real de T-AF036-US02-04: una Epic recién creada (sin US/Tasks)
    no aparecía en `by_epic` — el listado agrupado solo se poblaba desde
    los items hijos (US/Task), así que el criterio "la Epic aparece
    expandida tras crearla" quedaba sin tarjeta que expandir. Tras el fix,
    una Epic sin hijos aparece igualmente en `by_epic` con conteos vacíos
    (`user_stories`/`tasks` = {}), su título real, `unblock_degree` (1.0,
    nada que desbloquear) y, T-AF036-US18-01, sin `fase` (la Epic se
    versiona, no lleva fase), y el backlog NO es `empty` (hay una tarjeta
    real que mostrar)."""
    from atlas_forge.backlog.report import build_backlog_report

    backlog = tmp_path / "02-backlog"
    _write(
        backlog,
        "epics",
        "AF-600-epic-sin-hijos.md",
        "---\nid: AF-600\ntype: epic\ntitle: Epic Sin Hijos\nstate: TODO\n"
        "dependencies: []\nversion: 0.9\n---\n\n# AF-600 · Epic Sin Hijos\n\n"
        "## Objetivo\n\nObjetivo de prueba.\n",
    )

    report = build_backlog_report(backlog)

    assert report["empty"] is False
    assert report["by_epic"] == [
        {
            "epic": "AF-600",
            "epic_label": "Epic Sin Hijos",
            "user_stories": {},
            "tasks": {},
            "user_stories_detail": [],
            "unblock_degree": 1.0,
            # T-AF036-US15-06: `by_epic` expone la VERSION de la Epic (US-AF036-18).
            "version": "0.9",
        }
    ]


def test_build_backlog_report_empty_epic_coexists_with_populated_ones(
    tmp_path: Path,
) -> None:
    """Misma Epic con hijos y sin hijos conviven en `by_epic` sin
    duplicarse: la entrada de la Epic con hijos se puebla desde sus items,
    la de la Epic sin hijos se crea con conteos vacíos — nunca dos entradas
    para el mismo id."""
    from atlas_forge.backlog.report import build_backlog_report

    backlog = _synthetic_backlog(tmp_path)
    _write(
        backlog,
        "epics",
        "AF-100-epic-real.md",
        _EPIC_FRONTMATTER.format(epic_id="AF-100", title="Uno De Verdad"),
    )
    _write(
        backlog,
        "epics",
        "AF-600-epic-sin-hijos.md",
        "---\nid: AF-600\ntype: epic\ntitle: Epic Sin Hijos\nstate: TODO\n"
        "dependencies: []\n---\n\n# AF-600 · Epic Sin Hijos\n\n"
        "## Objetivo\n\nObjetivo de prueba.\n",
    )

    report = build_backlog_report(backlog)

    by_epic = {entry["epic"]: entry for entry in report["by_epic"]}
    assert list(by_epic) == ["AF-100", "AF-101", "AF-600"]
    # AF-100 sigue poblada desde sus items (5 US/Tasks en total), sin
    # duplicarse con la entrada de Epic sin hijos.
    # T-AF022-US13-09: backlog legacy sin `user_story:` -> US-AF100-01
    # DONE se ve sin Tasks vinculadas y deriva a NO_TASKS.
    assert by_epic["AF-100"]["user_stories"] == {"NO_TASKS": 1}
    assert by_epic["AF-100"]["tasks"] == {"READY": 2}
    # AF-600, recién creada sin hijos, entra con conteos vacíos.
    assert by_epic["AF-600"]["user_stories"] == {}
    assert by_epic["AF-600"]["tasks"] == {}


def test_build_backlog_report_lists_lista_sorted_by_priority(tmp_path: Path) -> None:
    report = build_backlog_report(_synthetic_backlog(tmp_path))

    # T-AF022-US13-09: US-AF100-01 (DONE con Tasks READY) deriva a READY y
    # pasa a ser un item TO_DO pendiente de `items_lista`.
    assert [entry["id"] for entry in report["items_lista"]] == [
        "T-AF100-01",
        "T-AF100-02",
        "US-AF100-01",
        "US-AF101-01",
    ]


def test_build_backlog_report_lists_bloqueada_with_pending_dependency(
    tmp_path: Path,
) -> None:
    report = build_backlog_report(_synthetic_backlog(tmp_path))

    assert [entry["id"] for entry in report["items_bloqueada"]] == ["T-AF101-01"]
    assert report["items_bloqueada"][0]["blocking_dependencies"] == [
        {"id": "T-AF100-01", "state": "READY"}
    ]
    assert [entry["id"] for entry in report["max_leverage_chain"]] == [
        "T-AF100-01",
        "T-AF101-01",
    ]


# ---------------------------------------------------------------------------
# CLI: salida humana y JSON sobre el backlog real (criterios 1 y 2)
# ---------------------------------------------------------------------------


def test_cli_human_and_json_show_the_same_figures_on_the_real_backlog() -> None:
    """Criterios 1 y 2 de la Task: `atlas_forge backlog-status` sobre el
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

    `drift` (T-AF022-US13-05) es opcional: solo aparece si el backlog
    real tiene algún padre DONE con un hijo reabierto — condición real
    hoy sobre `REAL_BACKLOG_PATH` (drift preexistente detectado en vivo,
    2026-08-16), así que se acepta con o sin la clave en vez de fijar un
    conjunto exacto que dependería del estado cambiante del backlog real.

    `duplicate_ids` (T-AF008-US18-01) es igualmente opcional: solo aparece
    si el backlog real tiene ids duplicados (hoy los detecta el checker);
    un backlog sin duplicados no expone la clave."""
    _, json_text = _run_cli([str(REAL_BACKLOG_PATH), "--json"])
    parsed = json.loads(json_text)

    expected = {
        "backlog_path",
        "empty",
        "total",
        "by_epic",
        "items_lista",
        "items_bloqueada",
        "items_in_progress",
        "max_leverage_chain",
        "errors",
    }
    assert set(parsed) - {"drift", "duplicate_ids"} == expected


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
    assert "AF-100 · Uno" in human
    assert "T-AF100-01 → T-AF101-01" in human
    assert json.loads(render_json_report(report)) == report


# ---------------------------------------------------------------------------
# T-AF022-US13-05: GET /backlog (via build_backlog_report) nunca sirve un
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
    _yaml_us(backlog / "user-stories" / "US-AF900-01.md", "US-AF900-01", "AF-900", "DONE")
    _yaml_task(backlog / "tasks" / "T-AF900-US01-01.md", "T-AF900-US01-01", "AF-900", "US-AF900-01", "DONE")
    _yaml_task(backlog / "tasks" / "T-AF900-US01-02.md", "T-AF900-US01-02", "AF-900", "US-AF900-01", "READY")

    report = build_backlog_report(backlog)

    # Ni el conteo agregado ni por-Epic cuentan la US como DONE (criterio 2);
    # la US DONE con una Task READY deriva a READY (T-AF022-US13-09).
    assert report["total"]["user_stories"].get("DONE", 0) == 0
    assert report["total"]["user_stories"]["READY"] == 1
    epic_entry = next(e for e in report["by_epic"] if e["epic"] == "AF-900")
    assert epic_entry["user_stories"].get("DONE", 0) == 0
    assert report["drift"] == ["US-AF900-01"]


def test_build_backlog_report_no_drift_field_when_backlog_consistent(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    _yaml_us(backlog / "user-stories" / "US-AF900-01.md", "US-AF900-01", "AF-900", "DONE")
    _yaml_task(backlog / "tasks" / "T-AF900-US01-01.md", "T-AF900-US01-01", "AF-900", "US-AF900-01", "DONE")

    report = build_backlog_report(backlog)

    # Criterio 3: sin drift, no aparece el campo — mismo formato que antes.
    assert "drift" not in report


def test_build_backlog_report_does_not_write_any_file(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    us_path = backlog / "user-stories" / "US-AF900-01.md"
    _yaml_us(us_path, "US-AF900-01", "AF-900", "DONE")
    _yaml_task(backlog / "tasks" / "T-AF900-US01-01.md", "T-AF900-US01-01", "AF-900", "US-AF900-01", "READY")

    before = us_path.read_text(encoding="utf-8")
    build_backlog_report(backlog)
    after = us_path.read_text(encoding="utf-8")

    assert before == after
    assert "state: DONE" in after


def test_build_backlog_report_exposes_version_per_epic(tmp_path: Path) -> None:
    """T-AF036-US15-06: `by_epic` expone la VERSION de cada Epic (US-AF036-18,
    campo `version` del frontmatter) para que la vista "Por Fase" agrupe por
    VERSION. La Epic que no declara `version` no recibe el campo (la vista
    la agrupa bajo "SIN_VERSION" en el frontend)."""
    backlog = tmp_path / "02-backlog"
    _write(
        backlog,
        "epics",
        "AF-910-con-version.md",
        "---\nid: AF-910\ntype: epic\ntitle: Con Version\nstate: READY\n"
        "dependencies: []\nversion: 0.9\n---\n\n# AF-910 · Con Version\n\n"
        "## Objetivo\n\nO.\n",
    )
    _yaml_us(backlog / "user-stories" / "US-AF910-01.md", "US-AF910-01", "AF-910", "NO_TASKS")
    _write(
        backlog,
        "epics",
        "AF-911-sin-version.md",
        "---\nid: AF-911\ntype: epic\ntitle: Sin Version\nstate: READY\n"
        "dependencies: []\n---\n\n# AF-911 · Sin Version\n\n"
        "## Objetivo\n\nO.\n",
    )
    _yaml_us(backlog / "user-stories" / "US-AF911-01.md", "US-AF911-01", "AF-911", "NO_TASKS")

    report = build_backlog_report(backlog)

    by_epic = {entry["epic"]: entry for entry in report["by_epic"]}
    assert by_epic["AF-910"]["version"] == "0.9"
    assert "version" not in by_epic["AF-911"]


# ---------------------------------------------------------------------------
# T-AF008-US18-01: el informe expone los ids duplicados como error consultable
# ---------------------------------------------------------------------------


def test_build_backlog_report_exposes_duplicate_ids(tmp_path: Path) -> None:
    """Criterio 4: un backlog YA escrito con dos ficheros del mismo `id`
    (la causal raíz del hallazgo de operaciones) se señala en el informe como
    error consultable (`duplicate_ids`), tanto en el dict como en la salida
    humana — para que el backlog existente pueda auditarse."""
    backlog = tmp_path / "backlog"
    _yaml_us(backlog / "user-stories" / "US-AF910-01.md", "US-AF910-01", "AF-910", "NO_TASKS")
    _yaml_task(
        backlog / "tasks" / "T-AF910-US01-01-primera.md",
        "T-AF910-US01-01", "AF-910", "US-AF910-01", "READY",
    )
    _yaml_task(
        backlog / "tasks" / "T-AF910-US01-01-segunda.md",
        "T-AF910-US01-01", "AF-910", "US-AF910-01", "READY",
    )

    report = build_backlog_report(backlog)

    assert "duplicate_ids" in report
    assert report["duplicate_ids"] == [
        {
            "id": "T-AF910-US01-01",
            "paths": [
                "tasks/T-AF910-US01-01-primera.md",
                "tasks/T-AF910-US01-01-segunda.md",
            ],
        }
    ]

    human = format_human_report(report)
    assert "IDs duplicados" in human
    assert "T-AF910-US01-01" in human


def test_build_backlog_report_no_duplicate_ids_key_when_clean(tmp_path: Path) -> None:
    """Un backlog sin ids duplicados no expone la clave `duplicate_ids`
    (campo opcional, igual que `drift`) — un backlog limpio no cambia su
    respuesta respecto a antes de esta Task."""
    backlog = tmp_path / "backlog"
    _yaml_us(backlog / "user-stories" / "US-AF910-01.md", "US-AF910-01", "AF-910", "NO_TASKS")
    _yaml_task(
        backlog / "tasks" / "T-AF910-US01-01.md",
        "T-AF910-US01-01", "AF-910", "US-AF910-01", "READY",
    )

    report = build_backlog_report(backlog)

    assert "duplicate_ids" not in report
    assert "IDs duplicados" not in format_human_report(report)


# ---------------------------------------------------------------------------
# T-AF022-US17-01: indicador de en vuelo/huérfana para items IN_PROGRESS
# ---------------------------------------------------------------------------


def _write_dispatch_queue(project_root: Path, entries: list[dict]) -> None:
    """Escribe `dispatch_queue.json` en la ruta canónica del proyecto
    (`<root>/.claude/state/<name>/dispatch_queue.json`) para que
    `_dispatched_task_ids_from_queue` lo lea por la vía real (`get_queue`)."""
    import json

    from atlas_forge.runtime.generic import sanitize_session_name_part

    state_dir = (
        project_root
        / ".claude"
        / "state"
        / sanitize_session_name_part(project_root.name)
    )
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "dispatch_queue.json").write_text(
        json.dumps(entries, ensure_ascii=False), encoding="utf-8"
    )


def _in_progress_fixture(tmp_path: Path) -> Path:
    """Mini-backlog con una US IN_PROGRESS y su Task IN_PROGRESS."""
    backlog = tmp_path / "repo" / "02-backlog"
    _yaml_us(
        backlog / "user-stories" / "US-AF910-01.md", "US-AF910-01", "AF-910", "IN_PROGRESS"
    )
    _yaml_task(
        backlog / "tasks" / "T-AF910-US01-01.md",
        "T-AF910-US01-01", "AF-910", "US-AF910-01", "IN_PROGRESS",
    )
    return backlog


def _dispatched_entry(task_id: str) -> dict:
    return {
        "task_id": task_id,
        "us_id": "US-AF910-01",
        "priority": "Alta",
        "status": "dispatched",
        "enqueued_at": "2026-08-24T00:00:00+00:00",
    }


class TestInFlightHuerfanaIndicator:
    """T-AF022-US17-01 (backend): el reporte de `GET /backlog` expone por item
    `IN_PROGRESS` el indicador `in_flight` — `True` si su `task_id` tiene
    entrada `dispatched` en `dispatch_queue.json` (Job legítimo en vuelo),
    `False` si está sin entrada (huérfana). Fuente persistida, determinista."""

    def test_in_progress_task_with_dispatched_entry_is_in_flight(self, tmp_path) -> None:
        backlog = _in_progress_fixture(tmp_path)
        _write_dispatch_queue(tmp_path / "repo", [_dispatched_entry("T-AF910-US01-01")])

        report = build_backlog_report(backlog)
        by_id = {entry["id"]: entry for entry in report["items_in_progress"]}

        assert by_id["T-AF910-US01-01"]["in_flight"] is True
        # La US IN_PROGRESS derivada se considera en vuelo si alguna de sus
        # Tasks lo está (la cola es por Task).
        assert by_id["US-AF910-01"]["in_flight"] is True

    def test_in_progress_task_without_queue_entry_is_orphan(self, tmp_path) -> None:
        backlog = _in_progress_fixture(tmp_path)  # sin dispatch_queue.json

        report = build_backlog_report(backlog)
        by_id = {entry["id"]: entry for entry in report["items_in_progress"]}

        assert by_id["T-AF910-US01-01"]["in_flight"] is False
        assert by_id["US-AF910-01"]["in_flight"] is False

    def test_dispatched_other_task_does_not_mark_this_one_in_flight(self, tmp_path) -> None:
        """Solo la Task con entrada `dispatched` es en vuelo; otra IN_PROGRESS
        sin entrada sigue siendo huérfana aunque la cola tenga otras entradas."""
        backlog = _in_progress_fixture(tmp_path)
        _yaml_task(
            backlog / "tasks" / "T-AF910-US01-02.md",
            "T-AF910-US01-02", "AF-910", "US-AF910-01", "IN_PROGRESS",
        )
        _write_dispatch_queue(
            tmp_path / "repo", [_dispatched_entry("T-AF910-US01-01")]
        )

        report = build_backlog_report(backlog)
        by_id = {entry["id"]: entry for entry in report["items_in_progress"]}

        assert by_id["T-AF910-US01-01"]["in_flight"] is True
        assert by_id["T-AF910-US01-02"]["in_flight"] is False
        assert by_id["US-AF910-01"]["in_flight"] is True  # alguna de sus Tasks va en vuelo

    def test_queued_entry_is_not_in_flight(self, tmp_path) -> None:
        """Criterio: `in_flight: true` exige entrada `dispatched` — una entrada
        `queued` (todavía sin agente) no cuenta como en vuelo."""
        backlog = _in_progress_fixture(tmp_path)
        queued = _dispatched_entry("T-AF910-US01-01")
        queued["status"] = "queued"
        _write_dispatch_queue(tmp_path / "repo", [queued])

        report = build_backlog_report(backlog)
        by_id = {entry["id"]: entry for entry in report["items_in_progress"]}

        assert by_id["T-AF910-US01-01"]["in_flight"] is False

    def test_rest_of_items_do_not_carry_in_flight(self, tmp_path) -> None:
        """El resto de items no llevan el campo: su shape no cambia."""
        backlog = tmp_path / "backlog"
        _yaml_us(
            backlog / "user-stories" / "US-AF910-01.md", "US-AF910-01", "AF-910", "NO_TASKS"
        )
        _yaml_task(
            backlog / "tasks" / "T-AF910-US01-01.md",
            "T-AF910-US01-01", "AF-910", "US-AF910-01", "READY",
        )
        _yaml_task(
            backlog / "tasks" / "T-AF910-US01-02.md",
            "T-AF910-US01-02", "AF-910", "US-AF910-01", "DONE",
        )

        report = build_backlog_report(backlog)

        assert report["items_in_progress"] == []
        for entry in report["items_lista"] + report["max_leverage_chain"]:
            assert "in_flight" not in entry

    def test_in_progress_items_surfaces_in_human_report(self, tmp_path) -> None:
        backlog = _in_progress_fixture(tmp_path)  # huérfana (sin cola)

        human = format_human_report(build_backlog_report(backlog))

        assert "IN_PROGRESS" in human
        assert "HUÉRFANA" in human
        assert "T-AF910-US01-01" in human


# ---------------------------------------------------------------------------
# T-AF022-US17-05 · Escenario del caso real (2026-08-20): T-AF023-US03-01
# IN_PROGRESS huérfana → T-AF023-US03-02 bloqueada por ella.
# ---------------------------------------------------------------------------


def _yaml_task_deps(
    backlog: Path, task_id: str, epic_id: str, us_id: str, state: str, deps: list[str]
) -> None:
    target = backlog / "tasks" / f"{task_id}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    if deps:
        dep_lines = "dependencies:\n" + "".join(f"  - {d}\n" for d in deps)
    else:
        dep_lines = "dependencies: []"
    target.write_text(
        "---\n"
        f"id: {task_id}\ntype: task\ntitle: {task_id}\nstate: {state}\n"
        f"{dep_lines}\n"
        f"epic: {epic_id}\nuser_story: {us_id}\npriority: Alta\n"
        "---\n\n## Objetivo\n\nO.\n\n## Criterios de aceptación\n\n- C.\n",
        encoding="utf-8",
    )


def test_caso_real_t_af023_us03_01_huerfana_bloquea_a_us03_02(tmp_path) -> None:
    """T-AF022-US17-05, escenario del caso real: T-AF023-US03-01 queda
    IN_PROGRESS huérfana (sin entrada `dispatched` en la cola → `in_flight:
    false`) y T-AF023-US03-02 (READY, depende de ella) aparece en
    `items_bloqueada` esperando a `T-AF023-US03-01 [IN_PROGRESS]` — el
    ataque que bloqueó la cadena (AT-023)."""
    backlog = tmp_path / "backlog"
    _yaml_task_deps(backlog, "T-AF023-US03-01", "AF-023", "US-AF023-03", "IN_PROGRESS", [])
    _yaml_task_deps(
        backlog, "T-AF023-US03-02", "AF-023", "US-AF023-03", "READY",
        ["T-AF023-US03-01"],
    )

    # Sin `dispatch_queue.json` → ningún `dispatched` → la IN_PROGRESS es
    # huérfana y la dependencia pendiente se señala con su estado.
    report = build_backlog_report(backlog)

    in_progress = {entry["id"]: entry for entry in report["items_in_progress"]}
    assert in_progress["T-AF023-US03-01"]["in_flight"] is False
    blocked = {entry["id"]: entry for entry in report["items_bloqueada"]}
    assert blocked["T-AF023-US03-02"]["blocking_dependencies"] == [
        {"id": "T-AF023-US03-01", "state": "IN_PROGRESS"}
    ]
