"""Validador determinista de formato YAML frontmatter + Markdown (AF-027).

Valida ficheros de Epic/User Story/Task de `02-backlog/` contra el esquema
definido en `02-backlog/README.md` (sección "Formato de fichero", versión
AF-027). Sustituye `validator.py` (que validaba el formato Markdown antiguo).

Campos validados:
- Frontmatter YAML válido entre `---`
- `id` presente y coincide con el prefijo del nombre del fichero
- `type` en {epic, user_story, task}
- `state` en el conjunto canónico del tipo (AF-040): Task = {READY,
  TO_DEVELOP, IN_PROGRESS, IN_REVIEW, DONE}; User Story = {NO_TASKS,
  TO_PLAN, READY, TO_DEVELOP, IN_PROGRESS, IN_REVIEW, DONE, OUT_OF_SCOPE};
  Epic = {TO_DO, DONE, FUERA_ROADMAP} (fuera del contrato canónico)
- `dependencies` como lista de strings con IDs válidos
- `priority` en {Critica, Alta, Media, Baja} o null (US/Task)
- `fase` en el conjunto cerrado del roadmap {Fase 0.9, Fase 0.9.1,
  Fase 0.9.2} o `null`/`SIN_ASIGNAR`/vacío (T-AF036-US14-05)
- `epic` presente y con formato AF-NNN (US/Task)
- `user_story` presente y con formato US-AFNNN-nn (Task)
- `title` presente y no vacio
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# AF-040: único vocabulario de estados — el conjunto canónico por tipo lo
# define `atlas_forge/core/state_machines.py`; este módulo lo consume, no lo
# re-declara (guardián T-AF040-US01-05).
from atlas_forge.core.state_machines import (
    TASK_STATES,
    USER_STORY_STATES,
    EPIC_STATES,
)

# T-AF036-US14-05: conjunto cerrado de fases del roadmap (central en
# `atlas_forge.backlog.fases`, reutilizado por edit/create/parser/routes/web).
from atlas_forge.backlog.fases import (
    SIN_ASIGNAR,
    VALID_FASES,
    format_valid_versions,
    is_valid_fase,
    is_valid_version,
)


@dataclass
class ValidationErrorV2:
    line: int
    message: str


@dataclass
class ValidationResultV2:
    valid: bool
    file_type: str = ""
    errors: list[ValidationErrorV2] = field(default_factory=list)


_VALID_STATES = TASK_STATES
_VALID_USER_STORY_ONLY_STATES = USER_STORY_STATES
_VALID_EPIC_STATES = EPIC_STATES
_VALID_US_TASK_STATES = TASK_STATES
_VALID_TYPES = {"epic", "user_story", "task"}
_VALID_PRIORITIES = {"Crítica", "Alta", "Media", "Baja"}
_VALID_DIFFICULTY_MIN = 0
_VALID_DIFFICULTY_MAX = 10

_ID_PATTERN = re.compile(
    r"^(AF-\d{3,}|US-AF\d{3,}-\d{2}[A-Z]?|T-AF\d{3,}(?:-US\d{2}[A-Z]?)?-\d{2}[A-Z]?)$"
)
_EPIC_ID_PATTERN = re.compile(r"^AF-\d{3,}$")
_US_ID_PATTERN = re.compile(r"^US-AF\d{3,}-\d{2}[A-Z]?$")

_REQUIRED_FIELDS = {
    "epic": {"id", "type", "title", "state", "dependencies"},
    "user_story": {"id", "type", "title", "state", "dependencies", "priority", "epic"},
    "task": {"id", "type", "title", "state", "dependencies", "priority", "epic", "user_story"},
}


def _extract_frontmatter(content: str) -> tuple[dict[str, Any] | None, int, str | None]:
    """Extrae el bloque YAML frontmatter del contenido.

    Devuelve (dict parseado, numero de lineas del frontmatter, mensaje de error).
    El frontmatter debe empezar con `---` en la primera linea del fichero.
    """
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        return None, 0, "el fichero no empieza con frontmatter YAML (`---`)"

    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break

    if end_idx is None:
        return None, 0, "frontmatter YAML no cerrado (falta `---` de cierre)"

    yaml_text = "\n".join(lines[1:end_idx])
    if not yaml_text.strip():
        return None, 0, "frontmatter YAML vacio"

    try:
        import yaml
    except ImportError:
        return None, 0, "PyYAML no esta instalado"

    try:
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError as e:
        return None, 0, f"error de sintaxis YAML: {e}"

    if not isinstance(data, dict):
        return None, 0, f"el frontmatter no es un diccionario YAML (tipo: {type(data).__name__})"

    return data, end_idx + 1, None


def _read_frontmatter_id(path: Path | str) -> str:
    """Lee el `id` del frontmatter YAML (`---...---`) de un fichero `.md`
    de forma ligera (escaneo de líneas del bloque inicial, sin parsear el
    resto del documento). Devuelve `""` si el fichero no tiene un `id` de
    string legible — ese fichero simplemente no participa en el chequeo de
    unicidad, sin romper el escaneo de los demás (mismo criterio que el
    escaneo previo de `landing_proposal`)."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""
    if not text.startswith("---"):
        return ""
    end = text.find("\n---", 3)
    if end == -1:
        return ""
    for line in text[3:end].splitlines():
        if line.startswith("id:"):
            return line[len("id:"):].strip().strip('"').strip("'")
    return ""


