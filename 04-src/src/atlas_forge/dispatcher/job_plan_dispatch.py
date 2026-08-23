"""Despacho de un `JobPlan` en estado `approved` (T-AF008-US04-03,
US-AF008-04): recorre `plan.steps` en orden, ejecutando cada paso según su
`mechanism`, y se detiene ante el primer fallo — el plan queda `blocked`,
sin continuar con los pasos siguientes, a la espera de indicación humana
(no hay reintento automático en esta Task).

## Mecanismo `"agent"`

Reutiliza `create_job`/`dispatch_job` (US-AF008-01/02) tal cual: crea un
`Job` real para el agente cuyo `role` coincide con `step.agent_role`
(buscado en `session` vía `list_agents`), lo despacha con su
`runtime_instance` ya registrado (`get_runtime_instance_for_agent`,
T-AF002-US03-00), y espera su finalización (`dispatch_job` ya es
síncrono/bloqueante) antes de continuar con el siguiente paso — cumple
"esperando cada uno antes de iniciar el siguiente" sin necesitar ninguna
coordinación adicional. Si el `Job` resultante no queda `completed`
(`failed`, o cualquier excepción de `create_job`/`dispatch_job`), el paso
se marca `failed` y el plan se bloquea.

`dispatch_job` recibe explícitamente `timeout_seconds=AGENT_STEP_TIMEOUT_SECONDS`
(T-AF008-US04-06), no el default de 30s: el trabajo real de una Task de
Developer detrás de un paso de plan tarda de forma habitual más de 30s en
completarse y reportar, a diferencia de un Job corto/determinista —
antes de esta Task, cualquier paso de agente real bloqueaba el plan por
timeout prematuro aunque el Developer no hubiera fallado (reproducido en
vivo con el plan de `US-AF036-01`, ver la Task). El timeout de 30s por
defecto de `dispatch_job` sigue vigente sin cambios para sus otros
llamadores (`architect_verdict_queue.py`, `api/routes.py`,
`actions/transversal.py`), donde sigue siendo un Job corto/determinista.

## Mecanismo `"scribe"`

Invoca `summarize_document` (AF-014) directamente sobre `step.description`
— sin crear ningún `Job` de agente cognitivo, tal como pide la
Descripción de la Task. Si Scribe lanza `ScribeUnavailableError`, este
paso concreto falla (a diferencia de `dispatch_job`, donde Scribe es solo
una ayuda opcional de pre-procesado: aquí Scribe ES el mecanismo elegido
para el paso, no un acelerador de otro — si no está disponible, el paso
no se puede completar por la vía que el plan decidió) y el plan se
bloquea, igual que cualquier otro fallo.

## Mecanismo `"script"` — degradación explícita (dos causas, un mismo
## efecto observable)

No existe todavía ningún catálogo de scripts invocables en el proyecto
(ver US-AF001-03, sin fase asignada) — la propia Descripción de esta Task
ya prevé este caso: sin ese catálogo, el paso se trata como
pendiente/no ejecutable automáticamente, sin bloquear el resto del plan.

Además, el crítico verificó (revisión de T-AF008-US04-01) que la
heurística de `build_job_plan_for_story` puede marcar como `"script"`
pasos que en realidad son Tasks de implementación real de Developer —
falso positivo cuando el *texto descriptivo* de la Task menciona la
palabra "script" sin ser resoluble por uno (visto en el propio backlog
real de esta Story). No se distingue en el código "no hay catálogo" de
"esta Task no era realmente un script" — el efecto observable pedido es
el mismo en ambos casos (degradar sin bloquear el resto del plan), y
determinar cuál de las dos causas aplica exigiría exactamente la
resolución de capacidades que AF-010 (inexistente) resolvería. Un paso
`"script"` por tanto NUNCA hace fallar el plan por sí solo: queda marcado
`pending` (ni `completed` ni `failed`) y el despacho continúa con el
siguiente paso.

## Progreso consultable

`get_plan_progress` expone el estado de cada paso (`pending`/`running`/
`completed`/`failed`) más el estado global del plan en cualquier momento
del despacho — `dispatch_plan` actualiza `step.status` inmediatamente
antes/después de ejecutar cada paso, no solo al final, así que una lectura
concurrente (p. ej. desde la TUI en un hilo aparte, mismo patrón ya usado
en la pantalla Jobs) ve el paso en curso reflejado como `running`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from atlas_forge.backlog.parser import load_backlog
from atlas_forge.core.session_lifecycle import list_agents
from atlas_forge.dispatcher.job_creation import JobCreationError, create_job
from atlas_forge.dispatcher.job_dispatch import dispatch_job
from atlas_forge.dispatcher.job_plan_builder import task_file_story_prefix
from atlas_forge.dispatcher.job_plan_cancellation_registry import (
    clear_active_job_for_plan,
    clear_job_plan_cancellation,
    is_job_plan_cancellation_requested,
    set_active_job_for_plan,
)
from atlas_forge.dispatcher.job_plan_lifecycle import transition_job_plan
from atlas_forge.dispatcher.job_report import write_job_report
from atlas_forge.dispatcher.architect_verdict import (
    VERDICT_APPROVED,
    VERDICT_APPROVED_WITH_NOTES,
    VERDICT_REJECTED,
    parse_verdict,
)
from atlas_forge.local_tools import ScribeUnavailableError, summarize_document
from atlas_forge.models import Agent, DevelopmentSession, JobPlan, JobPlanStep
from atlas_forge.runtime.agent_runtime_registry import get_runtime_instance_for_agent
from atlas_forge.tmux.manager import DEFAULT_SOCKET_NAME


# T-AF008-US04-06: timeout de `dispatch_job` para pasos de mecanismo
# 'agent', distinto del default de 30s (pensado para Jobs cortos/
# deterministas, no para el trabajo real de una Task de Developer). Un
# valor grande en vez de "sin timeout" para no tocar la firma de
# `dispatch_job`/`_wait_for_report` (ambos ya aceptan cualquier float) —
# la vía de escape ante un cuelgue real sigue siendo la cancelación
# explícita (`POST /plans/{id}/cancel`), comprobada en cada ciclo del
# polling de `_wait_for_report` sin depender de este timeout.
#
# T-AF008-US10-06 (2026-08-21): reducido de 3600s a 1800s. La antigua hora
# mantenía un agente `working` colgado (terminó sin que el Dispatcher
# detectara su cierre por el fichero de auto-reporte) hasta 1h sin que nada
# lo rescate. 1800s (30 min) sigue siendo un margen amplio para el trabajo
# real de un paso de Developer/Tester/Arquitecto, pero acota el atasco
# "working colgado" a media hora como máximo. La detección activa del cierre
# (fallback por marcador en el pane / reconciliación del estado colgado)
# queda documentada como hallazgo para el Arquitecto en el informe de la
# Task — esta constante es solo el techo, no el mecanismo de detección.
AGENT_STEP_TIMEOUT_SECONDS = 1800.0


class JobPlanDispatchError(ValueError):
    """No se puede despachar `plan` en su estado/condiciones actuales."""


class _StepCancelledSignal(Exception):
    """Señal interna (nunca cruza `dispatch_plan`): el paso 'agent' en
    curso fue cancelado (T-AF008-US08-01) — distinto de un fallo real del
    paso, se maneja de forma separada para transicionar el plan a
    `cancelled` en vez de `blocked`."""


class _NoAgentAvailableError(ValueError):
    """No hay ningún agente `idle` de `role` disponible para despachar un
    paso (T-AF008-US04-08). Distingue en el mensaje si el motivo es que
    todos los agentes de ese rol están ocupados (`all_working=True`) o
    que no existe ninguno (`all_working=False`) — quien llama decide el
    texto exacto del `JobCreationError` para cada caso."""

    def __init__(self, all_working: bool) -> None:
        self.all_working = all_working
        super().__init__()


def _find_agent_by_role(
    session: DevelopmentSession, role: str, agent_id: str | None = None
) -> Agent:
    """Resuelve el agente de `role` al que despachar un paso.

    Con `agent_id` explícito, se busca exactamente ese agente (mismo
    comportamiento previo a esta Task) — el llamador pidió uno concreto,
    no hay elección que hacer.

    Sin `agent_id`, prioriza un agente `idle` sobre uno `working` del
    mismo rol (T-AF008-US04-08, criterio 1): antes de esta Task se
    devolvía el primero encontrado sin mirar `status`, lo que con
    `MAX_SIMULTANEOUS_DEVELOPERS` > 1 podía reutilizar un Developer ya
    `working` en otro Job/paso — riesgo real de mezclar dos instrucciones
    en el mismo pane. Si no hay ningún agente `idle` disponible, lanza
    `_NoAgentAvailableError` (no devuelve `None`, no reutiliza uno
    ocupado): `all_working=True` si existe al menos un agente de `role`
    pero todos están `working`, `all_working=False` si no existe ninguno
    — el llamador (`_dispatch_agent_step`) traduce cada caso a un mensaje
    de `JobCreationError` distinto y explícito (criterio 3: fallar rápido,
    sin cola de espera automática)."""
    candidates_by_id: dict[str, Agent] = {
        agent.id: agent
        for agent in list_agents(session)
        if isinstance(agent, Agent) and agent.role == role
    }

    if agent_id is not None:
        agent = candidates_by_id.get(agent_id)
        if agent is None:
            raise _NoAgentAvailableError(all_working=False)
        return agent

    idle_agent = next(
        (agent for agent in candidates_by_id.values() if agent.status == "idle"),
        None,
    )
    if idle_agent is not None:
        return idle_agent

    raise _NoAgentAvailableError(all_working=bool(candidates_by_id))


def _dispatch_agent_step(
    step: JobPlanStep, session: DevelopmentSession, socket_name: str, plan: JobPlan
) -> None:
    if step.agent_role is None:
        raise JobCreationError(
            "Un paso de mecanismo 'agent' requiere 'agent_role' para "
            "resolver el agente destinatario."
        )

    try:
        agent = _find_agent_by_role(session, step.agent_role, agent_id=step.agent_id)
    except _NoAgentAvailableError as error:
        if step.agent_id is not None:
            raise JobCreationError(
                f"No hay ningún agente con role '{step.agent_role}' y "
                f"agent_id '{step.agent_id}' en la sesión activa."
            ) from error
        if error.all_working:
            raise JobCreationError(
                f"Todos los agentes con role '{step.agent_role}' están "
                f"ocupados — no se reutiliza un agente ya en curso para "
                f"evitar mezclar instrucciones en el mismo pane."
            ) from error
        raise JobCreationError(
            f"No hay ningún agente con role '{step.agent_role}' en la "
            f"sesión activa para despachar este paso."
        ) from error

    runtime_instance = get_runtime_instance_for_agent(agent.id)
    if runtime_instance is None:
        raise JobCreationError(
            f"El agente '{agent.name}' no tiene un runtime registrado — "
            f"debe estar lanzado antes de despachar el plan."
        )

    job = create_job(step.description, agent, session)
    job.story_id = plan.goal
    # Registrado ANTES de despachar (T-AF008-US08-01): si se cancela el
    # plan mientras este paso está en curso, `request_cancellation(plan)`
    # necesita encontrar este `job` para reenviarle la cancelación
    # (reutiliza T-AF008-US05-01) — ver `job_plan_cancellation_registry`.
    set_active_job_for_plan(plan, job)
    try:
        dispatch_job(
            job,
            agent,
            runtime_instance,
            timeout_seconds=AGENT_STEP_TIMEOUT_SECONDS,
            socket_name=socket_name,
        )
    finally:
        clear_active_job_for_plan(plan)
        # T-AF022-US06-03: persistir informe de cierre en
        # 07-informes/<story_id>/<job_id>.md siempre, tanto si el Job se
        # completó como si falló — un Job `cancelled` no se reporta aquí
        # (el paso se cancela sin información útil que persistir).
        if job.status in ("completed", "failed"):
            try:
                write_job_report(job)
            except Exception:
                pass

    if job.status == "cancelled":
        step.result = job.result
        raise _StepCancelledSignal(job.result)

    if job.status != "completed":
        raise JobCreationError(
            f"El Job del paso no se completó (estado '{job.status}'): "
            f"{job.result}"
        )

    step.result = job.result


def _dispatch_scribe_step(step: JobPlanStep) -> None:
    step.result = summarize_document(step.description)


def _execute_step(
    step: JobPlanStep, session: DevelopmentSession, socket_name: str, plan: JobPlan
) -> None:
    """Ejecuta `step` según su mecanismo. No captura excepciones propias —
    `dispatch_plan` decide qué hacer con cada resultado (fallo real vs.
    degradación explícita de `"script"`)."""
    if step.mechanism == "agent":
        _dispatch_agent_step(step, session, socket_name, plan)
    elif step.mechanism == "scribe":
        _dispatch_scribe_step(step)
    elif step.mechanism == "script":
        # Degradación explícita (ver docstring de módulo): sin catálogo de
        # scripts invocables, o ante un falso positivo de la heurística de
        # -01, el paso queda pendiente/no ejecutable automáticamente, sin
        # levantar ningún error ni bloquear el resto del plan.
        pass
    else:
        raise JobCreationError(f"Mecanismo de paso desconocido: '{step.mechanism}'.")


def dispatch_plan(
    plan: JobPlan,
    session: DevelopmentSession,
    socket_name: str = DEFAULT_SOCKET_NAME,
    on_step_status_changed: Callable[[JobPlan], None] | None = None,
) -> None:
    """Despacha cada paso de `plan` (debe estar `approved`) en orden,
    esperando la finalización de cada uno antes de iniciar el siguiente.
    Si un paso falla, `plan` transiciona a `blocked` y el despacho se
    detiene sin ejecutar los pasos restantes. Rechaza explícitamente
    despachar un plan que no esté `approved`, sin efecto alguno sobre
    `plan` ni sus pasos.

    ## Progreso observable por paso (T-AF017-US04-03)

    `dispatch_plan` es una única llamada síncrona bloqueante — quien la
    invoca (`POST /plans/{id}/approve`, `atlas_forge/api/routes.py`) solo
    recupera el control cuando la secuencia ENTERA ya terminó, sin ningún
    punto de retorno intermedio propio. Hasta esta Task, `WS /ws/plans`
    solo publicaba el progreso antes y después de la secuencia completa —
    verificado leyendo el código real (no asumido): el docstring de
    `post_plan_approve` decía "publicando el progreso... en cada paso",
    pero ningún punto del código intermedio lo hacía.

    `on_step_status_changed` (opcional, `None` por defecto — no rompe a
    ningún llamador existente) es el mecanismo mínimo para resolver esto
    sin acoplar el dominio a WebSockets (mismo principio ya fijado en
    `atlas_forge/api/events.py`: "el dominio no conoce a sus observadores"):
    una función genérica, invocada con `plan` cada vez que el `status` de
    un paso cambia (al pasar a `running`, y de nuevo al resolverse en
    `completed`/`failed`/`cancelled`/`pending`) — el endpoint HTTP es
    quien decide qué hacer con esa notificación (publicar en
    `plans_hub`), el dominio solo informa que algo cambió. Si se omite,
    el comportamiento es exactamente el de antes de esta Task.

    No se usa el mismo patrón de "registro + polling acotado" ya
    construido para la cancelación (`job_plan_cancellation_registry`)
    porque aquí no hay ninguna condición de carrera entre hilos que
    resolver — es el propio hilo que ejecuta `dispatch_plan` quien conoce
    el momento exacto de cada cambio de estado, un callback simple e
    inyectado es la solución más directa.

    ## Cancelación (T-AF008-US08-01)

    Antes de despachar cada paso, comprueba si se ha solicitado la
    cancelación de `plan` (`job_plan_cancellation_registry`,
    `threading.Event` por plan — mismo patrón de idempotencia por lock que
    T-AF016-US01-08, pero para señalizar en vez de proteger una sección
    crítica, igual que T-AF008-US05-01 para `Job`). Si ya estaba
    solicitada, el bucle se detiene sin despachar ningún paso pendiente
    más — `plan` transiciona a `cancelled`.

    Si la cancelación llega MIENTRAS un paso 'agent' está `running`,
    `_dispatch_agent_step` ya reenvió la señal al `Job` de ese paso
    (`job_plan_cancellation.request_cancellation`, que reutiliza
    `job_cancellation.request_cancellation` de T-AF008-US05-01) — el Job
    vuelve `cancelled` en vez de `completed`, señalado internamente con
    `_StepCancelledSignal` para distinguirlo de un fallo real del paso
    (que bloquearía el plan en vez de cancelarlo).

    El registro de cancelación de `plan` se limpia siempre al terminar
    (éxito, bloqueo o cancelación) — mismo motivo que
    `clear_job_cancellation` en `job_dispatch.py`: evita acumular `Event`
    de planes ya resueltos indefinidamente."""
    if plan.status != "approved":
        raise JobPlanDispatchError(
            f"No se puede despachar un plan en estado '{plan.status}': "
            f"debe estar 'approved'."
        )

    def _notify() -> None:
        # Notificación de mejor esfuerzo (T-AF017-US04-03): un fallo del
        # callback (p. ej. un error al publicar en el WebSocket) nunca
        # debe interrumpir el despacho real del plan — el callback es
        # observabilidad, no una precondición del dominio.
        if on_step_status_changed is None:
            return
        try:
            on_step_status_changed(plan)
        except Exception:
            pass

    try:
        for step in plan.steps:
            if is_job_plan_cancellation_requested(plan):
                transition_job_plan(plan, "cancelled")
                _notify()
                return

            step.status = "running"
            _notify()
            try:
                _execute_step(step, session, socket_name, plan)
            except _StepCancelledSignal:
                step.status = "cancelled"
                transition_job_plan(plan, "cancelled")
                _notify()
                return
            except (JobCreationError, ScribeUnavailableError) as error:
                step.status = "failed"
                step.result = str(error)
                transition_job_plan(plan, "blocked")
                _notify()
                return

            if step.mechanism == "script":
                # Degradación explícita (ver docstring de módulo): ni
                # completed ni failed — vuelve a pending, tal como estaba
                # antes de que este bucle lo marcara running para intentarlo.
                step.status = "pending"
            else:
                step.status = "completed"
            _notify()
    finally:
        clear_job_plan_cancellation(plan)

    # T-AF022-US05-02 / T-AF008-US14-02: disparo automático del Job de
    # veredicto al completarse todos los pasos del plan Y quedar TODA la
    # User Story con sus Tasks en DONE (no solo los pasos de este plan
    # concreto — un plan puede cubrir solo parte de la Story si el resto
    # ya se despachó por el otro mecanismo, la cola de EN_DESARROLLO/REVIEW de
    # US-AF008-14). Si el plan fue cancelado, no hay trabajo que
    # veredictar. `trigger_architect_verdict` ya no dispara el veredicto
    # directamente: marca la Story en REVIEW y es
    # `run_architect_verdict_dispatch_cycle` (`dispatch_queue_worker.py`)
    # quien la asigna a un Arquitecto libre.
    if plan.status != "cancelled":
        try:
            trigger_architect_verdict(
                plan.goal, session, socket_name=socket_name
            )
        except Exception:
            pass


def get_plan_progress(plan: JobPlan) -> dict[str, Any]:
    """Consulta el progreso de `plan` en cualquier momento: estado global
    del plan más el estado individual de cada paso, en orden.

    `result` por paso (T-AF008-US04-08): `JobPlanStep.result` ya se
    rellena con el mensaje real del error (`step.result = str(error)`,
    ver `dispatch_plan`) antes de marcar el plan `blocked`, pero hasta
    esta Task ese dato nunca llegaba a `GET /plans`/`GET /plans/{id}` —
    el usuario solo veía "BLOQUEADO" a nivel de plan, sin saber qué paso
    falló ni por qué. `step.result` es `str` con default `""` (no
    `str | None`) en el modelo — se traduce a `None` aquí cuando está
    vacío (paso sin terminar, o mecanismo que nunca escribe `result`,
    p. ej. `"script"` degradado) en vez de exponer una cadena vacía, para
    que el consumidor pueda distinguir "sin resultado" de "resultado
    vacío" de forma explícita en el JSON (`null` vs. `""`)."""
    return {
        "goal": plan.goal,
        "status": plan.status,
        "steps": [
            {
                "description": step.description,
                "mechanism": step.mechanism,
                "status": step.status,
                "result": step.result or None,
            }
            for step in plan.steps
        ],
    }


