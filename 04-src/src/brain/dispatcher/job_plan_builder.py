"""Construcción de un `JobPlan` a partir de un objetivo genérico del
desarrollador (T-FB008-US04-01, US-FB008-04 · "El Critic propone un plan
de Jobs y lo despacha tras una única aprobación humana").

## Cómo se interpreta el objetivo genérico de entrada

Esta Task pide decidir explícitamente cómo se llega de "objetivo genérico"
a una lista de pasos, sin inventar un motor de planificación ni NLP. La
decisión: el objetivo debe ser el identificador de una User Story ya
existente en el backlog (`US-FBNNN-nn`, ver `02-backlog/README.md`) —
"cerrar una fase" queda fuera de esta Task (no hay todavía forma de listar
las User Stories de una fase del roadmap salvo lectura manual de
`roadmap.md`; ver nota en la User Story sobre alcance acotado). Se listan
los ficheros de Task en `02-backlog/tasks/` cuyo nombre empieza por
`T-<identificador-US>-`, se descartan los que no están en estado `TO_DO`
(los ya `DONE`/`IN_PROGRESS`/`REVIEW` no son candidatos a un paso nuevo del
plan) y se ordenan por el correlativo `mm` del nombre de fichero — el mismo
orden en que ya aparecen en el backlog, tal como pide el criterio de
aceptación. Cada Task pendiente resultante se convierte en exactamente un
`JobPlanStep`, usando el título del fichero (línea `# T-... · <título>`)
como descripción del paso.

## Heurística de mecanismo (script > Scribe > agente cognitivo)

FB-010 Capability Engine no existe todavía (ver US-FB008-04, "Contexto"):
no hay un catálogo formal que resuelva "qué script determinista cierra
esta Task concreta". En vez de inventar esa resolución de capacidades
aquí (fuera del alcance de esta Task), se aplica una heurística explícita
y documentada sobre el propio texto de la Task, coherente con
`02-backlog/epics/FB-010-capability-engine.md` (Scripts deterministas /
Modelos locales / agentes cognitivos, con prioridad decreciente):

- si el título o la descripción de la Task menciona explícitamente
  "script" o "automatización"/"automatizacion" (Scripts deterministas del
  Automation Engine), el paso se propone con mecanismo `"script"`;
- si no, pero menciona "Scribe" (el modelo local de FB-014), el paso se
  propone con mecanismo `"scribe"`;
- en cualquier otro caso, el paso requiere razonamiento y se propone con
  mecanismo `"agent"`, con `agent_role` fijado a `"developer"` (todas las
  Tasks de implementación del backlog son trabajo de Developer; Critic
  interviene en el cierre de User Story, no paso a paso dentro del plan).

Esta heurística puede fallar falsos negativos (una Task resoluble por
script que no menciona la palabra "script" en su texto) — es una
limitación conocida y aceptable en v1, documentada aquí en vez de oculta:
sin un catálogo real de capacidades (FB-010), no hay forma fiable de
decidirlo mejor sin involucrar juicio humano o de un agente cognitivo, lo
que a su vez rompería el objetivo de evitar despachar un Job solo para
decidir el propio plan.
"""

from __future__ import annotations

import re
from pathlib import Path

from brain.backlog.parser import parse_frontmatter
from brain.models.job_plan import JobPlan, JobPlanStep

DEFAULT_TASKS_DIR = Path(__file__).resolve().parents[4] / "02-backlog" / "tasks"

_TITLE_PATTERN = re.compile(r"^#\s*T-[\w-]+\s*·\s*(?P<title>.+)$")

_SCRIPT_KEYWORDS = ("script", "automatización", "automatizacion")
_SCRIBE_KEYWORDS = ("scribe",)

# T-FB008-US04-07: coincidencia por PALABRA COMPLETA (`\b...\b`), no
# substring literal — "escribe"/"describe"/"suscribe"/"inscribe" (y
# cualquier conjugación de "escribir") contienen "scribe" como subcadena
# literal ("e-scribe"), lo que antes clasificaba Tasks reales de
# desarrollo como mecanismo `scribe` solo por decir "Escribe el
# fichero..." en su descripción (bug real reproducido con
# `US-FB036-02`). `\b` no reconoce acentos como límite de palabra en
# `re` estándar, pero no hace falta aquí: las palabras de
# `_SCRIPT_KEYWORDS`/`_SCRIBE_KEYWORDS` no llevan acento y sus falsos
# positivos conocidos tampoco los rodean de forma que cambie el
# resultado.
_KEYWORD_PATTERNS = {
    keyword: re.compile(r"\b" + re.escape(keyword) + r"\b", re.IGNORECASE)
    for keyword in _SCRIPT_KEYWORDS + _SCRIBE_KEYWORDS
}


def _contains_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    return any(_KEYWORD_PATTERNS[keyword].search(text) for keyword in keywords)


