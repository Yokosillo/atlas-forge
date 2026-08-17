from dataclasses import dataclass, field
from pathlib import Path

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


def _generate_tasks_from_sections(
    review: USReviewResult,
    epic_id: str,
    us_title: str,
) -> list[ProposedTask]:
    us_id = review.story_id
    # Extraer numero de US y Epic para generar T-FBxxx-USnn-mm
    # us_id tiene formato US-FB999-01, extraer 999 y 01
    us_parts = us_id.split("-")  # ["US", "FB999", "01"]
    epic_num = ""
    us_num = ""
    if len(us_parts) >= 3:
        epic_num = us_parts[1]  # "FB999"
        us_num = us_parts[2]    # "01"

    templates = [
        {
            "suffix": "implementar-nucleo",
            "title_part": "implementar la logica central",
            "objective": f"Implementar la logica central de la User Story {us_id} ({us_title}).",
            "description": (
                f"Construir la funcionalidad principal descrita en la User Story "
                f"sin exponer ningun punto de acceso externo — solo la capa de "
                f"dominio pura, invocable programaticamente sin dependencias de "
                f"infraestructura (HTTP, persistencia, I/O)."
            ),
            "criteria": [
                f"La logica principal de {us_id} esta implementada y es invocable programaticamente.",
                "No tiene dependencias de infraestructura externa.",
            ],
            "priority": "Critica",
            "difficulty": "Critica",
            "deps": [],
        },
        {
            "suffix": "conectar-entrada",
            "title_part": "conectar la logica a su contexto de uso",
            "objective": f"Integrar la funcionalidad de {us_id} en el flujo que la consume.",
            "description": (
                f"Conectar el modulo de dominio implementado al contexto que lo "
                f"invoca — ya sea desde otro modulo, desde un comando CLI, o desde "
                f"un flujo de agente. El objetivo es que el codigo implementado "
                f"sea accesible desde fuera del modulo, pero sin que ese punto de "
                f"conexion constituya una funcionalidad autonoma."
            ),
            "criteria": [
                f"El modulo de {us_id} es invocable desde su contexto de uso.",
                "La conexion no introduce logica de negocio duplicada.",
            ],
            "priority": "Critica",
            "difficulty": "Alta",
            "deps": [f"T-{us_id}-01"],
        },
        {
            "suffix": "validar-flujo",
            "title_part": "validar el flujo completo",
            "objective": f"Verificar que {us_id} funciona correctamente en su flujo real.",
            "description": (
                f"Ejecutar el flujo completo desde el contexto de uso y verificar "
                f"que el resultado cumple los criterios de aceptacion de la User "
                f"Story. Incluye ejercicios que recorren el camino real de "
                f"invocacion."
            ),
            "criteria": [
                f"El flujo completo de {us_id} se ejecuta sin errores.",
                "Los criterios de aceptacion de la US son verificables.",
            ],
            "priority": "Alta",
            "difficulty": "Alta",
            "deps": [f"T-{us_id}-02"],
        },
    ]

    tasks: list[ProposedTask] = []
    for i, tmpl in enumerate(templates, start=1):
        # Formato correcto: T-FB999-US01-01 (no US-FB999-01-01)
        task_id = f"T-{epic_num}-US{us_num}-{i:02d}"
        # Dependencies usan el mismo formato
        formatted_deps = []
        for d in tmpl["deps"]:
            if d == f"T-{us_id}-01":
                # Convertir viejo formato a nuevo
                formatted_deps.append(task_id[:-2] + "01")  # T-FB999-US01-01
            else:
                formatted_deps.append(d)

        task = ProposedTask(
            id=task_id,
            title=f"{task_id} · {tmpl['title_part']}",
            epic_id=epic_id,
            us_id=us_id,
            objective=tmpl["objective"],
            description=tmpl["description"],
            criteria=tmpl["criteria"],
            priority=tmpl["priority"],
            difficulty=tmpl["difficulty"],
            dependencies=formatted_deps,
        )
        tasks.append(task)
    return tasks


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
    if not us_title:
        us_title = "User Story sin titulo extraible"

    raw_tasks = _generate_tasks_from_sections(review, epic_id, us_title)

    for task in raw_tasks:
        if _is_independent_value(task):
            result.notes.append(
                f"{task.id}: descartada por tener valor observable independiente "
                f"(criterio de corte US vs Task de METODOLOGIA.md)."
            )
        else:
            result.tasks.append(task)

    return result
