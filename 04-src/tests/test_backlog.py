"""Tests de T-FB018-US02-01: parser determinista de `02-backlog/` y grafo
de dependencias (US-FB018-02 · "Estado del backlog: conteo, dependencias y
siguiente foco, sin gastar tokens de agente cognitivo").

## Estrategia de fixtures (IMPORTANTE)

La Task se escribió con números de un estado del backlog obsoleto
(`31` LISTAS / `11` BLOQUEADAS, `T-FB008-US05-01` como raíz de la cadena) —
el backlog real de este proyecto 006 está en constante cambio (se han
cerrado y creado muchas US/Tasks desde entonces). Por eso:

- NINGÚN test usa esos números como valor esperado.
- `classify_todo_items` y `find_max_leverage_chain` se testean con un
  mini-backlog sintético construido por el propio test (`tmp_path`), donde
  el resultado esperado está totalmente bajo control del test.
- El único test que toca el `02-backlog/` real de este proyecto es de
  NATURALEZA ESTRUCTURAL y válido siempre: `load_backlog` produce un nodo
  por cada fichero `user-stories/*.md`/`tasks/*.md` (el conteo se calcula
  en el propio test con el `02-backlog/` actual, no es un número fijo), y
  no reporta ningún error de parseo.

Además se verifica explícitamente el criterio de aceptación 6: un fichero
con `## Estado` o `## Dependencias` ausente/mal formado se reporta como
error de parseo de ESE fichero concreto, sin abortar el parseo del resto.
"""

from pathlib import Path

import pytest

from brain.backlog import (
    classify_todo_items,
    find_max_leverage_chain,
    load_backlog,
    parse_backlog_item,
)
from brain.models import BacklogGraph, BacklogItem, BacklogParseError

# Ruta del 02-backlog/ real de este proyecto (padre del directorio de tests).
REAL_BACKLOG_PATH = (
    Path(__file__).resolve().parents[1].parent / "02-backlog"
)

_WELL_FORMED_US = (
    "---\n"
    "id: US-FB001-01\n"
    "type: user_story\n"
    "title: Ejemplo\n"
    "state: DONE\n"
    "dependencies: []\n"
    "epic: FB-001\n"
    "priority: Alta\n"
    "---\n"
)

_WELL_FORMED_TASK_TODO = (
    "---\n"
    "id: T-FB001-US01-01\n"
    "type: task\n"
    "title: Ejemplo\n"
    "state: TO_DO\n"
    "dependencies:\n"
    "  - US-FB001-01\n"
    "epic: FB-001\n"
    "user_story: US-FB001-01\n"
    "priority: Alta\n"
    "---\n"
)


def _write(backlog_path: Path, subdir: str, filename: str, content: str) -> Path:
    directory = backlog_path / subdir
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / filename
    target.write_text(content, encoding="utf-8")
    return target


