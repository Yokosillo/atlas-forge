"""Tests de la cola FIFO de veredictos hacia el Arquitecto
(T-AF022-US07-01 / T-AF022-US07-02)."""

import threading
import time
from unittest.mock import patch

import pytest

from atlas_forge.agents.arquitecto import ARQUITECTO_ROLE
from atlas_forge.core.session_lifecycle import activate, assign_agent
from atlas_forge.dispatcher.architect_verdict_queue import (
    _do_dispatch_verdict,
    _instance,
    enqueue_architect_verdict,
    get_verdict_queue_status,
)
from atlas_forge.models import Agent, DevelopmentSession


@pytest.fixture(autouse=True)
def _reset_queue():
    _instance.reset_for_testing()
    yield
    _instance.reset_for_testing()


def test_verdict_queue_fifo_order_and_no_overlap() -> None:
    """T-AF022-US07-02: fuerza dos finalizaciones casi simultáneas de
    Developer y confirma que el segundo veredicto no empieza hasta que el
    primero termina, sin solapamiento."""
    # step_events[0] = señal de "completado" que espera el primer dispatch
    # step_events[1] = señal de "completado" que espera el segundo dispatch
    step_events: list[threading.Event] = [threading.Event(), threading.Event()]
    processing_order: list[str] = []

    def controlled_dispatch(story_id, session, socket_name, reports_root=None):
        processing_order.append(story_id)
        # Bloquear hasta que el test libere la señal correspondiente.
        idx = len(processing_order) - 1
        step_events[idx].wait()

    with patch(
        "atlas_forge.dispatcher.architect_verdict_queue._do_dispatch_verdict",
        side_effect=controlled_dispatch,
    ):
        enqueue_architect_verdict("US-AF022-07-A", None, "default")
        enqueue_architect_verdict("US-AF022-07-B", None, "default")

        time.sleep(0.2)

        status = get_verdict_queue_status()
        assert status["active"] == "US-AF022-07-A", (
            f"Esperado active='US-AF022-07-A', obtenido {status}"
        )
        assert "US-AF022-07-B" in status["waiting"], (
            f"Esperado 'US-AF022-07-B' en waiting, obtenido {status}"
        )
        assert len(processing_order) == 1, (
            f"Solo el primer veredicto debe haberse empezado, "
            f"no {processing_order}"
        )

        # Liberar el primer veredicto.
        step_events[0].set()

        # Esperar a que el worker recoja el segundo.
        for _ in range(50):
            if len(processing_order) >= 2:
                break
            time.sleep(0.05)
        else:
            pytest.fail(
                "El segundo veredicto nunca empezó después de "
                "liberar el primero."
            )

        status = get_verdict_queue_status()
        assert status["active"] == "US-AF022-07-B", (
            f"Esperado active='US-AF022-07-B' tras liberar el primero, "
            f"obtenido {status}"
        )
        assert status["waiting"] == [], (
            f"No debe haber veredictos en espera, obtenido {status}"
        )

        assert processing_order == [
            "US-AF022-07-A",
            "US-AF022-07-B",
        ], f"Orden esperado FIFO, obtenido {processing_order}"

        # Liberar el segundo para que el worker no se quede bloqueado.
        step_events[1].set()
        # Esperar a que termine de procesar para evitar interferir con
        # el siguiente test.
        for _ in range(50):
            status = get_verdict_queue_status()
            if status["active"] is None:
                break
            time.sleep(0.05)


def test_get_verdict_queue_status_returns_empty_when_idle() -> None:
    """El estado consultable muestra active=None y waiting=[] cuando
    no hay veredictos en curso ni en cola."""
    status = get_verdict_queue_status()
    assert status["active"] is None
    assert status["waiting"] == []


def test_do_dispatch_verdict_finds_agent_by_arquitecto_role() -> None:
    """Regresión: `_do_dispatch_verdict` buscaba `agent.role == "critic"`
    (rol pre-rename) en vez de `ARQUITECTO_ROLE`, por lo que nunca
    encontraba al agente Arquitecto real y el veredicto se descartaba en
    silencio (`return` sin error). Este test ejercita la búsqueda de rol
    real, sin mockear `_do_dispatch_verdict` como el resto de la suite.

    Mockea `get_runtime_instance_for_agent` en el namespace de
    `dispatch_queue_worker` (T-AF008-US14-02, refactor 2026-08-17: la
    lógica real de despacho vive ahora en
    `dispatch_queue_worker.dispatch_architect_verdict`, invocada por
    `_do_dispatch_verdict` como delegación fina) — mockear la ruta
    original (`atlas_forge.runtime.agent_runtime_registry`) ya no intercepta
    la llamada real, porque `dispatch_queue_worker.py` la importa a su
    propio namespace en tiempo de import del módulo."""
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    architect = Agent(
        id="architect-1", name="Arquitecto", role=ARQUITECTO_ROLE,
        prompt="p", runtime_id="r1",
    )
    assign_agent(session, architect)

    with patch(
        "atlas_forge.dispatcher.dispatch_queue_worker.get_runtime_instance_for_agent",
        return_value=None,
    ) as mock_get_runtime:
        _do_dispatch_verdict("US-AF022-99", session, "default")

    mock_get_runtime.assert_called_once_with(architect.id)


def test_do_dispatch_verdict_does_not_find_agent_by_old_critic_role() -> None:
    """Contraprueba de la regresión anterior: un agente con el rol viejo
    `"critic"` NO debe ser encontrado por `_do_dispatch_verdict` — solo
    `ARQUITECTO_ROLE` es válido tras el rename de T-AF022-US01-03."""
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    old_critic = Agent(
        id="critic-1", name="Critico", role="critic",
        prompt="p", runtime_id="r1",
    )
    assign_agent(session, old_critic)

    with patch(
        "atlas_forge.dispatcher.dispatch_queue_worker.get_runtime_instance_for_agent",
    ) as mock_get_runtime:
        _do_dispatch_verdict("US-AF022-99", session, "default")

    mock_get_runtime.assert_not_called()


def test_verdict_queue_enqueue_does_not_block() -> None:
    """`enqueue_architect_verdict` retorna inmediatamente (no bloquea),
    incluso si el worker está ocupado procesando otro veredicto."""
    step_events: list[threading.Event] = [threading.Event()]

    def blocking_dispatch(*args, **kwargs):
        step_events[0].wait()

    with patch(
        "atlas_forge.dispatcher.architect_verdict_queue._do_dispatch_verdict",
        side_effect=blocking_dispatch,
    ):
        enqueue_architect_verdict("US-AF022-07-C", None, "default")
        time.sleep(0.1)

        start = time.monotonic()
        enqueue_architect_verdict("US-AF022-07-D", None, "default")
        elapsed = time.monotonic() - start

        assert elapsed < 0.5, (
            f"enqueue_architect_verdict bloqueó {elapsed:.2f}s — "
            f"debe retornar inmediatamente"
        )

        status = get_verdict_queue_status()
        assert status["active"] == "US-AF022-07-C"
        assert "US-AF022-07-D" in status["waiting"]

        step_events[0].set()
        for _ in range(50):
            status = get_verdict_queue_status()
            if status["active"] is None:
                break
            time.sleep(0.05)
