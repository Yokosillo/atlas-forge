from dataclasses import dataclass, field
from pathlib import Path

from brain.architect.propose_user_stories import ProposedUserStories
from brain.backlog.validator_v2 import validate_backlog_content_v2


VERDICT_STATUSES = ("APROBADO", "APROBADO_CON_OBSERVACIONES", "RECHAZADO")


def _yaml_block_list(items: list[str]) -> str:
    if not items:
        return " []"
    return "\n" + "\n".join(f"  - {item}" for item in items)


@dataclass
class USValidationResult:
    valid: bool = False
    errors: list[str] = field(default_factory=list)


@dataclass
class USSelfAuditVerdict:
    status: str  # APROBADO / APROBADO_CON_OBSERVACIONES / RECHAZADO
    justification: str = ""
    suggestions: list[str] = field(default_factory=list)


@dataclass
class USApprovalResult:
    story_id: str
    approved: bool
    written_path: str = ""


@dataclass
class USPipelineResult:
    proposal: ProposedUserStories
    validation: USValidationResult = field(default_factory=USValidationResult)
    self_audit: USSelfAuditVerdict | None = None
    approved_stories: list[USApprovalResult] = field(default_factory=list)


def _build_us_content(story) -> str:
    criteria_text = "\n".join(f"- {c}" for c in story.criteria)
    deps_block = _yaml_block_list([story.epic_id])  # default: depends on parent Epic
    # `state: NO_TASKS` (T-FB008-US15-01, 2026-08-17; renombrado desde
    # `SIN_TAREAS` 2026-08-18): toda User Story nueva nace sin Tasks,
    # mismo criterio que `create_user_story`
    # (`backlog/create.py`, formulario manual) — un único punto de
    # verdad para "acabo de nacer, sin desgranar".
    return (
        "---\n"
        f"id: {story.id}\n"
        "type: user_story\n"
        f"title: {story.title}\n"
        f"epic: {story.epic_id}\n"
        f"state: NO_TASKS\n"
        f"dependencies:{deps_block}\n"
        f"priority: {story.priority}\n"
        "---\n\n"
        f"## Historia\n\n{story.description}\n\n"
        f"## Criterios de aceptación\n\n{criteria_text}\n"
    )


def _validate_format(proposal: ProposedUserStories) -> USValidationResult:
    errors: list[str] = []
    for story in proposal.stories:
        content = _build_us_content(story)
        result = validate_backlog_content_v2(content)
        if not result.valid:
            for err in result.errors:
                errors.append(f"{story.id}: L{err.line}: {err.message}")
    return USValidationResult(valid=len(errors) == 0, errors=errors)


def _self_audit(proposal: ProposedUserStories, validation: USValidationResult) -> USSelfAuditVerdict:
    suggestions: list[str] = []

    if not proposal.stories:
        return USSelfAuditVerdict(
            status="RECHAZADO",
            justification="No se generó ninguna User Story.",
        )

    if not validation.valid:
        suggestions.append("Corregir errores de formato detectados por el validador.")

    if proposal.stories:
        if not all(s.criteria for s in proposal.stories):
            suggestions.append(
                "APROBADO_CON_OBSERVACIONES: alguna User Story no tiene criterios "
                "de aceptación explícitos."
            )
        if not all(s.description.strip() for s in proposal.stories):
            suggestions.append(
                "RECHAZADO: alguna User Story tiene la descripción vacía."
            )

    if any("RECHAZADO" in s for s in suggestions):
        return USSelfAuditVerdict(
            status="RECHAZADO",
            justification="La autoauditoría encontró problemas que impiden la aprobación.",
            suggestions=suggestions,
        )
    elif suggestions:
        return USSelfAuditVerdict(
            status="APROBADO_CON_OBSERVACIONES",
            justification="La propuesta es funcional pero tiene observaciones menores.",
            suggestions=suggestions,
        )
    return USSelfAuditVerdict(
        status="APROBADO",
        justification="La propuesta pasa la autoauditoría sin observaciones.",
    )


def _write_story_file(story, output_dir: str) -> str:
    content = _build_us_content(story)
    filename = f"{story.id}-{_slugify(story.title)}.md"
    path = Path(output_dir) / filename
    path.write_text(content, encoding="utf-8")
    return str(path)


def _slugify(text: str) -> str:
    return text.lower().replace(" ", "-").replace("/", "-")


def validate_proposal(proposal: ProposedUserStories) -> USValidationResult:
    return _validate_format(proposal)


def self_audit_proposal(
    proposal: ProposedUserStories, validation: USValidationResult
) -> USSelfAuditVerdict:
    return _self_audit(proposal, validation)


def write_approved_stories(
    proposal: ProposedUserStories, output_dir: str
) -> list[USApprovalResult]:
    results: list[USApprovalResult] = []
    for story in proposal.stories:
        path = _write_story_file(story, output_dir)
        results.append(USApprovalResult(
            story_id=story.id,
            approved=True,
            written_path=path,
        ))
    return results


def run_us_pipeline(
    proposal: ProposedUserStories,
    output_dir: str = "",
    auto_approve: bool = False,
) -> USPipelineResult:
    result = USPipelineResult(proposal=proposal)

    result.validation = _validate_format(proposal)
    if not result.validation.valid:
        return result

    result.self_audit = _self_audit(proposal, result.validation)

    status = result.self_audit.status
    can_approve = status == "APROBADO" or (status == "APROBADO_CON_OBSERVACIONES" and auto_approve)

    if can_approve and output_dir:
        result.approved_stories = write_approved_stories(proposal, output_dir)

    return result
