"""Acciones transversales de proyecto (FB-025): lógica de dominio para
despachar Jobs a agentes, ejecutar scripts deterministas e invocar Scribe
desde un único punto de entrada (`POST /project/actions/{action_id}`).

Cada acción es atómica: el endpoint HTTP la recibe, resuelve el agente o
script correspondiente, y devuelve el resultado cuando termina (bloqueante,
mismo criterio que `POST /jobs`). La persistencia del informe en
`07-informes/` se hace aquí (no en la capa HTTP), igual que el resto del
pipeline lo hace en `dispatch_plan`.

Acciones definidas:
  - `documentar`       → despacha Job al Arquitecto (US-FB025-01, Hilo 3)
  - `analizar-arquitectura` → despacha Job al Arquitecto (US-FB025-02, Hilo 3)
  - `sugerir-ideas`    → despacha Job al Arquitecto (US-FB025-03, Hilo 3)
  - `testear`          → ejecuta `pytest` determinista (US-FB025-04, Hilo 3)
  - `auditar-ux`       → opencode run --auto headless (US-FB025-06, Hilo 4)
  - `indexar`          → Scribe index_documents (US-FB025-07, Hilo 4)
"""

from __future__ import annotations

import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from brain.agents.arquitecto import ARQUITECTO_ROLE
from brain.core.session_lifecycle import list_agents
from brain.core.session_registry import get_current_session
from brain.dispatcher.job_creation import create_job
from brain.dispatcher.job_dispatch import dispatch_job
from brain.dispatcher.job_history_registry import record_job
from brain.dispatcher.job_lifecycle import mark_completed, mark_failed, mark_running
from brain.dispatcher.job_orchestration import create_and_record_job
from brain.dispatcher.job_report import write_job_report
from brain.models import Agent, Job
from brain.runtime.agent_runtime_registry import get_runtime_instance_for_agent
from brain.workspace.active_project import (
    ProjectNotDiscoveredError,
    get_active_project,
)
from brain.workspace.generic_scripts import _run_project_tests
from brain.local_tools import ScribeUnavailableError, index_documents

_ACTION_DESCRIPTIONS: dict[str, str] = {
    "documentar": (
        "Documenta el proyecto completo. Compara el contenido de "
        "`01-documentacion/` contra el código real del repositorio. Detecta "
        "documentación obsoleta, ausente o inconsistente con la "
        "implementación real. Tu salida es una propuesta de cambios "
        "concreta con ficheros afectados y el texto sugerido para cada "
        "uno — no escribas directamente los ficheros de documentación, "
        "solo presenta la propuesta. Cita evidencia de código real para "
        "cada hallazgo (nombres de fichero, funciones, clases).\n\n"
        "Al terminar, escribe tu resultado completo en el fichero de "
        "reporte indicado."
    ),
    "analizar-arquitectura": (
        "Analiza la arquitectura del proyecto con evidencia de código "
        "real, sin supuestos. Sigue el mismo rigor que los análisis "
        "manuales previos en `07-informes/`. Tu informe debe cubrir:\n"
        "1. Estado real del código módulo por módulo (qué hay implementado "
        "y qué no).\n"
        "2. Deuda técnica detectada con ficheros y líneas concretas.\n"
        "3. Inconsistencias entre la documentación (`01-documentacion/`) y "
        "el código real.\n"
        "4. Recomendaciones priorizadas.\n\n"
        "No escribas a `02-backlog/` — tu salida es un informe para que el "
        "humano decida. Cita ficheros y fragmentos de código real para "
        "cada afirmación. Al terminar, escribe tu resultado completo en el "
        "fichero de reporte indicado."
    ),
    "sugerir-ideas": (
        "Analiza el estado actual del proyecto (backlog en `02-backlog/`, "
        "código en `04-src/`, informes recientes en `07-informes/`, "
        "documentación en `01-documentacion/`) y propón ideas candidatas "
        "de Epics o User Stories nuevas que podrían añadir valor.\n\n"
        "Tu salida debe ser una lista informal con:\n"
        "- Título descriptivo de cada idea.\n"
        "- Justificación breve (1-3 frases) de por qué aporta valor.\n"
        "- Área del proyecto a la que pertenece.\n\n"
        "NO escribas ficheros con formato estándar de backlog — esta salida "
        "es solo una propuesta para que el humano decida cuáles llevar al "
        "Arquitecto para aterrizarlas formalmente. Nada se escribe a "
        "`02-backlog/` como resultado directo. Al terminar, escribe tu "
        "resultado completo en el fichero de reporte indicado."
    ),
    "auditar-ux": (
        "Audita la interfaz web de Factory Brain siguiendo el rol y "
        "método definidos en `00-gobierno/UX.md`. "
        "Tu objetivo es evaluar `10-web/` como lo haría un desarrollador "
        "real, encontrando fricciones concretas con evidencia.\n\n"
        "Escribe tu informe completo en el fichero de reporte indicado al "
        "final de tu auditoría. No crees ficheros en 02-backlog/."
    ),
    "indexar": (
        "Indexa el proyecto para búsqueda rápida vía Scribe (modelo local "
        "Ollama). "
        "Recolecta ficheros de documentación, backlog y código fuente "
        "relevantes y genera un índice temático accesible por Developer "
        "y Arquitecto."
    ),
}

