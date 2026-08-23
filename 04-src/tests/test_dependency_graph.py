"""Tests de AF-026: grafo de dependencias, nivel topologico, hilos y
reparto (US-AF026-01 a US-AF026-03).

El caso real de AF-022 (34 Tasks, 4 hilos, con el cruce Tester->paralelismo
Developer ya detectado manualmente) se usa como fixture para verificar que
la implementacion reproduce ese resultado.
"""

from pathlib import Path

import pytest

from atlas_forge.backlog.dependency_graph import (
    CrossEdge,
    RepartoItem,
    TaskGraph,
    Thread,
    ThreadAnalysis,
    analyze_epic_threads,
    build_task_graph,
    compute_topological_levels,
    generate_reparto_recommendation,
    group_threads_and_detect_crosses,
)
from atlas_forge.backlog.parser import load_backlog, parse_backlog_item
from atlas_forge.models import BacklogGraph, BacklogItem, BacklogParseError

def _yaml_list(items: list[str]) -> str:
    if not items:
        return " []"
    return "\n" + "\n".join(f"  - {item}" for item in items)


def _make_task(task_id: str, us_id: str, deps: list[str],
               epic: str = "AF-022", state: str = "READY") -> str:
    return (
        "---\n"
        f"id: {task_id}\n"
        "type: task\n"
        f"title: {task_id}\n"
        f"state: {state}\n"
        f"dependencies:{_yaml_list(deps)}\n"
        f"epic: {epic}\n"
        f"user_story: {us_id}\n"
        "priority: Alta\n"
        "---\n"
    )


def _make_us(us_id: str, epic: str = "AF-022", deps: list[str] | None = None,
             state: str = "READY") -> str:
    deps = deps or []
    return (
        "---\n"
        f"id: {us_id}\n"
        "type: user_story\n"
        f"title: {us_id}\n"
        f"state: {state}\n"
        f"dependencies:{_yaml_list(deps)}\n"
        f"epic: {epic}\n"
        "priority: Alta\n"
        "---\n"
    )


def _make_epic(epic_id: str, state: str = "READY") -> str:
    return (
        "---\n"
        f"id: {epic_id}\n"
        "type: epic\n"
        f"title: {epic_id}\n"
        f"state: {state}\n"
        "dependencies: []\n"
        "---\n"
    )


def _write(backlog_path: Path, subdir: str, filename: str, content: str) -> Path:
    directory = backlog_path / subdir
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / filename
    target.write_text(content, encoding="utf-8")
    return target


