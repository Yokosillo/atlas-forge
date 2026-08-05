from dataclasses import dataclass, field
from pathlib import Path
from brain.backlog.validator import validate_backlog_content


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


_REQUIRED_US_FIELDS = {
    "Criterios de aceptación",
    "Historia",
    "Prioridad",
    "Dependencias",
    "Estado",
}


def review_user_story_for_gaps(file_path: str) -> USReviewResult:
    path = Path(file_path)
    if not path.exists():
        return USReviewResult(
            story_id=path.stem,
            has_gaps=True,
            gaps=[USGap("archivo", f"No se encuentra el fichero {file_path}")],
        )

    content = path.read_text(encoding="utf-8")
    lines = content.split("\n")

    story_id = ""
    if lines:
        first = lines[0].strip()
        if first.startswith("# "):
            story_id = first[2:].strip().split(" · ")[0] if " · " in first else first[2:].strip().split(" ")[0]

    result = USReviewResult(story_id=story_id, has_gaps=False)
    found_sections: set[str] = set()

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            section_name = stripped[3:].strip()
            if ":" in section_name:
                section_name = section_name.split(":", 1)[0].strip()
            found_sections.add(section_name)

    missing = _REQUIRED_US_FIELDS - found_sections
    if missing:
        for section in missing:
            result.gaps.append(USGap(
                section=section,
                description=f"Falta la sección obligatoria '## {section}' en la User Story."
            ))

    historia_start = None
    historia_end = None
    criterios_start = None
    for i, line in enumerate(lines):
        if line.strip() == "## Historia":
            historia_start = i
        elif historia_start is not None and line.strip().startswith("## ") and historia_end is None:
            historia_end = i
        if line.strip() == "## Criterios de aceptación":
            criterios_start = i

    if historia_start is not None and historia_end is not None:
        historia_content = "\n".join(
            lines[historia_start + 1:historia_end]
        ).strip()
        if not historia_content or historia_content.isspace():
            result.gaps.append(USGap(
                section="Historia",
                description="La sección Historia está vacía — la User Story no describe qué necesidad cubre."
            ))

    if criterios_start is not None:
        after_criterios = lines[criterios_start + 1:]
        criteria_items = []
        for line in after_criterios:
            if line.strip().startswith("## "):
                break
            stripped = line.strip()
            if stripped.startswith("- "):
                criteria_items.append(stripped)
        if not criteria_items:
            result.gaps.append(USGap(
                section="Criterios de aceptación",
                description="No se encontraron criterios de aceptación en formato lista (- item)."
            ))
    else:
        result.gaps.append(USGap(
            section="Criterios de aceptación",
            description="Falta la sección de criterios de aceptación explícita."
        ))

    if not result.gaps:
        format_result = validate_backlog_content(content)
        if not format_result.valid:
            for e in format_result.errors:
                result.gaps.append(USGap(
                    section="formato",
                    description=f"Error de formato L{e.line}: {e.message}",
                ))

    result.has_gaps = len(result.gaps) > 0
    result.ready_for_tasks = not result.has_gaps

    return result
