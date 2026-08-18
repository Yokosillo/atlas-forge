"""Cola de Tasks marcadas "lista para desarrollo" (T-FB008-US10-01,
US-FB008-10 · "Marcar Tasks como listas para desarrollo y que un
Dispatcher las asigne solo a un Developer libre").

## Por qué un segundo mecanismo, distinto del Plan (`US-FB008-04`)

El flujo de Plan (`build_job_plan_for_story`/`dispatch_plan`) exige
aprobar un lote completo de Tasks de una User Story por adelantado. Esta
Story añade un segundo camino: marcar Tasks sueltas (o todas las `TODO`
de una US) como encoladas, sin aprobación de lote, para que un
Dispatcher de fondo (`T-FB008-US10-02`, Task aparte — NO implementado
aquí) las vaya sacando cuando haya un Developer libre. Esta Task es
solo el mecanismo de cola en sí: marcar/desmarcar/consultar — nada
despacha nada todavía.

## Mecanismo de persistencia elegido

Fichero JSON **mutable** por proyecto (no append-only, a diferencia de
`architect_queue.py`): `<project_root>/.claude/state/<project_name>/
dispatch_queue.json`, mismo directorio de estado por proyecto que ya usa
`architect_queue_path` — reutiliza `_sanitize_project_dirname`
(`architect_queue.py`) para el mismo criterio de saneo, sin una segunda
convención de nombre de directorio.

Se eligió fichero sobre "campo nuevo en memoria del `DevelopmentSession`"
(la otra opción que planteaba la Task) porque el propio `_SessionRegistry`
ya vive en memoria y se pierde en cada reinicio del proceso (`FB-031`) —
la cola necesita sobrevivir a un reinicio de `brain-api` (un `restart` de
`systemd`, `T-FB037-US04-01`, es una operación esperada, no excepcional)
sin perder qué Tasks estaban marcadas para desarrollo.

No es append-only porque cada entrada muta su propio `status`
(`queued` → `dispatched`/`failed`) en el sitio, o se elimina por completo
(desencolar) — el patrón "leer todo, mutar en memoria, escribir todo de
vuelta" es correcto aquí: el volumen esperado (Tasks encoladas de un
proyecto) es pequeño (decenas, no miles), muy por debajo de donde
leer/escribir el fichero completo en cada operación sería un problema de
rendimiento real. Un `threading.Lock` por proceso serializa las
escrituras concurrentes dentro del mismo proceso (mismo criterio que
`architect_queue.py`); no hay garantía multi-proceso (fuera de alcance,
`brain-api` corre como un único proceso `systemd`, no varios workers)."""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from brain.runtime.generic import sanitize_session_name_part

_QUEUE_FILENAME = "dispatch_queue.json"

STATUS_QUEUED = "queued"
STATUS_DISPATCHED = "dispatched"
STATUS_FAILED = "failed"

# Serializa las escrituras concurrentes DENTRO de este proceso — mismo
# motivo que `architect_queue._write_lock`, pero aquí también protege el
# propio ciclo leer-modificar-escribir (no solo un `append`), porque dos
# hilos que lean el fichero a la vez y escriban de vuelta perderían la
# escritura del primero sin este lock.
_write_lock = threading.Lock()


class TaskAlreadyQueuedError(ValueError):
    """`task_id` ya tiene una entrada `queued` en la cola — no se duplica."""


class TaskNotQueuedError(ValueError):
    """`task_id` no tiene ninguna entrada `queued` en la cola (para
    desencolar) — nunca lanzada para "no existe en el backlog", eso lo
    valida el llamador (capa HTTP) antes de invocar este módulo."""


class TaskAlreadyDispatchedError(ValueError):
    """`task_id` está en la cola pero ya no en estado `queued`
    (`dispatched`/`failed`) — no se puede desencolar algo que el
    Dispatcher ya tomó."""