def _af022_fixture(tmp_path: Path) -> tuple[Path, list[str]]:
    """Backlog sintetico que reproduce la estructura de dependencias real de
    AF-022: 34 Tasks, 4 hilos tematicos, con los cruces detectados
    manualmente en el informe de reconfiguracion.

    Hilos esperados:
      hilo-1: US01 (Generalizar registro, Director, Arquitecto)
      hilo-2: US02+US03+US03A+US08 (Generador propuesta, Tasks, validador)
      hilo-3: US05+US06+US07+US09+US10+US11 (Veredicto, Developer, Cola, Modelos)
      hilo-4: US12 (Tester) — cruza con hilo-3 via T-AF022-US12-01 -> US-AF022-06
    """
    backlog = tmp_path / "backlog"

    tasks: list[tuple[str, str, list[str]]] = [
        ("T-AF022-US01-01", "US-AF022-01", []),
        ("T-AF022-US01-02", "US-AF022-01", ["T-AF022-US01-01"]),
        ("T-AF022-US01-03", "US-AF022-01", ["T-AF022-US01-01"]),
        ("T-AF022-US02-01", "US-AF022-02", ["T-AF022-US01-01"]),
        ("T-AF022-US02-02", "US-AF022-02", ["T-AF022-US02-01", "T-AF022-US03A-01"]),
        ("T-AF022-US02-03", "US-AF022-02", ["T-AF022-US02-02"]),
        ("T-AF022-US02-04", "US-AF022-02", ["T-AF022-US02-03"]),
        ("T-AF022-US03-01", "US-AF022-03", ["T-AF022-US01-01"]),
        ("T-AF022-US03-02", "US-AF022-03", ["T-AF022-US03-01"]),
        ("T-AF022-US03-03", "US-AF022-03",
         ["T-AF022-US03-02", "T-AF022-US02-02", "T-AF022-US02-03"]),
        ("T-AF022-US03A-01", "US-AF022-03A", []),
        ("T-AF022-US05-01", "US-AF022-05", ["T-AF022-US01-03"]),
        ("T-AF022-US05-02", "US-AF022-05",
         ["T-AF022-US05-01", "US-AF022-06"]),
        ("T-AF022-US05-03", "US-AF022-05", ["T-AF022-US05-02"]),
        ("T-AF022-US06-01", "US-AF022-06", []),
        ("T-AF022-US06-02", "US-AF022-06", ["T-AF022-US06-01"]),
        ("T-AF022-US06-03", "US-AF022-06", ["T-AF022-US06-02"]),
        ("T-AF022-US06-04", "US-AF022-06", ["T-AF022-US06-03"]),
        ("T-AF022-US07-01", "US-AF022-07", ["T-AF022-US05-02", "T-AF022-US06-02"]),
        ("T-AF022-US07-02", "US-AF022-07", ["T-AF022-US07-01"]),
        ("T-AF022-US08-01", "US-AF022-08", ["T-AF022-US02-04"]),
        ("T-AF022-US08-02", "US-AF022-08", ["T-AF022-US08-01"]),
        ("T-AF022-US09-01", "US-AF022-09", []),
        ("T-AF022-US09-02", "US-AF022-09", ["T-AF022-US09-01"]),
        ("T-AF022-US09-03", "US-AF022-09", ["T-AF022-US09-02"]),
        ("T-AF022-US10-01", "US-AF022-10", ["US-AF022-09"]),
        ("T-AF022-US10-02", "US-AF022-10", ["T-AF022-US10-01"]),
        ("T-AF022-US10-03", "US-AF022-10", ["T-AF022-US10-01"]),
        ("T-AF022-US11-01", "US-AF022-11", ["US-AF022-09", "US-AF022-10"]),
        ("T-AF022-US11-02", "US-AF022-11", ["T-AF022-US11-01"]),
        ("T-AF022-US12-01", "US-AF022-12",
         ["US-AF022-06"]),
        ("T-AF022-US12-02", "US-AF022-12", ["T-AF022-US12-01"]),
        ("T-AF022-US12-03", "US-AF022-12", ["T-AF022-US12-02"]),
        ("T-AF022-US12-04", "US-AF022-12",
         ["T-AF022-US12-03", "T-AF022-US06-03"]),
    ]

    us_ids = sorted(set(t[1] for t in tasks))
    for us_id in us_ids:
        _write(backlog, "user-stories", f"{us_id}-test.md", _make_us(us_id))

    for task_id, us_id, deps in tasks:
        _write(backlog, "tasks", f"{task_id}.md", _make_task(task_id, us_id, deps))

    expected_nodes = [t[0] for t in tasks] + us_ids
    return backlog, sorted(expected_nodes)


# ------------------------------------------------------------------ US01-01
# build_task_graph