# Cache LRU del escaneo de duplicados por directorio (T-AF008-US18-01):
# validar N ficheros del mismo directorio con un escaneo completo en cada
# llamada es O(N²); se cachea el mapa de duplicados por `(dir, fingerprint)`,
# donde el fingerprint son las entradas `.md` (nombre, mtime_ns, tamaño) —
# cambia cuando el directorio cambia, así que el cache nunca sirve un estado
# obsoleto (mismo criterio determinista: mismo estado de directorio → mismo
# resultado).
_DUP_SCAN_CACHE: dict[tuple, dict[str, list[Path]]] = {}
_DUP_SCAN_CACHE_MAX = 64


def _dir_fingerprint(dir_path: Path) -> tuple:
    """Fingerprint del conjunto de ficheros `.md` de `dir_path`:
    `(nombre, mtime_ns, tamaño)` ordenado. Vacío si el directorio no existe
    o no se puede leer (no distinguible de un directorio vacío irrealista)."""
    entries: list[tuple] = []
    try:
        with os.scandir(dir_path) as iterator:
            for entry in iterator:
                if entry.name.endswith(".md") and entry.is_file():
                    try:
                        stat = entry.stat()
                    except OSError:
                        continue
                    entries.append((entry.name, stat.st_mtime_ns, stat.st_size))
    except OSError:
        return ()
    return tuple(sorted(entries))


def _scan_duplicate_ids_in_dir(dir_path: Path) -> dict[str, list[Path]]:
    """Escaneo real (sin cache) de ids duplicados entre los `.md` de
    `dir_path`."""
    by_id: dict[str, list[Path]] = {}
    for path in sorted(dir_path.glob("*.md")):
        file_id = _read_frontmatter_id(path)
        if file_id:
            by_id.setdefault(file_id, []).append(path)
    return {
        file_id: paths
        for file_id, paths in by_id.items()
        if len(paths) > 1
    }


def find_duplicate_ids_in_dir(dir_path: Path | str) -> dict[str, list[Path]]:
    """Ids duplicados entre los ficheros `.md` de `dir_path` (T-AF008-US18-01).

    Es el checker determinista de unicidad de `id` del backlog: garantiza que
    un directorio (p. ej. `02-backlog/tasks/`) nunca tenga dos ficheros con el
    mismo `id` — la causal raíz del hallazgo "Agentic stuck" de 2026-08-24
    (`T-AF018-US03-01` duplicada, que al re-despacharse orfanó un Job del
    Dispatcher bloqueando la cola 4h).

    Devuelve un dict `id -> [rutas]` solo para los ids que aparecen en más de
    un fichero, ordenado alfabéticamente por fichero (determinista). Devuelve
    `{}` si `dir_path` no existe o no tiene duplicados. Cachea por
    fingerprint de directorio (ver `_DUP_SCAN_CACHE`)."""
    dir_path = Path(dir_path)
    if not dir_path.is_dir():
        return {}
    fingerprint = _dir_fingerprint(dir_path)
    if not fingerprint:
        return {}
    cache_key = (str(dir_path), fingerprint)
    cached = _DUP_SCAN_CACHE.get(cache_key)
    if cached is not None:
        return cached

    result = _scan_duplicate_ids_in_dir(dir_path)
    if len(_DUP_SCAN_CACHE) >= _DUP_SCAN_CACHE_MAX:
        _DUP_SCAN_CACHE.clear()
    _DUP_SCAN_CACHE[cache_key] = result
    return result


