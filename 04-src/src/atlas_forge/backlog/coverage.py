"""Cobertura de alcance de una Epic (T-AF036-US05-01, US-AF036-05 ·
"Revisar si una Epic cubre su alcance v1 declarado frente a sus User
Stories/Tasks reales").

Lee la sección `## Alcance v1 (mínimo)` del fichero real de la Epic
(`02-backlog/epics/{epic_id}-*.md`) y la compara contra las User
Stories/Tasks reales de esa Epic con un *matching determinista-parcial*.

IMPORTANTE (diseño, ver Contexto de la US): la detección de huecos es
APROXIMADA por construcción, no una garantía formal de cumplimiento. El
criterio es determinista y repetible (nada de LLM), pero el lenguaje
natural del alcance puede eludir el matching de tokens de formas
razonables — por eso el resultado se devuelve SIEMPRE con un aviso
explícito (`approximate: true` + `message`). No está diseñado para
producir un veredicto de aprobación, solo para ayudar a un humano a
orientar la revisión.

Criterio de matching (por orden de fiabilidad):

1. Si un punto del alcance declara un identificador de item real
   (`US-AF036-05`, `T-AF036-US07-02`, `AF-036`...) y ese identificador
   pertenece a la Epic, el punto se considera cubierto — el backlog de
   este proyecto lista sus alcances precisamente con ids (`- **US-AF036-01**: ...`),
   así que este es el señal dominante y determinista.
2. En caso contrario (punto sin id, p. ej. una capacidad descrita en
   prosa), se cae a un solapamiento de tokens significativos contra
   (id + título + objetivo) de cada item real de la Epic; un punto se
   considera cubierto si al menos `_COVERAGE_TOKEN_THRESHOLD` (60%) de sus
   tokens significativos aparecen en algún item. Es un heurístico laxo a
   propósito: mejor un falso cubierto que un falso hueco que asuste a un
   humano.

Si la Epic no declara la sección, devuelve un resultado explícito
"no se puede calcular cobertura", nunca un vacío ambiguo. Si la Epic no
tiene fichero propio, devuelve `None` (el llamador traduce a 404)."""

from __future__ import annotations

import re
from pathlib import Path

from atlas_forge.backlog.detail import _epic_prefix, _read_section
from atlas_forge.models.backlog import BacklogGraph, ITEM_KIND_TASK, ITEM_KIND_USER_STORY

# Encabezado buscado por prefijo: el backlog real mezcla variantes como
# "## Alcance v1 (mínimo)", "## Alcance v1 (mínimo) — Dispatcher manual",
# "## Alcance v1 (mínimo) — no depende de AF-022". Todas comparten el
# prefijo literal "Alcance v1", que es el que da la Task.
_ALCANCE_V1_PREFIX = "Alcance v1"

_SECTION_HEADER_PATTERN = re.compile(r"^##\s*(.+?)\s*$")

# Ítem de lista Markdown: `- ...` o `* ...`. También tolera sub-ítems
# indentados (`  - ...`), que se tratan igual que los de primer nivel.
_LIST_ITEM_PATTERN = re.compile(r"^\s*[-*]\s+(.+?)\s*$")

# Negritas de Markdown (`**texto**`) — se limpian antes de mostrar/comparar.
_BOLD_PATTERN = re.compile(r"\*\*(.+?)\*\*")

# Identificadores de item real: `AF-036`, `US-AF036-05`, `T-AF036-US07-02`.
_ID_PATTERN = re.compile(r"\b(?:T-)?(?:US-)?AF\d{3,}(?:-[A-Z]*\d+)*\b")

# Fracción de tokens significativos de un punto que deben aparecer en un
# item real para considerarlo cubierto por texto (ver docstring del módulo).
_COVERAGE_TOKEN_THRESHOLD = 0.60

# Palabras vacías mínimas (artículos/preposiciones comunes) que no aportan
# señal al matching de tokens — una lista corta a propósito, sin pretender
# ser un tokenizer lingüístico.
_STOPWORDS = frozenset(
    "a al ante bajo con de del desde durante el en entre hacia la las los "
    "lo para por que se sin sobre su sus un una y pero o ni".split()
)

_TOKEN_PATTERN = re.compile(r"[a-z0-9áéíóúñü]+")