class TestBuildTaskGraph:
    def test_builds_graph_with_correct_n_nodes(self, tmp_path: Path):
        backlog_path, _ = _af022_fixture(tmp_path)
        graph = load_backlog(backlog_path)
        task_graph = build_task_graph(graph, "AF-022")
        assert len(task_graph.nodes) == 34
        assert task_graph.epic == "AF-022"

    def test_task_with_no_deps_has_empty_edges(self, tmp_path: Path):
        backlog_path, _ = _af022_fixture(tmp_path)
        graph = load_backlog(backlog_path)
        task_graph = build_task_graph(graph, "AF-022")
        assert task_graph.edges["T-AF022-US01-01"] == ()
        assert task_graph.edges["T-AF022-US03A-01"] == ()

    def test_task_with_explicit_task_dep_has_edge(self, tmp_path: Path):
        backlog_path, _ = _af022_fixture(tmp_path)
        graph = load_backlog(backlog_path)
        task_graph = build_task_graph(graph, "AF-022")
        assert "T-AF022-US01-01" in task_graph.edges["T-AF022-US01-02"]

    def test_us_dependency_resolves_to_all_tasks(self, tmp_path: Path):
        """US-AF022-06 -> T-AF022-US06-01/02/03/04 via _resolve_us_deps."""
        backlog_path, _ = _af022_fixture(tmp_path)
        graph = load_backlog(backlog_path)
        task_graph = build_task_graph(graph, "AF-022")

        t12_01_deps = task_graph.edges.get("T-AF022-US12-01", ())
        for tid in ("T-AF022-US06-01", "T-AF022-US06-02",
                     "T-AF022-US06-03", "T-AF022-US06-04"):
            assert tid in t12_01_deps, (
                f"T-AF022-US12-01 should depend on {tid} (US-AF022-06 resolved)"
            )

    def test_missing_refs_reported(self, tmp_path: Path):
        """AF-022 fixture no tiene referencias rotas (todas las US existen)."""
        backlog_path, _ = _af022_fixture(tmp_path)
        graph = load_backlog(backlog_path)
        task_graph = build_task_graph(graph, "AF-022")
        assert task_graph.missing_refs == ()

    def test_missing_ref_reported_for_nonexistent_task(self, tmp_path: Path):
        """Una dependencia a un ID que no existe se reporta en missing_refs."""
        backlog = tmp_path / "backlog"
        _make_task_for = lambda tid, us, deps: _make_task(tid, us, deps, epic="AF-099")
        _make_us_for = lambda us: _make_us(us, epic="AF-099")

        _write(backlog, "tasks", "T-AF099-US99-01.md",
               _make_task_for("T-AF099-US99-01", "US-AF099-99",
                              ["T-AF099-US99-99"]))
        _write(backlog, "tasks", "T-AF099-US99-02.md",
               _make_task_for("T-AF099-US99-02", "US-AF099-99",
                              ["T-AF099-US99-01"]))
        _write(backlog, "user-stories", "US-AF099-99-test.md", _make_us_for("US-AF099-99"))

        graph = load_backlog(backlog)
        task_graph = build_task_graph(graph, "AF-099")
        assert "T-AF099-US99-99" in task_graph.missing_refs

    def test_empty_epic_returns_empty_graph(self, tmp_path: Path):
        backlog = tmp_path / "backlog"
        _write(backlog, "tasks", "T-AF001-US01-01-done.md",
               _make_task("T-AF001-US01-01", "US-AF001-01", [], state="DONE"))
        graph = load_backlog(backlog)
        task_graph = build_task_graph(graph, "AF-999")
        assert len(task_graph.nodes) == 0
        assert task_graph.missing_refs == ()


# ------------------------------------------------------------------ US02-01
# compute_topological_levels


class TestTopologicalLevels:
    def test_root_tasks_have_level_zero(self, tmp_path: Path):
        backlog_path, _ = _af022_fixture(tmp_path)
        graph = load_backlog(backlog_path)
        task_graph = build_task_graph(graph, "AF-022")
        levels = compute_topological_levels(task_graph)

        assert levels["T-AF022-US01-01"] == 0
        assert levels["T-AF022-US03A-01"] == 0
        assert levels["T-AF022-US06-01"] == 0
        assert levels["T-AF022-US09-01"] == 0

    def test_direct_dep_increases_level(self, tmp_path: Path):
        backlog_path, _ = _af022_fixture(tmp_path)
        graph = load_backlog(backlog_path)
        task_graph = build_task_graph(graph, "AF-022")
        levels = compute_topological_levels(task_graph)

        assert levels["T-AF022-US01-02"] >= 1

    def test_chain_increases_progressively(self, tmp_path: Path):
        backlog_path, _ = _af022_fixture(tmp_path)
        graph = load_backlog(backlog_path)
        task_graph = build_task_graph(graph, "AF-022")
        levels = compute_topological_levels(task_graph)

        assert levels["T-AF022-US06-01"] == 0
        assert levels["T-AF022-US06-02"] >= 1
        assert levels["T-AF022-US06-03"] >= 2
        assert levels["T-AF022-US06-04"] >= 3

    def test_cycle_detected_raises_value_error(self, tmp_path: Path):
        backlog = tmp_path / "backlog"
        _write(backlog, "epics", "AF-099.md", _make_epic("AF-099"))
        _write(backlog, "tasks", "T-AF099-US01-01.md", _make_task(
            "T-AF099-US01-01", "US-AF099-01", ["T-AF099-US01-02"],
            epic="AF-099"))
        _write(backlog, "tasks", "T-AF099-US01-02.md", _make_task(
            "T-AF099-US01-02", "US-AF099-01", ["T-AF099-US01-01"],
            epic="AF-099"))
        _write(backlog, "user-stories", "US-AF099-01-test.md",
               _make_us("US-AF099-01", epic="AF-099"))

        graph = load_backlog(backlog)
        task_graph = build_task_graph(graph, "AF-099")

        with pytest.raises(ValueError, match="Ciclo detectado"):
            compute_topological_levels(task_graph)

    def test_all_tasks_have_level(self, tmp_path: Path):
        backlog_path, _ = _af022_fixture(tmp_path)
        graph = load_backlog(backlog_path)
        task_graph = build_task_graph(graph, "AF-022")
        levels = compute_topological_levels(task_graph)

        assert len(levels) == 34
        for tid in task_graph.nodes:
            assert tid in levels, f"{tid} should have a topological level"