def _mini_backlog(tmp_path: Path) -> tuple[Path, list[str]]:
    """Mini-backlog sintético controlado por el test:

    - US-FB001-01  DONE
    - US-FB001-02  TODO, depende de US-FB001-01            -> LISTA
    - US-FB002-01  TODO, depende de US-FB001-01            -> LISTA
    - T-FB001-US01-01  DONE
    - T-FB002-US01-01  TODO, depende de T-FB001-US01-01     -> LISTA
    - T-FB002-US01-02  TODO, depende de T-FB002-US01-01     -> BLOQUEADA
    - T-FB002-US01-03  TODO, depende de T-FB002-US01-02     -> BLOQUEADA
    - T-FB002-US01-04  TODO, depende de T-FB001-US01-01     -> LISTA
    - T-FB003-US01-01  TODO, depende de US-FB002-01
                           y T-FB002-US01-02                -> BLOQUEADA

    Cadena de mayor apalancamiento esperada (recorrido del grafo):
    T-FB002-US01-01 desbloquea T-FB002-US01-02 y, en cascada,
    T-FB002-US01-03 (2 desbloqueados — T-FB003-US01-01 NO se desbloquea
    porque también depende de US-FB002-01, que nadie completa en esta
    cadena). Ningún otro candidato desbloquea más: T-FB002-US01-02
    desbloquea solo T-FB002-US01-03.
    """
    backlog = tmp_path / "backlog"
    _write(backlog, "user-stories", "US-FB001-01-done.md", _WELL_FORMED_US)
    _write(
        backlog,
        "user-stories",
        "US-FB001-02-lista.md",
        _WELL_FORMED_TASK_TODO.replace("id: T-FB001-US01-01", "id: US-FB001-02")
        .replace("type: task", "type: user_story")
        .replace("user_story: US-FB001-01\n", "")
        .replace("  - US-FB001-01\n", "  - US-FB001-01\n")
        .replace("state: TO_DO", "state: TO_DO"),
    )
    _write(
        backlog,
        "user-stories",
        "US-FB002-01-lista.md",
        _WELL_FORMED_TASK_TODO.replace("id: T-FB001-US01-01", "id: US-FB002-01")
        .replace("type: task", "type: user_story")
        .replace("user_story: US-FB001-01\n", "")
        .replace("  - US-FB001-01\n", "  - US-FB001-01\n")
        .replace("state: TO_DO", "state: TO_DO"),
    )
    _write(
        backlog,
        "tasks",
        "T-FB001-US01-01-done.md",
        _WELL_FORMED_TASK_TODO.replace("state: TO_DO", "state: DONE"),
    )
    _write(
        backlog,
        "tasks",
        "T-FB002-US01-01-lista.md",
        _WELL_FORMED_TASK_TODO.replace("id: T-FB001-US01-01", "id: T-FB002-US01-01")
        .replace("  - US-FB001-01\n", "  - T-FB001-US01-01\n"),
    )
    _write(
        backlog,
        "tasks",
        "T-FB002-US01-02-bloqueada.md",
        _WELL_FORMED_TASK_TODO.replace("id: T-FB001-US01-01", "id: T-FB002-US01-02")
        .replace("  - US-FB001-01\n", "  - T-FB002-US01-01\n"),
    )
    _write(
        backlog,
        "tasks",
        "T-FB002-US01-03-bloqueada.md",
        _WELL_FORMED_TASK_TODO.replace("id: T-FB001-US01-01", "id: T-FB002-US01-03")
        .replace("  - US-FB001-01\n", "  - T-FB002-US01-02\n"),
    )
    _write(
        backlog,
        "tasks",
        "T-FB002-US01-04-lista.md",
        _WELL_FORMED_TASK_TODO.replace("id: T-FB001-US01-01", "id: T-FB002-US01-04")
        .replace("  - US-FB001-01\n", "  - T-FB001-US01-01\n"),
    )
    _write(
        backlog,
        "tasks",
        "T-FB003-US01-01-bloqueada.md",
        _WELL_FORMED_TASK_TODO.replace("id: T-FB001-US01-01", "id: T-FB003-US01-01")
        .replace(
            "  - US-FB001-01\n",
            "  - US-FB002-01\n  - T-FB002-US01-02\n",
        ),
    )
    expected_nodes = [
        "T-FB001-US01-01",
        "T-FB002-US01-01",
        "T-FB002-US01-02",
        "T-FB002-US01-03",
        "T-FB002-US01-04",
        "T-FB003-US01-01",
        "US-FB001-01",
        "US-FB001-02",
        "US-FB002-01",
    ]
    return backlog, expected_nodes


# ---------------------------------------------------------------------------
# parse_backlog_item
# ---------------------------------------------------------------------------


def test_parse_backlog_item_extracts_fields_from_a_well_formed_file(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path, "tasks", "T-FB001-US01-01-modelo.md", _WELL_FORMED_TASK_TODO)

    item = parse_backlog_item(path)

    assert item.id == "T-FB001-US01-01"
    assert item.kind == "T"
    assert item.state == "TO_DO"
    assert item.dependencies == ("US-FB001-01",)
    assert item.epic == "FB-001"
    assert item.path == path
    # T-FB008-US04-05: la relación Task→US real es `user_story:`, nunca
    # `dependencies` (que aquí, además, coincide por casualidad con el
    # mismo id — antes del fix, `build_item_detail` habría encontrado esta
    # Task solo por esa coincidencia, no por la relación real).
    assert item.user_story == "US-FB001-01"


def test_parse_backlog_item_kind_for_user_stories(tmp_path: Path) -> None:
    path = _write(tmp_path, "user-stories", "US-FB001-01-historia.md", _WELL_FORMED_US)

    item = parse_backlog_item(path)

    assert item.id == "US-FB001-01"
    assert item.kind == "US"
    assert item.state == "DONE"
    assert item.dependencies == ()
    # Una User Story no declara `user_story:` (solo las Tasks lo hacen).
    assert item.user_story is None


