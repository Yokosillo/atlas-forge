"""Log persistente del resultado de `reconcile_session_agents` en cada
arranque de `atlas-forge-api` (T-AF037-US02-01, US-AF037-02 · "Log persistente
de la reconciliación de agentes al arrancar").

Antes de esta Task, `_lifespan` (`atlas_forge.api.app`) descartaba el valor de
retorno de `reconcile_session_agents` sin dejar ningún rastro fuera de
stdout — reconstruir qué ocurrió en un reinicio concreto exigía cruzar
`ps`/`ss`/`tmux list-sessions`/`.bash_history` a mano (incidente real del
2026-08-16, ver `07-informes/incidente-arquitecto-perdido-tras-reinicio-2026-08-16.md`).
Este módulo es puramente aditivo: no participa en la decisión de qué
sesión se reengancha (eso lo sigue decidiendo `reconcile_session_agents`
en solitario), solo persiste su resultado ya calculado.

Mismo patrón ya existente en `atlas_forge.dispatcher.architect_queue`
(`architect_queue_path`/`append_to_architect_queue`, `AF-030`): misma
ubicación `.claude/state/<project_name>/`, mismo fichero JSONL
append-only con lock para concurrencia dentro del proceso — reutilizado
aquí en vez de reimplementado, junto a `architect_queue.jsonl`."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from atlas_forge.runtime import sanitize_session_name_part

_LOG_FILENAME = "reconciliation_log.jsonl"

# Serializa los `append` concurrentes DENTRO de este mismo proceso — mismo
# motivo y mismo alcance que `architect_queue._write_lock` (el modo `"a"`
# del sistema de ficheros ya evita que dos `write()` de líneas completas
# se intercalen a nivel de SO; este lock solo evita que dos hilos del
# mismo proceso interfieran entre sí).
_write_lock = threading.Lock()


def reconciliation_log_path(project_root: Path | str, project_name: str) -> Path:
    """Ruta del log de `project_name`, dentro de
    `<project_root>/.claude/state/<sanitize_session_name_part(project_name)>/reconciliation_log.jsonl`
    — mismo directorio que `architect_queue_path` (misma sanitización de
    nombre de proyecto a nombre de directorio), fichero distinto."""
    dirname = sanitize_session_name_part(project_name)
    return Path(project_root) / ".claude" / "state" / dirname / _LOG_FILENAME


def append_dispatched_orphan_reconciliation(
    project_root: Path | str,
    project_name: str,
    *,
    task_id: str,
    target_state: str,
    ts: str | None = None,
) -> Path:
    """T-AF008-US10-05: registra en el mismo `reconciliation_log.jsonl`
    la reconciliación de una entrada `dispatched` huérfana (Job en vuelo
    perdido tras reiniciar atlas_forge) — misma ubicación y mismo formato JSONL
    append-only que `append_reconciliation_log`, motivo
    `dispatched_orphan_reconciled`.

    `task_id`: Task cuya entrada huérfana se reconcilió; `target_state`:
    estado real al que volvió la Task en su fichero (`READY`, o
    `TO_DEVELOP` si la preferencia automática está activa). Devuelve la
    ruta del fichero de log escrito."""
    path = reconciliation_log_path(project_root, project_name)

    entry = {
        "ts": ts if ts is not None else datetime.now(timezone.utc).isoformat(),
        "reason": "dispatched_orphan_reconciled",
        "task_id": task_id,
        "target_state": target_state,
    }
    line = json.dumps(entry, ensure_ascii=False) + "\n"

    with _write_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)

    return path


def append_unreachable_agent_log(
    project_root: Path | str,
    project_name: str,
    *,
    agent_id: str,
    agent_name: str,
    reason: str,
    ts: str | None = None,
) -> Path:
    """T-AF023-US05-02: registra en el `reconciliation_log.jsonl` (append-only)
    cada detección de un agente persistente inalcanzable — el canal consultable
    por un humano sin abrir la web/TUI.

    `agent_id`/`agent_name`: agente detectado inalcanzable; `reason`: motivo de
    la detección (p. ej. sesión/processo real desaparecido). Mismo formato
    JSONL append-only y mismo lock que las demás entradas de este log; motivo
    `persistent_agent_unreachable`. `ts` por defecto el instante actual en UTC
    (ISO 8601); se acepta explícito para tests deterministas. Devuelve la ruta
    del fichero de log escrito."""
    path = reconciliation_log_path(project_root, project_name)

    entry = {
        "ts": ts if ts is not None else datetime.now(timezone.utc).isoformat(),
        "reason": "persistent_agent_unreachable",
        "agent_id": agent_id,
        "agent_name": agent_name,
        "motivo": reason,
    }
    line = json.dumps(entry, ensure_ascii=False) + "\n"

    with _write_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)

    return path


def append_reconciliation_log(
    project_root: Path | str,
    project_name: str,
    *,
    total_sessions: int,
    recognized: int,
    reconciled: list[str],
    ignored: list[dict],
    ts: str | None = None,
) -> Path:
    """Añade una entrada de log al arranque actual.

    `total_sessions`: número de sesiones tmux vistas en el socket.
    `recognized`: número de esas sesiones reconocidas como agentes
    válidos de este proyecto (reenganchadas AHORA + ya reconciliadas de
    antes; excluye nombre no reconocido/otro proyecto/rol inválido).
    `reconciled`: nombres de sesión efectivamente reenganchados en esta
    llamada. `ignored`: lista de `{"session_name", "reason"}` (criterio
    de aceptación 2 de `US-AF037-02`: distingue explícitamente ignoradas
    de reenganchadas, con motivo) — mismo formato que devuelve
    `reconcile_session_agents`, persistido tal cual. `ts` por defecto es
    el instante actual en UTC (ISO 8601); se acepta explícito para tests
    deterministas.

    Devuelve la ruta del fichero de log escrito."""
    path = reconciliation_log_path(project_root, project_name)

    entry = {
        "ts": ts if ts is not None else datetime.now(timezone.utc).isoformat(),
        "total_sessions": total_sessions,
        "recognized": recognized,
        "reconciled_count": len(reconciled),
        "reconciled": reconciled,
        "ignored_count": len(ignored),
        "ignored": ignored,
    }
    line = json.dumps(entry, ensure_ascii=False) + "\n"

    with _write_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)

    return path
