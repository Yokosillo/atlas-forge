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

from typing import Any, Callable

from brain.core.session_lifecycle import list_agents
from brain.dispatcher.job_creation import JobCreationError, create_job
from brain.dispatcher.job_dispatch import dispatch_job
from brain.dispatcher.job_plan_cancellation_registry import (
    clear_active_job_for_plan,
    clear_job_plan_cancellation,
    is_job_plan_cancellation_requested,
    set_active_job_for_plan,
)
from brain.dispatcher.job_plan_lifecycle import transition_job_plan
from brain.local_tools import ScribeUnavailableError, summarize_document
from brain.models import Agent, DevelopmentSession, JobPlan, JobPlanStep
from brain.runtime.agent_runtime_registry import get_runtime_instance_for_agent
from brain.tmux.manager import DEFAULT_SOCKET_NAME


class JobPlanDispatchError(ValueError):
    """No se puede despachar `plan` en su estado/condiciones actuales."""


class _StepCancelledSignal(Exception):
    """Señal interna (nunca cruza `dispatch_plan`): el paso 'agent' en
    curso fue cancelado (T-FB008-US08-01) — distinto de un fallo real del
    paso, se maneja de forma separada para transicionar el plan a
    `cancelled` en vez de `blocked`."""


def _find_agent_by_role(session: DevelopmentSession, role: str) -> Agent | None:
    return next(
        (
            agent
            for agent in list_agents(session)
            if isinstance(agent, Agent) and agent.role == role
        ),
        None,
    )


def _dispatch_agent_step(
    step: JobPlanStep, session: DevelopmentSession, socket_name: str, plan: JobPlan
) -> None:
    if step.agent_role is None:
        raise JobCreationError(
            "Un paso de mecanismo 'agent' requiere 'agent_role' para "
            "resolver el agente destinatario."
        )

    agent = _find_agent_by_role(session, step.agent_role)
    if agent is None:
        raise JobCreationError(
            f"No hay ningún agente con role '{step.agent_role}' en la "
            f"sesión activa para despachar este paso."
        )

    runtime_instance = get_runtime_instance_for_agent(agent.id)
    if runtime_instance is None:
        raise JobCreationError(
            f"El agente '{agent.name}' no tiene un runtime registrado — "
            f"debe estar lanzado antes de despachar el plan."
        )

    job = create_job(step.description, agent, session)
    # Registrado ANTES de despachar (T-FB008-US08-01): si se cancela el
    # plan mientras este paso está en curso, `request_cancellation(plan)`
    # necesita encontrar este `job` para reenviarle la cancelación
    # (reutiliza T-FB008-US05-01) — ver `job_plan_cancellation_registry`.
    set_active_job_for_plan(plan, job)
    try:
        dispatch_job(job, agent, runtime_instance, socket_name=socket_name)
    finally:
        clear_active_job_for_plan(plan)

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


def get_plan_progress(plan: JobPlan) -> dict[str, Any]:
    """Consulta el progreso de `plan` en cualquier momento: estado global
    del plan más el estado individual de cada paso, en orden."""
    return {
        "goal": plan.goal,
        "status": plan.status,
        "steps": [
            {
                "description": step.description,
                "mechanism": step.mechanism,
                "status": step.status,
            }
            for step in plan.steps
        ],
    }