_REPORTS_DIRNAME = "07-informes"


def _find_agent_by_role(role: str) -> Agent | None:
    session = get_current_session()
    if session is None:
        return None
    return next(
        (
            agent
            for agent in list_agents(session)
            if isinstance(agent, Agent) and agent.role == role
        ),
        None,
    )


def _default_reports_root() -> Path:
    return Path(__file__).resolve().parents[4] / _REPORTS_DIRNAME


def _dispatch_agent_action(
    action_id: str,
    agent: Agent,
    socket_name: str,
) -> Job:
    description = _ACTION_DESCRIPTIONS.get(action_id)
    if description is None:
        raise ValueError(
            f"La acción '{action_id}' no tiene una descripción definida."
        )

    session = get_current_session()
    if session is None:
        raise RuntimeError("No hay ninguna sesión de desarrollo activa.")

    job = create_and_record_job(description, agent, session)

    runtime_instance = get_runtime_instance_for_agent(agent.id)
    if runtime_instance is None:
        raise RuntimeError(
            f"El agente '{agent.name}' no tiene un runtime registrado."
        )

    dispatch_job(job, agent, runtime_instance, socket_name=socket_name)

    _persist_action_report(action_id, job)

    return job


_STORY_ID_MAP = {
    "documentar": "US-FB025-01",
    "analizar-arquitectura": "US-FB025-02",
    "sugerir-ideas": "US-FB025-03",
    "testear": "US-FB025-04",
    "auditar-ux": "US-FB025-06",
    "indexar": "US-FB025-07",
}


def _persist_action_report(action_id: str, job: Job) -> Path:
    """Persiste el informe de cierre del Job en
    `07-informes/US-FB025-XX/<job.id>.md`, reutilizando el mismo mecanismo
    que `write_job_report` pero con un `story_id` específico de la acción
    (no `_sin-story`)."""
    job.story_id = _STORY_ID_MAP.get(action_id, f"FB-025-{action_id}")
    return write_job_report(job, reports_root=_default_reports_root())


class ActionType:
    DOCUMENTAR = "documentar"
    ANALIZAR_ARQUITECTURA = "analizar-arquitectura"
    SUGERIR_IDEAS = "sugerir-ideas"
    TESTEAR = "testear"
    AUDITAR_UX = "auditar-ux"
    INDEXAR = "indexar"


ACCIONES_DISPONIBLES: tuple[str, ...] = (
    ActionType.DOCUMENTAR,
    ActionType.ANALIZAR_ARQUITECTURA,
    ActionType.SUGERIR_IDEAS,
    ActionType.TESTEAR,
    ActionType.AUDITAR_UX,
    ActionType.INDEXAR,
)


def dispatch_action(action_id: str, socket_name: str = "default") -> dict:
    """Despacha una acción transversal de proyecto.

    Para acciones que requieren agente (`documentar`, `analizar-arquitectura`,
    `sugerir-ideas`): encuentra el Arquitecto en la sesión activa, crea y
    despacha un Job con la descripción predefinida, y persiste el informe
    en `07-informes/`.

    Para `testear`: ejecuta la suite de tests del proyecto de forma
    determinista (sin LLM), y persiste el resultado en `07-informes/`.

    Para `auditar-ux`: lanza opencode run --auto en modo headless (sin tmux,
    T-FB025-US06-01), crea un Job de registro y persiste el informe con
    timestamp en `07-informes/US-FB025-06/` (T-FB025-US06-02).

    Para `indexar`: recolecta ficheros del proyecto y genera un índice
    temático vía Scribe (modelo local Ollama, T-FB025-US07-01), sin gastar
    tokens de los agentes principales.

    Devuelve un dict con el resultado de la acción."""
    if action_id == ActionType.TESTEAR:
        return _dispatch_test_action()

    if action_id == ActionType.AUDITAR_UX:
        return _dispatch_audit_ux_action()

    if action_id == ActionType.INDEXAR:
        return _dispatch_index_action()

    if action_id not in _ACTION_DESCRIPTIONS:
        raise ValueError(f"Acción desconocida: '{action_id}'.")

    agent = _find_agent_by_role(ARQUITECTO_ROLE)
    if agent is None:
        raise RuntimeError(
            "No hay ningún agente Arquitecto en la sesión activa. "
            "Lanza un Arquitecto antes de ejecutar esta acción."
        )

    job = _dispatch_agent_action(action_id, agent, socket_name)

    return {
        "action": action_id,
        "job_id": job.id,
        "status": job.status,
        "result": job.result,
    }