# ------------------------------------------------------------------ US02-02
# group_threads_and_detect_crosses


class TestGroupThreads:
    def test_produces_4_threads_for_af022(self, tmp_path: Path):
        """Caso real de AF-022: 34 Tasks agrupadas en 4 hilos."""
        backlog_path, _ = _af022_fixture(tmp_path)
        graph = load_backlog(backlog_path)
        task_graph = build_task_graph(graph, "AF-022")
        threads, crosses = group_threads_and_detect_crosses(task_graph)

        assert len(threads) == 4, (
            f"Expected exactly 4 threads, got {len(threads)}"
        )

    def test_detects_cross_between_threads(self, tmp_path: Path):
        """Caso real de AF-022: se detectan exactamente 3 cruces entre
        hilos (corrección 2026-08-06: deduplicados por (from_task,
        to_thread) — antes de la corrección, la falta de deduplicación
        producía 6 cruces al contar cada arista individual en vez de cada
        punto de sincronización real). El cruce manual (Tester US12 ->
        Developer US06) se materializa como US12 siguiendo la cadena de
        US06 (todas sus deps son de US06), mientras que los cruces reales
        del algoritmo son US02(Arquitecto)->US03A(Validador),
        US05(Veredicto)->US06(Developer), US07(Cola)->US06(Developer)."""
        backlog_path, _ = _af022_fixture(tmp_path)
        graph = load_backlog(backlog_path)
        task_graph = build_task_graph(graph, "AF-022")
        threads, crosses = group_threads_and_detect_crosses(task_graph)

        assert len(crosses) == 3, (
            f"Expected exactly 3 crosses, got {len(crosses)}: {crosses}"
        )
        cross_pairs = {(c.from_task, c.to_task) for c in crosses}
        assert any(to.startswith("T-AF022-US06") for _, to in cross_pairs), (
            f"Cruce hacia Developer (US06) no detectado. Cruces: {cross_pairs}"
        )
        assert ("T-AF022-US02-02", "T-AF022-US03A-01") in cross_pairs, (
            f"Cruce US02 -> US03A no detectado. Cruces: {cross_pairs}"
        )

    def test_crosses_deduplicated_by_task_and_target_thread(
        self, tmp_path: Path
    ):
        """Regresión (corrección 2026-08-06): una Task con varias
        dependencias en el mismo hilo destino (T-AF022-US05-02 depende de
        las 4 Tasks de T-AF022-US06-*) cuenta como UN solo cruce, no uno
        por cada arista — pero dos Tasks DISTINTAS del mismo hilo origen
        dependiendo del mismo hilo destino (US05-02 y US07-01, ambas ->
        hilo-3) siguen siendo dos cruces reales, no se colapsan entre sí."""
        backlog_path, _ = _af022_fixture(tmp_path)
        graph = load_backlog(backlog_path)
        task_graph = build_task_graph(graph, "AF-022")
        _threads, crosses = group_threads_and_detect_crosses(task_graph)

        exact_pairs = {(c.from_task, c.to_task) for c in crosses}
        assert exact_pairs == {
            ("T-AF022-US02-02", "T-AF022-US03A-01"),
            ("T-AF022-US05-02", "T-AF022-US06-01"),
            ("T-AF022-US07-01", "T-AF022-US06-02"),
        }, f"Cruces exactos no coinciden: {exact_pairs}"

    def test_no_crosses_for_linear_chain(self, tmp_path: Path):
        """3 Tasks en cadena lineal: sin cruces."""
        backlog = tmp_path / "backlog"
        _write(backlog, "tasks", "T-AF099-US01-01.md", _make_task(
            "T-AF099-US01-01", "US-AF099-01", [], epic="AF-099"))
        _write(backlog, "tasks", "T-AF099-US01-02.md", _make_task(
            "T-AF099-US01-02", "US-AF099-01", ["T-AF099-US01-01"],
            epic="AF-099"))
        _write(backlog, "tasks", "T-AF099-US01-03.md", _make_task(
            "T-AF099-US01-03", "US-AF099-01", ["T-AF099-US01-02"],
            epic="AF-099"))
        _write(backlog, "user-stories", "US-AF099-01-test.md",
               _make_us("US-AF099-01", epic="AF-099"))

        graph = load_backlog(backlog)
        task_graph = build_task_graph(graph, "AF-099")
        threads, crosses = group_threads_and_detect_crosses(task_graph)

        assert len(threads) == 1
        assert crosses == []

    def test_independent_tasks_go_to_different_threads(self, tmp_path: Path):
        """Dos Tasks del mismo nivel sin relacion: hilos distintos."""
        backlog = tmp_path / "backlog"
        _write(backlog, "tasks", "T-AF099-US01-01.md", _make_task(
            "T-AF099-US01-01", "US-AF099-01", [], epic="AF-099"))
        _write(backlog, "tasks", "T-AF099-US02-01.md", _make_task(
            "T-AF099-US02-01", "US-AF099-02", [], epic="AF-099"))
        _write(backlog, "user-stories", "US-AF099-01-test.md",
               _make_us("US-AF099-01", epic="AF-099"))
        _write(backlog, "user-stories", "US-AF099-02-test.md",
               _make_us("US-AF099-02", epic="AF-099"))

        graph = load_backlog(backlog)
        task_graph = build_task_graph(graph, "AF-099")
        threads, crosses = group_threads_and_detect_crosses(task_graph)

        assert len(threads) >= 2, (
            f"Independent tasks should be in different threads, got {len(threads)}"
        )


