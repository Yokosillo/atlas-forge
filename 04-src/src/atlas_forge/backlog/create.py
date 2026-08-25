"""Creación de items de backlog nuevos desde cero (T-AF036-US02-01/-02/-03,
US-AF036-02 · "Crear una Epic, User Story o Task nueva sin salir de la
pantalla Backlog") — a diferencia de `atlas_forge.backlog.edit` (cambia un
campo de un item YA existente), este módulo escribe el fichero completo
por primera vez.

Epic, User Story y Task están las tres cubiertas (`T-AF036-US02-01`/
`-02`/`-03`)."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from atlas_forge.backlog.edit import InvalidFieldValueError
from atlas_forge.backlog.fases import (
    format_valid_versions,
    is_assignable_version,
)
from atlas_forge.backlog.parser import parse_frontmatter
from atlas_forge.backlog.validator_v2 import validate_backlog_content_v2
from atlas_forge.runtime import sanitize_session_name_part

EPIC_ID_PATTERN = re.compile(r"^AF-\d{3,}$")
# Mismos patrones que `_US_ID_PATTERN`/el segmento Task de `_ID_PATTERN`
# del validador determinista (`atlas_forge.backlog.validator_v2`) — no
# importados de ahí porque ese módulo los mantiene privados (con `_`);
# se replican aquí en vez de exponerlos solo para este uso, mismo
# criterio ya aplicado por `architect_queue.py` reimplementando su
# propia sanitización en vez de importar la de `runtime/generic.py` en
# su día. `TASK_ID_PATTERN` exige siempre el segmento `-US\d{2}` (a
# diferencia del patrón general del validador, que lo deja opcional para
# un caso legado) — toda Task creada por este módulo vive siempre bajo
# una User Story real, nunca huérfana de US.
US_ID_PATTERN = re.compile(r"^US-AF\d{3,}-\d{2}[A-Z]?$")
TASK_ID_PATTERN = re.compile(r"^T-AF\d{3,}-US\d{2}[A-Z]?-\d{2}[A-Z]?$")
VALID_PRIORITIES = ("Crítica", "Alta", "Media", "Baja")


class InvalidEpicIdError(ValueError):
    """El `id` recibido no tiene el formato `AF-\\d{3,}` — rechazo
    explícito antes de tocar disco (criterio de aceptación de la Task:
    "el servidor nunca confía únicamente en la validación de cliente")."""


class InvalidUserStoryIdError(ValueError):
    """El `id` recibido no tiene el formato `US-AF\\d{3,}-\\d{2}` — mismo
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


class InvalidTaskIdError(ValueError):
    """El `id` recibido no tiene el formato `T-AF\\d{3,}-US\\d{2}-\\d{2}` —
    mismo criterio de rechazo explícito que `InvalidUserStoryIdError`,
    para Task."""


class UserStoryNotFoundError(ValueError):
    """No existe ningún fichero `{us_id}*.md` en
    `02-backlog/user-stories/` — el llamador debe traducir esto a 404
    (no se puede crear una Task bajo una User Story que no existe)."""

    def __init__(self, us_id: str) -> None:
        self.us_id = us_id
        super().__init__(f"No existe ningun fichero de User Story con id '{us_id}'.")


class TaskAlreadyExistsError(ValueError):
    """Ya existe un fichero `{id}*.md` en `02-backlog/tasks/` — no se
    sobreescribe, el llamador debe traducir esto a 409."""

    def __init__(self, task_id: str, existing_path: Path) -> None:
        self.task_id = task_id
        self.existing_path = existing_path
        super().__init__(f"Ya existe una Task con id '{task_id}': {existing_path}")


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
    `atlas_forge.runtime` — ya usado para sesiones tmux y para
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


