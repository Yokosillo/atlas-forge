"""Parser determinista de `02-backlog/` y grafo de dependencias
(T-FB018-US02-01, US-FB018-02).

Lectura de los ficheros `user-stories/*.md`/`tasks/*.md` de un proyecto,
extracción de estado y dependencias con parseo de texto (regex sobre la
convención de `02-backlog/`), y grafo de dependencias entre US/Tasks, con
clasificación LISTA/BLOQUEADA de los items TODO y cadena de mayor
apalancamiento — todo sin gastar tokens de agente cognitivo."""

from brain.backlog.parser import (
    classify_todo_items,
    find_max_leverage_chain,
    load_backlog,
    parse_backlog_item,
)
from brain.backlog.report import (
    BACKLOG_STATUS_NO_DATA_TEXT,
    build_backlog_report,
    format_human_report,
    priority_rank,
    render_json_report,
)

__all__ = [
    "BACKLOG_STATUS_NO_DATA_TEXT",
    "build_backlog_report",
    "classify_todo_items",
    "find_max_leverage_chain",
    "format_human_report",
    "load_backlog",
    "parse_backlog_item",
    "priority_rank",
    "render_json_report",
]