def task_file_story_prefix(story_id: str) -> str:
    """Normaliza `story_id` al prefijo real de los ficheros de Task
    (`FB020-US01`), aceptando tanto la forma canónica del backlog
    (`US-FB020-01`) como la ya normalizada (`FB020-US01`).

    - `US-FB020-01` -> `FB020-US01`
    - `FB020-US01`  -> `FB020-US01` (idempotente)

    Los nombres de fichero reales de Task son `T-FB020-US01-...md`
    (NUNCA `T-US-FB020-01-...md`), así que el glob `T-{story_id}-` que
    construyen `_pending_task_files_for_story`, `_mark_story_tasks_done`
    (`job_plan_dispatch.py`) y `read_acceptance_criteria` (`tester_input.py`)
    debe partir de este prefijo, no de la forma canónica tal cual.
    """
    base = story_id.removeprefix("US-")
    if "-US" in base:
        return base
    epic, number = base.split("-", 1)
    return f"{epic}-US{number}"


def _task_correlative(task_path: Path) -> int:
    # T-FBNNN-USnn-mm-<slug>.md -> mm, para ordenar igual que aparecen en
    # el backlog (criterio de aceptación de la Task).
    match = re.match(r"T-FB\d+-US\d+-(\d+)-", task_path.stem)
    return int(match.group(1)) if match else 0


def _read_task_title(text: str, fallback: str) -> str:
    """Titulo de una Task: el campo `title:` del frontmatter YAML (formato
    vigente), o el encabezado `# T-... · <titulo>` si no hay frontmatter
    (Task legacy) — mismo bug de fondo que `_read_task_state`: antes de
    esta Task se asumia que la PRIMERA linea del fichero era ese
    encabezado, valido solo en formato antiguo; en formato YAML vigente la
    primera linea es `---`, asi que esta funcion caia siempre al
    `fallback` (el slug del nombre de fichero, no el titulo real)."""
    if text.startswith("---"):
        try:
            data = parse_frontmatter(text)
        except ValueError:
            return fallback
        title = data.get("title")
        return title.strip() if isinstance(title, str) and title.strip() else fallback

    for line in text.splitlines():
        match = _TITLE_PATTERN.match(line.strip())
        if match:
            return match.group("title").strip()
    return fallback


_LEGACY_STATE_HEADER_PATTERN = re.compile(r"^##\s*Estado\s*$")


def _read_task_state(text: str) -> str:
    """Lee el estado de una Task: campo `state:` del frontmatter YAML
    (formato vigente, FB-027), con fallback a la sección Markdown antigua
    `## Estado` si el fichero no tiene frontmatter (Task legacy sin migrar
    — criterio 4 de T-FB008-US04-05: no romper ese caso si quedara
    alguno). Antes de esta Task, esta funcion SOLO reconocia el formato
    antiguo, asi que cualquier Task en formato YAML vigente devolvia
    siempre `""` aqui (descartada en silencio por `_pending_task_files_for_story`,
    el bug real reportado)."""
    if text.startswith("---"):
        try:
            data = parse_frontmatter(text)
        except ValueError:
            return ""
        state = data.get("state")
        return state if isinstance(state, str) else ""

    lines = text.splitlines()
    for index, line in enumerate(lines):
        if _LEGACY_STATE_HEADER_PATTERN.match(line.strip()):
            for following in lines[index + 1 :]:
                stripped = following.strip()
                if stripped:
                    return stripped
    return ""


def _mechanism_for_task(text: str) -> tuple[str, str | None]:
    if _contains_keyword(text, _SCRIPT_KEYWORDS):
        return "script", None
    if _contains_keyword(text, _SCRIBE_KEYWORDS):
        return "scribe", None
    return "agent", "developer"


def _pending_task_files_for_story(story_id: str, tasks_dir: Path) -> list[Path]:
    prefix = f"T-{task_file_story_prefix(story_id)}-"
    candidates = sorted(
        (path for path in tasks_dir.glob(f"{prefix}*.md")),
        key=_task_correlative,
    )
    pending = []
    for path in candidates:
        text = path.read_text(encoding="utf-8")
        if _read_task_state(text) == "TO_DO":
            pending.append(path)
    return pending


def build_job_plan_for_story(
    story_id: str, tasks_dir: Path | str = DEFAULT_TASKS_DIR
) -> JobPlan:
    """Construye un `JobPlan` a partir del identificador de una User Story
    (p. ej. `"US-FB008-04"`): un `JobPlanStep` por cada Task en estado
    `TO_DO` de esa Story, en el orden en que aparecen en el backlog (ver
    docstring de módulo para el criterio completo de interpretación y la
    heurística de mecanismo). El plan se construye en estado `"proposed"`
    — no se despacha nada (T-FB008-US04-03)."""
    tasks_dir = Path(tasks_dir)
    steps = []
    for task_path in _pending_task_files_for_story(story_id, tasks_dir):
        text = task_path.read_text(encoding="utf-8")
        title = _read_task_title(text, fallback=task_path.stem)
        mechanism, agent_role = _mechanism_for_task(text)
        steps.append(
            JobPlanStep(
                description=title,
                mechanism=mechanism,
                agent_role=agent_role,
            )
        )

    return JobPlan(goal=story_id, steps=steps, status="proposed")