def _dispatch_test_action() -> dict:
    project = get_active_project()
    if project is None:
        raise ProjectNotDiscoveredError("No hay ningún proyecto activo.")

    result = _run_project_tests(project.path)

    story_id = "US-FB025-04"
    root = _default_reports_root()
    story_dir = root / story_id
    story_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%S")
    ts_path = story_dir / f"testear-{ts}.md"
    report = (
        f"# Informe de acción · testear\n\n"
        f"Fecha: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        f"Proyecto: {project.name}\n"
        f"Éxito: {'sí' if result.success else 'no'}\n"
    )
    if result.exit_code is not None:
        report += f"Exit code: {result.exit_code}\n"
    report += "\n## Salida\n\n"
    report += f"```\n{result.stdout}\n```\n"
    if result.stderr:
        report += f"\n### Stderr\n\n```\n{result.stderr}\n```\n"
    if result.error_message:
        report += f"\n### Error\n\n{result.error_message}\n"
    ts_path.write_text(report, encoding="utf-8")

    return {
        "action": "testear",
        "success": result.success,
        "exit_code": result.exit_code,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "error_message": result.error_message,
    }


_UX_AUDIT_TIMEOUT_SECONDS = 600
_INDEX_MAX_FILE_SIZE_BYTES = 50_000
_INDEX_MAX_FILES = 100
_INDEX_DIRS = ("01-documentacion", "02-backlog", "04-src", "00-gobierno")


def _dispatch_audit_ux_action() -> dict:
    """Lanza una auditoría UX headless con opencode run --auto (sin tmux,
    T-FB025-US06-01). Crea un Job de registro y persiste el informe con
    timestamp en `07-informes/US-FB025-06/` (T-FB025-US06-02: dos
    ejecuciones en fechas distintas producen ficheros distintos)."""
    project = get_active_project()
    if project is None:
        raise ProjectNotDiscoveredError("No hay ningún proyecto activo.")

    ux_path = Path(project.path) / "00-gobierno" / "UX.md"
    if not ux_path.is_file():
        raise RuntimeError(
            f"No se encontró el fichero de auditoría UX en '{ux_path}'. "
            "Asegúrate de que el proyecto activo es PROD-006-factory-brain."
        )

    ux_content = ux_path.read_text(encoding="utf-8")

    session = get_current_session()
    job_id = str(uuid.uuid4())

    job = Job(
        id=job_id,
        session_id=session.id if session else "_headless",
        agent_id="headless-ux-auditor",
        description="Auditoría UX de la interfaz web (headless, opencode run --auto)",
    )

    if session is not None:
        record_job(session.id, job)

    mark_running(job)

    prompt = (
        f"Eres el Auditor UX+Producto definido a continuación. Ejecuta tu "
        f"auditoría siguiendo exactamente el método y formato descritos. "
        f"Navega la web real, no solo leas el código.\n\n{ux_content}"
    )

    try:
        result = subprocess.run(
            ["opencode", "run", "--auto", prompt],
            cwd=project.path,
            capture_output=True,
            text=True,
            timeout=_UX_AUDIT_TIMEOUT_SECONDS,
        )
        output = result.stdout + "\n" + result.stderr
        if result.returncode != 0:
            error_msg = (
                f"opencode run --auto exited with code {result.returncode}\n\n"
                f"{output[:5000]}"
            )
            mark_failed(job, error_msg)
        else:
            mark_completed(job, output[:10_000])
    except subprocess.TimeoutExpired:
        mark_failed(
            job,
            f"La auditoría UX excedió el tiempo máximo de espera "
            f"({_UX_AUDIT_TIMEOUT_SECONDS}s).",
        )
    except FileNotFoundError:
        mark_failed(
            job,
            "No se encontró el comando 'opencode' en el PATH. "
            "¿Está instalado y accesible desde el entorno del backend?",
        )

    _persist_index_action_report("auditar-ux", job, job.result or "")

    return {
        "action": "auditar-ux",
        "job_id": job.id,
        "status": job.status,
        "result": job.result,
    }


