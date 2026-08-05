import re
from dataclasses import dataclass, field


@dataclass
class ValidationError:
    line: int
    message: str


@dataclass
class ValidationResult:
    valid: bool
    file_type: str = ""  # "epic", "user-story", "task", or ""
    errors: list[ValidationError] = field(default_factory=list)


_VALID_STATUSES = {"TODO", "IN_PROGRESS", "REVIEW", "DONE"}

_TITLE_PATTERNS = {
    "epic": re.compile(r"^# FB-\d{3} · .+$"),
    "user-story": re.compile(r"^# US-FB\d{3}-\d{2}[A-Z]? · .+$"),
    "task": re.compile(r"^# T-FB\d{3}-US\d{2}[A-Z]?-\d{2} · .+$"),
}

_EPIC_SECTIONS = {"Objetivo", "Alcance", "Estado", "Dependencias", "Criterios de aceptación"}
_US_SECTIONS = {"Historia", "Criterios de aceptación", "Prioridad", "Dependencias", "Estado"}
_TASK_SECTIONS = {"Objetivo", "Descripción", "Criterios de aceptación", "Prioridad", "Dependencias", "Estado"}

_REQUIRED_SECTIONS = {
    "epic": _EPIC_SECTIONS,
    "user-story": _US_SECTIONS,
    "task": _TASK_SECTIONS,
}

_REF_FIELD_PATTERN = re.compile(r"^\*\*(Epic|User Story):\*\*\s+\S+")

_EPIC_REF_PATTERN = re.compile(r"^\*\*Epic:\*\*\s+FB-\d{3}$")
_US_REF_PATTERN = re.compile(r"^\*\*User Story:\*\*\s+US-FB\d{3}-\d{2}[A-Z]?$")

_DEP_FIELD_RE = re.compile(
    r"\*\*(FB-\d{3}|US-FB\d{3}-\d{2}[A-Z]?|T-FB\d{3}-US\d{2}[A-Z]?-\d{2})\*\*"
)
_STATUS_PATTERN = re.compile(r"^## Estado\s*$|^## Estado:\s*(TODO|IN_PROGRESS|REVIEW|DONE)$")
_SECTION_HEADER = re.compile(r"^## (.+)")


def _detect_type(title: str) -> str | None:
    for file_type, pattern in _TITLE_PATTERNS.items():
        if pattern.match(title.strip()):
            return file_type
    return None


def _check_status_value(lines: list[str], status_line_idx: int) -> list[ValidationError]:
    errors: list[ValidationError] = []
    line = lines[status_line_idx].strip()
    m = _STATUS_PATTERN.match(line)
    if not m:
        errors.append(ValidationError(
            status_line_idx + 1,
            "## Estado: formato inválido — debe ser '## Estado' seguido del valor en la línea "
            "siguiente, o '## Estado: <TODO|IN_PROGRESS|REVIEW|DONE>' en la misma línea"
        ))
    else:
        if m.group(1) is not None:
            status_value = m.group(1)
            if status_value not in _VALID_STATUSES:
                errors.append(ValidationError(
                    status_line_idx + 1,
                    f"## Estado: valor '{status_value}' no válido — debe ser TODO, IN_PROGRESS, REVIEW o DONE"
                ))
            return errors
        # Status value is on the following line(s); skip blank lines.
        for j in range(status_line_idx + 1, len(lines)):
            next_line = lines[j].strip()
            if not next_line:
                continue
            if next_line.startswith("## "):
                errors.append(ValidationError(
                    status_line_idx + 1,
                    "## Estado: falta el valor (debe ser TODO, IN_PROGRESS, REVIEW o DONE)"
                ))
                return errors
            # Check if the line (or its first word) is a valid status
            first_word = next_line.split()[0] if next_line else ""
            if next_line in _VALID_STATUSES or first_word in _VALID_STATUSES:
                # Accept if line is exactly a valid status or starts with one
                if first_word not in _VALID_STATUSES:
                    errors.append(ValidationError(
                        j + 1,
                        f"## Estado: valor '{next_line}' no válido — debe ser TODO, IN_PROGRESS, REVIEW o DONE"
                    ))
                return errors
            else:
                errors.append(ValidationError(
                    j + 1,
                    f"## Estado: valor '{next_line}' no válido — debe ser TODO, IN_PROGRESS, REVIEW o DONE"
                ))
                return errors
        errors.append(ValidationError(
            status_line_idx + 1,
            "## Estado: falta el valor (debe estar en la línea siguiente)"
        ))
    return errors


