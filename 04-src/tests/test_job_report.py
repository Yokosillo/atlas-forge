"""Tests para el módulo de informes de cierre de Job (T-AF022-US06-03,
T-AF022-US06-04)."""

import threading
import uuid
from pathlib import Path

from atlas_forge.dispatcher.job_report import read_job_report, write_job_report
from atlas_forge.models import Job


def test_write_job_report_creates_file_in_story_dir(tmp_path) -> None:
    job = Job(
        id="job-001",
        session_id="s1",
        agent_id="dev-1",
        description="Implementar algo",
        status="completed",
        result="Tests pasan, código listo.",
        story_id="US-AF022-06",
    )

    path = write_job_report(job, reports_root=tmp_path)

    assert path.exists()
    assert path.parent.name == "US-AF022-06"
    content = path.read_text()
    assert "US-AF022-06" in content
    assert "Tests pasan, código listo." in content
    assert "completed" in content


def test_write_job_report_handles_failed_job(tmp_path) -> None:
    job = Job(
        id="job-002",
        session_id="s1",
        agent_id="dev-1",
        description="Implementar algo",
        status="failed",
        result="Timeout esperando reporte",
        story_id="US-AF022-06",
    )

    path = write_job_report(job, reports_root=tmp_path)

    assert path.exists()
    content = path.read_text()
    assert "failed" in content
    assert "Timeout esperando reporte" in content


def test_write_job_report_creates_story_dir_if_missing(tmp_path) -> None:
    job = Job(
        id="job-003",
        session_id="s1",
        agent_id="dev-1",
        description="x",
        status="completed",
        result="ok",
        story_id="US-AF999-99",
    )

    path = write_job_report(job, reports_root=tmp_path)

    assert path.parent.exists()
    assert path.parent.name == "US-AF999-99"


def test_write_job_report_does_not_overwrite_different_job(tmp_path) -> None:
    job_a = Job(
        id="job-a",
        session_id="s1",
        agent_id="dev-1",
        description="x",
        status="completed",
        result="resultado A",
        story_id="US-AF022-06",
    )
    job_b = Job(
        id="job-b",
        session_id="s1",
        agent_id="dev-2",
        description="y",
        status="completed",
        result="resultado B",
        story_id="US-AF022-06",
    )

    write_job_report(job_a, reports_root=tmp_path)
    write_job_report(job_b, reports_root=tmp_path)

    content_a = (tmp_path / "US-AF022-06" / "job-a.md").read_text()
    content_b = (tmp_path / "US-AF022-06" / "job-b.md").read_text()

    assert "resultado A" in content_a
    assert "resultado B" in content_b
    assert "resultado B" not in content_a
    assert "resultado A" not in content_b


def test_write_job_report_falls_back_to_sin_story_when_story_id_empty(tmp_path) -> None:
    job = Job(
        id="job-no-story",
        session_id="s1",
        agent_id="dev-1",
        description="x",
        status="completed",
        result="ok",
        story_id="",
    )

    path = write_job_report(job, reports_root=tmp_path)

    assert path.parent.name == "_sin-story"
    assert path.exists()


def test_read_job_report_returns_none_for_missing_file(tmp_path) -> None:
    result = read_job_report("US-AF999-99", "nonexistent", reports_root=tmp_path)
    assert result is None


def test_read_job_report_returns_content_for_existing_file(tmp_path) -> None:
    job = Job(
        id="job-read-test",
        session_id="s1",
        agent_id="dev-1",
        description="x",
        status="completed",
        result="contenido de prueba",
        story_id="US-AF022-06",
    )
    write_job_report(job, reports_root=tmp_path)

    content = read_job_report("US-AF022-06", "job-read-test", reports_root=tmp_path)

    assert content is not None
    assert "contenido de prueba" in content


def test_concurrent_writes_do_not_collide(tmp_path) -> None:
    """T-AF022-US06-04: dos Developer completándose en ventana solapada no
    colisionan al escribir sus informes — ambos informes quedan íntegros."""
    jobs = [
        Job(
            id=f"job-concurrent-{i}",
            session_id="s1",
            agent_id=f"dev-{i}",
            description=f"tarea {i}",
            status="completed",
            result=f"resultado completo {i}",
            story_id="US-AF022-06",
        )
        for i in range(2)
    ]

    results: list[Path] = []
    errors: list[Exception] = []

    def _write(job):
        try:
            p = write_job_report(job, reports_root=tmp_path)
            results.append(p)
        except Exception as e:
            errors.append(e)

    t0 = threading.Thread(target=_write, args=(jobs[0],))
    t1 = threading.Thread(target=_write, args=(jobs[1],))
    t0.start()
    t1.start()
    t0.join()
    t1.join()

    assert len(errors) == 0, f"Errores en escritura concurrente: {errors}"
    assert len(results) == 2

    for i, job in enumerate(jobs):
        report_path = tmp_path / "US-AF022-06" / f"{job.id}.md"
        assert report_path.exists(), f"Informe {job.id} no existe"
        content = report_path.read_text()
        assert job.result in content, f"Contenido incompleto para {job.id}"
