"""Creación de items de backlog nuevos desde cero (T-FB036-US02-01,
US-FB036-02 · "Crear una Epic, User Story o Task nueva sin salir de la
pantalla Backlog") — a diferencia de `brain.backlog.edit` (cambia un
campo de un item YA existente), este módulo escribe el fichero completo
por primera vez.

Solo Epic está cubierto por esta Task (`T-FB036-US02-01`); User Story y
Task son Tasks separadas de la misma Story (`T-FB036-US02-02`/`-03`),
todavía sin implementar — este módulo empieza con `create_epic` en
solitario, no con las tres a la vez, siguiendo la propia Task."""

from __future__ import annotations

import re
from pathlib import Path

from brain.backlog.validator_v2 import validate_backlog_content_v2
from brain.runtime import sanitize_session_name_part

EPIC_ID_PATTERN = re.compile(r"^FB-\d{3,}$")


class InvalidEpicIdError(ValueError):
    """El `id` recibido no tiene el formato `FB-\\d{3,}` — rechazo
    explícito antes de tocar disco (criterio de aceptación de la Task:
    "el servidor nunca confía únicamente en la validación de cliente")."""


class EpicAlreadyExistsError(ValueError):
    """Ya existe un fichero `{id}*.md` en `02-backlog/epics/` — no se
    sobreescribe, el llamador debe traducir esto a 409."""

    def __init__(self, epic_id: str, existing_path: Path) -> None:
        self.epic_id = epic_id
        self.existing_path = existing_path
        super().__init__(f"Ya existe una Epic con id '{epic_id}': {existing_path}")


class BacklogValidationError(ValueError):
    """El contenido generado no pasa `validate_backlog_content_v2` — el
    fichero real NO se escribe; los mensajes del validador se propagan
    verbatim para que la capa HTTP los devuelva tal cual."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def _epic_slug(title: str) -> str:
    """Mismo criterio de saneo que el resto del proyecto para nombres de
    fichero derivados de texto libre (`sanitize_session_name_part`,
    `brain.runtime` — ya usado para sesiones tmux y para
    `reconciliation_log_path`/`architect_queue_path`), reutilizado aquí
    en vez de definir una cuarta variante de "slugify" (`architect/
    us_pipeline.py`/`task_pipeline.py` ya tienen la suya propia, más
    simple — no se toca ninguna de las dos, esto es solo para Epic)."""
    return sanitize_session_name_part(title)


def _build_epic_content(epic_id: str, title: str, objetivo: str, fase: str | None) -> str:
    fase_line = f"fase: {fase}\n" if fase else "fase: null\n"
    return (
        "---\n"
        f"id: {epic_id}\n"
        "type: epic\n"
        f"title: {title}\n"
        "state: TODO\n"
        "dependencies: []\n"
        f"{fase_line}"
        "---\n\n"
        f"# {epic_id} · {title}\n\n"
        "## Objetivo\n\n"
        f"{objetivo}\n"
    )


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
    if epics_dir.is_dir():
        existing = next(iter(sorted(epics_dir.glob(f"{epic_id}-*.md"))), None)
        if existing is None:
            existing = next(iter(sorted(epics_dir.glob(f"{epic_id}.md"))), None)
        if existing is not None:
            raise EpicAlreadyExistsError(epic_id, existing)

    filename = f"{epic_id}-{_epic_slug(title)}.md"
    content = _build_epic_content(epic_id, title, objetivo, fase)

    result = validate_backlog_content_v2(content, filename=filename)
    if not result.valid:
        raise BacklogValidationError([error.message for error in result.errors])

    epics_dir.mkdir(parents=True, exist_ok=True)
    path = epics_dir / filename
    path.write_text(content, encoding="utf-8")
    return path