def _validate_id(data: dict, stem: str) -> list[ValidationErrorV2]:
    errors: list[ValidationErrorV2] = []
    file_id = data.get("id")
    if not file_id or not isinstance(file_id, str):
        errors.append(ValidationErrorV2(0, "campo 'id' ausente o no es string"))
        return errors

    if not _ID_PATTERN.match(file_id):
        errors.append(ValidationErrorV2(
            0,
            f"campo 'id' '{file_id}' no tiene formato valido (AF-NNN, US-AFNNN-nn, T-AFNNN-USnn-mm)"
        ))
        return errors

    from atlas_forge.backlog.parser import _item_id_from_stem
    stem_id = _item_id_from_stem(stem)
    if stem_id is not None and stem_id != file_id:
        errors.append(ValidationErrorV2(
            0,
            f"campo 'id' '{file_id}' no coincide con el identificador del fichero '{stem_id}'"
        ))

    return errors


def _validate_type(data: dict) -> list[ValidationErrorV2]:
    errors: list[ValidationErrorV2] = []
    file_type = data.get("type")
    if not file_type or not isinstance(file_type, str):
        errors.append(ValidationErrorV2(0, "campo 'type' ausente o no es string"))
    elif file_type not in _VALID_TYPES:
        errors.append(ValidationErrorV2(
            0,
            f"campo 'type' '{file_type}' no valido — debe ser: {', '.join(sorted(_VALID_TYPES))}"
        ))
    return errors


def _validate_state(data: dict) -> list[ValidationErrorV2]:
    errors: list[ValidationErrorV2] = []
    state = data.get("state")
    if data.get("type") == "user_story":
        allowed = _VALID_US_TASK_STATES | _VALID_USER_STORY_ONLY_STATES
    elif data.get("type") == "task":
        allowed = _VALID_US_TASK_STATES
    else:
        allowed = _VALID_EPIC_STATES
    if state is None or (isinstance(state, str) and not state.strip()):
        errors.append(ValidationErrorV2(0, "campo 'state' ausente o vacio"))
    elif not isinstance(state, str):
        errors.append(ValidationErrorV2(0, f"campo 'state' debe ser string, no {type(state).__name__}"))
    elif state not in allowed:
        errors.append(ValidationErrorV2(
            0,
            f"campo 'state' '{state}' no valido — debe ser: {', '.join(sorted(allowed))}"
        ))
    return errors


def _validate_dependencies(data: dict) -> list[ValidationErrorV2]:
    errors: list[ValidationErrorV2] = []
    deps = data.get("dependencies")
    if deps is None:
        errors.append(ValidationErrorV2(0, "campo 'dependencies' ausente"))
        return errors
    if not isinstance(deps, list):
        errors.append(ValidationErrorV2(
            0,
            f"campo 'dependencies' debe ser una lista, no {type(deps).__name__}"
        ))
        return errors
    for i, dep in enumerate(deps):
        if not isinstance(dep, str):
            errors.append(ValidationErrorV2(
                0,
                f"dependencies[{i}]: no es un string (tipo: {type(dep).__name__})"
            ))
        elif not _ID_PATTERN.match(dep):
            errors.append(ValidationErrorV2(
                0,
                f"dependencies[{i}]: '{dep}' no tiene formato de ID valido"
            ))
    return errors


def _validate_priority(data: dict, file_type: str) -> list[ValidationErrorV2]:
    errors: list[ValidationErrorV2] = []
    if file_type == "epic":
        return errors

    priority = data.get("priority")
    if priority is None:
        return errors
    if not isinstance(priority, str):
        errors.append(ValidationErrorV2(
            0,
            f"campo 'priority' debe ser string o null, no {type(priority).__name__}"
        ))
    elif priority not in _VALID_PRIORITIES:
        errors.append(ValidationErrorV2(
            0,
            f"campo 'priority' '{priority}' no valido — debe ser: {', '.join(sorted(_VALID_PRIORITIES))}"
        ))
    return errors


