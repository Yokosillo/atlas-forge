"""Empaquetado de entrada y construcción de instrucción para el Job del
Tester (T-FB022-US12-01, T-FB022-US12-02).

El Tester recibe: código tocado por el Developer, criterios de aceptación
de la Task/US, e informe de cierre del Developer — nunca el Epic completo.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from brain.dispatcher.job_report import read_job_report

_TASKS_DIRNAME = "02-backlog/tasks"


def _default_reports_root() -> Path:
    return Path(__file__).resolve().parents[4] / "07-informes"


def _default_tasks_dir() -> Path:
    return Path(__file__).resolve().parents[4] / _TASKS_DIRNAME


def read_acceptance_criteria(
    story_id: str,
    tasks_dir: Path | None = None,
) -> list[tuple[str, str]]:
    """Lee los criterios de aceptación de todas las Tasks de `story_id`.

    Devuelve una lista de tuplas `(task_id, criteria_text)` — una por cada
    fichero de Task que tenga sección '## Criterios de aceptación'. Si no
    hay Tasks o ninguna declara criterios, devuelve lista vacía — nunca
    lanza excepción no controlada.
    """
    root = tasks_dir if tasks_dir else _default_tasks_dir()
    if not root.is_dir():
        return []

    prefix = f"T-{story_id}-"
    results: list[tuple[str, str]] = []

    for task_path in sorted(root.glob(f"{prefix}*.md")):
        task_id = task_path.stem
        try:
            text = task_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        criteria = _extract_acceptance_criteria(text)
        if criteria:
            results.append((task_id, criteria))

    return results


def _extract_acceptance_criteria(task_text: str) -> str:
    """Extrae la sección '## Criterios de aceptación' del texto de una
    Task. Devuelve el texto de los criterios tal cual, sin el encabezado,
    o cadena vacía si no se encuentra."""
    match = re.search(
        r"##\s*Criterios de aceptación\s*\n+(.+?)(?=\n##\s|\Z)",
        task_text,
        re.DOTALL,
    )
    if not match:
        return ""
    return match.group(1).strip()


def collect_developer_code_diff(project_path: str | Path) -> str:
    """Obtiene el diff de los cambios del Developer (`git diff`) desde el
    repositorio `project_path`.

    En fase v1, el diff captura cambios unstaged+staged no commiteados
    (mismo comportamiento que `git diff HEAD` en un repo con cambios
    locales) — no incluye la historia completa del repo, solo lo tocado
    por el Developer en esta sesión de trabajo.

    Si el proyecto no es un repositorio git o no tiene cambios, devuelve
    cadena vacía — nunca lanza excepción no controlada.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(project_path), "diff", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout if result.returncode in (0, 1) else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def collect_changed_files(project_path: str | Path) -> list[str]:
    """Lista los ficheros tocados por el Developer (`git diff --name-only`)
    — más ligero que el diff completo, útil como índice de lo afectado."""
    try:
        result = subprocess.run(
            ["git", "-C", str(project_path), "diff", "HEAD", "--name-only"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode not in (0, 1):
            return []
        return [f for f in result.stdout.strip().split("\n") if f]
    except (OSError, subprocess.TimeoutExpired):
        return []


def build_tester_input_package(
    story_id: str,
    developer_job_id: str,
    project_path: str | Path,
    reports_root: Path | None = None,
    tasks_dir: Path | None = None,
) -> dict:
    """Construye el paquete de entrada del Tester como diccionario
    estructurado (T-FB022-US12-01): código tocado, criterios de aceptación
    e informe del Developer. El Epic completo NO se incluye."""

    code_diff = collect_developer_code_diff(project_path)
    changed_files = collect_changed_files(project_path)
    acceptance_criteria = read_acceptance_criteria(story_id, tasks_dir)
    developer_report = read_job_report(
        story_id, developer_job_id, reports_root=reports_root
    )

    return {
        "story_id": story_id,
        "developer_job_id": developer_job_id,
        "code_diff": code_diff,
        "changed_files": changed_files,
        "acceptance_criteria": acceptance_criteria,
        "developer_report": developer_report or "(informe no disponible)",
    }


def build_tester_job_description(
    story_id: str,
    developer_job_id: str,
    project_path: str | Path,
    reports_root: Path | None = None,
    tasks_dir: Path | None = None,
) -> str:
    """Construye la descripción completa del Job del Tester (T-FB022-US12-01
    + T-FB022-US12-02): empaqueta la entrada Y la instrucción de análisis
    de huecos y generación de tests.

    El Tester recibe:
    1. Datos de entrada (código, criterios, informe del Developer)
    2. Instrucción de analizar huecos de cobertura reales
    3. Instrucción de generar tests nuevos que NO dupliquen los ya
       ejecutados por el Developer (extraídos de su informe)
    4. Instrucción de reporte estructurado"""
    pkg = build_tester_input_package(
        story_id, developer_job_id, project_path,
        reports_root=reports_root, tasks_dir=tasks_dir,
    )

    acceptance_text = _format_acceptance_criteria(pkg["acceptance_criteria"])
    report_text = pkg["developer_report"]
    diff_text = pkg["code_diff"] or "(sin diff disponible — no hay cambios sin commitear)"
    files_list = "\n".join(f"  - {f}" for f in pkg["changed_files"]) or "(ninguno)"

    return (
        f"Eres el Tester del pipeline de Factory Brain. Tu responsabilidad "
        f"es verificar el trabajo del Developer para la User Story "
        f"'{story_id}' generando tests adicionales que cubran huecos de "
        f"cobertura reales.\n"
        f"\n"
        f"## Datos de entrada\n"
        f"\n"
        f"### Ficheros tocados por el Developer\n"
        f"{files_list}\n"
        f"\n"
        f"### Diff del código implementado\n"
        f"```\n"
        f"{diff_text}\n"
        f"```\n"
        f"\n"
        f"### Criterios de aceptación de las Tasks\n"
        f"{acceptance_text}\n"
        f"\n"
        f"### Informe de cierre del Developer\n"
        f"{report_text}\n"
        f"\n"
        f"## Instrucciones\n"
        f"\n"
        f"1. Analiza el diff, los criterios de aceptación y el informe del "
        f"Developer para identificar huecos de cobertura concretos — "
        f"casos no probados, caminos no cubiertos, condiciones de borde "
        f"omitidas.\n"
        f"2. NO dupliques tests que el Developer ya ejecutó y reportó en "
        f"su informe — enfócate solo en lo que falta.\n"
        f"3. Genera código de tests nuevos que cubran esos huecos. Escribe "
        f"los tests en ficheros reales dentro del proyecto.\n"
        f"4. Al terminar, redacta tu informe estructurado con estas "
        f"secciones:\n"
        f"   - Huecos de cobertura detectados: lista concreta de casos que "
        f"el Developer no cubrió.\n"
        f"   - Tests generados: descripción de cada test nuevo, qué cubre "
        f"y en qué fichero se escribió.\n"
        f"   - Resultado de ejecución: informa si pudiste ejecutarlos. Si "
        f"el script 'run_tests' del catálogo genérico está disponible, "
        f"invócalo y documenta el resultado real (pasa/falla por test)."
    )


def _format_acceptance_criteria(
    criteria: list[tuple[str, str]],
) -> str:
    if not criteria:
        return "(no se encontraron criterios de aceptación en las Tasks)"
    parts: list[str] = []
    for task_id, text in criteria:
        parts.append(f"**{task_id}**:\n{text}")
    return "\n\n".join(parts)
