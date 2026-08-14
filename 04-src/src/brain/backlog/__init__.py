"""Parser determinista de `02-backlog/` y grafo de dependencias
(T-FB018-US02-01, US-FB018-02).

Lectura de los ficheros `user-stories/*.md`/`tasks/*.md` de un proyecto,
extracción de estado y dependencias con parseo de texto (regex sobre la
convención de `02-backlog/`), y grafo de dependencias entre US/Tasks, con
clasificación LISTA/BLOQUEADA de los items TODO y cadena de mayor
apalancamiento — todo sin gastar tokens de agente cognitivo."""

from brain.backlog.dependency_graph import (
    CrossEdge,
    RepartoItem,
    TaskGraph,
    Thread,
    ThreadAnalysis,
    analyze_epic_threads,
    build_task_graph,
    compute_topological_levels,
    format_thread_analysis_markdown,
    generate_reparto_recommendation,
    group_threads_and_detect_crosses,
    persist_thread_analysis,
)
from brain.backlog.parser import (
    classify_todo_items,
    find_max_leverage_chain,
    load_backlog,
    parse_backlog_item,
)
from brain.backlog.ready_tasks import find_ready_tasks
from brain.backlog.report import (
    BACKLOG_STATUS_NO_DATA_TEXT,
    build_backlog_report,
    format_human_report,
    priority_rank,
    render_json_report,
)

__all__ = [
    "BACKLOG_STATUS_NO_DATA_TEXT",
    "CrossEdge",
    "RepartoItem",
    "TaskGraph",
    "Thread",
    "ThreadAnalysis",
    "analyze_epic_threads",
    "build_backlog_report",
    "build_task_graph",
    "classify_todo_items",
    "compute_topological_levels",
    "find_max_leverage_chain",
    "find_ready_tasks",
    "format_human_report",
    "format_thread_analysis_markdown",
    "generate_reparto_recommendation",
    "group_threads_and_detect_crosses",
    "load_backlog",
    "parse_backlog_item",
    "persist_thread_analysis",
    "priority_rank",
    "render_json_report",
]