def _collect_story_reports(story_id: str, reports_root: Path) -> list[str]:
    """Colecciona el contenido de todos los informes de cierre para
    `story_id` en `reports_root/<story_id>/`. Devuelve una lista de
    contenidos, uno por fichero `.md` encontrado. Si el directorio no
    existe, devuelve lista vacía."""
    story_dir = reports_root / story_id
    if not story_dir.is_dir():
        return []
    reports = []
    for report_path in sorted(story_dir.glob("*.md")):
        reports.append(report_path.read_text(encoding="utf-8"))
    return reports


def trigger_architect_verdict(
    story_id: str,
    session: DevelopmentSession,
    socket_name: str = DEFAULT_SOCKET_NAME,
    reports_root: Path | None = None,
    backlog_dir: Path | None = None,
) -> None:
    """T-AF022-US05-02 / T-AF008-US14-02: marca `story_id` en `IN_REVIEW`
    (AF-040; antes REVIEW) cuando TODAS sus Tasks están `DONE` — el
    disparo real del veredicto ya no ocurre aquí ni en la cola FIFO ciega
    (`architect_verdict_queue`, que no comprobaba disponibilidad del
    Arquitecto). En su lugar, es `run_architect_verdict_dispatch_cycle`
    (`dispatch_queue_worker.py`) quien, en su ciclo de polling, asigna
    las User Stories en `IN_REVIEW` a un Arquitecto libre — mismo
    criterio "un agente libre a la vez" ya vigente para Developer/Tester.

    No hace nada (silenciosamente) si `story_id` todavía tiene Tasks sin
    `DONE`: corrige el bug de diseño donde un Job suelto con `story_id`
    (`POST /jobs`) disparaba el veredicto tras completarse él mismo, sin
    esperar al resto de Tasks de la misma Story."""
    from atlas_forge.dispatcher.dispatch_queue_worker import story_is_fully_done

    if backlog_dir is None:
        backlog_dir = Path(__file__).resolve().parents[4] / "02-backlog"
    graph = load_backlog(backlog_dir)

    if not story_is_fully_done(graph, story_id):
        return

    item = graph.items.get(story_id)
    if item is None or item.state == "IN_REVIEW" or item.state == "DONE":
        return

    story_path = item.path
    text = story_path.read_text(encoding="utf-8")
    current_state = _read_task_state(text)
    if not current_state:
        return
    # T-AF036-US13-01 (corrección del Tester): este camino escribía
    # `state: IN_REVIEW` directo en disco sin actualizar `updated_at`.
    # Se enruta por `_set_state`, que actualiza el timestamp de la última
    # transición junto al `state` (igual que la promoción automática).
    from atlas_forge.backlog.promote import _set_state

    _set_state(story_path, "IN_REVIEW")


