"""Despacho de un `JobPlan` en estado `approved` (T-FB008-US04-03,
US-FB008-04): recorre `plan.steps` en orden, ejecutando cada paso según su
`mechanism`, y se detiene ante el primer fallo — el plan queda `blocked`,
sin continuar con los pasos siguientes, a la espera de indicación humana
(no hay reintento automático en esta Task).

## Mecanismo `"agent"`

Reutiliza `create_job`/`dispatch_job` (US-FB008-01/02) tal cual: crea un
`Job` real para el agente cuyo `role` coincide con `step.agent_role`
(buscado en `session` vía `list_agents`), lo despacha con su
`runtime_instance` ya registrado (`get_runtime_instance_for_agent`,
T-FB002-US03-00), y espera su finalización (`dispatch_job` ya es
síncrono/bloqueante) antes de continuar con el siguiente paso — cumple
"esperando cada uno antes de iniciar el siguiente" sin necesitar ninguna
coordinación adicional. Si el `Job` resultante no queda `completed`
(`failed`, o cualquier excepción de `create_job`/`dispatch_job`), el paso
se marca `failed` y el plan se bloquea.

`dispatch_job` recibe explícitamente `timeout_seconds=AGENT_STEP_TIMEOUT_SECONDS`
(T-FB008-US04-06), no el default de 30s: el trabajo real de una Task de
Developer detrás de un paso de plan tarda de forma habitual más de 30s en
completarse y reportar, a diferencia de un Job corto/determinista —
antes de esta Task, cualquier paso de agente real bloqueaba el plan por
timeout prematuro aunque el Developer no hubiera fallado (reproducido en
vivo con el plan de `US-FB036-01`, ver la Task). El timeout de 30s por
defecto de `dispatch_job` sigue vigente sin cambios para sus otros
llamadores (`architect_verdict_queue.py`, `api/routes.py`,
`actions/transversal.py`), donde sigue siendo un Job corto/determinista.

## Mecanismo `"scribe"`

Invoca `summarize_document` (FB-014) directamente sobre `step.description`
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
(ver US-FB001-03, sin fase asignada) — la propia Descripción de esta Task
ya prevé este caso: sin ese catálogo, el paso se trata como
pendiente/no ejecutable automáticamente, sin bloquear el resto del plan.

Además, el crítico verificó (revisión de T-FB008-US04-01) que la
heurística de `build_job_plan_for_story` puede marcar como `"script"`
pasos que en realidad son Tasks de implementación real de Developer —
falso positivo cuando el *texto descriptivo* de la Task menciona la
palabra "script" sin ser resoluble por uno (visto en el propio backlog
real de esta Story). No se distingue en el código "no hay catálogo" de
"esta Task no era realmente un script" — el efecto observable pedido es
el mismo en ambos casos (degradar sin bloquear el resto del plan), y
determinar cuál de las dos causas aplica exigiría exactamente la
resolución de capacidades que FB-010 (inexistente) resolvería. Un paso
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

from brain.core.session_lifecycle import list_agents
from brain.dispatcher.job_creation import JobCreationError, create_job
from brain.dispatcher.job_dispatch import dispatch_job
from brain.dispatcher.job_plan_builder import task_file_story_prefix
from brain.dispatcher.job_plan_cancellation_registry import (
    clear_active_job_for_plan,
    clear_job_plan_cancellation,
    is_job_plan_cancellation_requested,
    set_active_job_for_plan,
)
from brain.dispatcher.job_plan_lifecycle import transition_job_plan
from brain.dispatcher.job_report import write_job_report
from brain.dispatcher.architect_verdict import (
    VERDICT_APPROVED,
    VERDICT_APPROVED_WITH_NOTES,
    VERDICT_REJECTED,
    parse_verdict,
)
from brain.local_tools import ScribeUnavailableError, summarize_document
from brain.models import Agent, DevelopmentSession, JobPlan, JobPlanStep
from brain.runtime.agent_runtime_registry import get_runtime_instance_for_agent
from brain.tmux.manager import DEFAULT_SOCKET_NAME


# T-FB008-US04-06: timeout de `dispatch_job` para pasos de mecanismo
# 'agent', distinto del default de 30s (pensado para Jobs cortos/
# deterministas, no para el trabajo real de una Task de Developer). Un
# valor grande en vez de "sin timeout" para no tocar la firma de
# `dispatch_job`/`_wait_for_report` (ambos ya aceptan cualquier float) —
# la vía de escape ante un cuelgue real sigue siendo la cancelación
# explícita (`POST /plans/{id}/cancel`), comprobada en cada ciclo del
# polling de `_wait_for_report` sin depender de este timeout.
AGENT_STEP_TIMEOUT_SECONDS = 3600.0


class JobPlanDispatchError(ValueError):
    """No se puede despachar `plan` en su estado/condiciones actuales."""


class _StepCancelledSignal(Exception):
    """Señal interna (nunca cruza `dispatch_plan`): el paso 'agent' en
    curso fue cancelado (T-FB008-US08-01) — distinto de un fallo real del
    paso, se maneja de forma separada para transicionar el plan a
    `cancelled` en vez de `blocked`."""


class _NoAgentAvailableError(ValueError):
    """No hay ningún agente `idle` de `role` disponible para despachar un
    paso (T-FB008-US04-08). Distingue en el mensaje si el motivo es que
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
    mismo rol (T-FB008-US04-08, criterio 1): antes de esta Task se
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
    # Registrado ANTES de despachar (T-FB008-US08-01): si se cancela el
    # plan mientras este paso está en curso, `request_cancellation(plan)`
    # necesita encontrar este `job` para reenviarle la cancelación
    # (reutiliza T-FB008-US05-01) — ver `job_plan_cancellation_registry`.
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
        # T-FB022-US06-03: persistir informe de cierre en
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

    ## Progreso observable por paso (T-FB017-US04-03)

    `dispatch_plan` es una única llamada síncrona bloqueante — quien la
    invoca (`POST /plans/{id}/approve`, `brain/api/routes.py`) solo
    recupera el control cuando la secuencia ENTERA ya terminó, sin ningún
    punto de retorno intermedio propio. Hasta esta Task, `WS /ws/plans`
    solo publicaba el progreso antes y después de la secuencia completa —
    verificado leyendo el código real (no asumido): el docstring de
    `post_plan_approve` decía "publicando el progreso... en cada paso",
    pero ningún punto del código intermedio lo hacía.

    `on_step_status_changed` (opcional, `None` por defecto — no rompe a
    ningún llamador existente) es el mecanismo mínimo para resolver esto
    sin acoplar el dominio a WebSockets (mismo principio ya fijado en
    `brain/api/events.py`: "el dominio no conoce a sus observadores"):
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

    ## Cancelación (T-FB008-US08-01)

    Antes de despachar cada paso, comprueba si se ha solicitado la
    cancelación de `plan` (`job_plan_cancellation_registry`,
    `threading.Event` por plan — mismo patrón de idempotencia por lock que
    T-FB016-US01-08, pero para señalizar en vez de proteger una sección
    crítica, igual que T-FB008-US05-01 para `Job`). Si ya estaba
    solicitada, el bucle se detiene sin despachar ningún paso pendiente
    más — `plan` transiciona a `cancelled`.

    Si la cancelación llega MIENTRAS un paso 'agent' está `running`,
    `_dispatch_agent_step` ya reenvió la señal al `Job` de ese paso
    (`job_plan_cancellation.request_cancellation`, que reutiliza
    `job_cancellation.request_cancellation` de T-FB008-US05-01) — el Job
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
        # Notificación de mejor esfuerzo (T-FB017-US04-03): un fallo del
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

    # T-FB022-US05-02: disparo automático del Job de veredicto al
    # completarse todos los pasos del plan. Si el plan terminó en estado
    # 'approved' o 'blocked' (con trabajos completados), el veredicto
    # procede — el Arquitecto decide si bloquea o aprueba.
    # Si el plan fue cancelado, no hay trabajo que veredictar.
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

    `result` por paso (T-FB008-US04-08): `JobPlanStep.result` ya se
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
) -> None:
    """T-FB022-US05-02 / T-FB022-US07-01: encola automáticamente un Job de
    veredicto hacia el Arquitecto cuando todo el trabajo de Developer (y
    opcionalmente Tester) para `story_id` ha terminado.

    A partir de T-FB022-US07-01, esta función no despacha el veredicto
    directamente — lo encola en la cola FIFO (`architect_verdict_queue`),
    que garantiza que el Arquitecto procese los veredictos uno detrás de
    otro, sin solapamiento, en orden de llegada.

    Retorna inmediatamente (el worker daemon procesa la cola en segundo
    plano) — el estado "en cola, esperando veredicto" es consultable vía
    `get_verdict_queue_status()`.
    """
    from brain.dispatcher.architect_verdict_queue import enqueue_architect_verdict

    enqueue_architect_verdict(story_id, session, socket_name, reports_root)