def _build_epic_content(epic_id: str, title: str, objetivo: str) -> str:
    # `yaml.safe_dump` (no un f-string crudo) para el frontmatter: `title`
    # es texto libre del formulario y puede contener `:` — un valor sin
    # comillas con `:` dentro rompe el YAML ("mapping values are not
    # allowed here"), bug real detectado al escribir el test de esta
    # misma Task (`test_create_epic_slug_strips_accents_and_special_characters`).
    # `sort_keys=False` preserva el orden ya fijado por `02-backlog/README.md`
    # (id, type, title, state, dependencies, version); `allow_unicode=True`
    # evita que acentos en `title` salgan escapados como `\uXXXX`.
    # T-AF036-US18-01: la Epic se versiona (`version: "0.9"` por defecto), ya
    # NO declara `fase` (la fase es de la User Story).
    frontmatter = yaml.safe_dump(
        {
            "id": epic_id,
            "type": "epic",
            "title": title,
            "state": "TO_DO",
            "dependencies": [],
            "version": "0.9",
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

    T-AF036-US18-01: la Epic nace con `version: "0.9"` (se versiona) y no
    declara `fase` — la fase es de la User Story.

    Devuelve la ruta del fichero escrito."""
    if not EPIC_ID_PATTERN.match(epic_id):
        raise InvalidEpicIdError(
            f"'{epic_id}' no es un id de Epic válido — debe tener el formato AF-NNN (al menos 3 dígitos)."
        )

    epics_dir = Path(backlog_path) / "epics"
    existing = _find_existing(epics_dir, epic_id)
    if existing is not None:
        raise EpicAlreadyExistsError(epic_id, existing)

    filename = f"{epic_id}-{_slug(title)}.md"
    content = _build_epic_content(epic_id, title, objetivo)

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
    version: str | None,
) -> str:
    # Mismo criterio que `_build_epic_content`: `yaml.safe_dump`, nunca
    # concatenación manual — evita el mismo bug de `title`/`epic`/etc. con
    # `:` rompiendo el YAML generado (T-AF036-US02-01).
    #
    # `state: NO_TASKS` (T-AF008-US15-01, 2026-08-17; renombrado desde
    # `SIN_TAREAS` 2026-08-18): toda User Story nueva nace sin Tasks —
    # `TO_DO` queda reservado para cuando ya tiene al menos una Task real
    # (transición automática al completar "Progresar"/el aterrizaje del
    # Arquitecto, T-AF008-US15-02).
    frontmatter = yaml.safe_dump(
        {
            "id": us_id,
            "type": "user_story",
            "title": title,
            "state": "NO_TASKS",
            "dependencies": [],
            "epic": epic_id,
            "priority": priority,
            "version": version,
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
    version: str | None = None,
) -> Path:
    """Crea el fichero real de una User Story nueva en
    `<backlog_path>/user-stories/{us_id}-{slug(title)}.md`, bajo la Epic
    `epic_id` (T-AF036-US02-02).

    `epic_id` viene SIEMPRE de la URL del endpoint que llama a esta
    función, nunca de un campo del body que el cliente pudiera falsear —
    responsabilidad de la capa HTTP, no de este módulo (criterio de
    aceptación explícito de la Task: "el `epic_id` del fichero creado
    coincide siempre con el de la URL").

    Validación en cinco fases, nunca toca disco si falla: (1) `us_id`
    contra `US_ID_PATTERN` (`InvalidUserStoryIdError`); (2) `epic_id`
    tiene un fichero de Epic real en `epics/` (`EpicNotFoundError` — no
    tiene sentido crear una US bajo una Epic inexistente); (3) `priority`
    pertenece al conjunto cerrado o es `None` (`InvalidPriorityError`);
    (4) `version` pertenece al conjunto cerrado `VALID_VERSIONS` o es `None`
    (T-AF036-US25-01, `InvalidFieldValueError` — `fase` ya NO es asignable
    por creación, se sustituye por `version`); (5) ningún fichero
    `{us_id}*.md` ya existente en `user-stories/`
    (`UserStoryAlreadyExistsError`); (6) el contenido generado contra
    `validate_backlog_content_v2` (`BacklogValidationError`, mensajes
    verbatim).

    Devuelve la ruta del fichero escrito."""
    if not US_ID_PATTERN.match(us_id):
        raise InvalidUserStoryIdError(
            f"'{us_id}' no es un id de User Story válido — debe tener el formato US-AFNNN-nn."
        )

    epics_dir = Path(backlog_path) / "epics"
    if _find_existing(epics_dir, epic_id) is None:
        raise EpicNotFoundError(epic_id)

    if priority is not None and priority not in VALID_PRIORITIES:
        raise InvalidPriorityError(
            f"'{priority}' no es una prioridad válida — debe ser una de "
            f"{', '.join(VALID_PRIORITIES)} o null (sin prioridad)."
        )

    if not is_assignable_version(version):
        raise InvalidFieldValueError(
            f"'{version}' no es una versión válida — debe ser una de "
            f"{format_valid_versions()} o null (sin versión)."
        )

    stories_dir = Path(backlog_path) / "user-stories"
    existing = _find_existing(stories_dir, us_id)
    if existing is not None:
        raise UserStoryAlreadyExistsError(us_id, existing)

    filename = f"{us_id}-{_slug(title)}.md"
    content = _build_user_story_content(us_id, epic_id, title, objetivo, criterios_aceptacion, priority, version)

    result = validate_backlog_content_v2(content, filename=filename)
    if not result.valid:
        raise BacklogValidationError([error.message for error in result.errors])

    stories_dir.mkdir(parents=True, exist_ok=True)
    path = stories_dir / filename
    path.write_text(content, encoding="utf-8")
    return path


def _build_task_content(
    task_id: str,
    us_id: str,
    epic_id: str | None,
    title: str,
    objetivo: str,
    descripcion: str,
    criterios_aceptacion: str,
    priority: str | None,
    dependencies: list[str],
) -> str:
    # Mismo criterio que `_build_epic_content`/`_build_user_story_content`:
    # `yaml.safe_dump`, nunca concatenación manual — evita el mismo bug de
    # `title`/`epic`/etc. con `:` rompiendo el YAML generado
    # (T-AF036-US02-01). `epic_id` puede ser `None` (US huérfana, criterio
    # de aceptación 3/4 de la Task) — `yaml.safe_dump` lo serializa como
    # `epic: null`, campo PRESENTE (satisface `_REQUIRED_FIELDS["task"]`
    # del validador, que solo exige la clave, no un valor no nulo) pero
    # sin ID real, coherente con el resto del backlog para items sin
    # Epic.
    frontmatter = yaml.safe_dump(
        {
            "id": task_id,
            "type": "task",
            "title": title,
            "state": "READY",
            "dependencies": dependencies,
            "epic": epic_id,
            "user_story": us_id,
            "priority": priority,
        },
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )
    return (
        f"---\n{frontmatter}---\n\n"
        f"# {task_id} · {title}\n\n"
        f"## Objetivo\n\n{objetivo}\n\n"
        f"## Descripción\n\n{descripcion}\n\n"
        f"## Criterios de aceptación\n\n{criterios_aceptacion}\n\n"
        f"## Bugs encontrados\n\nTODO\n"
    )


def create_task(
    backlog_path: str | Path,
    us_id: str,
    task_id: str,
    title: str,
    objetivo: str,
    descripcion: str,
    criterios_aceptacion: str,
    priority: str | None = None,
    dependencies: list[str] | None = None,
) -> tuple[Path, str | None]:
    """Crea el fichero real de una Task nueva en
    `<backlog_path>/tasks/{task_id}-{slug(title)}.md`, bajo la User Story
    `us_id` (T-AF036-US02-03).

    `epic_id` NUNCA se pide al llamador — se resuelve leyendo el
    frontmatter de la propia US encontrada (campo `epic`), evitando la
    inconsistencia de que la Task declare una Epic distinta a la de su
    US real (criterio de aceptación explícito de la Task). Caso borde
    explícito (US huérfana, ya documentado en la especificación UX,
    sección "Casos borde"): si la US no tiene `epic` en su frontmatter
    (o está vacío), la Task se crea igualmente con `epic_id=None` — no
    bloquea la creación.

    Validación en cinco fases, nunca toca disco si falla: (1) `task_id`
    contra `TASK_ID_PATTERN` (`InvalidTaskIdError`); (2) `us_id` tiene un
    fichero de User Story real en `user-stories/`
    (`UserStoryNotFoundError`); (3) `priority` pertenece al conjunto
    cerrado o es `None` (`InvalidPriorityError`); (4) ningún fichero
    `{task_id}*.md` ya existente en `tasks/` (`TaskAlreadyExistsError`);
    (5) el contenido generado (incluidas `dependencies`, si se pasan)
    contra `validate_backlog_content_v2` (`BacklogValidationError`,
    mensajes verbatim — cubre también el formato de cada ID de
    `dependencies`, sin duplicar esa validación aquí).

    Devuelve `(path, epic_id)` — `epic_id` es `None` si la US es
    huérfana, para que el llamador (capa HTTP) pueda incluirlo tal cual
    en la respuesta `{..., "epic_id": null}`."""
    if not TASK_ID_PATTERN.match(task_id):
        raise InvalidTaskIdError(
            f"'{task_id}' no es un id de Task válido — debe tener el formato T-AFNNN-USnn-mm."
        )

    stories_dir = Path(backlog_path) / "user-stories"
    us_path = _find_existing(stories_dir, us_id)
    if us_path is None:
        raise UserStoryNotFoundError(us_id)

    us_frontmatter = parse_frontmatter(us_path.read_text(encoding="utf-8"))
    epic_id = us_frontmatter.get("epic") or None

    if priority is not None and priority not in VALID_PRIORITIES:
        raise InvalidPriorityError(
            f"'{priority}' no es una prioridad válida — debe ser una de "
            f"{', '.join(VALID_PRIORITIES)} o null (sin prioridad)."
        )

    tasks_dir = Path(backlog_path) / "tasks"
    existing = _find_existing(tasks_dir, task_id)
    if existing is not None:
        raise TaskAlreadyExistsError(task_id, existing)

    filename = f"{task_id}-{_slug(title)}.md"
    content = _build_task_content(
        task_id, us_id, epic_id, title, objetivo, descripcion, criterios_aceptacion,
        priority, dependencies or [],
    )

    result = validate_backlog_content_v2(content, filename=filename)
    if not result.valid:
        raise BacklogValidationError([error.message for error in result.errors])

    tasks_dir.mkdir(parents=True, exist_ok=True)
    path = tasks_dir / filename
    path.write_text(content, encoding="utf-8")
    return path, epic_id
