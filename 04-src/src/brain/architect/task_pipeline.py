from dataclasses import dataclass, field
from pathlib import Path

from brain.architect.propose_tasks import ProposedTasks
from brain.backlog.validator import validate_backlog_content


@dataclass
class TaskValidationResult:
    valid: bool = False
    errors: list[str] = field(default_factory=list)


@dataclass
class TaskSelfAuditVerdict:
    status: str  # APROBADO / APROBADO_CON_OBSERVACIONES / RECHAZADO
    justification: str = ""
    suggestions: list[str] = field(default_factory=list)


@dataclass
class TaskApprovalResult:
    task_id: str
    approved: bool
    written_path: str = ""


@dataclass
class TaskPipelineResult:
    proposal: ProposedTasks
    validation: TaskValidationResult = field(default_factory=TaskValidationResult)
    self_audit: TaskSelfAuditVerdict | None = None
    approved_tasks: list[TaskApprovalResult] = field(default_factory=list)


def _yaml_block_list(items: list[str]) -> str:
    if not items:
        return " []"
    return "\n" + "\n".join(f"  - {item}" for item in items)


def _build_task_content(task) -> str:
    criteria_text = "\n".join(f"- {c}" for c in task.criteria)
    deps_block = _yaml_block_list(task.dependencies) if task.dependencies else " []"
    difficulty = getattr(task, 'difficulty', None)
    difficulty_line = f"difficulty: {difficulty}\n" if difficulty else ""
    return (
        "---\n"
        f"id: {task.id}\n"
        "type: task\n"
        f"title: {task.title}\n"
        f"epic: {task.epic_id}\n"
        f"user_story: {task.us_id}\n"
        f"state: TODO\n"
        f"dependencies:{deps_block}\n"
        f"priority: {task.priority}\n"
        f"{difficulty_line}"
        "---\n\n"
        f"## Objetivo\n\n{task.objective}\n\n"
        f"## Descripción\n\n{task.description}\n\n"
        f"## Criterios de aceptación\n\n{criteria_text}\n"
    )


def _validate_tasks_format(proposal: ProposedTasks) -> TaskValidationResult:
    errors: list[str] = []
    for task in proposal.tasks:
        content = _build_task_content(task)
        result = validate_backlog_content(content)
        if not result.valid:
            for err in result.errors:
                errors.append(f"{task.id}: L{err.line}: {err.message}")
    return TaskValidationResult(valid=len(errors) == 0, errors=errors)


def _self_audit_tasks(proposal: ProposedTasks, validation: TaskValidationResult) -> TaskSelfAuditVerdict:
    suggestions: list[str] = []

    if not proposal.tasks:
        return TaskSelfAuditVerdict(
            status="RECHAZADO",
            justification="No se generó ninguna Task.",
        )

    if not validation.valid:
        suggestions.append("Corregir errores de formato detectados por el validador.")

    for task in proposal.tasks:
        if not task.criteria:
            suggestions.append(
                f"{task.id}: no tiene criterios de aceptación."
            )
        if not task.description.strip():
            suggestions.append(
                f"{task.id}: descripción vacía."
            )

    if any("vacía" in s or "no tiene" in s for s in suggestions):
        return TaskSelfAuditVerdict(
            status="RECHAZADO",
            justification="La autoauditoría encontró problemas que impiden la aprobación.",
            suggestions=suggestions,
        )
    elif suggestions:
        return TaskSelfAuditVerdict(
            status="APROBADO_CON_OBSERVACIONES",
            justification="La propuesta es funcional pero tiene observaciones menores.",
            suggestions=suggestions,
        )
    return TaskSelfAuditVerdict(
        status="APROBADO",
        justification="La propuesta pasa la autoauditoría sin observaciones.",
    )


def _write_task_file(task, output_dir: str) -> str:
    content = _build_task_content(task)
    filename = f"{task.id}-{_slugify(task.title)}.md"
    path = Path(output_dir) / filename
    path.write_text(content, encoding="utf-8")
    return str(path)


def _slugify(text: str) -> str:
    return text.lower().replace(" ", "-").replace("/", "-")


def run_task_pipeline(
    proposal: ProposedTasks,
    output_dir: str = "",
    auto_approve: bool = False,
) -> TaskPipelineResult:
    result = TaskPipelineResult(proposal=proposal)

    result.validation = _validate_tasks_format(proposal)
    if not result.validation.valid:
        return result

    result.self_audit = _self_audit_tasks(proposal, result.validation)

    status = result.self_audit.status
    can_approve = status == "APROBADO" or (status == "APROBADO_CON_OBSERVACIONES" and auto_approve)

    if can_approve and output_dir:
        for task in proposal.tasks:
            path = _write_task_file(task, output_dir)
            result.approved_tasks.append(TaskApprovalResult(
                task_id=task.id,
                approved=True,
                written_path=path,
            ))

    return result