# ------------------------------------------------------------------ US03-01
# generate_reparto_recommendation


class TestReparto:
    def test_reparto_with_one_agent_assigns_all_to_same(self, tmp_path: Path):
        backlog_path, _ = _af022_fixture(tmp_path)
        graph = load_backlog(backlog_path)
        analysis = analyze_epic_threads(graph, "AF-022")
        reparto = generate_reparto_recommendation(analysis, num_agents=1)

        assert len(reparto) == len(analysis.threads)
        for item in reparto:
            assert item.agent_index == 0

    def test_reparto_with_two_agents_distributes(self, tmp_path: Path):
        backlog_path, _ = _af022_fixture(tmp_path)
        graph = load_backlog(backlog_path)
        analysis = analyze_epic_threads(graph, "AF-022")
        reparto = generate_reparto_recommendation(analysis, num_agents=2)

        assert len(reparto) == len(analysis.threads)

    def test_reparto_includes_all_required_fields(self, tmp_path: Path):
        backlog_path, _ = _af022_fixture(tmp_path)
        graph = load_backlog(backlog_path)
        analysis = analyze_epic_threads(graph, "AF-022")
        reparto = generate_reparto_recommendation(analysis, num_agents=2)

        for item in reparto:
            assert item.thread_id
            assert len(item.tasks) > 0
            assert item.start_level >= 0
            assert item.agent_index >= 0

    def test_reparto_ordered_by_start_level(self, tmp_path: Path):
        backlog_path, _ = _af022_fixture(tmp_path)
        graph = load_backlog(backlog_path)
        analysis = analyze_epic_threads(graph, "AF-022")
        reparto = generate_reparto_recommendation(analysis, num_agents=2)

        start_levels = [item.start_level for item in reparto]
        assert start_levels == sorted(start_levels), (
            "Reparto should be ordered by start_level ascending"
        )

    def test_zero_agents_raises(self, tmp_path: Path):
        backlog_path, _ = _af022_fixture(tmp_path)
        graph = load_backlog(backlog_path)
        analysis = analyze_epic_threads(graph, "AF-022")

        with pytest.raises(ValueError):
            generate_reparto_recommendation(analysis, num_agents=0)


# ------------------------------------------------------------------ US01/02/03
# analyze_epic_threads (integration)