def _read_alcance_v1(text: str) -> str | None:
    """Contenido de la sección `## Alcance v1...` de `text`, o `None` si
    no hay ninguna sección cuyo encabezado empiece por "Alcance v1".

    Mismo parseo de texto simple por encabezados que `_read_section` de
    `detail.py`, con la diferencia de que aquí se casa por PREFIJO del
    nombre (no por igualdad exacta), para tolerar los sufijos
    "— Dispatcher manual" / "— no depende de AF-022" presentes en el
    backlog real."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = _SECTION_HEADER_PATTERN.match(line.strip())
        if match is None:
            continue
        header = match.group(1).strip()
        if not header.lower().startswith(_ALCANCE_V1_PREFIX.lower()):
            continue
        section_lines = []
        for following in lines[index + 1 :]:
            if re.match(r"^#{1,2}\s*", following):
                break
            section_lines.append(following)
        while section_lines and section_lines[-1].strip() in ("", "---"):
            section_lines.pop()
        content = "\n".join(section_lines).strip()
        return content or None
    return None


def _extract_points(alcance: str) -> list[str]:
    """Convierte el texto crudo de la sección en la lista de puntos
    declarados: cada línea que sea un ítem de lista Markdown, con las
    negritas limpias y el marcador `- `/`* ` recortado. El resto de
    líneas (párrafos introductorios, notas) se ignora — solo los ítems de
    lista son "puntos de alcance" comparables."""
    points: list[str] = []
    for line in alcance.splitlines():
        item_match = _LIST_ITEM_PATTERN.match(line)
        if item_match is None:
            continue
        raw = item_match.group(1).strip()
        cleaned = _BOLD_PATTERN.sub(r"\1", raw)
        cleaned = cleaned.strip()
        if cleaned:
            points.append(cleaned)
    return points


def _declared_ids(point: str) -> set[str]:
    """Ids reales (p. ej. `US-AF036-05`) mencionados literalmente en un
    punto del alcance."""
    return set(_ID_PATTERN.findall(point))


def _tokens(text: str) -> list[str]:
    """Tokens significativos de `text` (minúsculas, solo letras/dígitos,
    sin palabras vacías ni tokens de un solo carácter) — base del
    matching de texto aproximado."""
    return [
        token
        for token in _TOKEN_PATTERN.findall(text.lower())
        if token not in _STOPWORDS and len(token) > 1
    ]


def _item_candidate_text(item_id: str, path: Path) -> str:
    """Texto comparable de un item real: su id + título (H1) + objetivo
    (sección `## Objetivo`/`## Historia`). Lee el fichero en disco del
    item ya localizado en el grafo — mismo criterio de lectura que
    `build_item_detail`."""
    text = path.read_text(encoding="utf-8")
    title = ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            title = stripped[2:].strip()
            break
    objetivo = _read_section(text, "Objetivo")
    if objetivo is None:
        objetivo = _read_section(text, "Historia")
    return " ".join(part for part in (item_id, title, objetivo or "") if part)


def _epic_items(graph: BacklogGraph, epic_id: str) -> list:
    """Items reales de la Epic `epic_id`: User Stories cuyo `epic` tiene
    el prefijo `epic_id`, más Tasks de esas User Stories (vía el campo
    `user_story` del frontmatter) o cuyo propio `epic` pertenece a la
    Epic — mismo criterio de pertenencia que `build_epic_detail`."""
    us_ids = {
        item.id
        for item in graph.items.values()
        if item.kind == ITEM_KIND_USER_STORY and _epic_prefix(item.epic) == epic_id
    }
    items: list = []
    for item in graph.items.values():
        if item.kind == ITEM_KIND_USER_STORY:
            if item.id in us_ids:
                items.append(item)
        elif item.kind == ITEM_KIND_TASK:
            if item.user_story in us_ids or _epic_prefix(item.epic) == epic_id:
                items.append(item)
    return items


def _point_covered_by_id(point: str, known_ids: set[str]) -> bool:
    """Un punto queda cubierto si declara un id real que pertenece a la
    Epic (señal determinista más fiable del backlog real)."""
    return bool(known_ids & _declared_ids(point))


def _point_covered_by_text(point: str, candidates: list[tuple[str, str]]) -> bool:
    """Un punto queda cubierto por texto si al menos
    `_COVERAGE_TOKEN_THRESHOLD` de sus tokens significativos aparecen en
    el texto de ALGÚN item real de la Epic."""
    point_tokens = set(_tokens(point))
    if not point_tokens:
        return False
    point_len = len(point_tokens)
    for _item_id, candidate_text in candidates:
        candidate_tokens = set(_tokens(candidate_text))
        if not candidate_tokens:
            continue
        overlap = len(point_tokens & candidate_tokens)
        if overlap / point_len >= _COVERAGE_TOKEN_THRESHOLD:
            return True
    return False


def compute_epic_coverage(
    backlog_path: str | Path, graph: BacklogGraph, epic_id: str
) -> dict | None:
    """Cobertura del alcance v1 declarado de la Epic `epic_id` frente a
    sus items reales (ver docstring del módulo).

    Devuelve `None` si la Epic no tiene fichero propio en
    `02-backlog/epics/` (el llamador HTTP traduce a 404 — la Epic "no
    existe como fichero" a efectos de alcance). En cualquier otro caso
    devuelve un dict con `declared_alcance` y, si la sección existe,
    `points`/`gaps`/`approximate`."""
    epics_dir = Path(backlog_path) / "epics"
    epic_file = (
        next(iter(sorted(epics_dir.glob(f"{epic_id}-*.md"))), None)
        if epics_dir.is_dir()
        else None
    )
    if epic_file is None:
        return None

    text = epic_file.read_text(encoding="utf-8")
    alcance = _read_alcance_v1(text)

    if alcance is None:
        return {
            "epic_id": epic_id,
            "declared_alcance": None,
            "message": (
                "Esta Epic no declara un alcance v1 mínimo — no se puede "
                "calcular cobertura"
            ),
            "gaps": [],
        }

    points = _extract_points(alcance)
    items = _epic_items(graph, epic_id)
    known_ids = {item.id for item in items}
    candidates = [
        (item.id, _item_candidate_text(item.id, item.path)) for item in items
    ]

    gaps: list[str] = []
    for point in points:
        if _point_covered_by_id(point, known_ids):
            continue
        if _point_covered_by_text(point, candidates):
            continue
        gaps.append(point)

    return {
        "epic_id": epic_id,
        "declared_alcance": alcance,
        "points": points,
        "gaps": gaps,
        "approximate": True,
        "message": (
            "Detección aproximada de cobertura, no una garantía formal: "
            "revisa los puntos marcados como huecos contra las User "
            "Stories/Tasks reales de la Epic."
        ),
    }