@dataclass
class QueueEntry:
    """Una entrada de la cola: una Task marcada para desarrollo.

    `task_id`/`us_id`/`priority` se copian del `BacklogItem` en el
    momento de encolar (no se re-resuelven en cada lectura) — mismo
    criterio que el resto del backlog: el fichero de Task en disco sigue
    siendo la fuente de verdad de `state`/`priority` reales; esta cola
    solo recuerda "qué Tasks se marcaron y en qué orden", no duplica el
    parser. `agent_id`/`agent_name`/`result` quedan `None` hasta que el
    Dispatcher (`T-FB008-US10-02`) despache la entrada — esta Task deja
    los campos ya definidos para que ese Dispatcher no tenga que cambiar
    el esquema del fichero. `dispatch_reason` (T-FB008-US12-02) registra
    por qué se eligió ese Developer/modelo: "encaja directo" / "cambio de
    modelo aplicado" / "degradado por falta de runtime adecuado"."""

    task_id: str
    us_id: str | None
    priority: str | None
    status: str
    enqueued_at: str
    agent_id: str | None = None
    agent_name: str | None = None
    result: str | None = None
    dispatched_at: str | None = None
    dispatch_reason: str | None = None


def dispatch_queue_path(project_root: Path | str, project_name: str) -> Path:
    """Ruta del fichero de cola de `project_name`, dentro de
    `<project_root>/.claude/state/<project_name>/dispatch_queue.json` —
    misma raíz de estado por proyecto que `architect_queue_path`, mismo
    criterio de saneo (`sanitize_session_name_part`, pública desde
    `T-FB031-US02-02`) en vez del símbolo privado de `architect_queue.py`."""
    dirname = sanitize_session_name_part(project_name)
    return Path(project_root) / ".claude" / "state" / dirname / _QUEUE_FILENAME


def _read_all(path: Path) -> list[QueueEntry]:
    if not path.is_file():
        return []
    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        return []
    data = json.loads(raw)
    return [QueueEntry(**entry) for entry in data]


