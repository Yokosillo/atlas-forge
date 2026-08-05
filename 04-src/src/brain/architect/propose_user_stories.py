from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ProposedUserStory:
    id: str
    title: str
    epic_id: str
    description: str
    criteria: list[str]
    priority: str  # "Crítica", "Alta", "Media", "Baja"


@dataclass
class EpicContext:
    epic_id: str
    title: str
    objective: str
    scope: str
    scope_v1: str = ""
    scope_v2_deferred: str = ""
    dependencies: str = ""
    file_path: str = ""


@dataclass
class ProposedUserStories:
    epic: EpicContext
    stories: list[ProposedUserStory] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def load_epic_context(epic_path: str) -> EpicContext:
    path = Path(epic_path)
    content = path.read_text(encoding="utf-8")
    lines = content.split("\n")

    epic_id = ""
    title = ""
    objective = ""
    scope = ""
    scope_v1 = ""
    scope_v2_deferred = ""
    deps = ""

    current_section = ""
    section_lines: list[str] = []

    def flush_section():
        nonlocal objective, scope, scope_v1, scope_v2_deferred, deps
        text = "\n".join(section_lines).strip()
        if current_section == "## Objetivo":
            lines_stripped = [l for l in section_lines if l.strip()
                              and not l.strip() == "---"]
            objective = "\n".join(lines_stripped).strip()
        elif current_section == "## Alcance":
            scope_text = "\n".join(section_lines).strip()
            scope_v1 = _extract_subsection(scope_text, "Alcance v1")
            scope_v2_deferred = _extract_subsection(scope_text, "Diferido a v2")
            scope = scope_text
        elif current_section == "## Dependencias":
            deps = text

    for line in lines:
        if line.startswith("# ") and epic_id == "":
            parts = line[2:].strip().split(" ", 1)
            epic_id = parts[0] if parts else ""
            title = parts[1] if len(parts) > 1 else ""
            continue
        if line.startswith("## "):
            flush_section()
            section_lines = []
            current_section = line
            continue
        if current_section:
            section_lines.append(line)

    flush_section()

    return EpicContext(
        epic_id=epic_id,
        title=title,
        objective=objective,
        scope=scope,
        scope_v1=scope_v1,
        scope_v2_deferred=scope_v2_deferred,
        dependencies=deps,
        file_path=epic_path,
    )


def _extract_subsection(text: str, subsection_name: str) -> str:
    marker = f"## {subsection_name}"
    if marker in text:
        idx = text.index(marker)
        return text[idx + len(marker):].strip()
    for line in text.split("\n"):
        if line.strip() == subsection_name + ":" or line.strip().startswith(subsection_name):
            rest = line[len(subsection_name):].lstrip(":")
            if rest.strip():
                return rest.strip()
    return ""


def propose_user_stories_from_epic(epic: EpicContext) -> ProposedUserStories:
    result = ProposedUserStories(epic=epic)

    if epic.scope_v2_deferred:
        result.notes.append(
            f"La Epic {epic.epic_id} declara alcance v2 diferido. No se proponen "
            "User Stories de v2 hasta que el alcance v1 esté cerrado."
        )

    return result