def _process_verdict_result(
    story_id: str, verdict_output: str, backlog_dir: Path | None = None
) -> None:
    """T-AF022-US05-03 / T-AF008-US14-02: procesa el resultado del
    veredicto del Arquitecto sobre una User Story ya en `REVIEW` (con
    todas sus Tasks `DONE` por el ciclo de Tester).

    - APROBADO / APROBADO_CON_OBSERVACIONES: marca `Estado: DONE` en
      todos los ficheros de Task de `story_id` que estén en TO_DO/EN_DESARROLLO
      (caso residual, plan que no cubrió toda la Story) y promueve la
      propia US de REVIEW a DONE.
    - RECHAZADO por falta de cobertura de producto (rediseño 2026-08-17,
      "PIPELINE OPERATIVO Y RECONCILIACIÓN" — sustituye el diseño
      anterior de `US-AF008-14`): el Arquitecto AÑADE UNA TASK NUEVA A LA
      MISMA User Story, nunca crea una US nueva — decisión explícita del
      usuario. Esa Task entra DIRECTAMENTE en `state: EN_DESARROLLO` (se
      salta `TO_DO`, el Dispatcher la despacha ya en el siguiente ciclo,
      sin esperar a que el humano la progrese). La US original NO se
      promueve a `DONE` en este caso — tiene trabajo pendiente de nuevo,
      así que `_mark_story_tasks_done` no se invoca aquí; el ciclo normal
      (todas las Tasks vuelven a `DONE`) la llevará a `REVIEW`/veredicto
      otra vez cuando corresponda.
    """
    if not verdict_output:
        return

    estado, justificacion, siguiente_prompt = parse_verdict(verdict_output)

    if estado in (VERDICT_APPROVED, VERDICT_APPROVED_WITH_NOTES):
        _mark_story_tasks_done(story_id, backlog_dir=backlog_dir)
    elif estado == VERDICT_REJECTED:
        _create_rejection_correction_task(
            story_id, justificacion, siguiente_prompt, backlog_dir=backlog_dir
        )


