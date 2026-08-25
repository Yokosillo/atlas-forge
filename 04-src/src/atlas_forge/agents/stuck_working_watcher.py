"""Watcher de auto-liberación "working sin Job en vuelo" (T-AF008-US18-04,
US-AF008-18): detecta operativamente a un agente que quedó `working` pese a
no tener ningún Job en vuelo legítimo y sin actividad reciente (huérfano por
re-despacho del mismo task_id — T-AF008-US18-02 —, por reinicio o por
duplicado), lo marca `failed` con motivo consultable y devuelve su Task a
`TO_DEVELOP`, desbloqueando la cola sin intervención manual.

Caso real (2026-08-24): dos Developers quedaron `working` tras perder su Job
en vuelo, bloqueando la cola (15 queued, 0 dispatched durante 4h).

La señal de vuelo es EXCLUYENTE (criterio 3 de la Task): un agente `working`
que sí tiene un Job en vuelo (presente en los registros `inflight` del
Dispatcher) NUNCA se libera — no hay falsos positivos.

## Encaje con US-AF023-05 / US-AF024-17 (criterio 5 de la Task)

- US-AF023-05 vigila la INACTIVIDAD general del agente (pane/log congelados)
  y la expone en `supervision_status` (`vivo`/`colgado`/`detenido`) — NO
  toca el estado funcional ni re-despacha Tasks.
- US-AF024-17 (READY) expone QUÉ hace un agente `working` (Job en curso por
  agente) — informativo, no correctivo.
- Este watcher añade la pieza que faltaba: la AUTO-LIBERACIÓN específica de
  `working` sin Job en vuelo + `last_command_at` congelado, con retorno de la
  Task a `TO_DEVELOP`. No duplica la vigilancia general (no lee panes ni
  logs) ni el "qué hace" (no describe el Job); usa la MISMA señal de vuelo
  del Dispatcher (registros `inflight`) que US-AF042-04 consume.

## Patrón

Mismo patrón arquitectónico que `SessionLimitWatcher`/`RuntimeDeathWatcher`:
hilo `daemon` DENTRO del proceso `atlas-forge-api` — necesita `list_agents`
de la `DevelopmentSession` en memoria para mutar `Agent` directamente
(`mark_failed`/`mark_idle`), y la fuente viva de "Jobs en vuelo" del
`DispatchQueueWorker` (`get_inflight_agent_ids`). No bloquea frente al
despacho: cada ciclo solo comprueba y, a lo sumo, libera/redespacha en el
siguiente ciclo de polling normal.
"""

from __future__ import annotations

import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from atlas_forge.agents.lifecycle import mark_failed
from atlas_forge.core.session_lifecycle import list_agents
from atlas_forge.models import DevelopmentSession

# Umbral por defecto de inactividad de `last_command_at` para declarar el
# fallo (segundos). 30 min, mismo horizonte que
# `AGENT_STEP_TIMEOUT_SECONDS` (`job_plan_dispatch.py`): un agente con Job
# legítimo actualiza `last_command_at` al despacharlo; solo alguien cuyo Job
# se perdió queda congelado más allá de este umbral. Configurable vía
# parámetro `threshold_seconds` (criterio 4 de la Task).
DEFAULT_STUCK_WORKING_THRESHOLD_SECONDS = 1800.0

_DEFAULT_POLL_INTERVAL_SECONDS = 30.0

InflightAgentIdsProvider = Callable[[], set[str]]

_STATE_RE = re.compile(r"^state:\s*(.+)$", re.MULTILINE)


def _last_command_timestamp(agent) -> datetime | None:
    """`last_command_at` (ISO 8601 UTC) parseado; `None` si no se declaró o
    no es parseable — el watcher NUNCA libera sin evidencia temporal."""
    raw = getattr(agent, "last_command_at", None) or ""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw))
    except ValueError:
        return None


def _update_task_file_state(tasks_dir: Path, task_id: str, new_state: str) -> None:
    """Reescribe el campo `state:` del fichero real de `task_id` a
    `new_state`, actualizando `updated_at` — mismo criterio que el Dispatcher
    (`dispatch_queue_worker._update_task_file_state`), sin duplicar la lógica
    textual importándola (evita acoplamiento cruzado de módulo)."""
    from atlas_forge.backlog.promote import upsert_updated_at

    candidates = sorted(tasks_dir.glob(f"{task_id}-*.md")) or sorted(
        tasks_dir.glob(f"{task_id}.md")
    )
    task_path = next(iter(candidates), None)
    if task_path is None:
        return
    text = task_path.read_text(encoding="utf-8")
    match = _STATE_RE.search(text)
    if match is None:
        return
    updated = text.replace(f"state: {match.group(1)}", f"state: {new_state}", 1)
    updated = upsert_updated_at(updated)
    task_path.write_text(updated, encoding="utf-8")