class TestAnalyzeEpicThreads:
    def test_full_analysis_produces_thread_analysis(self, tmp_path: Path):
        backlog_path, _ = _af022_fixture(tmp_path)
        graph = load_backlog(backlog_path)
        analysis = analyze_epic_threads(graph, "AF-022")

        assert isinstance(analysis, ThreadAnalysis)
        assert analysis.epic == "AF-022"
        assert len(analysis.threads) >= 4
        assert len(analysis.topological_levels) == 34

    def test_all_tasks_in_threads_sum_to_34(self, tmp_path: Path):
        backlog_path, _ = _af022_fixture(tmp_path)
        graph = load_backlog(backlog_path)
        analysis = analyze_epic_threads(graph, "AF-022")

        total_tasks = sum(len(thread.tasks) for thread in analysis.threads)
        assert total_tasks == 34, (
            f"All 34 tasks should be in threads, got {total_tasks}"
        )

    def test_cross_detected_has_both_threads_different(self, tmp_path: Path):
        backlog_path, _ = _af022_fixture(tmp_path)
        graph = load_backlog(backlog_path)
        analysis = analyze_epic_threads(graph, "AF-022")

        for cross in analysis.crosses:
            assert cross.from_thread != cross.to_thread, (
                f"Cross {cross.from_task} -> {cross.to_task} "
                f"should connect different threads, "
                f"got {cross.from_thread} -> {cross.to_thread}"
            )

    def test_deterministic_across_calls(self, tmp_path: Path):
        backlog_path, _ = _af022_fixture(tmp_path)
        graph = load_backlog(backlog_path)
        a1 = analyze_epic_threads(graph, "AF-022")
        a2 = analyze_epic_threads(graph, "AF-022")

        assert a1 == a2, "Two calls with same input should produce identical results"

    def test_cycle_in_epic_propagates(self, tmp_path: Path):
        backlog = tmp_path / "backlog"
        _write(backlog, "tasks", "T-AF099-US01-01.md", _make_task(
            "T-AF099-US01-01", "US-AF099-01", ["T-AF099-US01-02"],
            epic="AF-099"))
        _write(backlog, "tasks", "T-AF099-US01-02.md", _make_task(
            "T-AF099-US01-02", "US-AF099-01", ["T-AF099-US01-01"],
            epic="AF-099"))
        _write(backlog, "user-stories", "US-AF099-01-test.md",
               _make_us("US-AF099-01", epic="AF-099"))

        graph = load_backlog(backlog)

        with pytest.raises(ValueError, match="Ciclo detectado"):
            analyze_epic_threads(graph, "AF-099")


# ------------------------------------------------------------------ US03-02
# persist_thread_analysis + format_thread_analysis_markdown


class TestPersistAnalysis:
    def test_format_produces_markdown_with_all_sections(self, tmp_path: Path):
        from atlas_forge.backlog.dependency_graph import format_thread_analysis_markdown

        backlog_path, _ = _af022_fixture(tmp_path)
        graph = load_backlog(backlog_path)
        analysis = analyze_epic_threads(graph, "AF-022")
        md = format_thread_analysis_markdown(analysis, num_agents=2)

        assert "AF-022" in md
        assert "## hilo-" in md
        assert "## Cruces entre hilos" in md
        assert "## Recomendacion de reparto" in md

    def test_persist_creates_file_with_unique_path(self, tmp_path: Path):
        from atlas_forge.backlog.dependency_graph import persist_thread_analysis

        backlog_path, _ = _af022_fixture(tmp_path)
        graph = load_backlog(backlog_path)
        analysis = analyze_epic_threads(graph, "AF-022")

        reports_root = tmp_path / "07-informes"
        path1 = persist_thread_analysis(analysis, num_agents=2,
                                         reports_root=reports_root)
        assert path1.exists()
        assert "analisis-hilos-" in path1.name

        content = path1.read_text(encoding="utf-8")
        assert "AF-022" in content

    def test_persist_two_executions_no_overwrite(self, tmp_path: Path):
        from atlas_forge.backlog.dependency_graph import persist_thread_analysis

        backlog_path, _ = _af022_fixture(tmp_path)
        graph = load_backlog(backlog_path)
        analysis = analyze_epic_threads(graph, "AF-022")

        reports_root = tmp_path / "07-informes"
        path1 = persist_thread_analysis(analysis, num_agents=2,
                                         reports_root=reports_root)
        path2 = persist_thread_analysis(analysis, num_agents=3,
                                         reports_root=reports_root)

        assert path1 != path2
        assert path1.exists()
        assert path2.exists()

        files = list((reports_root / "AF-022").glob("analisis-hilos-*.md"))
        assert len(files) >= 2

    def test_missing_refs_included_in_report(self, tmp_path: Path):
        from atlas_forge.backlog.dependency_graph import format_thread_analysis_markdown

        backlog = tmp_path / "backlog"
        _write(backlog, "tasks", "T-AF099-US01-01.md", _make_task(
            "T-AF099-US01-01", "US-AF099-01",
            ["T-AF099-US99-99"],
            epic="AF-099"))
        _write(backlog, "user-stories", "US-AF099-01-test.md",
               _make_us("US-AF099-01", epic="AF-099"))

        graph = load_backlog(backlog)
        analysis = analyze_epic_threads(graph, "AF-099")
        md = format_thread_analysis_markdown(analysis)

        assert "Dependencias no resueltas" in md
        assert "T-AF099-US99-99" in md