def _mark_story_tasks_done(story_id: str, backlog_dir: Path | None = None) -> None:
    """Marca `Estado: DONE` en todos los ficheros de Task de `story_id`
    que actualmente están en `TO_DO`/`EN_DESARROLLO` (ambos tratados como
    "todavía no empezado", ver más abajo), y promueve transitivamente la
    propia User Story (y su Epic) a `DONE` si con esto quedan todos sus
    hijos completados (T-AF022-US13-01) — misma invocación, sin paso
    posterior.

    `backlog_dir` solo se sobreescribe en tests (sintético con `tmp_path`);
    en producción se resuelve contra el `02-backlog/` real del proyecto.
    """
    if backlog_dir is None:
        backlog_dir = Path(__file__).resolve().parents[4] / "02-backlog"
    tasks_dir = backlog_dir / "tasks"
    prefix = f"T-{task_file_story_prefix(story_id)}-"
    from atlas_forge.backlog.promote import _set_state

    for task_path in sorted(tasks_dir.glob(f"{prefix}*.md")):
        text = task_path.read_text(encoding="utf-8")
        state = _read_task_state(text)
        # T-AF008-US14-01: EN_DESARROLLO se trata como "todavía no empezado",
        # igual que TO_DO — si una Story despachada por Plan tenía además
        # alguna Task marcada para desarrollo por el otro mecanismo
        # (cola de US-AF008-14), el veredicto del Arquitecto la cierra
        # igual, sin dejarla huérfana en EN_DESARROLLO.
        if state in ("READY", "TO_DEVELOP"):
            # T-AF036-US13-01 (corrección del Tester): este camino escribía
            # `state: DONE` directo sin `updated_at`; `_set_state` lo
            # actualiza junto al cambio de estado.
            _set_state(task_path, "DONE")

    from atlas_forge.backlog.promote import promote_backlog

    # AF-040 (criterio 7): el Arquitecto YA validó (APROBADO), así que la
    # US pasa explícitamente a DONE — la validación final nunca se omite
    # (dejarla en IN_REVIEW la atascaría para siempre).
    _mark_story_done_after_architect_approval(story_id, backlog_dir=backlog_dir)
    # Con la US ya DONE, la promoción automática propaga transitivamente a
    # la Epic cuando todas sus US están DONE. Idempotente.
    promote_backlog(backlog_dir)