def _release_stuck_working_agent(
    agent,
    *,
    project_root: Path | str | None,
    project_name: str | None,
    reason: str,
) -> list[str]:
    """Libera a `agent` marcándolo `failed` (motivo consultable) y devuelve a
    `TO_DEVELOP` la Task asociada (entrada `dispatched` de la cola con su
    `agent_id`), marcando la entrada como `failed` para no dejar residuo
    `dispatched`/`running` (criterio 5 de la US-AF008-18). Devuelve la lista
    de `task_id` devueltos a `TO_DEVELOP`."""
    from atlas_forge.dispatcher.dispatch_queue import (
        STATUS_DISPATCHED,
        get_queue,
        mark_failed as mark_queue_entry_failed,
    )

    task_ids: list[str] = []
    if project_root is not None and project_name is not None:
        for entry in get_queue(project_root, project_name):
            if entry.status != STATUS_DISPATCHED or entry.agent_id != agent.id:
                continue
            mark_queue_entry_failed(project_root, project_name, entry.task_id, result=reason)
            _update_task_file_state(
                Path(project_root) / "02-backlog" / "tasks",
                entry.task_id,
                "TO_DEVELOP",
            )
            task_ids.append(entry.task_id)

    mark_failed(agent, reason)
    return task_ids


def run_stuck_working_cycle(
    session: DevelopmentSession,
    inflight_agent_ids: set[str],
    *,
    project_root: Path | str | None = None,
    project_name: str | None = None,
    threshold_seconds: float = DEFAULT_STUCK_WORKING_THRESHOLD_SECONDS,
    now: datetime | None = None,
) -> list[dict]:
    """Un único ciclo de la regla de auto-liberación:

    Por cada agente `working`:
    - si tiene un Job en vuelo legítimo (`inflight_agent_ids`) -> se EXCLUYE
      (criterio 3: los Jobs reales nunca se liberan).
    - si `last_command_at` es reciente (o no hay señal temporal) -> se deja;
      solo se actúa tras `threshold_seconds` SIN actualizar `last_command_at`.
    - si cumple la condición -> `mark_failed` con motivo consultable + su
      Task (entrada `dispatched` en la cola con ese `agent_id`) vuelve a
      `TO_DEVELOP` (criterio 2), desbloqueando la cola para el siguiente
      ciclo del Dispatcher.

    No bloquea (no espera nada) y nunca toca agentes `idle`/`stopped`/
    `unavailable`/`limited` ni agentes `working` legítimos.

    Devuelve la lista de `{agent_id, task_ids}` liberados este ciclo."""
    if now is None:
        now = datetime.now(timezone.utc)
    released: list[dict] = []

    for agent in list_agents(session):
        if getattr(agent, "status", None) != "working":
            continue
        if agent.id in inflight_agent_ids:
            continue  # Job en vuelo legítimo: no hay falso positivo.
        last = _last_command_timestamp(agent)
        if last is None:
            continue  # sin evidencia temporal -> no se libera.
        if (now - last).total_seconds() < threshold_seconds:
            continue
        reason = (
            f"working sin Job en vuelo: el Job se perdió (huérfano) y sin "
            f"actividad (last_command_at congelado más de "
            f"{threshold_seconds:.0f}s). Liberado a failed y Task a TO_DEVELOP."
        )
        task_ids = _release_stuck_working_agent(
            agent,
            project_root=project_root,
            project_name=project_name,
            reason=reason,
        )
        released.append({"agent_id": agent.id, "task_ids": task_ids})

    return released


class StuckWorkingWatcher:
    """Hilo `daemon` que llama a `run_stuck_working_cycle` cada
    `poll_interval_seconds` mientras esté vivo. Mismo patrón de
    `SessionLimitWatcher`/`RuntimeDeathWatcher`: `start()` no lanza un
    segundo hilo si ya hay uno vivo, y un fallo de un ciclo nunca mata el
    hilo (mejor esfuerzo)."""

    def __init__(
        self,
        session: DevelopmentSession,
        inflight_agent_ids_provider: InflightAgentIdsProvider,
        threshold_seconds: float = DEFAULT_STUCK_WORKING_THRESHOLD_SECONDS,
        poll_interval_seconds: float = _DEFAULT_POLL_INTERVAL_SECONDS,
        project_root: Path | str | None = None,
        project_name: str | None = None,
    ) -> None:
        self._session = session
        self._inflight_provider = inflight_agent_ids_provider
        self._threshold_seconds = threshold_seconds
        self._poll_interval_seconds = poll_interval_seconds
        self._project_root = project_root
        self._project_name = project_name
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def threshold_seconds(self) -> float:
        """Umbral configurado (criterio 4: la regla es configurable)."""
        return self._threshold_seconds

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="stuck-working-watcher"
        )
        self._thread.start()

    def stop(self, timeout: float | None = 2.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def run_once(self) -> list[dict]:
        """Ejecuta un único ciclo de forma síncrona, sin hilo — usado en
        tests deterministas."""
        return run_stuck_working_cycle(
            self._session,
            self._inflight_provider(),
            project_root=self._project_root,
            project_name=self._project_name,
            threshold_seconds=self._threshold_seconds,
        )

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                run_stuck_working_cycle(
                    self._session,
                    self._inflight_provider(),
                    project_root=self._project_root,
                    project_name=self._project_name,
                    threshold_seconds=self._threshold_seconds,
                )
            except Exception:
                # Mismo criterio de "mejor esfuerzo" que el resto de watchers:
                # un fallo inesperado de un ciclo no debe matar el hilo.
                pass
            self._stop_event.wait(self._poll_interval_seconds)