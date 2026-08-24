"""Cola de Tasks marcadas "lista para desarrollo" (T-AF008-US10-01,
US-AF008-10 · "Marcar Tasks como listas para desarrollo y que un
Dispatcher las asigne solo a un Developer libre").

## Por qué un segundo mecanismo, distinto del Plan (`US-AF008-04`)

El flujo de Plan (`build_job_plan_for_story`/`dispatch_plan`) exige
aprobar un lote completo de Tasks de una User Story por adelantado. Esta
Story añade un segundo camino: marcar Tasks sueltas (o todas las `TODO`
de una US) como encoladas, sin aprobación de lote, para que un
Dispatcher de fondo (`T-AF008-US10-02`, Task aparte — NO implementado
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
ya vive en memoria y se pierde en cada reinicio del proceso (`AF-031`) —
la cola necesita sobrevivir a un reinicio de `atlas-forge-api` (un `restart` de
`systemd`, `T-AF037-US04-01`, es una operación esperada, no excepcional)
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
`atlas-forge-api` corre como un único proceso `systemd`, no varios workers)."""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from atlas_forge.runtime.generic import sanitize_session_name_part

_QUEUE_FILENAME = "dispatch_queue.json"

STATUS_QUEUED = "queued"
STATUS_DISPATCHED = "dispatched"
STATUS_FAILED = "failed"
# T-AF008-US10-04: estado terminal de una entrada cuya Task ya está
# `DONE` (veredicto EXITO del Tester) — deja de contar como "en curso".
STATUS_COMPLETED = "completed"
# T-AF008-US10-04: estado MOSTRADO (no persistido) de una entrada cuyo
# Developer la cerró y la Task espera veredicto del Tester (`IN_REVIEW`).
STATUS_AWAITING_TESTER = "awaiting_tester"

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


class TaskNotTerminalError(ValueError):
    """`task_id` tiene una entrada en la cola pero NO en estado terminal
    (`completed`/`failed`) — es una entrada en curso (`queued`/
    `dispatched`) que no es borrable por esta vía (T-AF036-US17-07); las
    en curso usan su propio mecanismo (dequeue para `queued`)."""


@dataclass
class QueueEntry:
    """Una entrada de la cola: una Task marcada para desarrollo.

    `task_id`/`us_id`/`priority` se copian del `BacklogItem` en el
    momento de encolar (no se re-resuelven en cada lectura) — mismo
    criterio que el resto del backlog: el fichero de Task en disco sigue
    siendo la fuente de verdad de `state`/`priority` reales; esta cola
    solo recuerda "qué Tasks se marcaron y en qué orden", no duplica el
    parser. `agent_id`/`agent_name`/`result` quedan `None` hasta que el
    Dispatcher (`T-AF008-US10-02`) despache la entrada — esta Task deja
    los campos ya definidos para que ese Dispatcher no tenga que cambiar
    el esquema del fichero. `dispatch_reason` (T-AF008-US12-02) registra
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
    # T-AF008-US10-05: ruta del fichero de reporte del Job de
    # implementación en vuelo (`dispatch_job_send`). Se persiste aquí para
    # que la reconciliación al arrancar distinga un Job legítimamente en
    # vuelo (el fichero existe) de una entrada huérfana tras un reinicio
    # (el fichero no existe / no es localizable).
    report_file: str | None = None
    # T-AF036-US17-01: timestamp UTC en el que la entrada pasó a un estado
    # terminal (`completed`/`failed`), asignado por `mark_completed`/
    # `mark_failed`. `None` si aún no ha terminado (o registro legacy sin el
    # campo — compatibilidad hacia atrás).
    finished_at: str | None = None


def dispatch_queue_path(project_root: Path | str, project_name: str) -> Path:
    """Ruta del fichero de cola de `project_name`, dentro de
    `<project_root>/.claude/state/<project_name>/dispatch_queue.json` —
    misma raíz de estado por proyecto que `architect_queue_path`, mismo
    criterio de saneo (`sanitize_session_name_part`, pública desde
    `T-AF031-US02-02`) en vez del símbolo privado de `architect_queue.py`."""
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
    formaba parte de un `enqueue-all` previo).

    Al re-encolar una Task que ya tiene entradas TERMINALES previas
    (`failed`/`completed`, p. ej. tras un reintento legítimo de una Task
    que volvió a `READY`), esas entradas históricas se eliminan y solo
    queda la entrada nueva — se garantiza exactamente una entrada por
    `task_id` en la cola, sin acumular historial que confunda a la UI."""
    path = dispatch_queue_path(project_root, project_name)
    with _write_lock:
        entries = _read_all(path)
        if any(e.task_id == task_id and e.status == STATUS_QUEUED for e in entries):
            raise TaskAlreadyQueuedError(
                f"La Task '{task_id}' ya está encolada."
            )
        # Re-encolado tras un fallo/cierre previo: se eliminan las entradas
        # históricas terminales de la misma Task (nunca una `queued`/`dispatched`
        # activa — la `queued` ya se descartó arriba, y una `dispatched` no se
        # puede re-encolar por el flujo normal). Garantiza una sola entrada por
        # `task_id`.
        entries = [e for e in entries if e.task_id != task_id]
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
    `T-AF008-US04-08` de distinguir el mensaje real según la causa."""
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
    de `atlas_forge.backlog.report`), no aquí: esta función es solo lectura
    cruda del fichero, sin lógica de negocio de orden."""
    path = dispatch_queue_path(project_root, project_name)
    with _write_lock:
        return _read_all(path)