def _mark_story_done_after_architect_approval(
    story_id: str, backlog_dir: Path | None = None
) -> None:
    """Marca `state: DONE` en el fichero de la User Story `story_id` tras
    la aprobación del Arquitecto (AF-040, US-AF040-01 criterio 7: la US
    solo pasa a `DONE` después de la validación final). Es la contrapartida
    de `promote_backlog`, que tras la migración deja la US en `IN_REVIEW`
    (pendiente de validación) — sin este paso explícito la US quedaría
    atascada en `IN_REVIEW` para siempre.

    `backlog_dir` solo se sobreescribe en tests; en producción se resuelve
    contra el `02-backlog/` real del proyecto."""
    import re as _re

    from atlas_forge.backlog.promote import _set_state

    if backlog_dir is None:
        backlog_dir = Path(__file__).resolve().parents[4] / "02-backlog"
    # Normaliza la forma `AF100-US01` a la canónica `US-AF100-01` (misma
    # aceptación de ambos formatos que `task_file_story_prefix`).
    if not story_id.startswith("US-"):
        normalized = _re.sub(r"^AF(\d+)-US(\d+)$", r"US-AF\1-\2", story_id)
        if normalized == story_id:
            return
        story_id = normalized
    # El fichero real puede llevar slug (`US-AF100-01-titulo.md`), mismo
    # patrón que las Tasks — se localiza por glob, nunca por nombre exacto.
    us_dir = backlog_dir / "user-stories"
    candidates = sorted(us_dir.glob(f"{story_id}-*.md")) or sorted(us_dir.glob(f"{story_id}.md"))
    if not candidates:
        return
    # Escritura directa de la línea `state:` (mismo mecanismo que
    # `promote_backlog`), sin re-validar el fichero completo — el veredicto
    # del Arquitecto ya pasó por `promote_backlog`/validadores antes.
    _set_state(str(candidates[0]), "DONE")


