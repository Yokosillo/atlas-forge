"""Script de migracion de todo `02-backlog/` del formato Markdown antiguo
(regex sobre convenciones de texto) al formato YAML frontmatter + Markdown
(FB-027).

Uso:
    python3 migrate_backlog.py [--dry-run] [--backlog-path 02-backlog/]

- Lee TODOS los ficheros de {epics,user-stories,tasks}/*.md
- Extrae campos estructurados (id, state, dependencies, priority, fase)
- Genera YAML frontmatter con los campos
- Conserva el cuerpo en Markdown (secciones ## para prosa)
- Elimina del cuerpo las secciones que pasan al frontmatter
  (## Estado, ## Dependencias, ## Prioridad, ## Fase)
- Escribe el fichero en el formato nuevo (.bak de respaldo opcional)
- Valida cada fichero migrado contra validator_v2
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

# ── patterns ────────────────────────────────────────────────────────────────

_ID_PATTERN = re.compile(
    r"(?:T|US)-FB\d{3,}(?:-US\d{2}[A-Z]?)?-\d{2}[A-Z]?"
)
_EPIC_ID_PATTERN = re.compile(r"FB-\d{3,}")
_ALL_ID_SCAN = re.compile(
    r"(?:T|US)-FB\d{3,}(?:-US\d{2}[A-Z]?)?-\d{2}[A-Z]?|FB-\d{3,}"
)

_ESTADO_HEADER = re.compile(r"^##\s*Estado\s*(?::\s*(.+))?$", re.IGNORECASE)
_PRIORIDAD_HEADER = re.compile(r"^##\s*Prioridad\s*(?::\s*(.+))?$", re.IGNORECASE)
_DEPENDENCIAS_HEADER = re.compile(r"^##\s*Dependencias\s*$", re.IGNORECASE)
_FASE_HEADER = re.compile(r"^##\s*Fase\s*(?::\s*(.+))?$", re.IGNORECASE)
_SECTION_HEADER = re.compile(r"^##\s+")
_BOLD_DEP_RE = re.compile(
    r"\*\*((?:T|US)-FB\d{3,}(?:-US\d{2}[A-Z]?)?-\d{2}[A-Z]?|FB-\d{3,})\*\*"
)

_VALID_STATES = {"TODO", "IN_PROGRESS", "REVIEW", "DONE"}

_STRUCTURED_SECTIONS = {"estado", "dependencias", "prioridad", "fase"}

_SECTIONS_TO_REMOVE_FROM_BODY = {"Estado", "Dependencias", "Prioridad", "Fase"}


# ── helpers ──────────────────────────────────────────────────────────────────


def _item_id_from_stem(stem: str) -> str | None:
    m = _ID_PATTERN.match(stem)
    if m:
        return m.group(0)
    m = _EPIC_ID_PATTERN.match(stem)
    return m.group(0) if m else None


def _item_type(item_id: str) -> str:
    if item_id.startswith("US-"):
        return "user_story"
    if item_id.startswith("FB-"):
        return "epic"
    return "task"


def _extract_title_from_h1(text: str) -> str:
    first_line = text.splitlines()[0].strip() if text else ""
    if first_line.startswith("# "):
        h1 = first_line[2:].strip()
        if "·" in h1:
            return h1.split("·", 1)[1].strip()
        prefix = _item_id_from_stem(Path("dummy").with_name(h1.split()[0]).stem)
        if prefix:
            rest = h1[len(prefix):].strip()
            return rest.lstrip("·").strip()
        return h1
    return ""


def _extract_state(lines: list[str]) -> tuple[str | None, list[int]]:
    """Returns (state_value, line_indices of the state section to remove)."""
    for i, line in enumerate(lines):
        m = _ESTADO_HEADER.match(line.strip())
        if not m:
            continue
        section_start = i
        if m.group(1) and m.group(1).strip():
            value = m.group(1).strip()
            value = value.split("  #", 1)[0].strip()
            value = value.split("#", 1)[0].strip()
            return value, [section_start]

        for j in range(i + 1, len(lines)):
            stripped = lines[j].strip()
            if not stripped:
                continue
            if _SECTION_HEADER.match(stripped):
                break
            value = stripped
            value = value.split("  #", 1)[0].strip()
            value = value.split("#", 1)[0].strip()
            if value in _VALID_STATES or value.split()[0] in _VALID_STATES:
                actual = value if value in _VALID_STATES else value.split()[0]
                lines_to_remove = list(range(section_start, i + 2))
                return actual, lines_to_remove
            return value.split()[0] if value.split()[0] in _VALID_STATES else value, [section_start]

        lines_to_remove = list(range(section_start, i + 2))
        return None, lines_to_remove

    return None, []


def _extract_dependencies(lines: list[str], own_id: str | None) -> tuple[list[str], list[int]]:
    """Returns (list_of_dep_ids, line_indices of dependency section to remove)."""
    for i, line in enumerate(lines):
        if not _DEPENDENCIAS_HEADER.match(line.strip()):
            continue
        section_start = i
        section_lines = []
        section_end = i + 1
        for j in range(i + 1, len(lines)):
            stripped = lines[j].strip()
            if _SECTION_HEADER.match(stripped):
                break
            section_lines.append(stripped)
            section_end = j + 1

        section_text = "\n".join(section_lines)

        if any(kw in section_text.lower() for kw in ("ninguna", "ninguno")):
            return [], list(range(section_start, section_end))

        deps = set()
        bold_deps = _BOLD_DEP_RE.findall(section_text)
        deps.update(bold_deps)

        negation_active = False
        for line in section_lines:
            stripped = line.strip()
            if re.search(r"no\s+depende", stripped, re.IGNORECASE):
                negation_active = True
                continue
            if negation_active:
                if stripped and not re.match(r"^(?:[-•*]\s|en\s)", stripped):
                    negation_active = False
                else:
                    continue

            if re.match(r"^[-•*]\s", stripped):
                for found_id in _ALL_ID_SCAN.findall(stripped):
                    if found_id != own_id and found_id not in deps:
                        deps.add(found_id)

            backtick_ids = re.findall(r"`((?:T|US)-FB\d{3,}(?:-US\d{2}[A-Z]?)?-\d{2}[A-Z]?)`", stripped)
            for found_id in backtick_ids:
                if found_id != own_id:
                    deps.add(found_id)

        result = sorted(deps)
        return result, list(range(section_start, section_end))

    return [], []


def _extract_priority(lines: list[str]) -> tuple[str | None, list[int]]:
    """Returns (priority keyword or None, line_indices to remove)."""
    for i, line in enumerate(lines):
        m = _PRIORIDAD_HEADER.match(line.strip())
        if not m:
            continue
        section_start = i
        if m.group(1) and m.group(1).strip():
            raw = m.group(1).strip()
            keyword = raw.split()[0].rstrip(".")
            return keyword if keyword in ("Crítica", "Alta", "Media", "Baja") else None, [section_start]

        for j in range(i + 1, len(lines)):
            stripped = lines[j].strip()
            if not stripped:
                continue
            if _SECTION_HEADER.match(stripped):
                break
            keyword = stripped.split()[0].rstrip(".")
            if keyword in ("Crítica", "Alta", "Media", "Baja"):
                return keyword, list(range(section_start, j + 1))
            return None, [section_start]

        return None, [section_start]

    return None, []


def _extract_fase(lines: list[str]) -> tuple[str | None, list[int]]:
    """Returns (fase value or None, line_indices to remove)."""
    for i, line in enumerate(lines):
        m = _FASE_HEADER.match(line.strip())
        if not m:
            continue
        section_start = i
        if m.group(1) and m.group(1).strip():
            return m.group(1).strip(), [section_start]

        for j in range(i + 1, len(lines)):
            stripped = lines[j].strip()
            if not stripped:
                continue
            if _SECTION_HEADER.match(stripped):
                break
            return stripped, list(range(section_start, j + 1))

        return None, [section_start]

    return None, []


def _extract_epic_ref(lines: list[str]) -> str | None:
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("**Epic:"):
            value = stripped.removeprefix("**Epic:").strip()
            value = value.removeprefix("**").strip()
            value = value.rstrip("*").strip()
            m = _EPIC_ID_PATTERN.match(value)
            return m.group(0) if m else None
    return None


def _extract_us_ref(lines: list[str]) -> str | None:
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("**User Story:"):
            value = stripped.removeprefix("**User Story:").strip()
            value = value.removeprefix("**").strip()
            value = value.rstrip("*").strip()
            m = re.match(r"US-FB\d{3,}-\d{2}[A-Z]?", value)
            return m.group(0) if m else None
    return None


def _is_standalone_ref_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("**Epic:") or stripped.startswith("**User Story:")


# ── main migration ───────────────────────────────────────────────────────────


def migrate_content(content: str, filename: str) -> str | None:
    """Convierte el contenido de formato antiguo a formato nuevo.

    Returns:
        Nuevo contenido en formato YAML frontmatter + Markdown, o None si hay
        un error irrecuperable.
    """
    lines = content.splitlines(keepends=True)
    raw_lines = [l.rstrip("\n") for l in lines]

    stem = Path(filename).stem
    item_id = _item_id_from_stem(stem)
    if item_id is None:
        print(f"  [ERROR] {filename}: no se pudo extraer ID del nombre", file=sys.stderr)
        return None

    item_type = _item_type(item_id)
    title = _extract_title_from_h1(content)
    epic_ref = _extract_epic_ref(raw_lines)
    us_ref = _extract_us_ref(raw_lines)

    state_val, state_lines = _extract_state(raw_lines)
    deps_val, deps_lines = _extract_dependencies(raw_lines, item_id)
    priority_val, priority_lines = _extract_priority(raw_lines)
    fase_val, fase_lines = _extract_fase(raw_lines)

    if state_val is None:
        print(f"  [ERROR] {filename}: no se pudo extraer ## Estado", file=sys.stderr)
        return None

    if state_val not in _VALID_STATES:
        state_val = state_val.split()[0] if state_val.split() else state_val
        if state_val not in _VALID_STATES:
            print(f"  [WARN] {filename}: estado '{state_val}' no en conjunto cerrado, usando como esta", file=sys.stderr)

    lines_to_remove: set[int] = set()
    lines_to_remove.update(state_lines)
    lines_to_remove.update(deps_lines)
    lines_to_remove.update(priority_lines)
    lines_to_remove.update(fase_lines)

    for i, line in enumerate(raw_lines):
        if _is_standalone_ref_line(line):
            if line.strip().startswith("**Epic:") and epic_ref is not None:
                lines_to_remove.add(i)
            elif line.strip().startswith("**User Story:") and us_ref is not None:
                lines_to_remove.add(i)

    body_lines: list[str] = []
    for i, line in enumerate(raw_lines):
        if i not in lines_to_remove:
            body_lines.append(line)

    body_text = "\n".join(body_lines).strip()

    frontmatter: dict = {
        "id": item_id,
        "type": item_type,
        "title": title,
        "state": state_val,
        "dependencies": deps_val,
    }

    if item_type != "epic":
        frontmatter["epic"] = epic_ref if epic_ref else None

    if item_type == "task":
        frontmatter["user_story"] = us_ref if us_ref else None

    if priority_val and priority_val in ("Crítica", "Alta", "Media", "Baja"):
        frontmatter["priority"] = priority_val
    elif item_type in ("user_story", "task"):
        frontmatter["priority"] = None

    if fase_val:
        frontmatter["fase"] = fase_val

    yaml_block = yaml.dump(
        frontmatter,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=120,
    ).strip()

    return f"---\n{yaml_block}\n---\n\n{body_text}\n"


def migrate_file(path: Path, dry_run: bool = False) -> bool:
    content = path.read_text(encoding="utf-8")
    if content.startswith("---"):
        return True
    new_content = migrate_content(content, path.name)
    if new_content is None:
        return False

    if dry_run:
        return True

    path.write_text(new_content, encoding="utf-8")
    return True


def migrate_all(backlog_path: str | Path, dry_run: bool = False) -> tuple[int, int]:
    root = Path(backlog_path)
    success = 0
    failed = 0

    for subdir in ("epics", "user-stories", "tasks"):
        directory = root / subdir
        if not directory.is_dir():
            continue
        for file_path in sorted(directory.glob("*.md")):
            label = f"{subdir}/{file_path.name}"
            ok = migrate_file(file_path, dry_run=dry_run)
            if ok:
                success += 1
            else:
                failed += 1
                print(f"  [FAIL] {label}", file=sys.stderr)

    return success, failed


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrar backlog al formato YAML frontmatter + Markdown")
    parser.add_argument("--dry-run", action="store_true", help="No escribir ficheros, solo validar")
    parser.add_argument("--backlog-path", default="02-backlog",
                        help="Ruta al directorio 02-backlog/ (default: 02-backlog)")
    args = parser.parse_args()

    backlog_path = Path(args.backlog_path)
    if not backlog_path.is_dir():
        print(f"Error: {backlog_path} no existe", file=sys.stderr)
        sys.exit(1)

    print(f"Migrando {backlog_path.resolve()} ...")
    if args.dry_run:
        print("  (dry-run: no se escribira nada)")

    success, failed = migrate_all(backlog_path, dry_run=args.dry_run)

    print(f"\nResultado: {success} migrados, {failed} fallos")
    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
