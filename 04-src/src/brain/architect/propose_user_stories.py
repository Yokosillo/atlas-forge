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
            scope = scope_text
        elif current_section.startswith("## Alcance v1"):
            scope_v1 = text
        elif current_section.startswith("## Diferido a v2"):
            scope_v2_deferred = text
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


def _parse_scope_items(scope_text: str) -> list[str]:
    items: list[str] = []
    for line in scope_text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("- "):
            name = stripped[2:].strip()
            if name and not name.startswith("(") and not name.startswith("*"):
                items.append(name)
    return items


def _split_scope_into_stories(
    epic: EpicContext, scope_items: list[str]
) -> list[ProposedUserStory]:
    stories: list[ProposedUserStory] = []
    epic_num = epic.epic_id.split("-")[-1] if "-" in epic.epic_id else epic.epic_id
    for idx, item in enumerate(scope_items, start=1):
        # Formato correcto: US-FB999-01 (no US-FB-999-01)
        us_id = f"US-{epic.epic_id.replace('-', '')}-{idx:02d}"
        short = item.split("(")[0].strip().rstrip(".") if "(" in item else item.split(".")[0].strip()
        short = short.split("—")[0].strip()
        title = short[:80] if len(short) > 80 else short
        description = (
            f"Como usuario de Factory Brain, quiero {short[0].lower() + short[1:] if short else short} "
            f"para cumplir con el alcance v1 del Epic {epic.epic_id}."
        )
        criteria = [
            f"La funcionalidad '{short}' esta implementada y es verificable.",
            f"El resultado cumple con lo descrito en el alcance v1 del Epic {epic.epic_id}: '{item[:120]}'.",
        ]
        priority = "Alta"
        stories.append(ProposedUserStory(
            id=us_id,
            title=title,
            epic_id=epic.epic_id,
            description=description,
            criteria=criteria,
            priority=priority,
        ))
    return stories


def propose_user_stories_from_epic(
    epic: EpicContext,
    llm_generate=None,
) -> ProposedUserStories:
    result = ProposedUserStories(epic=epic)

    if epic.scope_v2_deferred:
        result.notes.append(
            f"La Epic {epic.epic_id} declara alcance v2 diferido. No se proponen "
            "User Stories de v2 hasta que el alcance v1 esté cerrado."
        )

    if llm_generate is not None:
        return llm_generate(epic)

    if not epic.scope_v1 and not epic.objective:
        result.notes.append(
            f"La Epic {epic.epic_id} no tiene alcance v1 ni objetivo definido — "
            "no se pueden proponer User Stories sin contexto."
        )
        return result

    scope_items = _parse_scope_items(epic.scope_v1)
    if not scope_items:
        result.notes.append(
            f"El alcance v1 de la Epic {epic.epic_id} no contiene items de "
            "alcance parseables en formato de lista (- item)."
        )
        return result

    result.stories = _split_scope_into_stories(epic, scope_items)
    return result