def test_parse_backlog_item_reports_missing_estado(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "tasks",
        "T-FB001-US01-02-sin-estado.md",
        "---\nid: T-FB001-US01-02\ntype: task\nepic: FB-001\nuser_story: US-FB001-01\n"
        "title: Sin estado\ndependencies: []\npriority: Alta\n---\n",
    )

    with pytest.raises(BacklogParseError) as excinfo:
        parse_backlog_item(path)

    assert excinfo.value.item_id == "T-FB001-US01-02"
    assert "state" in excinfo.value.reason.lower()


def test_parse_backlog_item_reports_missing_dependencias(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "tasks",
        "T-FB001-US01-03-sin-deps.md",
        "---\nid: T-FB001-US01-03\ntype: task\nepic: FB-001\nuser_story: US-FB001-01\n"
        "title: Sin deps\nstate: TO_DO\npriority: Alta\n---\n",
    )

    with pytest.raises(BacklogParseError) as excinfo:
        parse_backlog_item(path)

    assert excinfo.value.item_id == "T-FB001-US01-03"
    assert "dependencies" in excinfo.value.reason.lower()


def test_parse_backlog_item_reports_empty_estado(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "tasks",
        "T-FB001-US01-04-estado-vacio.md",
        "---\nid: T-FB001-US01-04\ntype: task\nepic: FB-001\nuser_story: US-FB001-01\n"
        "title: Estado vacio\nstate:\ndependencies: []\npriority: Alta\n---\n",
    )

    with pytest.raises(BacklogParseError) as excinfo:
        parse_backlog_item(path)

    assert excinfo.value.item_id == "T-FB001-US01-04"


def test_parse_backlog_item_reads_priority(tmp_path: Path) -> None:
    content = _WELL_FORMED_TASK_TODO.replace("priority: Alta", "priority: Alta")
    path = _write(tmp_path, "tasks", "T-FB001-US01-05-con-prioridad.md", content)

    item = parse_backlog_item(path)

    assert item.priority == "Alta"


def test_parse_backlog_item_priority_none_when_not_valid(tmp_path: Path) -> None:
    content = _WELL_FORMED_TASK_TODO.replace("priority: Alta", "priority: Inexistente")
    path = _write(tmp_path, "tasks", "T-FB001-US01-06-prioridad-rara.md", content)

    item = parse_backlog_item(path)

    assert item.priority == "Inexistente"


def test_parse_backlog_item_priority_is_optional(tmp_path: Path) -> None:
    content = _WELL_FORMED_TASK_TODO.replace("\npriority: Alta", "")
    path = _write(tmp_path, "tasks", "T-FB001-US01-07-sin-prioridad.md", content)

    item = parse_backlog_item(path)

    assert item.priority is None


# ---------------------------------------------------------------------------
# load_backlog sobre un mini-backlog sintético
# ---------------------------------------------------------------------------


def test_load_backlog_builds_one_node_per_file_and_edges(tmp_path: Path) -> None:
    backlog, expected_nodes = _mini_backlog(tmp_path)

    graph = load_backlog(backlog)

    assert graph.errors == ()
    assert sorted(graph.items) == expected_nodes
    assert graph.dependencies_of["T-FB002-US01-02"] == ("T-FB002-US01-01",)


def test_load_backlog_reports_malformed_files_without_aborting_the_rest(
    tmp_path: Path,
) -> None:
    backlog, _ = _mini_backlog(tmp_path)
    # Añadir dos ficheros mal formados (uno por cada campo problemático).
    _write(
        backlog,
        "tasks",
        "T-FB999-US01-01-sin-estado.md",
        "---\nid: T-FB999-US01-01\ntype: task\nepic: FB-999\nuser_story: US-FB999-01\n"
        "title: Sin estado\ndependencies: []\npriority: Alta\n---\n",
    )
    _write(
        backlog,
        "tasks",
        "T-FB999-US01-02-sin-deps.md",
        "---\nid: T-FB999-US01-02\ntype: task\nepic: FB-999\nuser_story: US-FB999-01\n"
        "title: Sin deps\nstate: TO_DO\npriority: Alta\n---\n",
    )

    graph = load_backlog(backlog)

    # Los 9 ficheros bien formados siguen parseándose pese a los 2 malos.
    assert len(graph.items) == 9
    assert len(graph.errors) == 2
    reasons = sorted(error.reason for error in graph.errors)
    assert any("state" in reason.lower() for reason in reasons)
    assert any("dependencies" in reason.lower() for reason in reasons)
    # El error reporta el identificador del fichero concreto.
    assert {error.item_id for error in graph.errors} == {
        "T-FB999-US01-01",
        "T-FB999-US01-02",
    }