def _dispatch_index_action() -> dict:
    """Genera un índice temático del proyecto vía Scribe (modelo local
    Ollama, T-FB025-US07-01): recolecta ficheros de documentación, backlog,
    código fuente y gobierno, los pasa a `index_documents` de Scribe, y
    persiste el resultado en `07-informes/US-FB025-07/`."""
    project = get_active_project()
    if project is None:
        raise ProjectNotDiscoveredError("No hay ningún proyecto activo.")

    texts = _collect_project_texts(Path(project.path))

    if not texts:
        raise RuntimeError(
            "No se encontraron ficheros de texto para indexar en el proyecto "
            f"'{project.name}'. Directorios buscados: {', '.join(_INDEX_DIRS)}."
        )

    try:
        index_result = index_documents(texts, timeout_seconds=60.0)
    except ScribeUnavailableError as error:
        raise RuntimeError(
            f"El modelo local de Scribe no está disponible para indexar el "
            f"proyecto. Detalle: {error}"
        ) from error

    job_id = str(uuid.uuid4())

    session = get_current_session()
    job = Job(
        id=job_id,
        session_id=session.id if session else "_headless",
        agent_id="scribe-indexer",
        description=f"Indexación del proyecto vía Scribe ({len(texts)} ficheros recolectados)",
        status="completed",
        result=index_result,
    )

    if session is not None:
        record_job(session.id, job)

    _persist_index_action_report("indexar", job, index_result)

    return {
        "action": "indexar",
        "job_id": job.id,
        "status": "completed",
        "result": index_result,
    }


def _collect_project_texts(project_root: Path) -> list[str]:
    """Recolecta el contenido de ficheros de texto relevantes del proyecto
    para indexación vía Scribe. Solo directorios con valor informativo
    alto (documentación, backlog, código fuente, gobierno). Limita tamaño
    y número de ficheros para que el modelo local no se sature."""
    texts: list[str] = []
    for dirname in _INDEX_DIRS:
        target_dir = project_root / dirname
        if not target_dir.is_dir():
            continue
        for file_path in sorted(target_dir.rglob("*")):
            if not file_path.is_file():
                continue
            if file_path.name.startswith(".") or file_path.name.endswith(
                (".pyc", ".pyo", "__pycache__", ".git")
            ):
                continue
            if _is_binary_path(file_path):
                continue
            try:
                content = file_path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if len(content) > _INDEX_MAX_FILE_SIZE_BYTES:
                content = content[:_INDEX_MAX_FILE_SIZE_BYTES] + "\n\n[...]"
            relative = str(file_path.relative_to(project_root))
            texts.append(f"--- {relative} ---\n{content}")
            if len(texts) >= _INDEX_MAX_FILES:
                break
        if len(texts) >= _INDEX_MAX_FILES:
            break
    return texts


def _is_binary_path(file_path: Path) -> bool:
    suffix = file_path.suffix.lower()
    return suffix in (
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg",
        ".pdf", ".zip", ".gz", ".tar", ".whl", ".egg",
        ".pyc", ".pyo", ".so", ".dll", ".exe", ".bin",
        ".db", ".sqlite", ".sqlite3",
    )


def _persist_index_action_report(
    action_id: str, job: Job, result_text: str
) -> Path:
    """Persiste el informe de una acción de indexación/auditoría en
    `07-informes/<US-FB025-XX>/<action_id>-<timestamp>.md`, con timestamp
    para que ejecuciones distintas no se sobrescriban
    (T-FB025-US06-02)."""
    story_id = _STORY_ID_MAP.get(action_id, f"FB-025-{action_id}")
    root = _default_reports_root()
    story_dir = root / story_id
    story_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%S")
    report_path = story_dir / f"{action_id}-{ts}.md"
    report = (
        f"# Informe de acción · {action_id}\n\n"
        f"Fecha: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        f"Proyecto: {(get_active_project() or _FakeProject('?')).name}\n"
        f"Job ID: {job.id}\n"
        f"Estado: {job.status}\n\n"
        f"## Resultado\n\n{result_text}\n"
    )
    report_path.write_text(report, encoding="utf-8")
    return report_path


class _FakeProject:
    def __init__(self, name: str) -> None:
        self.name = name


def dispatch_transversal_action(
    action_id: str, socket_name: str = "default"
) -> dict:
    """Alias legacy — mismo comportamiento que `dispatch_action`."""
    return dispatch_action(action_id, socket_name=socket_name)