def _next_task_id_for_story(tasks_dir: Path, story_id: str) -> str:
    """Siguiente `task_id` libre bajo `story_id` (p. ej. `T-AF008-US14-05`)
    — acepta tanto ficheros con slug (`T-AF008-US14-05-slug.md`) como el
    formato legacy sin slug (`T-AF008-US14-05.md`)."""
    import re as _re

    prefix = task_file_story_prefix(story_id)
    existing = list(tasks_dir.glob(f"T-{prefix}-*.md"))
    max_n = 0
    for path in existing:
        match = _re.match(rf"T-{_re.escape(prefix)}-(\d+)(?:-.*)?$", path.stem)
        if match:
            max_n = max(max_n, int(match.group(1)))
    return f"T-{prefix}-{max_n + 1:02d}"


def _create_rejection_correction_task(
    story_id: str, justificacion: str, siguiente_prompt: str, backlog_dir: Path | None = None
) -> str | None:
    """Rediseño 2026-08-17 ("PIPELINE OPERATIVO Y RECONCILIACIÓN",
    sustituye `_write_rejection_instruction`): ante un veredicto
    RECHAZADO del Arquitecto sobre una User Story, crea una Task nueva
    bajo LA MISMA US (nunca una US nueva) con el contenido del rechazo
    como objetivo/descripción, y la escribe directamente en
    `state: TO_DEVELOP` (AF-040; antes EN_DESARROLLO) — se salta `READY`,
    el Dispatcher la despacha en el siguiente ciclo sin esperar a que el
    humano la progrese.

    Devuelve el `task_id` creado, o `None` si no se pudo (US inexistente
    u otro fallo de validación — no debe tumbar el procesamiento del
    veredicto)."""
    from atlas_forge.backlog.create import create_task
    from atlas_forge.backlog.edit import set_item_state

    if backlog_dir is None:
        backlog_dir = Path(__file__).resolve().parents[4] / "02-backlog"
    tasks_dir = backlog_dir / "tasks"
    new_task_id = _next_task_id_for_story(tasks_dir, story_id)

    try:
        path, _epic_id = create_task(
            backlog_dir,
            us_id=story_id,
            task_id=new_task_id,
            title=f"Cobertura pendiente tras veredicto RECHAZADO de {story_id}",
            objetivo=(
                f"Ampliar {story_id} para cubrir lo que el Arquitecto detectó "
                f"como faltante en su veredicto de cierre."
            ),
            descripcion=siguiente_prompt or justificacion or "Ver veredicto del Arquitecto.",
            criterios_aceptacion=justificacion or "Ver veredicto del Arquitecto.",
            priority="Alta",
        )
    except Exception:
        return None

    set_item_state(path, "TO_DEVELOP")
    return new_task_id


def _read_task_state(text: str) -> str:
    """Lee el valor del campo `state` del frontmatter YAML de un fichero de Task."""
    import re

    match = re.search(r"^state:\s*(.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else ""