def _validate_fase(data: dict, file_type: str) -> list[ValidationErrorV2]:
    """Conjunto cerrado de fases (T-AF036-US14-05): `fase` solo puede ser
    una de `VALID_FASES` o un valor de "sin fase" (`None`, cadena vacía o
    `SIN_ASIGNAR`). Cualquier otra cadena (incluidos los 0.x legados como
    `Fase 0.1`) hace el fichero inválido.

    T-AF036-US18-01: solo aplica a User Story/Task — la Epic ya NO tiene
    `fase` (se versiona con `version:`), así que se ignora para Epics
    (los `fase` legados en ficheros de Epic no se validan ni se exigen).
    `version` es un campo extra admitido (el validador no rechaza campos
    desconocidos, igual que `updated_at`)."""
    errors: list[ValidationErrorV2] = []
    if file_type == "epic":
        return errors
    fase = data.get("fase")
    if fase is None:
        return errors
    if not isinstance(fase, str):
        errors.append(ValidationErrorV2(
            0,
            f"campo 'fase' debe ser string o null, no {type(fase).__name__}"
        ))
    elif not is_valid_fase(fase):
        errors.append(ValidationErrorV2(
            0,
            f"campo 'fase' '{fase}' no valido — debe ser: "
            f"{', '.join(sorted(VALID_FASES))} o {SIN_ASIGNAR}/null"
        ))
    return errors


def _validate_version(data: dict, file_type: str) -> list[ValidationErrorV2]:
    """Conjunto cerrado de versiones (T-AF036-US25-01): `version` solo puede
    ser una de `VALID_VERSIONS` o `None`/ausente (sin versión). Cualquier otro
    valor (`0.8`, `1.0`, `Fase 0.9`, un no-string) hace el fichero inválido.

    Aplica a Epic y User Story (los dos tipos que versionan); las Tasks no
    declaran `version`. `fase` sigue tolerándose como legacy persistido por
    `_validate_fase` (no asignable por edición/creación, solo datos previos)."""
    errors: list[ValidationErrorV2] = []
    if file_type not in ("epic", "user_story"):
        return errors
    version = data.get("version")
    if version is None:
        return errors
    if not isinstance(version, str):
        # `version: 0.9` sin comillas lo lee PyYAML como float — se normaliza
        # a su forma de texto canónica antes de validar (mismo criterio que
        # el parser, parser.py). Cualquier otro tipo no numérico es inválido.
        if isinstance(version, (int, float)):
            version = str(version)
        else:
            errors.append(ValidationErrorV2(
                0,
                f"campo 'version' debe ser string o null, no {type(version).__name__}"
            ))
            return errors
    if not is_valid_version(version):
        errors.append(ValidationErrorV2(
            0,
            f"campo 'version' '{version}' no valido — debe ser: "
            f"{format_valid_versions()} o null"
        ))
    return errors


def _validate_difficulty(data: dict, file_type: str) -> list[ValidationErrorV2]:
    errors: list[ValidationErrorV2] = []
    if file_type != "task":
        return errors

    difficulty = data.get("difficulty")
    if difficulty is None:
        return errors
    if isinstance(difficulty, bool) or not isinstance(difficulty, int):
        errors.append(ValidationErrorV2(
            0,
            f"campo 'difficulty' debe ser entero 0-10 o null, no {type(difficulty).__name__}"
        ))
    elif not (_VALID_DIFFICULTY_MIN <= difficulty <= _VALID_DIFFICULTY_MAX):
        errors.append(ValidationErrorV2(
            0,
            f"campo 'difficulty' '{difficulty}' fuera de rango — debe estar entre {_VALID_DIFFICULTY_MIN} y {_VALID_DIFFICULTY_MAX}"
        ))
    return errors


def _validate_epic(data: dict, file_type: str) -> list[ValidationErrorV2]:
    errors: list[ValidationErrorV2] = []
    if file_type not in ("user_story", "task"):
        return errors

    epic = data.get("epic")
    if epic is None:
        return errors
    if not isinstance(epic, str):
        errors.append(ValidationErrorV2(0, f"campo 'epic' debe ser string o null, no {type(epic).__name__}"))
    elif epic and not _EPIC_ID_PATTERN.match(epic):
        errors.append(ValidationErrorV2(
            0,
            f"campo 'epic' '{epic}' no es un ID de Epic valido (AF-NNN)"
        ))
    return errors