def _check_ref_field(lines: list[str], idx: int, expected_field: str, expected_pattern: re.Pattern) -> list[ValidationError]:
    errors: list[ValidationError] = []
    line = lines[idx].strip()
    prefix = f"**{expected_field}:**"
    if not line.startswith(prefix):
        errors.append(ValidationError(
            idx + 1,
            f"Campo '{expected_field}': falta el prefijo '**{expected_field}:**'"
        ))
    elif not expected_pattern.match(line):
        errors.append(ValidationError(
            idx + 1,
            f"Campo '{expected_field}': el identificador no tiene el formato esperado "
            f"({expected_pattern.pattern}) o contiene texto libre añadido"
        ))
    return errors


def _check_dependencies(lines: list[str], deps_header_idx: int) -> list[ValidationError]:
    errors: list[ValidationError] = []
    for i in range(deps_header_idx + 1, len(lines)):
        line = lines[i].strip()
        if line.startswith("## "):
            break
        if not line or line == "Ninguna.":
            continue
        if "**" not in line:
            continue
        refs = _DEP_FIELD_RE.findall(line)
        if not refs:
            errors.append(ValidationError(
                i + 1,
                "## Dependencias: línea con '**' que no tiene formato de dependencia válido **<ID>**"
            ))
    return errors


def validate_backlog_content(content: str) -> ValidationResult:
    lines = content.split("\n")
    errors: list[ValidationError] = []

    # 1. Title
    if not lines:
        return ValidationResult(valid=False, errors=[
            ValidationError(0, "El fichero está vacío")
        ])
    title = lines[0].strip()
    file_type = _detect_type(title)
    if file_type is None:
        errors.append(ValidationError(
            1,
            "Título: no coincide con el formato # <ID> · <título>. "
            "IDs esperados: FB-NNN (Epic), US-FBNNN-nn (User Story), "
            "T-FBNNN-USnn-mm (Task)"
        ))

    # 2. Collect sections
    found_sections: dict[str, int] = {}
    for i, line in enumerate(lines):
        m = _SECTION_HEADER.match(line.strip())
        if m:
            section_name = m.group(1).strip()
            # Normalize: "Estado: REVIEW" → "Estado"
            if ":" in section_name:
                base_name = section_name.split(":", 1)[0].strip()
                found_sections[base_name] = i
            found_sections[section_name] = i

    # 3. All internal sections must be ##
    for i, line in enumerate(lines):
        if i == 0:
            continue
        stripped = line.strip()
        if stripped.startswith("# ") and not stripped.startswith("## "):
            errors.append(ValidationError(
                i + 1,
                f"Sección '{stripped}' usa H1 — todas las secciones internas deben ser H2 (##)"
            ))

    # 4. Required sections per type
    if file_type:
        required = _REQUIRED_SECTIONS.get(file_type, set())
        for section in required:
            if section not in found_sections:
                errors.append(ValidationError(
                    0,
                    f"Falta la sección obligatoria '## {section}' para tipo {file_type}"
                ))

    # 5. Reference fields (Epic, User Story) for US and Task types
    if file_type in ("user-story", "task"):
        for i, line in enumerate(lines):
            if line.strip().startswith("**Epic:**"):
                errors.extend(_check_ref_field(lines, i, "Epic", _EPIC_REF_PATTERN))
                break
        else:
            errors.append(ValidationError(
                0,
                "Falta el campo obligatorio '**Epic:** FB-NNN'"
            ))
    if file_type == "task":
        for i, line in enumerate(lines):
            if line.strip().startswith("**User Story:**"):
                errors.extend(_check_ref_field(lines, i, "User Story", _US_REF_PATTERN))
                break
        else:
            errors.append(ValidationError(
                0,
                "Falta el campo obligatorio '**User Story:** US-FBNNN-nn'"
            ))

    # 6. Estado
    if "Estado" in found_sections or "Estado:" in found_sections:
        estado_key = "Estado" if "Estado" in found_sections else "Estado:"
        errors.extend(_check_status_value(lines, found_sections[estado_key]))

    # 7. Dependencies
    if "Dependencias" in found_sections:
        errors.extend(_check_dependencies(lines, found_sections["Dependencias"]))

    return ValidationResult(
        valid=len(errors) == 0,
        file_type=file_type or "",
        errors=errors,
    )


def validate_backlog_file(path: str) -> ValidationResult:
    with open(path, encoding="utf-8") as f:
        content = f.read()
    return validate_backlog_content(content)
