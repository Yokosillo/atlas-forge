import re
from dataclasses import dataclass, field
from pathlib import Path

from brain.backlog.parser import parse_frontmatter


@dataclass
class USGap:
    section: str
    description: str


@dataclass
class USReviewResult:
    story_id: str
    has_gaps: bool
    gaps: list[USGap] = field(default_factory=list)
    ready_for_tasks: bool = False


# Campos del frontmatter YAML que sustituyen a las antiguas secciones
# Markdown `## Estado`/`## Dependencias`/`## Prioridad` (formato pre-FB-027).
_FRONTMATTER_REQUIRED_FIELDS = (
    ("state", "Estado"),
    ("dependencies", "Dependencias"),
    ("priority", "Prioridad"),
)

_NUMBERED_ITEM_RE = re.compile(r"^\d+[.)]\s+")


def _is_numbered_item(line: str) -> bool:
    return bool(_NUMBERED_ITEM_RE.match(line))


def review_user_story_for_gaps(file_path: str) -> USReviewResult:
    path = Path(file_path)
    if not path.exists():
        return USReviewResult(
            story_id=path.stem,
            has_gaps=True,
            gaps=[USGap("archivo", f"No se encuentra el fichero {file_path}")],
        )

    content = path.read_text(encoding="utf-8")

    story_id = path.stem
    gaps: list[USGap] = []

    data: dict | None = None
    try:
        data = parse_frontmatter(content)
    except ValueError as error:
        gaps.append(USGap(
            section="formato",
            description=(
                "La User Story no tiene frontmatter YAML válido: "
                f"{error}."
            ),
        ))

    if data is not None:
        data_id = data.get("id")
        if isinstance(data_id, str) and data_id.strip():
            story_id = data_id.strip()

        for field, label in _FRONTMATTER_REQUIRED_FIELDS:
            value = data.get(field)
            if value is None or (isinstance(value, str) and not value.strip()):
                gaps.append(USGap(
                    section=label,
                    description=(
                        f"Falta el campo obligatorio '{field}' en el "
                        "frontmatter YAML de la User Story."
                    ),
                ))

    lines = content.split("\n")

    historia_start = None
    historia_end = None
    criterios_start = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "## Historia":
            historia_start = i
        elif historia_start is not None and historia_end is None and stripped.startswith("## "):
            historia_end = i
        if stripped == "## Criterios de aceptación":
            criterios_start = i

    if historia_start is None:
        gaps.append(USGap(
            section="Historia",
            description="Falta la sección '## Historia' en la User Story.",
        ))
    else:
        historia_lines_end = historia_end if historia_end is not None else len(lines)
        historia_content = "\n".join(lines[historia_start + 1:historia_lines_end]).strip()
        if not historia_content:
            gaps.append(USGap(
                section="Historia",
                description=(
                    "La sección Historia está vacía — la User Story no "
                    "describe qué necesidad cubre."
                ),
            ))

    if criterios_start is None:
        gaps.append(USGap(
            section="Criterios de aceptación",
            description="Falta la sección de criterios de aceptación explícita.",
        ))
    else:
        criteria_items = []
        for line in lines[criterios_start + 1:]:
            stripped = line.strip()
            if stripped.startswith("## "):
                break
            if stripped.startswith("- ") or _is_numbered_item(stripped):
                criteria_items.append(stripped)
        if not criteria_items:
            gaps.append(USGap(
                section="Criterios de aceptación",
                description=(
                    "No se encontraron criterios de aceptación en formato "
                    "lista (- item o 1. item)."
                ),
            ))

    return USReviewResult(
        story_id=story_id,
        has_gaps=len(gaps) > 0,
        gaps=gaps,
        ready_for_tasks=len(gaps) == 0,
    )
