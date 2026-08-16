"""Tests de T-FB030-US02-01: cola append-only de cierres de Task por
proyecto (`brain.dispatcher.architect_queue`)."""

import json
import shutil
import threading
import time
from pathlib import Path

import pytest

from brain.dispatcher.architect_queue import (
    append_to_architect_queue,
    architect_queue_path,
    launch_architect_queue_watcher,
    read_architect_queue,
)


def test_append_creates_the_file_and_directory_if_they_do_not_exist(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "some-project"

    path = append_to_architect_queue(
        project_root,
        "some-project",
        agente="developer",
        task_id="T-FB030-US02-01",
        informe="07-informes/US-FB030-02/job-1.md",
    )

    assert path.is_file()
    assert path == project_root / ".claude" / "state" / "some-project" / "architect_queue.jsonl"


def test_each_line_is_a_standalone_valid_json_object_not_a_single_array(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "proj"

    append_to_architect_queue(
        project_root, "proj", agente="developer", task_id="T-1", informe="a.md",
        ts="2026-08-14T10:00:00+00:00",
    )
    append_to_architect_queue(
        project_root, "proj", agente="developer", task_id="T-2", informe="b.md",
        ts="2026-08-14T10:05:00+00:00",
    )

    path = architect_queue_path(project_root, "proj")
    lines = path.read_text(encoding="utf-8").splitlines()

    assert len(lines) == 2
    for line in lines:
        # Cada linea es un objeto JSON completo por si misma (JSONL) — un
        # unico array englobando todo el fichero fallaria aqui, porque
        # cada linea individual no seria JSON valido por separado.
        parsed = json.loads(line)
        assert isinstance(parsed, dict)

    first = json.loads(lines[0])
    assert first == {
        "agente": "developer",
        "task_id": "T-1",
        "informe": "a.md",
        "ts": "2026-08-14T10:00:00+00:00",
    }


def test_entry_includes_agente_task_id_informe_and_ts(tmp_path: Path) -> None:
    project_root = tmp_path / "proj"

    append_to_architect_queue(
        project_root,
        "proj",
        agente="arquitecto",
        task_id="T-FB030-US02-02",
        informe="07-informes/US-FB030-02/job-2.md",
        ts="2026-08-14T12:00:00+00:00",
    )

    entries = read_architect_queue(project_root, "proj")
    assert len(entries) == 1
    assert entries[0] == {
        "agente": "arquitecto",
        "task_id": "T-FB030-US02-02",
        "informe": "07-informes/US-FB030-02/job-2.md",
        "ts": "2026-08-14T12:00:00+00:00",
    }


def test_ts_defaults_to_now_when_not_given(tmp_path: Path) -> None:
    project_root = tmp_path / "proj"

    append_to_architect_queue(
        project_root, "proj", agente="developer", task_id="T-1", informe="a.md"
    )

    entries = read_architect_queue(project_root, "proj")
    assert entries[0]["ts"]  # no vacio: se resolvio un timestamp real


def test_queue_of_one_project_never_written_under_another_projects_path(
    tmp_path: Path,
) -> None:
    root_a = tmp_path / "project-a"
    root_b = tmp_path / "project-b"

    append_to_architect_queue(
        root_a, "project-a", agente="developer", task_id="T-A", informe="a.md"
    )
    append_to_architect_queue(
        root_b, "project-b", agente="developer", task_id="T-B", informe="b.md"
    )

    entries_a = read_architect_queue(root_a, "project-a")
    entries_b = read_architect_queue(root_b, "project-b")

    assert [e["task_id"] for e in entries_a] == ["T-A"]
    assert [e["task_id"] for e in entries_b] == ["T-B"]
    # Los ficheros fisicos viven bajo raices distintas, sin cruzarse.
    path_a = architect_queue_path(root_a, "project-a")
    path_b = architect_queue_path(root_b, "project-b")
    assert root_b not in path_a.parents
    assert root_a not in path_b.parents


def test_read_architect_queue_returns_empty_list_when_file_does_not_exist(
    tmp_path: Path,
) -> None:
    assert read_architect_queue(tmp_path / "never-written", "proj") == []


def test_concurrent_writes_from_multiple_threads_lose_no_line(tmp_path: Path) -> None:
    project_root = tmp_path / "proj"
    writer_count = 20

    def _write(index: int) -> None:
        append_to_architect_queue(
            project_root,
            "proj",
            agente="developer",
            task_id=f"T-{index}",
            informe=f"{index}.md",
            ts=f"2026-08-14T10:{index:02d}:00+00:00",
        )

    threads = [threading.Thread(target=_write, args=(i,)) for i in range(writer_count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    entries = read_architect_queue(project_root, "proj")
    assert len(entries) == writer_count
    assert {e["task_id"] for e in entries} == {f"T-{i}" for i in range(writer_count)}


def _write_from_subprocess(project_root: str, index: int) -> None:
    """Target de `multiprocessing.Process` — debe ser importable a nivel de
    módulo (no una closure/lambda) para que `spawn`/`fork` puedan
    localizarla en el proceso hijo."""
    from brain.dispatcher.architect_queue import append_to_architect_queue

    append_to_architect_queue(
        project_root,
        "proj",
        agente="developer",
        task_id=f"T-proc-{index}",
        informe=f"{index}.md",
        ts=f"2026-08-14T11:{index:02d}:00+00:00",
    )


def test_concurrent_writes_from_multiple_processes_lose_no_line(
    tmp_path: Path,
) -> None:
    import multiprocessing

    project_root = tmp_path / "proj"
    writer_count = 8

    ctx = multiprocessing.get_context("fork")
    processes = [
        ctx.Process(target=_write_from_subprocess, args=(str(project_root), i))
        for i in range(writer_count)
    ]
    for p in processes:
        p.start()
    for p in processes:
        p.join(timeout=30)
        assert p.exitcode == 0

    entries = read_architect_queue(project_root, "proj")
    assert len(entries) == writer_count
    assert {e["task_id"] for e in entries} == {
        f"T-proc-{i}" for i in range(writer_count)
    }
    # Cada linea sigue siendo JSON valido por separado — ningun escritor
    # concurrente trunco o intercalo la escritura de otro.
    path = architect_queue_path(project_root, "proj")
    for line in path.read_text(encoding="utf-8").splitlines():
        json.loads(line)


# T-FB030-US03-04: lanzamiento automático de architect_queue_watcher.sh
# (antes solo lanzable a mano). `tmux`/`inotifywait` reales, sin mocks —
# el propio incidente motivador (07-informes/incidente-arquitecto-perdido-
# tras-reinicio-2026-08-16.md) fue indetectable solo con lectura de
# código, así que el criterio de aceptación 5 exige verificación real, no
# solo comprobar que se invoca subprocess.Popen con los argumentos
# correctos.
_HAS_WATCHER_DEPS = shutil.which("inotifywait") is not None and shutil.which("tmux") is not None


def _kill_watcher_tree(proc) -> None:
    if proc is None:
        return
    try:
        import os
        import signal

        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    proc.wait(timeout=5)


@pytest.mark.skipif(not _HAS_WATCHER_DEPS, reason="requiere inotifywait y tmux instalados")
def test_launch_architect_queue_watcher_starts_a_live_process(tmp_path: Path) -> None:
    project_root = tmp_path / "proj"
    project_root.mkdir()

    proc = launch_architect_queue_watcher(str(project_root), "watchtest")
    try:
        time.sleep(1)
        assert proc is not None
        assert proc.poll() is None  # sigue vivo, no ha terminado

        log_path = (
            project_root / ".claude" / "state" / "watchtest" / "logs"
            / "architect_queue_watcher.log"
        )
        assert log_path.is_file()
        assert "arrancado" in log_path.read_text(encoding="utf-8")
    finally:
        _kill_watcher_tree(proc)


@pytest.mark.skipif(not _HAS_WATCHER_DEPS, reason="requiere inotifywait y tmux instalados")
def test_launch_architect_queue_watcher_does_not_duplicate_on_relaunch(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "proj"
    project_root.mkdir()

    first = launch_architect_queue_watcher(str(project_root), "watchtest2")
    try:
        time.sleep(1)
        second = launch_architect_queue_watcher(str(project_root), "watchtest2")
        assert second is None
    finally:
        _kill_watcher_tree(first)


@pytest.mark.skipif(not _HAS_WATCHER_DEPS, reason="requiere inotifywait y tmux instalados")
def test_watcher_pushes_to_the_real_architect_tmux_session_when_a_task_closes(
    tmp_path: Path,
) -> None:
    """Criterio de aceptación 2/5: reproduce el flujo real completo —
    sesión tmux del Arquitecto viva, watcher lanzado automáticamente,
    cierre de una Task real (append_to_architect_queue) — y confirma que
    el push (tmux send-keys) llega de verdad al pane, leyendo su
    contenido con capture-pane. Nada de esto se puede verificar solo
    leyendo código (mismo motivo que el incidente que motivó esta Task)."""
    import subprocess

    project_root = tmp_path / "proj"
    project_root.mkdir()
    project_name = "watchtest3"
    session_name = f"arquitecto-{project_name}"

    # tmux CLI directo (no libtmux) para crear/leer/matar la sesión: el
    # propio script bajo prueba (architect_queue_watcher.sh) también
    # invoca tmux por CLI, así que este test verifica exactamente el
    # mismo mecanismo real, sin intermediar un wrapper Python con su
    # propio comportamiento de caché entre lecturas.
    subprocess.run(["tmux", "kill-session", "-t", session_name], capture_output=True)
    subprocess.run(
        ["tmux", "new-session", "-d", "-s", session_name], check=True
    )
    try:
        proc = launch_architect_queue_watcher(str(project_root), project_name)
        try:
            time.sleep(1)

            append_to_architect_queue(
                project_root,
                project_name,
                agente="developer",
                task_id="T-FB030-US03-04",
                informe="07-informes/FB030-US03/FB030-US03.md#T-FB030-US03-04",
            )

            deadline = time.monotonic() + 10
            content = ""
            while time.monotonic() < deadline:
                result = subprocess.run(
                    ["tmux", "capture-pane", "-p", "-t", session_name],
                    capture_output=True,
                    text=True,
                )
                content = result.stdout
                if "cola de cierres pendientes" in content:
                    break
                time.sleep(0.3)

            assert "cola de cierres pendientes" in content
        finally:
            _kill_watcher_tree(proc)
    finally:
        subprocess.run(["tmux", "kill-session", "-t", session_name], capture_output=True)