def _write_all(path: Path, entries: list[QueueEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps([asdict(entry) for entry in entries], ensure_ascii=False, indent=2)
    path.write_text(payload, encoding="utf-8")


def enqueue_task(
    project_root: Path | str,
    project_name: str,
    *,
    task_id: str,
    us_id: str | None,
    priority: str | None,
    ts: str | None = None,
) -> QueueEntry:
    """Añade `task_id` a la cola con estado `queued`. No valida aquí que
    la Task exista en el backlog ni que esté en estado `TO_DO` — esa
    validación (404/400) vive en la capa HTTP (`routes.py`), que ya tiene
    el `BacklogGraph` cargado y no debe cargarlo dos veces.

    Lanza `TaskAlreadyQueuedError` si `task_id` ya tiene una entrada
    `queued` — evita duplicados silenciosos en la cola (un doble clic en
    el botón de encolar, o encolar individualmente una Task que ya
    formaba parte de un `enqueue-all` previo)."""
    path = dispatch_queue_path(project_root, project_name)
    with _write_lock:
        entries = _read_all(path)
        if any(e.task_id == task_id and e.status == STATUS_QUEUED for e in entries):
            raise TaskAlreadyQueuedError(
                f"La Task '{task_id}' ya está encolada."
            )
        entry = QueueEntry(
            task_id=task_id,
            us_id=us_id,
            priority=priority,
            status=STATUS_QUEUED,
            enqueued_at=ts if ts is not None else datetime.now(timezone.utc).isoformat(),
        )
        entries.append(entry)
        _write_all(path, entries)
        return entry


def dequeue_task(project_root: Path | str, project_name: str, task_id: str) -> None:
    """Retira `task_id` de la cola — solo si tiene una entrada en estado
    `queued` (no despachada todavía, criterio de aceptación explícito:
    "sin ningún efecto secundario").

    Lanza `TaskNotQueuedError` si no hay ninguna entrada para `task_id`
    en absoluto (nunca se encoló), o `TaskAlreadyDispatchedError` si la
    entrada existe pero ya no está `queued` (el Dispatcher ya la tomó) —
    dos motivos de fallo distintos, mismo criterio ya establecido en
    `T-FB008-US04-08` de distinguir el mensaje real según la causa."""
    path = dispatch_queue_path(project_root, project_name)
    with _write_lock:
        entries = _read_all(path)
        match = next((e for e in entries if e.task_id == task_id), None)
        if match is None:
            raise TaskNotQueuedError(f"La Task '{task_id}' no está en la cola.")
        if match.status != STATUS_QUEUED:
            raise TaskAlreadyDispatchedError(
                f"La Task '{task_id}' ya fue tomada por el Dispatcher "
                f"(estado '{match.status}') — no se puede desencolar."
            )
        entries = [e for e in entries if e.task_id != task_id]
        _write_all(path, entries)


def get_queue(project_root: Path | str, project_name: str) -> list[QueueEntry]:
    """Todas las entradas de la cola (cualquier estado), en el orden en
    que se añadieron — el orden POR PRIORIDAD para el Dispatcher se
    calcula en la capa HTTP (`routes.py`, reutilizando `priority_rank`
    de `brain.backlog.report`), no aquí: esta función es solo lectura
    cruda del fichero, sin lógica de negocio de orden."""
    path = dispatch_queue_path(project_root, project_name)
    with _write_lock:
        return _read_all(path)


def migrate_queued_entries_to_state(
    project_root: Path | str, project_name: str, backlog_dir: Path | str
) -> list[str]:
    """T-FB008-US14-01, criterio de aceptación de migración: entradas ya
    encoladas en `dispatch_queue.json` (`status == "queued"`) ANTES de
    esta Task nunca tuvieron su `state` real escrito a `EN_DESARROLLO` — solo
    vivían en el JSON, con el fichero real todavía en `TO_DO` (el
    comportamiento anterior a esta Task). Esta función pone al día esos
    ficheros reales, sin tocar el propio JSON (sigue siendo el registro
    de orden/auditoría auxiliar, no cambia de formato).

    Solo toca Tasks cuyo `state` real es TODAVÍA `TO_DO` — si ya está en
    `EN_DESARROLLO` (encolada de nuevo tras esta Task) o en cualquier otro
    estado (alguien la movió manualmente, o el Dispatcher ya la tomó y
    el JSON quedó desincronizado), no se toca: mismo criterio de
    "solo promueve hacia adelante, nunca revierte" ya usado en
    `promote_backlog`.

    Devuelve la lista de `task_id` migrados. Idempotente: ejecutarlo dos
    veces no vuelve a tocar nada la segunda vez (las ya migradas están en
    `EN_DESARROLLO`, no en `TO_DO`)."""
    from brain.backlog.edit import set_item_state
    from brain.backlog.parser import load_backlog

    entries = get_queue(project_root, project_name)
    queued_task_ids = {e.task_id for e in entries if e.status == STATUS_QUEUED}
    if not queued_task_ids:
        return []

    graph = load_backlog(Path(backlog_dir))
    migrated = []
    for task_id in sorted(queued_task_ids):
        item = graph.items.get(task_id)
        if item is None or item.state != "TO_DO":
            continue
        set_item_state(item.path, "EN_DESARROLLO")
        migrated.append(task_id)
    return migrated


def mark_dispatched(
    project_root: Path | str,
    project_name: str,
    task_id: str,
    *,
    agent_id: str,
    agent_name: str,
    ts: str | None = None,
    dispatch_reason: str | None = None,
) -> None:
    """Transiciona la entrada `queued` de `task_id` a `dispatched`, con el
    agente que la tomó — usado por el Dispatcher (`T-FB008-US10-02`, no
    esta Task), incluido aquí porque forma parte del esquema de la cola
    que esta Task ya fija. No lanza si `task_id` no está en la cola
    (`queued` ya consumido por una carrera con otro despacho) — el
    Dispatcher decide si eso es un caso a loguear, no responsabilidad de
    este módulo. `dispatch_reason` (T-FB008-US12-02) documenta motivo de
    selección del Developer/modelo."""
    path = dispatch_queue_path(project_root, project_name)
    with _write_lock:
        entries = _read_all(path)
        for entry in entries:
            if entry.task_id == task_id and entry.status == STATUS_QUEUED:
                entry.status = STATUS_DISPATCHED
                entry.agent_id = agent_id
                entry.agent_name = agent_name
                entry.dispatched_at = ts if ts is not None else datetime.now(timezone.utc).isoformat()
                entry.dispatch_reason = dispatch_reason
        _write_all(path, entries)


def mark_failed(
    project_root: Path | str, project_name: str, task_id: str, *, result: str
) -> None:
    """Transiciona una entrada `dispatched` de `task_id` a `failed`, con
    el motivo real — mismo consumidor futuro que `mark_dispatched`
    (Dispatcher, `T-FB008-US10-02`)."""
    path = dispatch_queue_path(project_root, project_name)
    with _write_lock:
        entries = _read_all(path)
        for entry in entries:
            if entry.task_id == task_id and entry.status == STATUS_DISPATCHED:
                entry.status = STATUS_FAILED
                entry.result = result
        _write_all(path, entries)
