"""Escritura de informes de cierre de Job en `07-informes/<US-id>/<job_id>.md`
(T-FB022-US06-03): cada Job de Developer (y en el futuro, de Tester)
persiste su informe en una ubicación canónica y versionada, nunca en
`.claude/state/`. Un `job_id` pertenece siempre a una User Story concreta.
"""

from __future__ import annotations

from pathlib import Path

from brain.models import Job

_REPORTS_DIRNAME = "07-informes"


def _default_reports_root() -> Path:
    return Path(__file__).resolve().parents[4] / _REPORTS_DIRNAME


def write_job_report(
    job: Job,
    reports_root: Path | str | None = None,
) -> Path:
    """Escribe el informe de cierre de `job` en
    `07-informes/<story_id>/<job.id>.md`, creando el directorio de la
    User Story si no existe.

    Formato: mismo nivel de detalle que `worker_output.txt` hoy (resumen,
    ficheros afectados, tests, notas). Legible tanto por humano como por
    el Job de veredicto (T-FB022-US05-02).

    Si `job.story_id` está vacío, el informe se escribe en
    `07-informes/_sin-story/<job.id>.md` para no perder el registro.
    """
    root = Path(reports_root) if reports_root else _default_reports_root()
    story_dirname = job.story_id if job.story_id else "_sin-story"
    story_dir = root / story_dirname
    story_dir.mkdir(parents=True, exist_ok=True)

    report_path = story_dir / f"{job.id}.md"
    report_path.write_text(
        _format_report_content(job),
        encoding="utf-8",
    )
    return report_path


def _format_report_content(job: Job) -> str:
    return (
        f"# Informe de cierre · Job {job.id}\n"
        f"\n"
        f"User Story: {job.story_id or '(no especificada)'}\n"
        f"Agente: {job.agent_id}\n"
        f"Estado final: {job.status}\n"
        f"\n"
        f"## Resultado\n"
        f"\n"
        f"{job.result or '(sin resultado registrado)'}\n"
    )


def read_job_report(
    story_id: str,
    job_id: str,
    reports_root: Path | str | None = None,
) -> str | None:
    """Lee el informe de cierre de `job_id` dentro de `story_id`. Devuelve
    `None` si el fichero no existe."""
    root = Path(reports_root) if reports_root else _default_reports_root()
    report_path = root / story_id / f"{job_id}.md"
    try:
        return report_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
