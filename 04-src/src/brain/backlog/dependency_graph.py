"""Grafo de dependencias, nivel topologico y hilos de desarrollo
para una Epic (FB-026): construccion del grafo (US01-01), calculo de nivel
topologico (US02-01), agrupacion en hilos y deteccion de cruces (US02-02),
y recomendacion de reparto entre agentes (US03-01).

Reutiliza los datos ya extraidos por `brain.backlog.parser` — no
reimplementa el parseo de ficheros, solo construye el grafo y el analisis
de hilos sobre los datos ya extraidos.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from brain.models.backlog import (
    BacklogGraph,
    BacklogItem,
    ITEM_KIND_TASK,
    ITEM_KIND_USER_STORY,
)


@dataclass(frozen=True)
class TaskGraph:
    """Grafo dirigido de dependencias entre Tasks de una sola Epic.

    Nodos = Tasks de la Epic. Aristas = dependencias declaradas.
    Dependencias a nivel de US se resuelven a todas las Tasks de esa US.
    Referencias a Task/US inexistente se reportan en `missing_refs`.
    """

    epic: str
    nodes: Mapping[str, BacklogItem]
    edges: Mapping[str, tuple[str, ...]]
    missing_refs: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Thread:
    """Un hilo de desarrollo: secuencia de Tasks conectadas por dependencia
    directa dentro de la misma cadena."""

    id: str
    tasks: tuple[BacklogItem, ...]
    start_level: int


@dataclass(frozen=True)
class CrossEdge:
    """Un cruce entre hilos: una Task de un hilo que depende de una Task de
    otro hilo distinto."""

    from_task: str
    from_thread: str
    to_task: str
    to_thread: str


@dataclass(frozen=True)
class ThreadAnalysis:
    """Resultado completo del analisis de hilos de una Epic.

    - threads: hilos en el orden recomendado de lanzamiento.
    - topological_levels: nivel topologico por Task.
    - crosses: aristas que cruzan entre hilos.
    - missing_refs: dependencias a nodos que no existen en el grafo.
    """

    epic: str
    threads: tuple[Thread, ...]
    topological_levels: Mapping[str, int]
    crosses: tuple[CrossEdge, ...]
    missing_refs: tuple[str, ...]


@dataclass(frozen=True)
class RepartoItem:
    """Recomendacion de asignacion de un hilo a un agente."""

    thread_id: str
    tasks: tuple[str, ...]
    start_level: int
    agent_index: int


def _resolve_us_deps(
    graph: BacklogGraph, epic_prefix: str, dep_id: str
) -> tuple[str, ...]:
    """Si `dep_id` es una US de la Epic, la resuelve a todas las Tasks de
    esa US que pertenecen a la misma Epic. Si es una Task, la devuelve tal
    cual. Si no existe en el grafo, se reporta como missing."""
    item = graph.items.get(dep_id)
    if item is None:
        return ()
    raw_prefix = epic_prefix.rstrip("-")
    if item.kind == ITEM_KIND_USER_STORY and (
        item.epic is not None and item.epic.strip().startswith(raw_prefix)
    ):
        parts = dep_id.split("-")
        if len(parts) >= 3:
            fb_num = parts[1]
            us_num = parts[2]
            task_prefix = f"T-{fb_num}-US{us_num}-"
            tasks = tuple(
                t.id
                for t in graph.items.values()
                if t.kind == ITEM_KIND_TASK
                and t.epic is not None
                and t.epic.strip().startswith(raw_prefix)
                and t.id.startswith(task_prefix)
            )
            return tasks
        return ()
    if item.kind == ITEM_KIND_TASK and (
        item.epic is not None and item.epic.strip().startswith(raw_prefix)
    ):
        return (dep_id,)
    return ()


def build_task_graph(graph: BacklogGraph, epic_prefix: str) -> TaskGraph:
    """Construye el grafo dirigido de dependencias entre las Tasks de una
    Epic a partir del `BacklogGraph` ya parseado.

    - Cada Task de la Epic es un nodo.
    - Cada dependencia declarada genera una arista.
    - Una dependencia a nivel de US se resuelve a todas las Tasks de esa US
      dentro de la misma Epic.
    - Una referencia a Task/US inexistente (o fuera de la Epic) se reporta
      en `missing_refs` — no falla en silencio ni se ignora.
    """
    raw_prefix = epic_prefix.rstrip("-")

    nodes: dict[str, BacklogItem] = {}
    edges: dict[str, tuple[str, ...]] = {}
    missing_refs_list: list[str] = []

    for item in graph.items.values():
        if item.kind != ITEM_KIND_TASK:
            continue
        if item.epic is None or not item.epic.strip().startswith(raw_prefix):
            continue
        nodes[item.id] = item

    for task_id, item in nodes.items():
        resolved: list[str] = []
        for dep_id in item.dependencies:
            expanded = _resolve_us_deps(graph, epic_prefix, dep_id)
            if expanded:
                resolved.extend(expanded)
            else:
                dep_item = graph.items.get(dep_id)
                if dep_item is not None and dep_item.kind == ITEM_KIND_USER_STORY:
                    if dep_item.epic is None or not dep_item.epic.strip().startswith(
                        raw_prefix
                    ):
                        missing_refs_list.append(dep_id)
                    else:
                        missing_refs_list.append(dep_id)
                elif dep_id not in nodes:
                    missing_refs_list.append(dep_id)
        edges[task_id] = tuple(sorted(set(resolved)))

    return TaskGraph(
        epic=epic_prefix,
        nodes=nodes,
        edges=edges,
        missing_refs=tuple(sorted(set(missing_refs_list))),
    )


def compute_topological_levels(task_graph: TaskGraph) -> Mapping[str, int]:
    """Calcula el nivel topologico de cada Task del grafo.

    - 0 si no depende de nada dentro de la Epic.
    - N+1 si depende de al menos una Task de nivel N.

    Un ciclo en el grafo se reporta como `ValueError` con la lista de
    Tasks involucradas — no produce un calculo infinito ni silencioso.
    """
    levels: dict[str, int] = {}
    in_degree: dict[str, int] = {}

    for task_id in task_graph.nodes:
        in_degree[task_id] = 0

    for task_id, deps in task_graph.edges.items():
        for dep_id in deps:
            if dep_id in in_degree:
                in_degree[task_id] = in_degree.get(task_id, 0) + 1

    queue = deque(
        task_id for task_id, deg in in_degree.items() if deg == 0
    )

    for task_id in queue:
        levels[task_id] = 0

    processed = 0
    while queue:
        current = queue.popleft()
        processed += 1
        current_level = levels[current]

        for task_id, deps in task_graph.edges.items():
            if current in deps:
                new_level = current_level + 1
                existing = levels.get(task_id)
                if existing is None or new_level > existing:
                    levels[task_id] = new_level
                in_degree[task_id] = in_degree.get(task_id, 1) - 1
                if in_degree.get(task_id, 0) == 0:
                    queue.append(task_id)

    remaining = sorted(
        tid for tid in task_graph.nodes if tid not in levels
    )
    if remaining:
        raise ValueError(
            f"Ciclo detectado en el grafo de dependencias de "
            f"'{task_graph.epic}'. Tareas involucradas en el ciclo: "
            f"{', '.join(remaining)}."
        )

    for task_id in task_graph.nodes:
        if task_id not in levels:
            levels[task_id] = 0

    return levels


def group_threads_and_detect_crosses(
    task_graph: TaskGraph,
) -> tuple[list[list[str]], list[CrossEdge]]:
    """Agrupa las Tasks en hilos de trabajo paralelizables por cadena de
    dependencia directa, y detecta cruces entre hilos.

    - Dos Tasks del mismo nivel sin relacion entre si no se fuerzan al
      mismo hilo.
    - Una Task sigue la cadena de su primera dependencia intra-Epic.
    - Un cruce (Task de un hilo que depende de una Task de otro) se lista
      explicitamente.

    Devuelve:
      - Lista de hilos, cada uno con sus Tasks en orden topologico.
      - Lista de cruces detectados.
    """
    task_ids = list(task_graph.nodes.keys())
    edges = task_graph.edges

    thread_of: dict[str, str] = {}
    cross_edges: list[CrossEdge] = []

    roots = sorted(
        tid for tid in task_ids if not edges.get(tid, ())
    )

    threads: list[list[str]] = []
    for i, root_id in enumerate(roots):
        thread_id = f"hilo-{i + 1}"
        thread_of[root_id] = thread_id
        threads.append([root_id])

    ordered = _topological_order(task_graph)

    for task_id in ordered:
        if task_id in thread_of:
            continue
        deps = edges.get(task_id, ())
        intra_deps = [d for d in deps if d in thread_of]
        if not intra_deps:
            next_thread_num = len(threads) + 1
            thread_id = f"hilo-{next_thread_num}"
            thread_of[task_id] = thread_id
            threads.append([task_id])
            for d in deps:
                if d in task_graph.nodes and d not in thread_of:
                    continue
        else:
            chosen = intra_deps[0]
            thread_id = thread_of[chosen]
            thread_of[task_id] = thread_id
            for thread_list in threads:
                if thread_list and thread_of.get(thread_list[0]) == thread_id:
                    thread_list.append(task_id)
                    break
            for d in intra_deps[1:]:
                if thread_of.get(d) != thread_id:
                    cross_edges.append(
                        CrossEdge(
                            from_task=task_id,
                            from_thread=thread_id,
                            to_task=d,
                            to_thread=thread_of[d],
                        )
                    )

        for d in deps:
            if d not in thread_of and d in task_graph.nodes:
                cross_edges.append(
                    CrossEdge(
                        from_task=task_id,
                        from_thread=thread_id,
                        to_task=d,
                        to_thread="(aun sin hilo)",
                    )
                )

    return threads, cross_edges


def _topological_order(task_graph: TaskGraph) -> list[str]:
    """Orden topologico determinista de las Tasks del grafo."""
    in_degree: dict[str, int] = {tid: 0 for tid in task_graph.nodes}
    for tid, deps in task_graph.edges.items():
        for d in deps:
            if d in in_degree:
                in_degree[tid] = in_degree.get(tid, 0) + 1

    queue = deque(sorted(tid for tid, deg in in_degree.items() if deg == 0))
    result: list[str] = []

    while queue:
        current = queue.popleft()
        result.append(current)
        for tid, deps in task_graph.edges.items():
            if current in deps:
                in_degree[tid] -= 1
                if in_degree[tid] == 0:
                    queue.append(tid)

    return result


def analyze_epic_threads(graph: BacklogGraph, epic_prefix: str) -> ThreadAnalysis:
    """Analisis completo de hilos para una Epic: construye el grafo de
    Tasks, calcula niveles topologicos, agrupa en hilos y detecta cruces."""
    task_graph = build_task_graph(graph, epic_prefix)

    try:
        levels = compute_topological_levels(task_graph)
    except ValueError:
        raise

    threads_raw, crosses = group_threads_and_detect_crosses(task_graph)

    thread_objects: list[Thread] = []
    for i, thread_task_ids in enumerate(threads_raw):
        tasks = tuple(task_graph.nodes[tid] for tid in thread_task_ids)
        start_level = min(levels.get(tid, 0) for tid in thread_task_ids)
        thread_objects.append(
            Thread(id=f"hilo-{i + 1}", tasks=tasks, start_level=start_level)
        )

    final_crosses: list[CrossEdge] = []
    seen_crosses: set[tuple[str, str]] = set()
    for cross in crosses:
        key = (cross.from_task, cross.to_task)
        if key not in seen_crosses:
            seen_crosses.add(key)
            final_crosses.append(cross)

    return ThreadAnalysis(
        epic=epic_prefix,
        threads=tuple(thread_objects),
        topological_levels=levels,
        crosses=tuple(final_crosses),
        missing_refs=task_graph.missing_refs,
    )


def generate_reparto_recommendation(
    analysis: ThreadAnalysis,
    num_agents: int = 1,
) -> list[RepartoItem]:
    """Genera una recomendacion de que hilo asignar a que agente y en que
    orden lanzarlos.

    - N (agentes disponibles) es un parametro de entrada configurable.
    - Si hay cruces, el orden recomendado los respeta: el hilo dependiente
      no se recomienda antes de que el hilo del que depende llegue al punto
      de cruce.
    - Es una sugerencia, nunca una decision vinculante.

    La heuristica es round-robin simple por nivel de arranque: los hilos
    con menor `start_level` se asignan primero, respetando que si un hilo
    tiene un cruce entrante, se asigna al mismo agente del hilo del que
    depende para minimizar cambios de contexto.
    """
    if num_agents < 1:
        raise ValueError("num_agents debe ser >= 1")

    threads = list(analysis.threads)

    threads.sort(key=lambda t: t.start_level)

    cross_map: dict[str, int] = {}
    for cross in analysis.crosses:
        for i, thread in enumerate(threads):
            for j, other in enumerate(threads):
                if thread.id != other.id:
                    continue
                if cross.from_thread == thread.id and cross.to_thread == other.id:
                    pass

    agent_assign = _assign_agents(threads, num_agents, analysis.crosses)

    result: list[RepartoItem] = []
    for idx, thread in enumerate(threads):
        result.append(
            RepartoItem(
                thread_id=thread.id,
                tasks=tuple(t.id for t in thread.tasks),
                start_level=thread.start_level,
                agent_index=agent_assign[idx],
            )
        )

    return result


def _assign_agents(
    threads: list[Thread],
    num_agents: int,
    crosses: tuple[CrossEdge, ...],
) -> list[int]:
    """Algoritmo de asignacion de hilos a agentes.

    - Round-robin empezando por los hilos de menor `start_level`.
    - Si un hilo depende via cruce de otro, se asigna al mismo agente que
      el hilo del que depende (si cabe en el orden).
    """
    assigned: list[int] = [-1] * len(threads)

    dep_map: dict[str, str] = {}
    for cross in crosses:
        dep_map[cross.from_thread] = cross.to_thread

    next_agent = 0
    thread_indices = list(range(len(threads)))

    sorted_indices = sorted(thread_indices, key=lambda i: threads[i].start_level)

    for sorted_pos, idx in enumerate(sorted_indices):
        thread = threads[idx]
        if thread.id in dep_map:
            target_thread = dep_map[thread.id]
            for j, other in enumerate(threads):
                if other.id == target_thread and assigned[j] >= 0:
                    assigned[idx] = assigned[j]
                    break
            else:
                assigned[idx] = sorted_pos % num_agents
        else:
            assigned[idx] = sorted_pos % num_agents

    return assigned


def format_thread_analysis_markdown(
    analysis: ThreadAnalysis,
    num_agents: int = 1,
) -> str:
    """Formatea el analisis de hilos como informe Markdown legible por
    humano, con secciones de hilos, cruces, niveles topologicos y
    recomendacion de reparto."""
    lines: list[str] = []
    lines.append(f"# Analisis de hilos de desarrollo · {analysis.epic}")
    lines.append("")
    lines.append(f"**Epic:** {analysis.epic}")
    lines.append(f"**Hilos detectados:** {len(analysis.threads)}")
    lines.append(f"**Tareas totales:** {sum(len(t.tasks) for t in analysis.threads)}")
    lines.append(f"**Cruces entre hilos:** {len(analysis.crosses)}")
    if analysis.missing_refs:
        lines.append(f"**Dependencias no resueltas:** {', '.join(analysis.missing_refs)}")
    lines.append("")

    for thread in analysis.threads:
        lines.append(f"## {thread.id}")
        lines.append(f"**Nivel de arranque:** {thread.start_level}")
        lines.append(f"**Tareas ({len(thread.tasks)}):**")
        lines.append("")
        for task in thread.tasks:
            deps = analysis.topological_levels.get(task.id, -1)
            lines.append(f"- `{task.id}` (nivel {deps})")
        lines.append("")

    if analysis.crosses:
        lines.append("## Cruces entre hilos")
        lines.append("")
        for cross in analysis.crosses:
            lines.append(
                f"- `{cross.from_task}` ({cross.from_thread}) → "
                f"`{cross.to_task}` ({cross.to_thread})"
            )
        lines.append("")

    reparto = generate_reparto_recommendation(analysis, num_agents)
    lines.append(f"## Recomendacion de reparto ({num_agents} agente(s))")
    lines.append("")
    for item in reparto:
        lines.append(f"### {item.thread_id} → Agente {item.agent_index + 1}")
        lines.append(f"- **Nivel de arranque:** {item.start_level}")
        lines.append(f"- **Tareas ({len(item.tasks)}):**")
        for tid in item.tasks:
            lvl = analysis.topological_levels.get(tid, -1)
            lines.append(f"  - `{tid}` (nivel {lvl})")
        lines.append("")

    if analysis.missing_refs:
        lines.append("## Dependencias no resueltas")
        lines.append("")
        for ref in analysis.missing_refs:
            lines.append(f"- `{ref}`")
        lines.append("")

    return "\n".join(lines)


def persist_thread_analysis(
    analysis: ThreadAnalysis,
    num_agents: int = 1,
    reports_root: Path | str | None = None,
) -> Path:
    """Persiste el informe de hilos en `07-informes/<Epic-id>/` con
    identificador unico por ejecucion (timestamp), sin sobrescribir
    informes anteriores.

    Mismo patron que FB-025 (acciones transversales) y FB-022-US06-03
    (informe de cierre por job_id): persistencia canónica en
    `07-informes/`, versionado junto al resto del proyecto.
    """
    from datetime import datetime, timezone

    if reports_root is None:
        reports_root = Path(__file__).resolve().parents[4] / "07-informes"

    root = Path(reports_root)
    epic_dir = root / analysis.epic
    epic_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%S-%f")
    report_path = epic_dir / f"analisis-hilos-{ts}.md"

    content = format_thread_analysis_markdown(analysis, num_agents)
    report_path.write_text(content, encoding="utf-8")

    return report_path