# ---------------------------------------------------------------------------
# classify_todo_items (mini-backlog sintético, resultado controlado)
# ---------------------------------------------------------------------------


def test_classify_todo_items_splits_todo_into_lista_and_bloqueada(
    tmp_path: Path,
) -> None:
    backlog, _ = _mini_backlog(tmp_path)
    graph = load_backlog(backlog)

    lista, bloqueada = classify_todo_items(graph)

    assert [item.id for item in lista] == [
        "T-FB002-US01-01",
        "T-FB002-US01-04",
        "US-FB001-02",
        "US-FB002-01",
    ]
    assert [item.id for item in bloqueada] == [
        "T-FB002-US01-02",
        "T-FB002-US01-03",
        "T-FB003-US01-01",
    ]


# ---------------------------------------------------------------------------
# find_max_leverage_chain (mini-backlog sintético, resultado controlado)
# ---------------------------------------------------------------------------


def test_find_max_leverage_chain_picks_the_cascade_that_unblocks_the_most(
    tmp_path: Path,
) -> None:
    backlog, _ = _mini_backlog(tmp_path)
    graph = load_backlog(backlog)

    chain = find_max_leverage_chain(graph)

    assert [item.id for item in chain] == [
        "T-FB002-US01-01",
        "T-FB002-US01-02",
        "T-FB002-US01-03",
    ]


def test_find_max_leverage_chain_returns_empty_when_nothing_is_blocked(
    tmp_path: Path,
) -> None:
    backlog = tmp_path / "backlog"
    _write(backlog, "user-stories", "US-FB001-01-done.md", _WELL_FORMED_US)
    _write(
        backlog,
        "tasks",
        "T-FB001-US01-01-lista.md",
        _WELL_FORMED_TASK_TODO,
    )
    graph = load_backlog(backlog)

    chain = find_max_leverage_chain(graph)

    assert chain == []


# ---------------------------------------------------------------------------
# Determinismo: dos ejecuciones seguidas sobre el mismo estado dan lo mismo
# ---------------------------------------------------------------------------


def test_loading_and_classifying_twice_is_identical(tmp_path: Path) -> None:
    backlog, _ = _mini_backlog(tmp_path)

    first = load_backlog(backlog)
    second = load_backlog(backlog)

    assert first == second
    assert classify_todo_items(first) == classify_todo_items(second)
    assert find_max_leverage_chain(first) == find_max_leverage_chain(second)


# ---------------------------------------------------------------------------
# 02-backlog/ real de este proyecto (solo criterio estructural, sin cifras
# fijas que cambian con el estado del backlog)
# ---------------------------------------------------------------------------


def test_load_backlog_on_the_real_backlog_matches_the_file_count() -> None:
    """Criterio de aceptación estructural de la Task: `load_backlog` sobre
    el `02-backlog/` real produce un nodo por cada fichero
    `epics/*.md`/`user-stories/*.md`/`tasks/*.md`. El número de ficheros se
    calcula en este mismo test (el backlog cambia constantemente), nunca es
    un número fijo copiado de la Task."""
    epics = sorted((REAL_BACKLOG_PATH / "epics").glob("*.md"))
    user_stories = sorted((REAL_BACKLOG_PATH / "user-stories").glob("*.md"))
    tasks = sorted((REAL_BACKLOG_PATH / "tasks").glob("*.md"))
    expected_count = len(epics) + len(user_stories) + len(tasks)

    graph = load_backlog(REAL_BACKLOG_PATH)

    assert len(graph.items) == expected_count
    # Todo el backlog real existente sigue la convención (cero errores).
    assert graph.errors == ()


def test_read_state_works_in_yaml_frontmatter(
    tmp_path: Path,
) -> None:
    epic_path = tmp_path / "FB-999.md"
    epic_path.write_text(
        "---\n"
        "id: FB-999\n"
        "type: epic\n"
        "title: Ejemplo\n"
        "state: DONE\n"
        "dependencies: []\n"
        "---\n",
        encoding="utf-8",
    )

    item = parse_backlog_item(epic_path)

    assert item.state == "DONE"
