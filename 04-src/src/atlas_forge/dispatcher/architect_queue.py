"""Cola append-only de cierres de Task hacia el Arquitecto, por proyecto
(T-AF030-US02-01, AF-030 · "Cola de cierre de trabajo hacia el Arquitecto").

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
consumido por el watcher de `US-AF030-03`, no por la API."""

from __future__ import annotations

import json
import re
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path

_QUEUE_FILENAME = "architect_queue.jsonl"

# T-AF030-US03-04: ruta del script vigilante, raíz del repo (mismo patrón
# que `WEB_ROOT` en `atlas_forge.api.app`: ancla a `__file__`, no al cwd, para
# funcionar igual se lance `atlas-forge-api` desde la raíz del repo o desde
# dentro de `04-src/`). `architect_queue.py` vive en
# `04-src/src/atlas_forge/dispatcher/`, cuatro niveles por debajo de la raíz.
_WATCHER_SCRIPT_PATH = (
    Path(__file__).resolve().parents[4] / "architect_queue_watcher.sh"
)

# Serializa los `append` concurrentes DENTRO de este mismo proceso — no
# evita colisión entre procesos distintos (el modo `"a"` del sistema de
# ficheros ya la evita para líneas que caben en un único write() a nivel de
# SO), pero sí evita que dos hilos del mismo proceso intercalen bytes de
# dos `json.dumps` distintos si llegaran a escribir a la vez sin este lock.
_write_lock = threading.Lock()


def _sanitize_project_dirname(project_name: str) -> str:
    """Mismo criterio de sanitización que `sanitize_session_name_part`
    (`atlas_forge.runtime.generic`, T-AF030-US01-01) para que el nombre del
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
    (`atlas_forge.dispatcher.job_report`) — esta función NO invoca
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


def _watcher_already_running(project_root: Path | str, project_name: str) -> bool:
    """`True` si ya hay un proceso `architect_queue_watcher.sh` vivo para
    este mismo `(project_root, project_name)` (T-AF030-US03-04, criterio 3
    — no lanzar un segundo watcher duplicado, mismo problema de fondo que
    `AF-037`). Busca por línea de comandos completa (`pgrep -f`) con los
    mismos argumentos sin sanear que recibiría el propio lanzamiento —
    coincide exactamente con lo que `subprocess.Popen` invocaría a
    continuación, así que no hace falta un registro de PID propio."""
    pattern = f"{_WATCHER_SCRIPT_PATH} {project_root} {project_name}"
    try:
        result = subprocess.run(
            ["pgrep", "-f", re.escape(pattern)],
            capture_output=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        # Sin `pgrep` disponible (o si tarda de forma anómala), no se puede
        # verificar duplicado — se prefiere arriesgar un watcher duplicado
        # (mismo efecto observable, solo un proceso de más) antes que
        # bloquear el arranque de `atlas-forge-api` por esta comprobación.
        return False
    return result.returncode == 0


def launch_architect_queue_watcher(
    project_root: Path | str, project_name: str
) -> subprocess.Popen | None:
    """Lanza `architect_queue_watcher.sh <project_root> <project_name>`
    como subproceso independiente en segundo plano (T-AF030-US03-04), para
    que el aviso al Arquitecto de un cierre de Task funcione sin que nadie
    tenga que ejecutar el script a mano en una terminal aparte.

    No bloquea: `subprocess.Popen` devuelve el control inmediatamente,
    dejando el proceso corriendo de forma indefinida (nunca termina en
    operación normal). `start_new_session=True` lo desacopla del proceso
    padre (`atlas-forge-api`) — no debe morir si `atlas-forge-api` recibe una señal
    que no le llega directamente a él.

    Devuelve `None` sin lanzar nada si ya hay un watcher vivo para el
    mismo proyecto (`_watcher_already_running`) — idempotente ante
    reinicios de `atlas-forge-api` (criterio de aceptación 3)."""
    if _watcher_already_running(project_root, project_name):
        return None
    return subprocess.Popen(
        [str(_WATCHER_SCRIPT_PATH), str(project_root), project_name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


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