def _process_verdict_result(story_id: str, verdict_output: str) -> None:
    """T-FB022-US05-03: procesa el resultado del veredicto del Arquitecto.

    - APROBADO / APROBADO_CON_OBSERVACIONES: marca `Estado: DONE` en
      todos los ficheros de Task de `story_id` que estén en TODO.
    - RECHAZADO: genera instrucción de corrección accionable (persistida
      como informe en 07-informes/<story_id>/_rechazo.md).
    """
    if not verdict_output:
        return

    estado, justificacion, siguiente_prompt = parse_verdict(verdict_output)

    if estado in (VERDICT_APPROVED, VERDICT_APPROVED_WITH_NOTES):
        _mark_story_tasks_done(story_id)
    elif estado == VERDICT_REJECTED:
        _write_rejection_instruction(story_id, justificacion, siguiente_prompt)


def _mark_story_tasks_done(story_id: str, backlog_dir: Path | None = None) -> None:
    """Marca `Estado: DONE` en todos los ficheros de Task de `story_id`
    que actualmente están en `TODO`, y promueve transitivamente la propia
    User Story (y su Epic) a `DONE` si con esto quedan todos sus hijos
    completados (T-FB022-US13-01) — misma invocación, sin paso posterior.

    `backlog_dir` solo se sobreescribe en tests (sintético con `tmp_path`);
    en producción se resuelve contra el `02-backlog/` real del proyecto.
    """
    if backlog_dir is None:
        backlog_dir = Path(__file__).resolve().parents[4] / "02-backlog"
    tasks_dir = backlog_dir / "tasks"
    prefix = f"T-{task_file_story_prefix(story_id)}-"
    for task_path in sorted(tasks_dir.glob(f"{prefix}*.md")):
        text = task_path.read_text(encoding="utf-8")
        state = _read_task_state(text)
        if state == "TODO":
            updated = text.replace("state: TODO", "state: DONE", 1)
            task_path.write_text(updated, encoding="utf-8")

    from brain.backlog.promote import promote_backlog

    promote_backlog(backlog_dir)


def _write_rejection_instruction(
    story_id: str, justificacion: str, siguiente_prompt: str
) -> None:
    """Persiste la instrucción de corrección del Arquitecto en
    07-informes/<story_id>/_rechazo.md."""
    root = Path(__file__).resolve().parents[4] / "07-informes"
    story_dir = root / story_id
    story_dir.mkdir(parents=True, exist_ok=True)
    content = (
        f"# Veredicto RECHAZADO · {story_id}\n\n"
        f"## Justificación\n\n{justificacion}\n\n"
        f"## Instrucción para el Developer\n\n{siguiente_prompt}\n"
    )
    (story_dir / "_rechazo.md").write_text(content, encoding="utf-8")


def _read_task_state(text: str) -> str:
    """Lee el valor del campo `state` del frontmatter YAML de un fichero de Task."""
    import re

    match = re.search(r"^state:\s*(.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else ""
