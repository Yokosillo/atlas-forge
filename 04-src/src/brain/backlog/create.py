"""Creación de items de backlog nuevos desde cero (T-FB036-US02-01/-02,
US-FB036-02 · "Crear una Epic, User Story o Task nueva sin salir de la
pantalla Backlog") — a diferencia de `brain.backlog.edit` (cambia un
campo de un item YA existente), este módulo escribe el fichero completo
por primera vez.

Epic y User Story están cubiertas (`T-FB036-US02-01`/`-02`); Task es una
Task separada de la misma Story (`T-FB036-US02-03`), todavía sin
implementar."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from brain.backlog.validator_v2 import validate_backlog_content_v2
from brain.runtime import sanitize_session_name_part

EPIC_ID_PATTERN = re.compile(r"^FB-\d{3,}$")
# Mismo patrón que `_US_ID_PATTERN` del validador determinista
# (`brain.backlog.validator_v2`) — no importado de ahí porque ese módulo
# lo mantiene privado (con `_`); se replica aquí en vez de exponerlo solo
# para este uso, mismo criterio ya aplicado por `architect_queue.py`
# reimplementando su propia sanitización en vez de importar la de
# `runtime/generic.py` en su día.
US_ID_PATTERN = re.compile(r"^US-FB\d{3,}-\d{2}[A-Z]?$")
VALID_PRIORITIES = ("Crítica", "Alta", "Media", "Baja")


class InvalidEpicIdError(ValueError):
    """El `id` recibido no tiene el formato `FB-\\d{3,}` — rechazo
    explícito antes de tocar disco (criterio de aceptación de la Task:
    "el servidor nunca confía únicamente en la validación de cliente")."""


class InvalidUserStoryIdError(ValueError):
    """El `id` recibido no tiene el formato `US-FB\\d{3,}-\\d{2}` — mismo
    criterio de rechazo explícito que `InvalidEpicIdError`, para User
    Story."""


class EpicNotFoundError(ValueError):
    """No existe ningún fichero `{epic_id}*.md` en `02-backlog/epics/` —
    el llamador debe traducir esto a 404 (no se puede crear una User
    Story bajo una Epic que no existe)."""

    def __init__(self, epic_id: str) -> None:
        self.epic_id = epic_id
        super().__init__(f"No existe ningun fichero de Epic con id '{epic_id}'.")


class EpicAlreadyExistsError(ValueError):
    """Ya existe un fichero `{id}*.md` en `02-backlog/epics/` — no se
    sobreescribe, el llamador debe traducir esto a 409."""

    def __init__(self, epic_id: str, existing_path: Path) -> None:
        self.epic_id = epic_id
        self.existing_path = existing_path
        super().__init__(f"Ya existe una Epic con id '{epic_id}': {existing_path}")


class UserStoryAlreadyExistsError(ValueError):
    """Ya existe un fichero `{id}*.md` en `02-backlog/user-stories/` —
    no se sobreescribe, el llamador debe traducir esto a 409."""

    def __init__(self, us_id: str, existing_path: Path) -> None:
        self.us_id = us_id
        self.existing_path = existing_path
        super().__init__(f"Ya existe una User Story con id '{us_id}': {existing_path}")


class InvalidPriorityError(ValueError):
    """`priority` recibido no pertenece al conjunto cerrado (o `null`) —
    mismo conjunto que exige el validador determinista para User
    Story/Task."""


class BacklogValidationError(ValueError):
    """El contenido generado no pasa `validate_backlog_content_v2` — el
    fichero real NO se escribe; los mensajes del validador se propagan
    verbatim para que la capa HTTP los devuelva tal cual."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def _slug(title: str) -> str:
    """Mismo criterio de saneo que el resto del proyecto para nombres de
    fichero derivados de texto libre (`sanitize_session_name_part`,
    `brain.runtime` — ya usado para sesiones tmux y para
    `reconciliation_log_path`/`architect_queue_path`), reutilizado aquí
    en vez de definir una cuarta variante de "slugify" (`architect/
    us_pipeline.py`/`task_pipeline.py` ya tienen la suya propia, más
    simple — ninguna de las dos se toca, esto es solo para este módulo)."""
    return sanitize_session_name_part(title)


def _find_existing(directory: Path, item_id: str) -> Path | None:
    """Busca un fichero `{item_id}*.md` ya existente en `directory` —
    mismo criterio de glob que `build_epic_detail`/`build_backlog_report`
    usan para RESOLVER un item ya creado, aquí para comprobar que
    todavía NO existe (o, en `_epic_dir_or_raise`, que SÍ existe). Cubre
    tanto el patrón vigente (`{id}-{slug}.md`) como el legado sin slug
    (`{id}.md`) con dos globs — el legado no tiene guion tras el id, así
    que `{id}-*.md` no lo alcanza por sí solo."""
    if not directory.is_dir():
        return None
    existing = next(iter(sorted(directory.glob(f"{item_id}-*.md"))), None)
    if existing is None:
        existing = next(iter(sorted(directory.glob(f"{item_id}.md"))), None)
    return existing


def _build_epic_content(epic_id: str, title: str, objetivo: str, fase: str | None) -> str:
    # `yaml.safe_dump` (no un f-string crudo) para el frontmatter: `title`
    # es texto libre del formulario y puede contener `:` — un valor sin
    # comillas con `:` dentro rompe el YAML ("mapping values are not
    # allowed here"), bug real detectado al escribir el test de esta
    # misma Task (`test_create_epic_slug_strips_accents_and_special_characters`).
    # `sort_keys=False` preserva el orden ya fijado por `02-backlog/README.md`
    # (id, type, title, state, dependencies, fase); `allow_unicode=True`
    # evita que acentos en `title` salgan escapados como `\uXXXX`.
    frontmatter = yaml.safe_dump(
        {
            "id": epic_id,
            "type": "epic",
            "title": title,
            "state": "TODO",
            "dependencies": [],
            "fase": fase,
        },
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )
    return f"---\n{frontmatter}---\n\n# {epic_id} · {title}\n\n## Objetivo\n\n{objetivo}\n"


