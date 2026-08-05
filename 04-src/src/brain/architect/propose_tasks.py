from dataclasses import dataclass, field

from brain.architect.review_user_story import USReviewResult


@dataclass
class ProposedTask:
    id: str
    title: str
    epic_id: str
    us_id: str
    objective: str
    description: str
    criteria: list[str]
    priority: str  # "Crítica", "Alta", "Media", "Baja"
    dependencies: list[str] = field(default_factory=list)


@dataclass
class ProposedTasks:
    story_id: str
    epic_id: str
    tasks: list[ProposedTask] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _is_independent_value(task: ProposedTask) -> bool:
    objective_lower = task.objective.lower()
    description_lower = task.description.lower()
    value_indicators = [
        "observable", "verificable", "comprobar", "visual", "pantalla",
        "interfaz", "endpoint", "api", "tui", "app",
    ]
    return any(ind in objective_lower or ind in description_lower
               for ind in value_indicators)


def propose_tasks_from_user_story(
    review: USReviewResult,
    epic_id: str,
    us_file_path: str,
) -> ProposedTasks:
    result = ProposedTasks(story_id=review.story_id, epic_id=epic_id)

    if review.has_gaps:
        result.notes.append(
            "La User Story tiene huecos detectados en la revisión previa. "
            "No se generan Tasks hasta que los huecos estén resueltos:\n" +
            "\n".join(f"  - {g.section}: {g.description}" for g in review.gaps)
        )
        return result

    if not review.ready_for_tasks:
        result.notes.append(
            "La User Story no está lista para desgranar en Tasks."
        )
        return result

    return result