def _validate_user_story(data: dict, file_type: str) -> list[ValidationErrorV2]:
    errors: list[ValidationErrorV2] = []
    if file_type != "task":
        return errors

    us = data.get("user_story")
    if us is None:
        return errors
    if not isinstance(us, str):
        errors.append(ValidationErrorV2(0, f"campo 'user_story' debe ser string o null, no {type(us).__name__}"))
    elif us and not _US_ID_PATTERN.match(us):
        errors.append(ValidationErrorV2(
            0,
            f"campo 'user_story' '{us}' no es un ID de User Story valido (US-AFNNN-nn)"
        ))
    return errors


def _validate_title(data: dict) -> list[ValidationErrorV2]:
    errors: list[ValidationErrorV2] = []
    title = data.get("title")
    if not title or not isinstance(title, str) or not title.strip():
        errors.append(ValidationErrorV2(0, "campo 'title' ausente o vacio"))
    return errors


def _validate_required_fields(data: dict, file_type: str) -> list[ValidationErrorV2]:
    errors: list[ValidationErrorV2] = []
    required = _REQUIRED_FIELDS.get(file_type, set())
    for field in required:
        if field not in data:
            errors.append(ValidationErrorV2(
                0,
                f"campo obligatorio '{field}' ausente para tipo '{file_type}'"
            ))
    return errors


def validate_backlog_content_v2(content: str, filename: str = "") -> ValidationResultV2:
    """Valida el contenido de un fichero de backlog en formato YAML
    frontmatter + Markdown.

    Args:
        content: Contenido del fichero.
        filename: Nombre del fichero (para validar `id` contra el stem).

    Returns:
        ValidationResultV2 con `valid=True` si pasa todas las validaciones,
        o la lista de errores encontrados.
    """
    errors: list[ValidationErrorV2] = []

    data, fm_lines, fm_error = _extract_frontmatter(content)
    if fm_error is not None:
        errors.append(ValidationErrorV2(1, fm_error))
        return ValidationResultV2(valid=False, errors=errors)

    assert data is not None

    file_type = data.get("type", "")
    if isinstance(file_type, str) and file_type in _VALID_TYPES:
        resolved_type = file_type
    else:
        resolved_type = ""

    stem = Path(filename).stem if filename else ""

    errors.extend(_validate_required_fields(data, resolved_type))
    errors.extend(_validate_type(data))
    errors.extend(_validate_id(data, stem))
    errors.extend(_validate_title(data))
    errors.extend(_validate_state(data))
    errors.extend(_validate_dependencies(data))
    errors.extend(_validate_priority(data, resolved_type))
    errors.extend(_validate_fase(data, resolved_type))
    errors.extend(_validate_version(data, resolved_type))
    errors.extend(_validate_difficulty(data, resolved_type))
    errors.extend(_validate_epic(data, resolved_type))
    errors.extend(_validate_user_story(data, resolved_type))

    return ValidationResultV2(
        valid=len(errors) == 0,
        file_type=resolved_type,
        errors=errors,
    )


def validate_backlog_file_v2(path: str | Path) -> ValidationResultV2:
    """Valida un fichero de backlog en disco contra el formato nuevo.

    Args:
        path: Ruta al fichero `.md`.

    Returns:
        ValidationResultV2 con el resultado de la validacion.

    T-AF008-US18-01: además de la validación individual del contenido, chequea
    la unicidad de `id` dentro del directorio del fichero: si OTRO fichero
    `.md` del mismo directorio declara el mismo `id`, la validación FALLA
    (error, no warning) — el backlog no puede tener dos ficheros con el mismo
    id (causal raíz del hallazgo "Agentic stuck" 2026-08-24).
    """
    path = Path(path)
    content = path.read_text(encoding="utf-8")
    result = validate_backlog_content_v2(content, filename=path.name)

    duplicates = find_duplicate_ids_in_dir(path.parent)
    if duplicates:
        file_id = _read_frontmatter_id(path)
        if file_id and file_id in duplicates:
            other_paths = [str(p) for p in duplicates[file_id] if p != path]
            errors = list(result.errors)
            errors.append(ValidationErrorV2(
                0,
                f"id duplicado '{file_id}': también existe en "
                f"'{', '.join(other_paths)}' — el backlog no puede tener dos "
                "ficheros con el mismo id.",
            ))
            result = ValidationResultV2(
                valid=False,
                file_type=result.file_type,
                errors=errors,
            )
    return result
