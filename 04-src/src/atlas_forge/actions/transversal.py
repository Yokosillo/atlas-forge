"""Acciones transversales de proyecto (AF-025): lógica de dominio para
despachar Jobs a agentes, ejecutar scripts deterministas e invocar Scribe
desde un único punto de entrada (`POST /project/actions/{action_id}`).

Cada acción es atómica: el endpoint HTTP la recibe, resuelve el agente o
script correspondiente, y devuelve el resultado cuando termina (bloqueante,
mismo criterio que `POST /jobs`). La persistencia del informe en
`07-informes/` se hace aquí (no en la capa HTTP), igual que el resto del
pipeline lo hace en `dispatch_plan`.

Acciones definidas:
  - `documentar`       → despacha Job a la instancia de Documentador ya
    lanzada (T-AF024-US20-01, US-AF025-01, Hilo 3; antes despachaba al
    Arquitecto con el prompt de `DOCUMENTADOR.md` prestado)
  - `analizar-arquitectura` → despacha Job al Arquitecto (US-AF025-02, Hilo 3)
  - `sugerir-ideas`    → despacha Job al Arquitecto (US-AF025-03, Hilo 3)
  - `testear`          → ejecuta `pytest` determinista (US-AF025-04, Hilo 3)
  - `auditar-ux`       → despacha Job a la instancia de UX ya lanzada
    (T-AF024-US13-03; antes `opencode run --auto` headless, US-AF025-06)
  - `auditar-oss`      → despacha Job a la instancia de Auditor-OSS ya
    lanzada (T-AF024-US13-02; imagen pública del repo + auditoría de la web,
    US-AF025-08)
  - `auditar-backlog`  → despacha Job al Arquitecto para el paso 1 de la
    auditoría del backlog (T-AF018-US03-01, US-AF018-03); persiste el
    informe en `07-informes/US-AF018-03/` con nombre con fecha, nunca solo
    en pantalla
  - `verificar-auditoria` → despacha Job al Auditor (rol `auditor_oss`
    existente; renombrar la etiqueta visible a "Auditor" se decide aparte)
    para el paso 2 de la auditoría del backlog (T-AF018-US03-02,
    US-AF018-03): recibe como entrada la ruta del fichero del paso 1
    (`auditar-backlog`) y verifica cada hallazgo contra el código real,
    emitiendo una acción concreta parseable por hallazgo
    (`corregir_estado`/`crear_task_correccion`/`descartar`); persiste el
    informe en `07-informes/US-AF018-03/` con nombre con fecha y referencia
    al fichero del paso 1. Acción independiente: NO se ejecuta
    automáticamente tras `auditar-backlog`
  - `indexar`          → Scribe index_documents (US-AF025-07, Hilo 4)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from atlas_forge.agents.arquitecto import ARQUITECTO_ROLE
from atlas_forge.agents.auditor_oss import AUDITOR_OSS_ROLE
from atlas_forge.agents.documentador import DOCUMENTADOR_ROLE
from atlas_forge.agents.ux import UX_ROLE
from atlas_forge.core.session_lifecycle import list_agents
from atlas_forge.core.session_registry import get_current_session
from atlas_forge.dispatcher.job_creation import create_job
from atlas_forge.dispatcher.job_dispatch import dispatch_job
from atlas_forge.dispatcher.job_history_registry import record_job
from atlas_forge.dispatcher.job_orchestration import create_and_record_job
from atlas_forge.dispatcher.job_report import write_job_report
from atlas_forge.models import Agent, Job, ScriptRunResult
from atlas_forge.runtime.agent_runtime_registry import get_runtime_instance_for_agent
from atlas_forge.workspace.active_project import (
    ProjectNotDiscoveredError,
    get_active_project,
)
from atlas_forge.workspace.generic_scripts import _run_project_tests, run_subprocess, DEFAULT_SCRIPT_TIMEOUT_SECONDS
from atlas_forge.local_tools import ScribeUnavailableError, index_documents

_ACTION_DESCRIPTIONS: dict[str, str] = {
    "documentar": (
        "Documenta el proyecto completo. Compara el contenido de "
        "`docs/` contra el código real del repositorio. Detecta "
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
        "3. Inconsistencias entre la documentación (`docs/`) y "
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
        "documentación en `docs/`) y propón ideas candidatas "
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
        "Audita la interfaz web de Atlas Forge siguiendo el rol y "
        "método definidos en `00-gobierno/UX.md`. "
        "Tu objetivo es evaluar `10-web/` como lo haría un desarrollador "
        "real, encontrando fricciones concretas con evidencia.\n\n"
        "Escribe tu informe completo en el fichero de reporte indicado al "
        "final de tu auditoría. No crees ficheros en 02-backlog/."
    ),
    "auditar-oss": (
        "Audita Atlas Forge como lo haría un maintainer senior de proyectos "
        "open source de referencia, siguiendo el rol y método definidos en "
        "`00-gobierno/AUDITOR-OSS.md`. Tu objetivo es evaluar (1) la imagen "
        "pública del repositorio — qué percibe un desarrollador que lo descubre "
        "por primera vez en GitHub, y (2) la auditoría de UX+Producto de la "
        "interfaz web ya construida (`10-web/`) navegando y ejerciendo su "
        "superficie real contra el backend real.\n\n"
        "Navega como un desarrollador que usa Atlas Forge por primera vez. "
        "Prueba los flujos completos con datos reales. Anota fricciones "
        "concretas: clics de más, terminología sin explicar, estados sin "
        "feedback, información técnica cruda sin traducir.\n\n"
        "Para cada hallazgo, di explícitamente si vale o no vale, y por qué. "
        "Contrasta hallazgos de 'falta algo' contra el backend real "
        "(`04-src/src/atlas_forge/api/routes.py`) antes de reportar.\n\n"
        "Escribe tu informe completo en el fichero de reporte indicado al "
        "final de tu auditoría. No crees ficheros en 02-backlog/."
    ),
    "auditar-backlog": (
        "Audita el backlog activo (paso 1 de la auditoría, US-AF018-03): "
        "recorre el backlog completo y cruza el `## Estado` declarado de "
        "cada item (Epic, User Story y Task) contra la evidencia REAL de "
        "implementación en el código. Lee y entiende el código; esto NO es "
        "un parseo determinista (esa función la cubre US-AF018-02) y el "
        "texto de `### Descripción`/`## Objetivo` de las Tasks y sus "
        "`## Criterios` es solo una pista sobre lo que debería existir, no "
        "la prueba de que existe.\n\n"
        "Tu informe debe incluir:\n"
        "1. Panorama general: conteo de Epics/User Stories/Tasks por estado "
        "declarado.\n"
        "2. Tabla por Epic con el estado de sus User Stories y Tasks.\n"
        "3. Discrepancias entre `## Estado` declarado y evidencia real en "
        "el código (items colgados en TO_DO/READY ya implementados, items "
        "DONE incompletos, dependencias no satisfechas).\n"
        "4. TODOs sin evidencia de implementación.\n"
        "5. Observaciones de proceso.\n\n"
        "Por CADA item auditado declara un hallazgo en formato estructurado "
        "y parseable (el paso 2 consume esta salida):\n"
        "- id: identificador del item (Epic/User Story/Task).\n"
        "- estado_declarado: estado que declara el fichero del backlog.\n"
        "- evidencia: ficheros/funciones/líneas de código que confirman o "
        "refutan el estado declarado.\n"
        "- veredicto: confirmado | falso_positivo | incompleto.\n\n"
        "No escribas a `02-backlog/` — tu salida es un informe para el "
        "humano y para el paso 2, no una modificación del backlog. Cita "
        "evidencia de código real para cada hallazgo. Escribe el informe "
        "completo en el fichero de reporte indicado al terminar — la acción "
        "lo persiste en 07-informes/ con nombre con fecha; nunca lo dejes "
        "solo en pantalla/scrollback."
    ),
    "verificar-auditoria": (
        "Verifica la auditoría del backlog (paso 2 de la auditoría, "
        "US-AF018-03): recibes como entrada el fichero de la auditoría del "
        "paso 1 (`auditar-backlog`) y verificas CADA hallazgo contra el "
        "código REAL del repositorio — NO te fíes de la conclusión del paso "
        "1 sin comprobarla: en un caso real 5 hallazgos de los que 1 era "
        "erróneo.\n\n"
        "Fichero de la auditoría del paso 1 (su ruta parte de este Job):\n"
        "{INPUT_PATH}\n\n"
        "Lee COMPLETO ese fichero y, por CADA hallazgo declarado (id, "
        "estado_declarado, evidencia, veredicto provisional), abre el código "
        "real del item y emite UNA acción concreta y parseable, en este "
        "formato:\n"
        "- id: identificador del item (Epic/User Story/Task).\n"
        "- accion: corregir_estado | crear_task_correccion | descartar.\n"
        "  - corregir_estado: el hallazgo es correcto pero el `## Estado` "
        "del fichero del backlog está mal — añade además `- estado_correcto: "
        "<ESTADO>` con el estado real verificado (p. ej. DONE o READY) y "
        "evidencia de código.\n"
        "  - crear_task_correccion: existe un hueco real de implementación "
        "que requiere una Task nueva de corrección — indica el hueco y su "
        "evidencia.\n"
        "  - descartar: falso positivo del paso 1 — indica el motivo con "
        "evidencia.\n\n"
        "Tu informe debe declarar qué hallazgos confirmas, cuáles corriges "
        "y cuáles descartas, referenciando el fichero del paso 1 (nombre "
        "con fecha). No escribas a `02-backlog/` — tu salida es un informe "
        "para el humano. Escribe el informe completo en el fichero de "
        "reporte indicado al terminar — la acción lo persiste en "
        "07-informes/ con nombre con fecha; nunca lo dejes solo en "
        "pantalla/scrollback."
    ),
    "indexar": (
        "Indexa el proyecto para búsqueda rápida vía Scribe (modelo local "
        "Ollama). "
        "Recolecta ficheros de documentación, backlog y código fuente "
        "relevantes y genera un índice temático accesible por Developer "
        "y Arquitecto."
    ),
    "testear-ui": (
        "Ejecuta la suite de tests de interfaz web (Puppeteer) del proyecto. "
        "Verifica la funcionalidad real de la web mediante navegación headless, "
        "sin intervención manual."
    ),
}

_REPORTS_DIRNAME = "07-informes"

# Marcador de entrada en las descripciones de acción que requieren un fichero
# como entrada (actualmente solo `verificar-auditoria`, T-AF018-US03-02). La
# descripción del Job se construye sustituyéndolo por la ruta real.
_DESCRIPTION_INPUT_PLACEHOLDER = "{INPUT_PATH}"


def _build_action_description(
    action_id: str, input_path: str | None = None
) -> str:
    """Devuelve la descripción del Job de una acción, sustituyendo el
    marcador de entrada `_DESCRIPTION_INPUT_PLACEHOLDER` por la ruta real del
    fichero de entrada cuando la acción lo requiere. Si la acción usa el
    marcador y no se le pasa `input_path`, falla explícitamente en vez de
    despachar un Job con la entrada ausente."""
    description = _ACTION_DESCRIPTIONS.get(action_id)
    if description is None:
        raise ValueError(
            f"La acción '{action_id}' no tiene una descripción definida."
        )
    if _DESCRIPTION_INPUT_PLACEHOLDER in description:
        if not input_path:
            raise ValueError(
                f"La acción '{action_id}' requiere la ruta del fichero de "
                "entrada (parámetro 'input_path')."
            )
        description = description.replace(
            _DESCRIPTION_INPUT_PLACEHOLDER, str(input_path)
        )
    return description


def _find_agent_by_role(role: str) -> Agent | None:
    """Busca un agente `idle` de `role` en la sesión activa — mismo
    criterio que `job_plan_dispatch.py` aplica para Developer (T-AF024-
    US13-03): un agente `stopped`/`working`/`unavailable` no cuenta como
    "instancia lanzada disponible", para que el llamador informe
    explícitamente ("lanza un <rol>") en vez de propagar un
    `JobCreationError` sin traducir cuando el agente existe pero no puede
    recibir un Job ahora mismo."""
    session = get_current_session()
    if session is None:
        return None
    return next(
        (
            agent
            for agent in list_agents(session)
            if isinstance(agent, Agent) and agent.role == role and agent.status == "idle"
        ),
        None,
    )


def _default_reports_root() -> Path:
    return Path(__file__).resolve().parents[4] / _REPORTS_DIRNAME


def _dispatch_agent_action(
    action_id: str,
    agent: Agent,
    socket_name: str,
    input_path: str | None = None,
) -> Job:
    description = _build_action_description(action_id, input_path)

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

    # T-AF025-US08-02: auditar-oss produce 5 ficheros, no 1
    if action_id == ActionType.AUDITAR_OSS:
        _persist_auditor_oss_reports(job)
    elif action_id in (ActionType.AUDITAR_BACKLOG, ActionType.VERIFICAR_AUDITORIA):
        # T-AF018-US03-01/02: tanto el paso 1 (`auditar-backlog`) como el
        # paso 2 (`verificar-auditoria`) de la auditoría persisten con nombre
        # con fecha (<action_id>-<ts>.md) para que nunca se pierdan en
        # scrollback y cada ejecución tenga su propio fichero. El paso 2
        # además referencia el fichero del paso 1 como entrada.
        _persist_timestamped_action_report(
            action_id, job, job.result or "", input_path=input_path
        )
    else:
        _persist_action_report(action_id, job)

    return job


_STORY_ID_MAP = {
    "documentar": "US-AF025-01",
    "analizar-arquitectura": "US-AF025-02",
    "sugerir-ideas": "US-AF025-03",
    "testear": "US-AF025-04",
    "auditar-ux": "US-AF025-06",
    "auditar-oss": "US-AF025-08",
    "auditar-backlog": "US-AF018-03",
    "verificar-auditoria": "US-AF018-03",
    "testear-ui": "US-AF022-15",
    "indexar": "US-AF025-07",
}


def _persist_action_report(action_id: str, job: Job) -> Path:
    """Persiste el informe de cierre del Job en
    `07-informes/US-AF025-XX/<job.id>.md`, reutilizando el mismo mecanismo
    que `write_job_report` pero con un `story_id` específico de la acción
    (no `_sin-story`)."""
    job.story_id = _STORY_ID_MAP.get(action_id, f"AF-025-{action_id}")
    return write_job_report(job, reports_root=_default_reports_root())


class ActionType:
    DOCUMENTAR = "documentar"
    ANALIZAR_ARQUITECTURA = "analizar-arquitectura"
    SUGERIR_IDEAS = "sugerir-ideas"
    TESTEAR = "testear"
    AUDITAR_UX = "auditar-ux"
    AUDITAR_OSS = "auditar-oss"
    AUDITAR_BACKLOG = "auditar-backlog"
    VERIFICAR_AUDITORIA = "verificar-auditoria"
    TESTEAR_UI = "testear-ui"
    INDEXAR = "indexar"


ACCIONES_DISPONIBLES: tuple[str, ...] = (
    ActionType.DOCUMENTAR,
    ActionType.ANALIZAR_ARQUITECTURA,
    ActionType.SUGERIR_IDEAS,
    ActionType.TESTEAR,
    ActionType.AUDITAR_UX,
    ActionType.AUDITAR_OSS,
    ActionType.AUDITAR_BACKLOG,
    ActionType.VERIFICAR_AUDITORIA,
    ActionType.TESTEAR_UI,
    ActionType.INDEXAR,
)


# Metadatos de listado del catálogo combinado (T-AF034-US01-01). El catálogo
# expone cada acción con `name` (etiqueta visible), `description` (resumen
# corto), `origin` (siempre "generic": no existe concepto de acción particular
# en esta Task — ver AF-034, "Acciones particulares por manifiesto" es
# US-AF034-02) y `execution_type`.
_ACTION_DISPLAY: dict[str, str] = {
    "documentar": "Documentar todo",
    "analizar-arquitectura": "Analizar arquitectura",
    "sugerir-ideas": "Sugerir ideas para el backlog",
    "testear": "Testear todo",
    "auditar-ux": "Auditar UX de la web",
    "auditar-oss": "Auditar imagen open source",
    "auditar-backlog": "Auditar el backlog contra el código",
    "verificar-auditoria": "Verificar la auditoría del backlog",
    "testear-ui": "Testear UI web",
    "indexar": "Indexar proyecto (Scribe)",
}

_ACTION_SHORT_DESCRIPTION: dict[str, str] = {
    "documentar": (
        "Revisa que la documentación de docs/ esté al día con el código "
        "real. Propone cambios, no escribe directamente."
    ),
    "analizar-arquitectura": (
        "Análisis de arquitectura con evidencia de código real. Informe "
        "para decisión humana."
    ),
    "sugerir-ideas": (
        "Propone ideas candidatas de Epics/User Stories a partir del estado "
        "actual del proyecto. No escribe a 02-backlog/."
    ),
    "testear": (
        "Ejecuta la suite completa de tests del proyecto. Resultado "
        "determinista (pasa/falla), sin corrección automática."
    ),
    "auditar-ux": (
        "Lanza una auditoría UX de la interfaz web a la instancia de UX "
        "ya lanzada. Sigue el protocolo de 00-gobierno/UX.md."
    ),
    "auditar-oss": (
        "Audita Atlas Forge como lo haría un maintainer senior de open "
        "source: imagen pública del repositorio en GitHub y auditoría de la "
        "interfaz web contra el backend real. Sigue 00-gobierno/AUDITOR-OSS.md."
    ),
    "auditar-backlog": (
        "Lanza al Arquitecto el paso 1 de la auditoría del backlog: cruza el "
        "## Estado declarado de cada item contra la evidencia real del código "
        "y persiste el informe en 07-informes/ con nombre con fecha."
    ),
    "verificar-auditoria": (
        "Lanza al Auditor el paso 2 de la auditoría del backlog: recibe como "
        "entrada el fichero del paso 1 (auditar-backlog), verifica cada "
        "hallazgo contra el código real y emite una acción concreta por "
        "hallazgo (corregir_estado / crear_task_correccion / descartar)."
    ),
    "testear-ui": (
        "Ejecuta la suite de tests de interfaz web (Puppeteer) del "
        "proyecto de forma determinista."
    ),
    "indexar": (
        "Genera un índice temático del proyecto usando el modelo local de "
        "Ollama. Sin gastar tokens de los agentes principales."
    ),
}

# Tipo de ejecución de cada acción, derivado de su naturaleza REAL verificada
# en `dispatch_action`/`transversal.py` (T-AF034-US01-01):
#   - "script": ejecución determinista (subproceso o cálculo), segundos.
#   - "agent_job": despacha un Job a un agente persistente, minutos.
#   - "external_process": proceso externo headless sin agente.
_ACTION_EXECUTION_TYPE: dict[str, str] = {
    "testear": "script",
    "testear-ui": "script",
    "documentar": "agent_job",
    "analizar-arquitectura": "agent_job",
    "sugerir-ideas": "agent_job",
    "auditar-ux": "agent_job",
    "auditar-oss": "agent_job",
    "auditar-backlog": "agent_job",
    "verificar-auditoria": "agent_job",
    "indexar": "external_process",
}


def list_actions() -> list[dict]:
    """Catálogo de acciones transversales con sus metadatos de listado
    (T-AF034-US01-01): `id`, `name`, `description`, `origin="generic"` y
    `execution_type`. Es la fuente única de metadatos del catálogo combinado
    que `GET /scripts` agrega — no hay otro endpoint de listado propio."""
    return [
        {
            "id": action_id,
            "name": _ACTION_DISPLAY.get(action_id, action_id),
            "description": _ACTION_SHORT_DESCRIPTION.get(action_id, ""),
            "origin": "generic",
            "execution_type": _ACTION_EXECUTION_TYPE.get(action_id, "agent_job"),
        }
        for action_id in ACCIONES_DISPONIBLES
    ]


# Rol destinatario de cada acción que despacha Job a un agente persistente
# (T-AF024-US13-03): `auditar-ux` pasa a usar el mismo mecanismo genérico
# `_dispatch_agent_action`/`_find_agent_by_role` que ya usan `documentar`/
# `analizar-arquitectura`/`sugerir-ideas` con Arquitecto, en vez del
# `subprocess.run(["opencode", "run", "--auto", ...])` headless previo.
_ACTION_ROLE_MAP = {
    # T-AF024-US20-01: `documentar` pasa de despachar al Arquitecto (con
    # el prompt de DOCUMENTADOR.md prestado) a despachar a una instancia
    # independiente del rol `documentador` — mismo mecanismo genérico que
    # ya usa `auditar-ux` con UX, sin cambios en `_dispatch_agent_action`/
    # `_find_agent_by_role`.
    "documentar": DOCUMENTADOR_ROLE,
    "analizar-arquitectura": ARQUITECTO_ROLE,
    "sugerir-ideas": ARQUITECTO_ROLE,
    "auditar-ux": UX_ROLE,
    "auditar-oss": AUDITOR_OSS_ROLE,
    "auditar-backlog": ARQUITECTO_ROLE,
    # T-AF018-US03-02: `verificar-auditoria` (paso 2 de la auditoría del
    # backlog) despacha al rol Auditor existente (`auditor_oss`). Renombrar
    # la etiqueta visible a "Auditor" se decide aparte y NO corresponde a
    # esta Task.
    "verificar-auditoria": AUDITOR_OSS_ROLE,
}

_ROLE_DISPLAY_NAME = {
    ARQUITECTO_ROLE: "Arquitecto",
    UX_ROLE: "UX",
    DOCUMENTADOR_ROLE: "Documentador",
    AUDITOR_OSS_ROLE: "Auditor-OSS",
}

# Mensaje específico cuando la acción requiere un agente `idle` del rol y no
# hay ninguno lanzado (T-AF018-US03-01, criterio 4 de `auditar-backlog`): la
# acción informa "Lanza el Arquitecto antes de auditar" — no falla en
# silencio, mismo criterio que `_find_agent_by_role`. Por defecto se usa el
# mensaje genérico.
_ACTION_NO_AGENT_MESSAGE: dict[str, str] = {
    "auditar-backlog": "Lanza el Arquitecto antes de auditar.",
    # T-AF018-US03-02, criterio espejo del paso 1: sin un Auditor `idle`
    # lanzado la acción informa explícitamente, no falla en silencio.
    "verificar-auditoria": "Lanza el Auditor-OSS antes de verificar la auditoría.",
}


def dispatch_action(
    action_id: str,
    socket_name: str = "default",
    input_path: str | None = None,
) -> dict:
    """Despacha una acción transversal de proyecto.

    Para acciones que requieren agente (`documentar` → Documentador,
    T-AF024-US20-01; `analizar-arquitectura`/`sugerir-ideas` →
    Arquitecto; `auditar-ux` → UX, T-AF024-US13-03; `auditar-backlog` →
    Arquitecto, T-AF018-US03-01; `verificar-auditoria` → Auditor,
    T-AF018-US03-02):
    encuentra el agente del rol correspondiente en la sesión activa, crea y
    despacha un Job con la descripción predefinida, y persiste el informe
    en `07-informes/`. Si no hay ninguna instancia lanzada de ese rol,
    informa explícitamente en vez de fallar en silencio (mismo criterio que
    `job_plan_dispatch.py` aplica para Developer).

    `input_path` es la ruta del fichero de entrada que la acción incorpora
    a la descripción de su Job (obligatorio para `verificar-auditoria`, que
    recibe el fichero de la auditoría del paso 1 `auditar-backlog`).

    Para `testear`: ejecuta la suite de tests del proyecto de forma
    determinista (sin LLM), y persiste el resultado en `07-informes/`.

    Para `testear-ui`: ejecuta la suite de tests de interfaz (Puppeteer)
    de forma determinista (sin LLM), y persiste el resultado en `07-informes/`.

    Para `indexar`: recolecta ficheros del proyecto y genera un índice
    temático vía Scribe (modelo local Ollama, T-AF025-US07-01), sin gastar
    tokens de los agentes principales.

    Devuelve un dict con el resultado de la acción."""
    if action_id == ActionType.TESTEAR:
        return _dispatch_test_action()

    if action_id == ActionType.TESTEAR_UI:
        return _dispatch_test_ui_action()

    if action_id == ActionType.INDEXAR:
        return _dispatch_index_action()

    if action_id not in _ACTION_DESCRIPTIONS:
        raise ValueError(f"Acción desconocida: '{action_id}'.")

    if action_id == ActionType.VERIFICAR_AUDITORIA and not input_path:
        raise ValueError(
            "La acción 'verificar-auditoria' requiere la ruta del fichero de "
            "la auditoría del paso 1 como entrada (parámetro 'input_path')."
        )

    role = _ACTION_ROLE_MAP.get(action_id, ARQUITECTO_ROLE)
    agent = _find_agent_by_role(role)
    if agent is None:
        role_name = _ROLE_DISPLAY_NAME.get(role, role)
        specific = _ACTION_NO_AGENT_MESSAGE.get(action_id)
        raise RuntimeError(
            f"No hay ningún agente {role_name} en la sesión activa. "
            + (specific if specific else f"Lanza un {role_name} antes de ejecutar esta acción.")
        )

    job = _dispatch_agent_action(action_id, agent, socket_name, input_path=input_path)

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

    story_id = "US-AF025-04"
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


def _run_web_tests(project_path: str) -> ScriptRunResult:
    """Ejecuta los tests de interfaz web (Puppeteer) del proyecto
    (T-AF022-US15-03) como paso determinista. No es parte del razonamiento
    del Tester — es un script genérico que corre la suite completa.

    Devuelve `ScriptRunResult` con `success=True` si todos los tests
    pasan (exit_code 0), o `success=False` con el detalle de fallos en
    `stdout`/`stderr`. Si no se encuentra un runner de tests web disponible,
    devuelve un resultado de error explícito, nunca una excepción no
    controlada."""
    web_tests_dir = Path(project_path) / "10-web" / "tests"
    if not web_tests_dir.is_dir():
        return ScriptRunResult(
            success=False,
            exit_code=None,
            stdout="",
            stderr="",
            error_message=(
                "No se encontró el directorio de tests de interfaz "
                f"(esperado: {web_tests_dir}). Se necesita "
                "`10-web/tests/run.js` con la suite de tests."
            ),
        )

    run_js_path = web_tests_dir / "run.js"
    if not run_js_path.exists():
        return ScriptRunResult(
            success=False,
            exit_code=None,
            stdout="",
            stderr="",
            error_message=(
                f"No se encontró {run_js_path}. Se necesita el runner "
                "de tests Puppeteer."
            ),
        )

    command = ["node", str(run_js_path)]
    return run_subprocess(
        command,
        project_path,
        DEFAULT_SCRIPT_TIMEOUT_SECONDS,
        action_description="la suite de tests de interfaz web (Puppeteer)",
    )


def _dispatch_test_ui_action() -> dict:
    """Ejecuta la suite de tests de interfaz web (Puppeteer) del proyecto
    de forma determinista (sin LLM), y persiste el resultado en
    `07-informes/US-AF022-15/` con timestamp."""
    project = get_active_project()
    if project is None:
        raise ProjectNotDiscoveredError("No hay ningún proyecto activo.")

    result = _run_web_tests(project.path)

    story_id = "US-AF022-15"
    root = _default_reports_root()
    story_dir = root / story_id
    story_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%S")
    ts_path = story_dir / f"testear-ui-{ts}.md"
    report = (
        f"# Informe de acción · testear-ui\n\n"
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
        "action": "testear-ui",
        "success": result.success,
        "exit_code": result.exit_code,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "error_message": result.error_message,
    }


_INDEX_MAX_FILE_SIZE_BYTES = 50_000
_INDEX_MAX_FILES = 100
_INDEX_DIRS = ("docs", "02-backlog", "04-src", "00-gobierno")


def _dispatch_index_action() -> dict:
    """Genera un índice temático del proyecto vía Scribe (modelo local
    Ollama, T-AF025-US07-01): recolecta ficheros de documentación, backlog,
    código fuente y gobierno, los pasa a `index_documents` de Scribe, y
    persiste el resultado en `07-informes/US-AF025-07/`."""
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

    _persist_timestamped_action_report("indexar", job, index_result)

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


def _persist_timestamped_action_report(
    action_id: str, job: Job, result_text: str, input_path: str | None = None
) -> Path:
    """Persiste el informe de una acción en
    `07-informes/<US-XX>/<action_id>-<timestamp>.md`, con timestamp para
    que ejecuciones distintas no se sobrescriban (T-AF025-US06-02;
    reutilizada por `auditar-backlog` y `verificar-auditoria`,
    T-AF018-US03-01/02). Simétrica a `_persist_action_report` pero con
    nombre de fichero con fecha.

    Cuando `input_path` se proporciona (paso 2 de la auditoría del backlog,
    T-AF018-US03-02), el informe declara explícitamente el fichero del paso 1
    que se ha verificado — el criterio 4 de la US exige que el informe del
    paso 2 referencie el fichero del paso 1."""
    story_id = _STORY_ID_MAP.get(action_id, f"AF-025-{action_id}")
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
        f"Estado: {job.status}\n"
    )
    if input_path:
        report += (
            f"Fichero auditado (paso 1 de la auditoría): {input_path}\n"
        )
    report += (
        f"\n## Resultado\n\n{result_text}\n"
    )
    report_path.write_text(report, encoding="utf-8")
    return report_path


def _persist_auditor_oss_reports(job: Job) -> None:
    """Persiste los 5 ficheros de salida del Auditor-OSS en
    `07-informes/US-AF025-08/<timestamp>/`, sin sobrescribir ejecuciones
    anteriores (T-AF025-US08-02).

    Los 5 ficheros esperados son:
    - OPEN_SOURCE_REVIEW.md
    - GITHUB_IMPROVEMENTS.md
    - REPOSITORY_SCORE.md
    - FIRST_IMPRESSION.md
    - TOP_100_IMPROVEMENTS.md

    El Job.result contiene la salida del agente. Se espera que incluya
    estos 5 ficheros (separados por un marcador o como secciones con
    encabezado '# FILENAME.md')."""
    story_id = "US-AF025-08"
    root = _default_reports_root()
    story_dir = root / story_id
    story_dir.mkdir(parents=True, exist_ok=True)

    # Crear directorio timestamped para esta ejecución
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%S")
    exec_dir = story_dir / ts
    exec_dir.mkdir(parents=True, exist_ok=True)

    # Ficheros esperados (en orden alfabético para consistencia)
    expected_files = [
        "FIRST_IMPRESSION.md",
        "GITHUB_IMPROVEMENTS.md",
        "OPEN_SOURCE_REVIEW.md",
        "REPOSITORY_SCORE.md",
        "TOP_100_IMPROVEMENTS.md",
    ]

    result_text = job.result or ""

    # Parser simple: buscar cada fichero como una sección marcada con
    # "# FILENAME.md" y extraer contenido hasta el siguiente fichero o fin
    for filename in expected_files:
        marker = f"# {filename}\n"
        if marker in result_text:
            # Extraer contenido entre este marcador y el siguiente fichero
            start = result_text.index(marker) + len(marker)
            # Buscar el siguiente marcador de fichero
            remaining = result_text[start:]
            next_marker_pos = None
            for other_filename in expected_files:
                if other_filename != filename:
                    other_marker = f"# {other_filename}\n"
                    if other_marker in remaining:
                        pos = remaining.index(other_marker)
                        if next_marker_pos is None or pos < next_marker_pos:
                            next_marker_pos = pos
            if next_marker_pos is not None:
                content = remaining[:next_marker_pos]
            else:
                content = remaining
            # Escribir fichero, removiendo trailing whitespace
            file_path = exec_dir / filename
            file_path.write_text(content.rstrip() + "\n", encoding="utf-8")


class _FakeProject:
    def __init__(self, name: str) -> None:
        self.name = name


def dispatch_transversal_action(
    action_id: str, socket_name: str = "default"
) -> dict:
    """Alias legacy — mismo comportamiento que `dispatch_action`."""
    return dispatch_action(action_id, socket_name=socket_name)
