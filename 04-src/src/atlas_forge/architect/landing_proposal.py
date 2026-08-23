"""Procesa la propuesta de aterrizaje US→Tasks del agente Arquitecto
(T-AF008-US16-02): interpreta el reporte del Job (YAML con una lista
`tasks:`), valida CADA Task con el validador determinista
`validate_backlog_file_v2` y escribe SOLO las Tasks que validan en
`02-backlog/tasks/`.

Este es el paso de completión del aterrizaje no bloqueante
(`poll_inflight_landing_completions` en `dispatch_queue_worker.py`): el
Dispatcher despacha un Job de aterrizaje al Arquitecto (T-AF008-US16-01),
que escribe su propuesta en el fichero de reporte; esta capa lee esa
propuesta, la valida y la persiste. El validador determinista actúa como
red de seguridad: una Task que no valida NUNCA se persiste. Ninguna lógica
de negocio se duplica — se reutiliza `_build_task_content` (la misma
serialización de Task que ya usa `task_pipeline.py`) y
`validate_backlog_file_v2` (el validador canónico del backlog).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from atlas_forge.architect.propose_tasks import ProposedTask
from atlas_forge.architect.task_pipeline import _build_task_content, _slugify
from atlas_forge.backlog.validator_v2 import validate_backlog_file_v2


@dataclass
class LandingProposalResult:
    """Resultado de `write_validated_landing_tasks`: qué se escribió, qué
    se rechazó (por no validar) y qué errores de I/O hubo."""

    written: list[Path] = field(default_factory=list)
    rejected: list[tuple[str, list[str]]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def has_written_tasks(self) -> bool:
        return bool(self.written)


def parse_landing_proposal(report_content: str) -> list[ProposedTask]:
    """Interpreta el reporte de la propuesta del Arquitecto.

    Formato (YAML, sin el marcador de fin — lo extrae `read_finished_report`):

    ```yaml
    tasks:
      - id: T-AF999-US01-01
        title: ...
        objective: ...
        description: ...
        criteria:
          - ...
        priority: Alta
        difficulty: Alta
        dependencies: []
        epic_id: AF-999
        us_id: US-AF999-01
    ```

    Las claves de Task son `epic_id`/`us_id` (no `epic`/`user_story`) — el
    prompt del Job de aterrizaje (`_build_landing_job_description`) las
    instruye con ese nombre, y el id sigue el patrón `T-<EPIC-SIN-GUION>-USxx-NN`
    (sin guion entre `AF` y el número).

    Devuelve una lista de `ProposedTask`. Si el YAML no es válido, no es un
    diccionario o no trae `tasks` como lista, devuelve `[]` (el llamador
    tratará la propuesta como no aterrizable, sin escribir nada)."""
    try:
        data = yaml.safe_load(report_content)
    except yaml.YAMLError:
        return []
    if not isinstance(data, dict):
        return []

    tasks_raw = data.get("tasks")
    if not isinstance(tasks_raw, list):
        return []

    required = ("id", "title", "epic_id", "us_id", "objective", "description")
    parsed: list[ProposedTask] = []
    for raw in tasks_raw:
        if not isinstance(raw, dict):
            continue
        if not all(k in raw for k in required):
            continue
        parsed.append(ProposedTask(
            id=str(raw.get("id", "")).strip(),
            title=str(raw.get("title", "")).strip(),
            epic_id=str(raw.get("epic_id", "")).strip(),
            us_id=str(raw.get("us_id", "")).strip(),
            objective=str(raw.get("objective", "")).strip(),
            description=str(raw.get("description", "")).strip(),
            criteria=[str(c) for c in raw.get("criteria", [])],
            priority=str(raw.get("priority", "Alta")),
            difficulty=str(raw.get("difficulty", "Alta")),
            dependencies=[str(d) for d in raw.get("dependencies", [])],
        ))
    return parsed


def write_validated_landing_tasks(
    tasks: list[ProposedTask],
    tasks_dir: Path | str,
) -> LandingProposalResult:
    """Valida CADA Task con `validate_backlog_file_v2` y escribe solo las
    que validan en `tasks_dir`.

    Para cada Task se serializa su fichero con `_build_task_content` (misma
    representación canónica que el resto del backlog), se escribe y se
    valida el fichero real en disco con `validate_backlog_file_v2`. Si la
    Task valida, se conserva y se registra en `result.written`; si no
    valida, se ELIMINA y se registra en `result.rejected` con los errores
    del validador. Devuelve `LandingProposalResult`."""
    result = LandingProposalResult()
    tasks_dir = Path(tasks_dir)
    tasks_dir.mkdir(parents=True, exist_ok=True)

    for task in tasks:
        if not task.id:
            result.rejected.append((task.id, ["Task sin id — se descarta."]))
            continue
        content = _build_task_content(task)
        filename = f"{task.id}-{_slugify(task.title)}.md"
        path = tasks_dir / filename
        try:
            path.write_text(content, encoding="utf-8")
        except OSError as error:
            result.errors.append(f"{task.id}: no se pudo escribir '{path}': {error}")
            continue

        validation = validate_backlog_file_v2(path)
        if validation.valid:
            result.written.append(path)
        else:
            path.unlink(missing_ok=True)
            result.rejected.append((task.id, [e.message for e in validation.errors]))

    return result
