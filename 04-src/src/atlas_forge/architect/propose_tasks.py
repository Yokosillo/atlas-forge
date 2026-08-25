from dataclasses import dataclass, field
from pathlib import Path

from atlas_forge.architect.review_user_story import USReviewResult


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
    difficulty: str  # "Crítica", "Alta", "Media", "Baja"
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


def _read_us_content(us_file_path: str) -> str:
    path = Path(us_file_path)
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def _parse_us_sections(content: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current_section = ""
    section_lines: list[str] = []
    for line in content.split("\n"):
        if line.startswith("## "):
            if current_section:
                sections[current_section] = "\n".join(section_lines).strip()
            current_section = line[3:].strip()
            section_lines = []
            continue
        if current_section:
            section_lines.append(line)
    if current_section:
        sections[current_section] = "\n".join(section_lines).strip()
    return sections


def _extract_us_title(content: str) -> str:
    sections = _parse_us_sections(content)
    for key in sections:
        if "historia" in key.lower():
            return sections[key].split(".")[0].strip()[:120]
    return ""


def propose_tasks_from_review(
    review: USReviewResult,
    epic_id: str,
    us_title: str = "",
    llm_generate=None,
) -> ProposedTasks:
    """Genera la propuesta de Tasks a partir de un `USReviewResult` ya
    cargado (función pura, sin I/O de ficheros).

    Núcleo de dominio de `propose_tasks_from_user_story`, invocable sin
    ruta de fichero: las condiciones de negocio (US con huecos, no lista
    para desgranar) se reflejan en `notes`, nunca lanzan excepción.
    `us_title` se pasa ya extraído; si no viene, se usa el texto por
    defecto. `llm_generate` permite sustituir la generación determinista
    con una propuesta externa (recibe `review`, `epic_id` y `us_title`).
    """
    result = ProposedTasks(story_id=review.story_id, epic_id=epic_id)

    if review.has_gaps:
        result.notes.append(
            "La User Story tiene huecos detectados en la revisión previa. "
            "No se generan Tasks hasta que los huecos esten resueltos:\n" +
            "\n".join(f"  - {g.section}: {g.description}" for g in review.gaps)
        )
        return result

    if not review.ready_for_tasks:
        result.notes.append(
            "La User Story no esta lista para desgranar en Tasks."
        )
        return result

    if llm_generate is not None:
        return llm_generate(review, epic_id, us_title)

    if not us_title:
        us_title = "User Story sin titulo extraible"

    # T-AF036-US23-XX (decisión de producto): se retira el fallback de
    # generación por plantillas genéricas ("implementar la logica central" /
    # "conectar la logica" / "validar el flujo completo"). Para cualquier US,
    # esas 3 Tasks hardcodeadas no representan trabajo real y contaminaban el
    # pipeline con falso pendiente (casos reales: US-AF005-03 "declarar
    # capacidades", US-AF008-09 "investigación de mensajería nativa").
    # Sin `llm_generate` (agente Arquitecto que desglosa la US con criterios
    # reales), NO se inventa trabajo: la US se deja sin Tasks (estado
    # NO_TASKS/TO_PLAN del backlog) y la nota informa al operador de que el
    # desglose debe venir del Arquitecto o a mano.
    result.notes.append(
        "Esta User Story no generó Tasks por el camino automático: el "
        "desglose de US en Tasks requiere el desglose del Arquitecto "
        "(`llm_generate`) o aterrizaje manual con criterios verificables — "
        "no se generan plantillas genéricas (decisión de producto "
        "T-AF036-US23-00). La US queda pendiente de desglose real."
    )

    return result


def propose_tasks_from_user_story(
    review: USReviewResult,
    epic_id: str,
    us_file_path: str,
    llm_generate=None,
) -> ProposedTasks:
    result = ProposedTasks(story_id=review.story_id, epic_id=epic_id)

    if review.has_gaps:
        result.notes.append(
            "La User Story tiene huecos detectados en la revisión previa. "
            "No se generan Tasks hasta que los huecos esten resueltos:\n" +
            "\n".join(f"  - {g.section}: {g.description}" for g in review.gaps)
        )
        return result

    if not review.ready_for_tasks:
        result.notes.append(
            "La User Story no esta lista para desgranar en Tasks."
        )
        return result

    if llm_generate is not None:
        return llm_generate(review, epic_id, us_file_path)

    content = _read_us_content(us_file_path)
    us_title = _extract_us_title(content)

    return propose_tasks_from_review(review, epic_id, us_title)


def us_title_from_file(us_file_path: str) -> str:
    """Extrae el título de una User Story desde su fichero (I/O) — helper
    público de la capa de conexión (T-AF036-US04-02): el núcleo puro
    `us_landing.plan_us_landing` recibe el título ya cargado, así que la
    extracción desde disco vive aquí (único punto de I/O), sin duplicar
    la lógica de `_extract_us_title` en el llamador."""
    content = _read_us_content(us_file_path)
    title = _extract_us_title(content)
    return title or "User Story sin titulo extraible"