def migrate_queued_entries_to_state(
    project_root: Path | str, project_name: str, backlog_dir: Path | str
) -> list[str]:
    """T-AF008-US14-01, criterio de aceptación de migración: entradas ya
    encoladas en `dispatch_queue.json` (`status == "queued"`) ANTES de
    esta Task nunca tuvieron su `state` real escrito a `TO_DEVELOP` (AF-040;
    antes `EN_DESARROLLO`) — solo vivían en el JSON, con el fichero real
    todavía en `READY` (antes `TO_DO`). Esta función pone al día esos
    ficheros reales, sin tocar el propio JSON (sigue siendo el registro
    de orden/auditoría auxiliar, no cambia de formato).

    Solo toca Tasks cuyo `state` real es TODAVÍA `READY` — si ya está en
    `TO_DEVELOP` (encolada de nuevo tras esta Task) o en cualquier otro
    estado (alguien la movió manualmente, o el Dispatcher ya la tomó y
    el JSON quedó desincronizado), no se toca: mismo criterio de
    "solo promueve hacia adelante, nunca revierte" ya usado en
    `promote_backlog`.

    Devuelve la lista de `task_id` migrados. Idempotente: ejecutarlo dos
    veces no vuelve a tocar nada la segunda vez (las ya migradas están en
    `TO_DEVELOP`, no en `READY`)."""
    from atlas_forge.backlog.edit import set_item_state
    from atlas_forge.backlog.parser import load_backlog

    entries = get_queue(project_root, project_name)
    queued_task_ids = {e.task_id for e in entries if e.status == STATUS_QUEUED}
    if not queued_task_ids:
        return []

    graph = load_backlog(Path(backlog_dir))
    migrated = []
    for task_id in sorted(queued_task_ids):
        item = graph.items.get(task_id)
        if item is None or item.state != "READY":
            continue
        set_item_state(item.path, "TO_DEVELOP")
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
    agente que la tomó — usado por el Dispatcher (`T-AF008-US10-02`, no
    esta Task), incluido aquí porque forma parte del esquema de la cola
    que esta Task ya fija. No lanza si `task_id` no está en la cola
    (`queued` ya consumido por una carrera con otro despacho) — el
    Dispatcher decide si eso es un caso a loguear, no responsabilidad de
    este módulo. `dispatch_reason` (T-AF008-US12-02) documenta motivo de
    selección del Developer/modelo.

    Decisión 2026-08-19 (reintento automático): también transiciona una
    entrada `failed` a `dispatched` — el caso de una Task que falló (su
    entrada quedó `failed`), volvió a `TO_DEVELOP` y el siguiente ciclo
    la re-despacha: la misma entrada se reutiliza en vez de acumular una
    nueva, y su estado vuelve a reflejar "en curso"."""
    path = dispatch_queue_path(project_root, project_name)
    with _write_lock:
        entries = _read_all(path)
        for entry in entries:
            if entry.task_id == task_id and entry.status in (STATUS_QUEUED, STATUS_FAILED):
                entry.status = STATUS_DISPATCHED
                entry.agent_id = agent_id
                entry.agent_name = agent_name
                entry.dispatched_at = ts if ts is not None else datetime.now(timezone.utc).isoformat()
                entry.dispatch_reason = dispatch_reason
                # Al re-despachar se limpia el resultado del fallo previo
                # (la misma entrada se reutiliza).
                entry.result = None
        _write_all(path, entries)


def set_entry_report_file(
    project_root: Path | str,
    project_name: str,
    task_id: str,
    report_file: Path | str,
) -> None:
    """T-AF008-US10-05: persiste la ruta del fichero de reporte del Job de
    implementación en vuelo en la entrada `dispatched` de `task_id`.

    `dispatch_job_send` genera un fichero de reporte único por Job en
    `/tmp` (no derivable desde la entrada); guardarlo en la propia cola
    es lo que permite a la reconciliación al arrancar
    (`reconcile_dispatch_queue_entries`) distinguir un Job legítimamente
    en vuelo (el fichero todavía existe) de una entrada huérfana tras un
    reinicio de `atlas-forge-api` (el fichero no existe / no es localizable) —
    sin persistirlo, tras reiniciar no habría forma determinista de saber
    si el Job sigue vivo.

    Mejor esfuerzo, mismo criterio que `mark_dispatched`: si `task_id` no
    tiene una entrada `dispatched` (carrera, ya resuelta), no hace nada."""
    path = dispatch_queue_path(project_root, project_name)
    with _write_lock:
        entries = _read_all(path)
        for entry in entries:
            if entry.task_id == task_id and entry.status == STATUS_DISPATCHED:
                entry.report_file = str(report_file)
        _write_all(path, entries)


def mark_failed(
    project_root: Path | str,
    project_name: str,
    task_id: str,
    *,
    result: str,
    allow_queued: bool = False,
) -> None:
    """Transiciona una entrada `dispatched` de `task_id` a `failed`, con
    el motivo real — mismo consumidor futuro que `mark_dispatched`
    (Dispatcher, `T-AF008-US10-02`).

    `allow_queued` (T-AF008-US10-04, corrección de entradas `queued`
    huérfanas): cuando es `True`, también terminaliza una entrada aún
    `queued` — usado por la reconciliación al arrancar para limpiar una
    entrada `queued` cuyo estado real del fichero ya no la justifica
    (Task `DONE`/`READY` o inexistente). El resto de llamadores sigue
    dejando intactas las `queued` (una entrada pendiente no se toca)."""
    path = dispatch_queue_path(project_root, project_name)
    with _write_lock:
        entries = _read_all(path)
        for entry in entries:
            if entry.task_id == task_id and (
                entry.status == STATUS_DISPATCHED
                or (allow_queued and entry.status == STATUS_QUEUED)
            ):
                entry.status = STATUS_FAILED
                entry.result = result
                # T-AF036-US17-01: timestamp del cierre del Job.
                entry.finished_at = datetime.now(timezone.utc).isoformat()
        _write_all(path, entries)


def mark_completed(
    project_root: Path | str,
    project_name: str,
    task_id: str,
    *,
    result: str | None = None,
    allow_queued: bool = False,
) -> None:
    """T-AF008-US10-04: transiciona una entrada de `task_id` a `completed`
    (estado terminal) cuando el estado REAL de la Task pasa a `DONE`
    (veredicto EXITO del Tester, o cierre por veredicto de US). Solo se
    toca una entrada que todavía pudiera mostrar "en curso"
    (`dispatched`) — una entrada ya `queued`/`failed` no se toca. No lanza
    si `task_id` no está en la cola (mismo criterio de mejor esfuerzo que
    `mark_dispatched`).

    `allow_queued` (T-AF008-US10-04, corrección de entradas `queued`
    obsoletas): cuando es `True`, también terminaliza una entrada aún
    `queued` — usado por la reconciliación al arrancar para cerrar una
    entrada `queued` cuya Task real ya está `DONE` (cerrada fuera del
    pipeline, nunca despachada por esta cola). El resto de llamadores
    sigue dejando intactas las `queued`."""
    path = dispatch_queue_path(project_root, project_name)
    with _write_lock:
        entries = _read_all(path)
        for entry in entries:
            if entry.task_id == task_id and (
                entry.status == STATUS_DISPATCHED
                or (allow_queued and entry.status == STATUS_QUEUED)
            ):
                entry.status = STATUS_COMPLETED
                if result is not None:
                    entry.result = result
                # T-AF036-US17-01: timestamp del cierre del Job.
                entry.finished_at = datetime.now(timezone.utc).isoformat()
        _write_all(path, entries)


# Estados terminales del histórico (T-AF036-US17-02): `clear_history` los
# elimina del fichero de auditoría. Lo "en curso" (`queued`/`dispatched`) se
# conserva.
_TERMINAL_STATUSES = frozenset({STATUS_COMPLETED, STATUS_FAILED})


def clear_history(project_root: Path | str, project_name: str) -> int:
    """T-AF036-US17-02: elimina del `dispatch_queue.json` las entradas en
    estado terminal (`completed`/`failed`), conservando las en curso
    (`queued`/`dispatched`).

    No toca el estado real de las Tasks ni el Dispatcher — solo el registro
    de auditoría/histórico. Devuelve el número de entradas borradas. Es
    idempotente: si no hay entradas terminales, devuelve 0 y no reescribe
    nada."""
    path = dispatch_queue_path(project_root, project_name)
    with _write_lock:
        entries = _read_all(path)
        before = len(entries)
        remaining = [e for e in entries if e.status not in _TERMINAL_STATUSES]
        removed = before - len(remaining)
        if removed:
            _write_all(path, remaining)
    return removed


def clear_completed(project_root: Path | str, project_name: str) -> int:
    """T-AF042-US07-01: elimina del `dispatch_queue.json` SOLO las entradas
    `completed` (DONE), conservando `failed`, `queued`, `dispatched` y
    `awaiting_tester` — el borrado masivo de completadas que la web usa
    (botón "Borrar completadas"), distinto de `clear_history` (completed +
    failed) y de `remove_entry` (una sola).

    No toca el estado real de las Tasks ni el Dispatcher — solo el registro
    de auditoría. Devuelve el número de entradas borradas; idempotente
    (segunda llamada sin `completed` devuelve 0)."""
    path = dispatch_queue_path(project_root, project_name)
    with _write_lock:
        entries = _read_all(path)
        before = len(entries)
        remaining = [e for e in entries if e.status != STATUS_COMPLETED]
        removed = before - len(remaining)
        if removed:
            _write_all(path, remaining)
    return removed


def remove_entry(project_root: Path | str, project_name: str, task_id: str) -> bool:
    """T-AF036-US17-07: elimina del `dispatch_queue.json` SOLO la entrada
    terminal (`completed`/`failed`) cuyo `task_id` coincide, conservando el
    resto de la cola — el borrado individual que la UI usará (un aspa por
    fila, T-AF036-US17-09), distinto del borrado masivo `clear_history`.

    No toca el estado real de las Tasks ni el Dispatcher — solo el registro
    de auditoría. Lanza excepción tipada en lugar de borrar en silencio:

    - `TaskNotQueuedError` (404) si `task_id` no tiene NINGUNA entrada.
    - `TaskNotTerminalError` (409) si la entrada existe pero está en curso
      (`queued`/`dispatched`) — no es borrable por esta vía.

    Devuelve `True` tras borrar la entrada."""
    path = dispatch_queue_path(project_root, project_name)
    with _write_lock:
        entries = _read_all(path)
        entry = next((e for e in entries if e.task_id == task_id), None)
        if entry is None:
            raise TaskNotQueuedError(f"La Task '{task_id}' no está en la cola.")
        if entry.status not in _TERMINAL_STATUSES:
            raise TaskNotTerminalError(
                f"La entrada de la Task '{task_id}' no es terminal "
                f"(estado '{entry.status}') — no se puede borrar por esta vía."
            )
        entries = [e for e in entries if e.task_id != task_id]
        _write_all(path, entries)
        return True


def requeue_entry(
    project_root: Path | str,
    project_name: str,
    task_id: str,
    *,
    task_state: str | None = None,
) -> QueueEntry:
    """Reencola una entrada `failed` de `task_id` de vuelta a `queued` para
    que el Dispatcher pueda reintentarla (T-AF036-US17-08). Es reencolable una
    entrada almacenada `failed`, o una entrada cuyo estado DERIVADO es `failed`
    (entrada `dispatched` cuya Task real ya no justifica "en curso" — Task
    READY/TO_DEVELOP tras reinicio/revertida) — mismo criterio que la UI usa
    para ofrecer el botón Reencolar.

    Lanza:
    - `TaskNotQueuedError` (404) si `task_id` no tiene NINGUNA entrada en la
      cola.
    - `TaskNotTerminalError` (409) si la entrada ni está almacenada `failed` ni
      deriva a `failed` (`queued` en vuelo / `completed` / `awaiting_tester`).

    El estado real de la Task no se toca aquí — es la capa HTTP quien, si
    `task_state == "READY"`, la promueve a `TO_DEVELOP` (la fuente de verdad
    de "lista para desarrollo"). Devuelve la entrada reencolada."""
    path = dispatch_queue_path(project_root, project_name)
    with _write_lock:
        entries = _read_all(path)
        match = next((e for e in entries if e.task_id == task_id), None)
        if match is None:
            raise TaskNotQueuedError(f"La Task '{task_id}' no está en la cola.")
        # Reencolable si la entrada está almacenada `failed`, o si está
        # `dispatched` pero su estado DERIVADO es `failed` (Task real
        # READY/TO_DEVELOP tras reinicio/revertida) — mismo criterio que la
        # UI usa para ofrecer el botón Reencolar.
        effective_status = derive_effective_status(match, task_state)
        is_stored_failed = match.status == STATUS_FAILED
        is_huerfana_reencolable = match.status != STATUS_FAILED and effective_status == STATUS_FAILED
        if not (is_stored_failed or is_huerfana_reencolable):
            raise TaskNotTerminalError(
                f"La entrada de la Task '{task_id}' no está 'failed' "
                f"(estado '{match.status}', derivado '{effective_status}') — solo una entrada fallida se "
                f"reencola por esta vía."
            )
        # Re-encolar elimina las entradas terminales previas de la misma Task
        # y crea una `queued` nueva (garantiza una sola entrada por task_id).
        entries = [e for e in entries if e.task_id != task_id]
        entry = QueueEntry(
            task_id=task_id,
            us_id=match.us_id,
            priority=match.priority,
            status=STATUS_QUEUED,
            enqueued_at=datetime.now(timezone.utc).isoformat(),
        )
        entries.append(entry)
        _write_all(path, entries)
        return entry


def derive_effective_status(entry: QueueEntry, task_state: str | None) -> str:
    """T-AF008-US10-04: deriva el estado MOSTRADO de una entrada de la
    cola cruzando su estado almacenado con el estado REAL del fichero de
    la Task (la fuente de verdad tras AF-040). El almacenado (`queued`/
    `dispatched`/`failed`/`completed`) sigue siendo el registro de orden y
    auditoría; lo que se pinta en la UI es este derivado, de modo que la
    cola nunca muestre una Task `DONE`/`READY`/`TO_DEVELOP` como "en
    curso".

    Reglas:
    - `queued` -> `queued` (Pendiente) mientras la Task real siga
      justificando la espera (`TO_DEVELOP`); si la Task real ya está
      `DONE` -> `completed` (cerrada fuera del pipeline, nunca despachada);
      si la Task real está `READY`/no existe -> `failed` (entrada huérfana;
      nunca "Pendiente").
    - Task `DONE` (o entrada ya `completed`) -> `completed`.
    - `failed` -> `failed`.
    - Entrada `dispatched` con Task `IN_REVIEW` -> `awaiting_tester`
      (el Developer que la cerró está retenido esperando al Tester).
    - Entrada `dispatched` con Task `READY`/`TO_DEVELOP`, o Task que ya no
      existe -> `failed` (huérfana tras reinicio / revertida; nunca "en
      curso").
    - Cualquier otro caso (`IN_PROGRESS` real) -> `dispatched` (En curso)."""
    if entry.status == STATUS_QUEUED:
        # La Task real decide lo que se muestra también para `queued`: la
        # entrada es "Pendiente" solo mientras la Task la justifica. Una
        # Task `DONE` o `READY`/inexistente con entrada `queued` residual
        # (cerrada por otra vía, o revertida) no debe pintarse como
        # Pendiente para siempre.
        if task_state == "DONE":
            return STATUS_COMPLETED
        if task_state in ("READY",) or task_state is None:
            return STATUS_FAILED
        return STATUS_QUEUED
    if entry.status == STATUS_COMPLETED or task_state == "DONE":
        return STATUS_COMPLETED
    if entry.status == STATUS_FAILED:
        return STATUS_FAILED
    # `dispatched` (o cualquier otro estado no terminal): el estado REAL
    # del fichero decide lo que se muestra.
    if task_state is None:
        return STATUS_FAILED
    if task_state == "IN_REVIEW":
        return STATUS_AWAITING_TESTER
    if task_state in ("READY", "TO_DEVELOP"):
        return STATUS_FAILED
    return STATUS_DISPATCHED


def reconcile_dispatch_queue_entries(
    project_root: Path | str,
    project_name: str,
    backlog_dir: Path | str,
    *,
    auto_reenqueue_orphaned: bool = False,
) -> list[str]:
    """T-AF008-US10-04, criterio 3/4: al arrancar el worker, las entradas
    `dispatched` cuyo estado real del fichero ya no las justifica
    (huérfanas tras un reinicio del worker/`atlas-forge-api`) se reconcilian y
    dejan de poder mostrarse como "en curso". También reconcilia las
    entradas `queued` cuyo estado real ya no las justifica como
    pendientes (Task `DONE` cerrada fuera del pipeline, o Task revertida
    a `READY`/inexistente):

    - Task `DONE` -> entrada `completed` (cierre por veredicto previo que
      nunca llegó a terminalizarse en la cola, o Task cerrada por otra
      vía sin pasar por esta cola).
    - Task `READY`/`TO_DEVELOP`, o Task que ya no existe -> entrada
      `failed` con el motivo real de la reconciliación.
    - Task `IN_PROGRESS` (T-AF008-US10-05): si el fichero de reporte del
      Job en vuelo ya no existe (o no se registró) es una huérfana real —
      la Task vuelve a `READY` (o `TO_DEVELOP` si `auto_reenqueue_orphaned`
      está activa) en su fichero real y la entrada queda `failed` con el
      motivo, dejando la plaza libre para que el siguiente ciclo la
      re-despache. Si el fichero de reporte todavía existe, el Job sigue
      legítimamente en vuelo y NO se toca (no se duplica trabajo).
    - Task `IN_REVIEW` se deja intacta: el ciclo de revisión del Tester
      (`run_review_dispatch_cycle`) la re-despacha sola cada poll, no
      necesita reconciliación (y revertirla descartaría el trabajo ya
      cerrado por el Developer).
    - Una entrada `queued` con Task `TO_DEVELOP` (su estado normal, el
      fichero se escribe al encolar) se deja intacta — sigue siendo una
      entrada pendiente legítima.
    - Cualquier otro estado real se deja intacta.

    Idempotente y de mejor esfuerzo: no lanza si el backlog no existe.
    Devuelve la lista de `task_id` reconciliados este arranque."""
    from atlas_forge.backlog.edit import set_item_state
    from atlas_forge.backlog.parser import load_backlog
    from atlas_forge.core.reconciliation_log import (
        append_dispatched_orphan_reconciliation,
    )

    entries = get_queue(project_root, project_name)
    pending = [
        e for e in entries if e.status in (STATUS_DISPATCHED, STATUS_QUEUED)
    ]
    if not pending:
        return []

    graph = load_backlog(Path(backlog_dir))
    reconciled: list[str] = []
    for entry in pending:
        item = graph.items.get(entry.task_id)
        state = item.state if item is not None else None
        if state == "DONE":
            mark_completed(
                project_root, project_name, entry.task_id,
                result="Reconciliada al arrancar: la Task ya estaba DONE.",
                allow_queued=(entry.status == STATUS_QUEUED),
            )
            reconciled.append(entry.task_id)
        elif state in ("READY", "TO_DEVELOP") or state is None:
            # Para una entrada `queued`, `TO_DEVELOP` es su estado normal
            # (el fichero se escribe al encolar) — NO es huérfana; el resto
            # de estados reales sí la dejan obsoleta.
            if entry.status == STATUS_QUEUED and state == "TO_DEVELOP":
                continue
            mark_failed(
                project_root, project_name, entry.task_id,
                result=(
                    f"Reconciliada al arrancar: estado real del fichero "
                    f"'{state or 'desconocido'}' — entrada huérfana tras reinicio."
                ),
                allow_queued=(entry.status == STATUS_QUEUED),
            )
            reconciled.append(entry.task_id)
        elif state == "IN_PROGRESS":
            # T-AF008-US10-05: huérfana real solo si el Job en vuelo ya no
            # tiene reporte (o nunca se registró). Si el reporte existe, el
            # Job sigue vivo — no se toca para no duplicar trabajo.
            report_file = Path(entry.report_file) if entry.report_file else None
            if report_file is not None and report_file.is_file():
                continue
            target_state = "TO_DEVELOP" if auto_reenqueue_orphaned else "READY"
            # T-AF036-US22-01: `IN_PROGRESS -> TO_DEVELOP/READY` (reencolar
            # una huérfana tras reinicio) no la modela la máquina canónica —
            # es una reconciliación operativa interna, se fuerza.
            set_item_state(item.path, target_state, force=True)
            mark_failed(
                project_root, project_name, entry.task_id,
                result=(
                    "Job en vuelo perdido tras reinicio — "
                    + ("reencolada automáticamente" if auto_reenqueue_orphaned else "reencolada manualmente")
                ),
            )
            append_dispatched_orphan_reconciliation(
                project_root, project_name,
                task_id=entry.task_id,
                target_state=target_state,
            )
            reconciled.append(entry.task_id)
    return reconciled


def reconcile_orphaned_in_progress_tasks(
    project_root: Path | str,
    project_name: str,
    backlog_dir: Path | str,
    *,
    auto_reenqueue_orphaned: bool = False,
) -> list[str]:
    """T-AF022-US18-01 (US-AF022-18, criterio 1/2/7): cierra el hueco de
    `reconcile_dispatch_queue_entries`, que solo recorre entradas CON
    presencia en `dispatch_queue.json`. Una task `IN_PROGRESS` SIN entrada
    en la cola (el caso real T-AF023-US03-01, bloqueando su cadena) nunca
    se arreglaba. Esta función detecta esas huérfanas reales y las revierte
    automáticamente.

    Lógica (por cada task `kind == "T"` con `state == "IN_PROGRESS"`):

    - Es **huérfana real** si NO tiene entrada `dispatched` en la cola
      (`dispatch_queue.json`) **y** ningún fichero de reporte en vuelo
      localizable (el de la entrada `dispatched`, o el de cualquier otra
      entrada que apunte a un `report_file` que todavía exista). Sin
      entrada `dispatched` ni reporte persistido no hay forma de que un
      Job siga legítimamente en vuelo.
    - Para cada huérfana real, `set_item_state(item.path, target_state)`
      con `target_state = "TO_DEVELOP" if auto_reenqueue_orphaned else
      "READY"` (`force=True`: `IN_PROGRESS -> TO_DEVELOP/READY` no la
      modela la máquina canónica — es una reconciliación operativa interna,
      mismo patrón que `reconcile_dispatch_queue_entries`), y se registra
      en `reconciliation_log.jsonl` vía `append_dispatched_orphan_reconciliation`
      (mismo motivo `dispatched_orphan_reconciled` que el resto de
      huérfanas, para un log coherente).
    - Se **respeta** una `IN_PROGRESS` con entrada `dispatched` o con
      `report_file` presente (Job legítimo en vuelo — no duplicar trabajo,
      criterio de seguridad de la US).
    - Las User Stories derivadas NO se tocan: su estado deriva de sus
      Tasks (`derive_user_story_state`), así que revirtiendo la Task su US
      derivará sola; esta función solo filtra `kind == "T"`.

    Idempotente y de mejor esfuerzo: si el backlog no existe (o está vacío)
    `load_backlog` devuelve un grafo vacío y la función retorna `[]` sin
    lanzar. Devuelve la lista de `task_id` reconciliados.

    Se compone con `reconcile_dispatch_queue_entries` (ambas coexisten): la
    primera recorre las entradas de la cola; esta recorre las tasks reales
    sin entrada. Un mismo arranque puede llamar a las dos sin conflicto."""
    from atlas_forge.backlog.edit import set_item_state
    from atlas_forge.backlog.parser import load_backlog
    from atlas_forge.core.reconciliation_log import (
        append_dispatched_orphan_reconciliation,
    )

    entries = get_queue(project_root, project_name)
    # Protegidas: con entrada `dispatched` (en vuelo) o con un `report_file`
    # localizable en disco (Job legítimo en vuelo — nunca se revierte).
    dispatched_task_ids = {
        e.task_id for e in entries if e.status == STATUS_DISPATCHED
    }
    live_report_task_ids = {
        e.task_id
        for e in entries
        if e.report_file and Path(e.report_file).is_file()
    }

    graph = load_backlog(Path(backlog_dir))
    reconciled: list[str] = []
    for task_id in sorted(graph.items):
        item = graph.items[task_id]
        if item.kind != "T":
            continue
        if item.state != "IN_PROGRESS":
            continue
        if task_id in dispatched_task_ids or task_id in live_report_task_ids:
            continue
        target_state = "TO_DEVELOP" if auto_reenqueue_orphaned else "READY"
        set_item_state(item.path, target_state, force=True)
        append_dispatched_orphan_reconciliation(
            project_root, project_name,
            task_id=task_id,
            target_state=target_state,
        )
        reconciled.append(task_id)
    return reconciled
