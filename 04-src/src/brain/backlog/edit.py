"""Edición directa de campos del frontmatter de un item de backlog ya
existente (T-FB036-US08-01, US-FB036-08 · "Editar prioridad y estado de
una User Story o Task desde su línea de título, sin desplegar").

Distinto de `US-FB008-10` ("Marcar para desarrollo"): esta Story cambia
el campo `state`/`priority` DIRECTAMENTE en el fichero real, sin pasar
por ninguna cola ni Dispatcher — dos acciones independientes que pueden
convivir sobre el mismo item (ver Contexto de la propia User Story).

Solo Epic queda fuera por completo: `priority` no existe en su esquema
(`02-backlog/README.md`), y su `state` cambia solo por promoción
automática (`promote_backlog`), nunca manualmente — mismo comportamiento
ya vigente que este módulo preserva sin tocar."""

from __future__ import annotations

import re
from pathlib import Path

from brain.backlog.validator_v2 import validate_backlog_content_v2

VALID_PRIORITIES = ("Crítica", "Alta", "Media", "Baja")
VALID_STATES = ("TODO", "IN_PROGRESS", "REVIEW", "DONE")

_FIELD_LINE_PATTERN = "{field}: {value}"


class InvalidFieldValueError(ValueError):
    """El valor recibido no pertenece al conjunto cerrado válido para el
    campo (`priority`/`state`) — nunca llega a leer ni escribir ningún
    fichero, se rechaza antes de tocar disco."""


class BacklogValidationError(ValueError):
    """El contenido resultante tras el cambio no pasa
    `validate_backlog_file_v2` — el fichero real NO se modifica; el
    error del validador se propaga verbatim (mensaje por línea, unido)
    para que la capa HTTP lo devuelva tal cual, sin reformular."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def _replace_frontmatter_field(content: str, field: str, current_value: str, new_value: str) -> str:
    """Reemplaza la línea `field: current_value` del frontmatter por
    `field: new_value` — mismo patrón de reemplazo textual simple ya
    usado en `dispatch_queue_worker._update_task_file_state`/
    `_mark_story_tasks_done` (`job_plan_dispatch.py`), no un
    re-serializador YAML completo (evita reordenar/reformatear el resto
    del frontmatter, que el usuario pudo haber editado a mano con su
    propio estilo)."""
    old_line = _FIELD_LINE_PATTERN.format(field=field, value=current_value)
    new_line = _FIELD_LINE_PATTERN.format(field=field, value=new_value)
    return content.replace(old_line, new_line, 1)


def _read_frontmatter_field(content: str, field: str) -> str | None:
    match = re.search(rf"^{re.escape(field)}:\s*(.*)$", content, re.MULTILINE)
    if match is None:
        return None
    return match.group(1).strip()


def set_item_priority(item_path: str | Path, new_priority: str | None) -> None:
    """Cambia el campo `priority` del fichero real de una User Story/Task
    a `new_priority` (uno de `VALID_PRIORITIES`, o `None` para "sin
    prioridad"), validando el contenido resultante ANTES de escribir a
    disco.

    Lanza `InvalidFieldValueError` si `new_priority` no es `None` ni
    pertenece a `VALID_PRIORITIES` — rechazo explícito sin tocar el
    fichero. Lanza `BacklogValidationError` si el contenido resultante no
    pasa el validador determinista (criterio de aceptación 3 de la
    Task) — el fichero real tampoco se modifica en este caso."""
    if new_priority is not None and new_priority not in VALID_PRIORITIES:
        raise InvalidFieldValueError(
            f"'{new_priority}' no es una prioridad válida — debe ser una de "
            f"{', '.join(VALID_PRIORITIES)} o null (sin prioridad)."
        )

    path = Path(item_path)
    content = path.read_text(encoding="utf-8")
    current_priority_raw = _read_frontmatter_field(content, "priority")
    if current_priority_raw is None:
        raise BacklogValidationError(
            ["el fichero no declara el campo 'priority' en su frontmatter"]
        )

    new_value_raw = new_priority if new_priority is not None else "null"
    updated = _replace_frontmatter_field(content, "priority", current_priority_raw, new_value_raw)

    result = validate_backlog_content_v2(updated, filename=path.name)
    if not result.valid:
        raise BacklogValidationError([error.message for error in result.errors])

    path.write_text(updated, encoding="utf-8")


def set_item_state(item_path: str | Path, new_state: str) -> None:
    """Cambia el campo `state` del fichero real de una User Story/Task a
    `new_state` (uno de `VALID_STATES`), validando el contenido
    resultante antes de escribir a disco — mismo criterio de rechazo
    explícito sin tocar disco que `set_item_priority`.

    No dispara `promote_backlog` por sí sola — el llamador (capa HTTP)
    decide cuándo invocarlo (solo si `new_state == "DONE"` sobre una
    User Story, criterio de aceptación 4/2 de `US-FB036-08`), este
    módulo se limita a escribir el campo del fichero concreto."""
    if new_state not in VALID_STATES:
        raise InvalidFieldValueError(
            f"'{new_state}' no es un estado válido — debe ser uno de "
            f"{', '.join(VALID_STATES)}."
        )

    path = Path(item_path)
    content = path.read_text(encoding="utf-8")
    current_state = _read_frontmatter_field(content, "state")
    if current_state is None:
        raise BacklogValidationError(
            ["el fichero no declara el campo 'state' en su frontmatter"]
        )

    updated = _replace_frontmatter_field(content, "state", current_state, new_state)

    result = validate_backlog_content_v2(updated, filename=path.name)
    if not result.valid:
        raise BacklogValidationError([error.message for error in result.errors])

    path.write_text(updated, encoding="utf-8")
