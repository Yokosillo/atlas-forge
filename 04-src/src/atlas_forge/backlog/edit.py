"""Edición directa de campos del frontmatter de un item de backlog ya
existente (T-AF036-US08-01, US-AF036-08 · "Editar prioridad y estado de
una User Story o Task desde su línea de título, sin desplegar").

Distinto de `US-AF008-10` ("Marcar para desarrollo"): esta Story cambia
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

from atlas_forge.backlog.fases import (
    VALID_VERSIONS,
    format_valid_fases,
    format_valid_versions,
    is_assignable_fase,
    is_assignable_version,
)
from atlas_forge.backlog.promote import upsert_updated_at
from atlas_forge.backlog.validator_v2 import validate_backlog_content_v2
from atlas_forge.core.state_machines import TASK_STATES, USER_STORY_STATES, can_transition

VALID_PRIORITIES = ("Crítica", "Alta", "Media", "Baja")
# AF-040: el vocabulario canónico lo define `atlas_forge/core/state_machines.py`;
# este guardarraíl previo es un superset deliberado (Task ∪ User Story), no
# distingue tipo porque `set_item_state` no lo recibe como parámetro — la
# precisión real la da `validator_v2` (por `type`), que se ejecuta después,
# antes de escribir a disco. Epic queda fuera por completo de
# `set_item_state` (ver docstring de módulo).
VALID_STATES = tuple(sorted(TASK_STATES | USER_STORY_STATES))

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


def _insert_frontmatter_field(content: str, field: str, value: str | None) -> str:
    """Inserta la línea `field: <value>` en el frontmatter (justo antes del
    cierre `---`) cuando el item no declara aún ese campo — mismo criterio de
    edición textual simple que `_replace_frontmatter_field`, sin re-serializar
    el resto del frontmatter. `None` se escribe como `null`."""
    lines = content.split("\n")
    close_idx = None
    for i, line in enumerate(lines):
        if i > 0 and line.strip() == "---":
            close_idx = i
            break
    if close_idx is None:
        raise BacklogValidationError(["el frontmatter no está cerrado ('---' de cierre ausente)"])
    value_raw = value if value is not None else "null"
    lines.insert(close_idx, f"{field}: {value_raw}")
    return "\n".join(lines)


def set_item_fase(item_path: str | Path, new_fase: str | None) -> None:
    """Cambia el campo `fase` del fichero real de una Epic/User Story a
    `new_fase` (una de `VALID_FASES`, o `None` para "sin fase"), validando
    el contenido resultante ANTES de escribir a disco (T-AF036-US14-01).

    Conjunto cerrado (T-AF036-US14-05): `new_fase` debe pertenecer a
    `VALID_FASES` o ser `None` — se lanza `InvalidFieldValueError` (mismo
    patrón que `set_item_priority`) sin tocar el fichero para cualquier
    otro valor, incluidos los 0.x legados y `SIN_ASIGNAR` (que no es
    asignable; "sin fase" se asigna con `None`). Si el item no declara aún
    el campo `fase`, se inserta. Lanza `BacklogValidationError` si el
    contenido resultante no pasa el validador determinista — el fichero
    real NO se modifica en ese caso."""
    if not is_assignable_fase(new_fase):
        raise InvalidFieldValueError(
            f"'{new_fase}' no es una fase válida — debe ser una de "
            f"{format_valid_fases()} o null (sin fase)."
        )

    path = Path(item_path)
    content = path.read_text(encoding="utf-8")

    current = _read_frontmatter_field(content, "fase")
    if current is None:
        updated = _insert_frontmatter_field(content, "fase", new_fase)
    else:
        new_value_raw = new_fase if new_fase is not None else "null"
        updated = _replace_frontmatter_field(content, "fase", current, new_value_raw)

    result = validate_backlog_content_v2(updated, filename=path.name)
    if not result.valid:
        raise BacklogValidationError([error.message for error in result.errors])

    path.write_text(updated, encoding="utf-8")


def set_item_version(item_path: str | Path, new_version: str | None) -> None:
    """Cambia el campo `version` del fichero real de una Epic/User Story a
    `new_version` (una de `VALID_VERSIONS`, o `None` para "sin versión"),
    validando el contenido resultante ANTES de escribir a disco
    (T-AF036-US25-01).

    Conjunto cerrado: `new_version` debe pertenecer a `VALID_VERSIONS` o
    ser `None` — se lanza `InvalidFieldValueError` (mismo patrón que
    `set_item_fase`) sin tocar el fichero para cualquier otro valor. Si el
    item no declara aún el campo `version`, se inserta. Lanza
    `BacklogValidationError` si el contenido resultante no pasa el
    validador determinista — el fichero real NO se modifica en ese caso."""
    if not is_assignable_version(new_version):
        raise InvalidFieldValueError(
            f"'{new_version}' no es una versión válida — debe ser una de "
            f"{format_valid_versions()} o null (sin versión)."
        )

    path = Path(item_path)
    content = path.read_text(encoding="utf-8")

    current = _read_frontmatter_field(content, "version")
    if current is None:
        updated = _insert_frontmatter_field(content, "version", new_version)
    else:
        new_value_raw = new_version if new_version is not None else "null"
        updated = _replace_frontmatter_field(content, "version", current, new_value_raw)

    result = validate_backlog_content_v2(updated, filename=path.name)
    if not result.valid:
        raise BacklogValidationError([error.message for error in result.errors])

    path.write_text(updated, encoding="utf-8")


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


def set_item_state(
    item_path: str | Path,
    new_state: str,
    *,
    kind: str | None = None,
    force: bool = False,
) -> None:
    """Cambia el campo `state` del fichero real de una User Story/Task a
    `new_state` (uno de `VALID_STATES`), validando el contenido
    resultante antes de escribir a disco — mismo criterio de rechazo
    explícito sin tocar disco que `set_item_priority`.

    T-AF036-US22-01: además del vocabulario, se comprueba que
    `current_state → new_state` sea una transición LEGAL según la máquina
    canónica (`can_transition`, `atlas_forge/core/state_machines.py`); si no lo
    es, se lanza `InvalidFieldValueError` sin tocar disco. `kind`
    (task/user_story) se infiere del `type` del frontmatter si no se pasa;
    Epic queda fuera (no llega aquí). `force=True` permite a los caminos
    internos del pipeline escribir transiciones que la máquina no modela
    (p. ej. la reconciliación de huérfanas `IN_PROGRESS → TO_DEVELOP/READY`
    o la derivación automática `NO_TASKS → READY`) — el endpoint manual
    (`PUT /backlog/{item_id}/state`) nunca la usa.

    No dispara `promote_backlog` por sí sola — el llamador (capa HTTP)
    decide cuándo invocarlo (solo si `new_state == "DONE"` sobre una
    User Story, criterio de aceptación 4/2 de `US-AF036-08`), este
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

    # T-AF036-US22-01: la transición debe ser legal para el tipo del item.
    if not force:
        resolved_kind = kind or _read_frontmatter_field(content, "type")
        if resolved_kind in ("task", "user_story") and not can_transition(
            resolved_kind, current_state, new_state
        ):
            raise InvalidFieldValueError(
                f"Transición de estado ilegal: '{current_state}' -> "
                f"'{new_state}' para {resolved_kind} — la máquina canónica "
                "no la permite (atlas_forge/core/state_machines.py)."
            )

    updated = _replace_frontmatter_field(content, "state", current_state, new_state)
    # T-AF036-US13-01: todo cambio de estado (web o promoción automática)
    # actualiza también el timestamp de la última transición en el
    # frontmatter — el validador no rechaza campos extra, así que añadir
    # `updated_at` no rompe el esquema.
    updated = upsert_updated_at(updated)

    result = validate_backlog_content_v2(updated, filename=path.name)
    if not result.valid:
        raise BacklogValidationError([error.message for error in result.errors])

    path.write_text(updated, encoding="utf-8")
