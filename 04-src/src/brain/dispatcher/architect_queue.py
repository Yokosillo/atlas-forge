"""Cola append-only de cierres de Task hacia el Arquitecto, por proyecto
(T-FB030-US02-01, FB-030 · "Cola de cierre de trabajo hacia el Arquitecto").

Sustituye, para el caso "un agente termina una Task y el Arquitecto debe
enterarse", tanto la espera síncrona de `dispatch_job` (pensada para Jobs
cortos, no para el trabajo real de una Task de Developer) como el mecanismo
legado `watch_worker.sh` (destino hardcodeado a un único proyecto/crítico).

Cada proyecto tiene su propia cola en
`<project_root>/.claude/state/<project_name>/architect_queue.jsonl` — un
fichero JSONL (una línea, un objeto JSON completo, no un único array), al
que cualquier agente que cierra una Task añade una entrada sin esperar
respuesta ni bloquear su propio flujo. La escritura es un `append` puro
(modo `"a"`, sin leer el contenido previo del fichero) para que dos
escritores concurrentes nunca se pisen: cada `write()` de una línea
completa es atómico a nivel de sistema de ficheros para escrituras que
caben en un único bloque, así que dos `append` concurrentes producen dos
líneas completas, nunca una mezclada — a diferencia de leer-modificar-
escribir un array JSON completo, donde el segundo escritor sobrescribiría
lo que el primero acababa de añadir.

No hay ningún endpoint HTTP para esta Task: es un mecanismo de fichero,
consumido por el watcher de `US-FB030-03`, no por la API."""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

_QUEUE_FILENAME = "architect_queue.jsonl"

# Serializa los `append` concurrentes DENTRO de este mismo proceso — no
# evita colisión entre procesos distintos (el modo `"a"` del sistema de
# ficheros ya la evita para líneas que caben en un único write() a nivel de
# SO), pero sí evita que dos hilos del mismo proceso intercalen bytes de
# dos `json.dumps` distintos si llegaran a escribir a la vez sin este lock.
_write_lock = threading.Lock()


def _sanitize_project_dirname(project_name: str) -> str:
    """Mismo criterio de sanitización que `sanitize_session_name_part`
    (`brain.runtime.generic`, T-FB030-US01-01) para que el nombre del
    proyecto sea también un nombre de directorio válido — reutiliza la
    misma regla en vez de definir una segunda convención de saneo."""
    sanitized = re.sub(r"[^a-zA-Z0-9_-]+", "-", project_name.strip()).strip("-")
    return sanitized.lower()


def architect_queue_path(project_root: Path | str, project_name: str) -> Path:
    """Ruta del fichero de cola de `project_name`, dentro de
    `<project_root>/.claude/state/<project_name>/architect_queue.jsonl`.

    `project_root` es la raíz del repositorio del proyecto (`Project.path`)
    — la cola vive DENTRO del propio proyecto gestionado, nunca en un
    directorio compartido entre proyectos, para que un cierre de la Task de
    un proyecto nunca pueda acabar escrito bajo la ruta de otro."""
    dirname = _sanitize_project_dirname(project_name)
    return Path(project_root) / ".claude" / "state" / dirname / _QUEUE_FILENAME


def append_to_architect_queue(
    project_root: Path | str,
    project_name: str,
    *,
    agente: str,
    task_id: str,
    informe: str,
    ts: str | None = None,
) -> Path:
    """Añade una entrada de cierre de Task a la cola de `project_name`.

    Crea el directorio y el fichero si no existen. `informe` es la ruta
    (relativa, p. ej. `07-informes/<story_id>/<job_id>.md`) del informe de
    cierre ya escrito por `write_job_report`
    (`brain.dispatcher.job_report`) — esta función NO invoca
    `write_job_report` ni conoce su formato, solo referencia la ruta que el
    llamador ya generó. `ts` por defecto es el instante actual en UTC
    (ISO 8601); se acepta explícito para tests deterministas.

    Devuelve la ruta del fichero de cola escrito."""
    path = architect_queue_path(project_root, project_name)

    entry = {
        "agente": agente,
        "task_id": task_id,
        "informe": informe,
        "ts": ts if ts is not None else datetime.now(timezone.utc).isoformat(),
    }
    line = json.dumps(entry, ensure_ascii=False) + "\n"

    with _write_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)

    return path


def read_architect_queue(project_root: Path | str, project_name: str) -> list[dict]:
    """Lee todas las entradas de la cola de `project_name`, en orden de
    escritura. Devuelve una lista vacía si el fichero no existe todavía —
    nunca lanza excepción por cola vacía o inexistente (misma cola nunca
    escrita es un caso normal, no un error)."""
    path = architect_queue_path(project_root, project_name)
    if not path.is_file():
        return []
    entries: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            entries.append(json.loads(stripped))
    return entries