def create_epic(
    backlog_path: str | Path,
    epic_id: str,
    title: str,
    objetivo: str,
    fase: str | None = None,
) -> Path:
    """Crea el fichero real de una Epic nueva en
    `<backlog_path>/epics/{epic_id}-{slug(title)}.md`.

    Validación en tres fases, nunca toca disco si falla: (1) `epic_id`
    contra `EPIC_ID_PATTERN` (`InvalidEpicIdError`); (2) ningún fichero
    `{epic_id}*.md` ya existente en `epics/` (`EpicAlreadyExistsError`,
    glob — mismo criterio que `build_epic_detail`/`build_backlog_report`
    usan para RESOLVER una Epic ya creada, aquí para comprobar que
    todavía no existe); (3) el contenido generado contra
    `validate_backlog_content_v2` (`BacklogValidationError`, mensajes
    verbatim).

    Devuelve la ruta del fichero escrito."""
    if not EPIC_ID_PATTERN.match(epic_id):
        raise InvalidEpicIdError(
            f"'{epic_id}' no es un id de Epic válido — debe tener el formato FB-NNN (al menos 3 dígitos)."
        )

    epics_dir = Path(backlog_path) / "epics"
    existing = _find_existing(epics_dir, epic_id)
    if existing is not None:
        raise EpicAlreadyExistsError(epic_id, existing)

    filename = f"{epic_id}-{_slug(title)}.md"
    content = _build_epic_content(epic_id, title, objetivo, fase)

    result = validate_backlog_content_v2(content, filename=filename)
    if not result.valid:
        raise BacklogValidationError([error.message for error in result.errors])

    epics_dir.mkdir(parents=True, exist_ok=True)
    path = epics_dir / filename
    path.write_text(content, encoding="utf-8")
    return path


def _build_user_story_content(
    us_id: str,
    epic_id: str,
    title: str,
    objetivo: str,
    criterios_aceptacion: str,
    priority: str | None,
) -> str:
    # Mismo criterio que `_build_epic_content`: `yaml.safe_dump`, nunca
    # concatenación manual — evita el mismo bug de `title`/`epic`/etc. con
    # `:` rompiendo el YAML generado (T-FB036-US02-01).
    frontmatter = yaml.safe_dump(
        {
            "id": us_id,
            "type": "user_story",
            "title": title,
            "state": "TODO",
            "dependencies": [],
            "epic": epic_id,
            "priority": priority,
        },
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )
    return (
        f"---\n{frontmatter}---\n\n"
        f"# {us_id} · {title}\n\n"
        f"## Historia\n\n{objetivo}\n\n"
        f"## Criterios de aceptación\n\n{criterios_aceptacion}\n"
    )


def create_user_story(
    backlog_path: str | Path,
    epic_id: str,
    us_id: str,
    title: str,
    objetivo: str,
    criterios_aceptacion: str,
    priority: str | None = None,
) -> Path:
    """Crea el fichero real de una User Story nueva en
    `<backlog_path>/user-stories/{us_id}-{slug(title)}.md`, bajo la Epic
    `epic_id` (T-FB036-US02-02).

    `epic_id` viene SIEMPRE de la URL del endpoint que llama a esta
    función, nunca de un campo del body que el cliente pudiera falsear —
    responsabilidad de la capa HTTP, no de este módulo (criterio de
    aceptación explícito de la Task: "el `epic_id` del fichero creado
    coincide siempre con el de la URL").

    Validación en cuatro fases, nunca toca disco si falla: (1) `us_id`
    contra `US_ID_PATTERN` (`InvalidUserStoryIdError`); (2) `epic_id`
    tiene un fichero de Epic real en `epics/` (`EpicNotFoundError` — no
    tiene sentido crear una US bajo una Epic inexistente); (3) `priority`
    pertenece al conjunto cerrado o es `None` (`InvalidPriorityError`);
    (4) ningún fichero `{us_id}*.md` ya existente en `user-stories/`
    (`UserStoryAlreadyExistsError`); (5) el contenido generado contra
    `validate_backlog_content_v2` (`BacklogValidationError`, mensajes
    verbatim).

    Devuelve la ruta del fichero escrito."""
    if not US_ID_PATTERN.match(us_id):
        raise InvalidUserStoryIdError(
            f"'{us_id}' no es un id de User Story válido — debe tener el formato US-FBNNN-nn."
        )

    epics_dir = Path(backlog_path) / "epics"
    if _find_existing(epics_dir, epic_id) is None:
        raise EpicNotFoundError(epic_id)

    if priority is not None and priority not in VALID_PRIORITIES:
        raise InvalidPriorityError(
            f"'{priority}' no es una prioridad válida — debe ser una de "
            f"{', '.join(VALID_PRIORITIES)} o null (sin prioridad)."
        )

    stories_dir = Path(backlog_path) / "user-stories"
    existing = _find_existing(stories_dir, us_id)
    if existing is not None:
        raise UserStoryAlreadyExistsError(us_id, existing)

    filename = f"{us_id}-{_slug(title)}.md"
    content = _build_user_story_content(us_id, epic_id, title, objetivo, criterios_aceptacion, priority)

    result = validate_backlog_content_v2(content, filename=filename)
    if not result.valid:
        raise BacklogValidationError([error.message for error in result.errors])

    stories_dir.mkdir(parents=True, exist_ok=True)
    path = stories_dir / filename
    path.write_text(content, encoding="utf-8")
    return path
