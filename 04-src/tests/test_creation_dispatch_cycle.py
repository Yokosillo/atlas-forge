"""Tests del quinto nivel del worker: ciclo de despacho de peticiones de
creación hacia el Arquitecto (T-AF036-US20-07, US-AF036-20).

`run_creation_dispatch_cycle` recoge la siguiente petición `pending` (FIFO)
de `creation_queue` y, SOLO con el Arquitecto `idle` y listo, le despacha un
Job NO BLOQUEANTE con la descripción libre + contexto, registrando la petición
`in_flight` con su `report_file` — sin generar ni escribir entidades.

Cubre los criterios de aceptación de la Task, deterministas SIN tmux (mismo
patrón que `test_us_landing_dispatch_*` de `test_dispatch_queue_worker.py`):
- petición pending + Arquitecto idle y listo -> despacha exactamente 1 petición
  (request_id devuelto, estado in_flight, registro `inflight_creation`);
- Arquitecto ocupado / sin runtime / no listo -> no despacha, petición pending
  (reintento en el siguiente ciclo);
- con varias pending -> despacha la más antigua (FIFO);
- integrado en `_run_loop` como quinto ciclo (ver `DispatchQueueWorker`);
- no escribe ninguna entidad de backlog."""

from pathlib import Path

from atlas_forge.core.session_lifecycle import activate, assign_agent
from atlas_forge.dispatcher.creation_queue import (
    STATUS_IN_FLIGHT,
    STATUS_PENDING,
    enqueue_creation_request,
    get_creation_requests,
)
from atlas_forge.dispatcher.dispatch_queue_worker import (
    run_creation_dispatch_cycle,
)
from atlas_forge.models import Agent, DevelopmentSession


def _mock_creation_send(tmp_path, monkeypatch) -> Path:
    """Sustituye el envío no bloqueante del Job de creación por un doble
    determinista SIN tmux: `dispatch_job_send` devuelve un fichero de reporte
    y `get_runtime_instance_for_agent` entrega un runtime falso (que
    `is_agent_ready_for_input` considera listo, ver job_dispatch.py)."""
    from atlas_forge.agents.lifecycle import mark_working
    from atlas_forge.dispatcher import dispatch_queue_worker as worker_module
    from atlas_forge.dispatcher.job_lifecycle import mark_running

    class _FakeRuntime:
        session_name = "test-session"

    monkeypatch.setattr(worker_module, "get_runtime_instance_for_agent", lambda agent_id: _FakeRuntime())

    report_path = tmp_path / "reporte-creacion.txt"

    def _fake_send(job, agent, runtime_instance, socket_name=None):
        mark_running(job)
        mark_working(agent)
        return report_path

    monkeypatch.setattr(worker_module, "dispatch_job_send", _fake_send)
    return report_path


def _architect_session():
    architect = Agent(id="arch-1", name="Arquitecto", role="arquitecto", prompt="p", runtime_id="r1")
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    assign_agent(session, architect)
    return session, architect


def _seed_us_request(project_root: Path, epic_id: str, description: str, ts: str):
    return enqueue_creation_request(
        project_root, "proj", tipo="us", description=description, epic_id=epic_id, ts=ts,
    )


def test_creation_dispatch_despacha_peticion_pending_y_la_marca_in_flight(
    tmp_path, monkeypatch,
) -> None:
    """Con una petición `pending` y Arquitecto idle y listo, se despacha
    exactamente 1 petición: request_id devuelto, entrada `in_flight` con
    `report_file`, y el Job registrado en `inflight_creation`."""
    project_root = tmp_path / "project"
    report_path = _mock_creation_send(tmp_path, monkeypatch)
    request = _seed_us_request(project_root, "AF-999", "Crear US para filtrar por prioridad.", "2026-08-25T00:00:00+00:00")

    session, architect = _architect_session()
    inflight_creation = {}
    result = run_creation_dispatch_cycle(
        project_root, "proj", session, inflight_creation=inflight_creation,
    )

    assert result == request.request_id
    # La petición queda in_flight con su report_file persistido.
    entry = get_creation_requests(project_root, "proj")[0]
    assert entry.status == STATUS_IN_FLIGHT
    assert entry.report_file == str(report_path)
    # Registro en vuelo.
    assert set(inflight_creation) == {request.request_id}
    infl = inflight_creation[request.request_id]
    assert infl.tipo == "us"
    assert infl.architect_agent_id == "arch-1"
    assert infl.report_file == report_path
    assert infl.job is not None
    assert infl.dispatched_at > 0
    # No escribe ninguna entidad de backlog.
    assert not (project_root / "02-backlog").exists()


def test_creation_dispatch_devuelve_none_con_arquitecto_ocupado(tmp_path, monkeypatch) -> None:
    """Con una petición pending y el Arquitecto NO idle (working por un
    veredicto/aterrizaje en curso), no se despacha y la petición sigue
    `pending` (reintento en el siguiente ciclo)."""
    project_root = tmp_path / "project"
    _mock_creation_send(tmp_path, monkeypatch)
    _seed_us_request(project_root, "AF-999", "Descripción.", "2026-08-25T00:00:00+00:00")

    from atlas_forge.agents.lifecycle import mark_working

    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    architect = Agent(id="arch-1", name="Arquitecto", role="arquitecto", prompt="p", runtime_id="r1")
    assign_agent(session, architect)
    mark_working(architect)  # Ocupado: no recibe la petición.

    result = run_creation_dispatch_cycle(project_root, "proj", session, inflight_creation={})

    assert result is None
    assert get_creation_requests(project_root, "proj")[0].status == STATUS_PENDING


def test_creation_dispatch_devuelve_none_sin_arquitecto(tmp_path, monkeypatch) -> None:
    """Sin ningún Arquitecto en la sesión, no se despacha y la petición sigue
    pending."""
    project_root = tmp_path / "project"
    _mock_creation_send(tmp_path, monkeypatch)
    _seed_us_request(project_root, "AF-999", "Descripción.", "2026-08-25T00:00:00+00:00")

    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)

    result = run_creation_dispatch_cycle(project_root, "proj", session, inflight_creation={})

    assert result is None
    assert get_creation_requests(project_root, "proj")[0].status == STATUS_PENDING


def test_creation_dispatch_devuelve_none_sin_runtime(tmp_path, monkeypatch) -> None:
    """Sin runtime registrado para el Arquitecto, no se despacha y la petición
    queda pending (se reintenta en el siguiente ciclo)."""
    project_root = tmp_path / "project"
    from atlas_forge.dispatcher import dispatch_queue_worker as worker_module

    monkeypatch.setattr(worker_module, "get_runtime_instance_for_agent", lambda agent_id: None)
    _seed_us_request(project_root, "AF-999", "Descripción.", "2026-08-25T00:00:00+00:00")

    session, _ = _architect_session()
    result = run_creation_dispatch_cycle(project_root, "proj", session, inflight_creation={})

    assert result is None
    assert get_creation_requests(project_root, "proj")[0].status == STATUS_PENDING


def test_creation_dispatch_devuelve_none_agente_no_ready(tmp_path, monkeypatch) -> None:
    """Gate de readiness: si el Arquitecto no acepta input, la petición queda
    pending (no se despacha)."""
    project_root = tmp_path / "project"
    from atlas_forge.dispatcher import dispatch_queue_worker as worker_module

    class _NoReadiness:
        session_name = "test-session"

    monkeypatch.setattr(
        worker_module, "get_runtime_instance_for_agent", lambda agent_id: _NoReadiness()
    )
    monkeypatch.setattr(worker_module, "is_agent_ready_for_input", lambda *a, **k: False)
    _seed_us_request(project_root, "AF-999", "Descripción.", "2026-08-25T00:00:00+00:00")

    session, _ = _architect_session()
    result = run_creation_dispatch_cycle(project_root, "proj", session, inflight_creation={})

    assert result is None
    assert get_creation_requests(project_root, "proj")[0].status == STATUS_PENDING


def test_creation_dispatch_fifo_despacha_la_mas_antigua(tmp_path, monkeypatch) -> None:
    """Con varias peticiones pending, se despacha la más antigua (FIFO por
    created_at), dejando la otra pending."""
    project_root = tmp_path / "project"
    _mock_creation_send(tmp_path, monkeypatch)
    primera = _seed_us_request(project_root, "AF-999", "Primera petición.", "2026-08-25T00:00:00+00:00")
    _seed_us_request(project_root, "AF-999", "Segunda petición.", "2026-08-25T00:00:01+00:00")

    session, _ = _architect_session()
    inflight_creation = {}
    result = run_creation_dispatch_cycle(project_root, "proj", session, inflight_creation=inflight_creation)

    assert result == primera.request_id
    requests = {r.request_id: r for r in get_creation_requests(project_root, "proj")}
    assert requests[primera.request_id].status == STATUS_IN_FLIGHT
    # La segunda sigue pending (una petición por ciclo).
    segunda = [r for r in get_creation_requests(project_root, "proj") if r.request_id != primera.request_id][0]
    assert segunda.status == STATUS_PENDING
    assert set(inflight_creation) == {primera.request_id}


def test_creation_dispatch_no_despacha_con_peticion_ya_en_vuelo(tmp_path, monkeypatch) -> None:
    """El Arquitecto es secuencial: con una petición ya en vuelo
    (`inflight_creation` no vacío), no se despacha otra en el mismo ciclo."""
    project_root = tmp_path / "project"
    _mock_creation_send(tmp_path, monkeypatch)
    _seed_us_request(project_root, "AF-999", "Descripción.", "2026-08-25T00:00:00+00:00")

    session, _ = _architect_session()

    # Simulación: ya hay una petición en vuelo (de un ciclo anterior).
    from atlas_forge.dispatcher.dispatch_queue_worker import InFlightCreationJob
    from atlas_forge.models import Job

    inflight_creation = {
        "existing": InFlightCreationJob(
            request_id="existing",
            tipo="us",
            architect_agent_id="arch-1",
            report_file=tmp_path / "r",
            job=Job(id="j", session_id="s", agent_id="arch-1", description="d", status="running"),
            dispatched_at=0.0,
        ),
    }

    result = run_creation_dispatch_cycle(
        project_root, "proj", session, inflight_creation=inflight_creation,
    )

    assert result is None
    # La petición nueva sigue pending; la en-vuelo no se tocó.
    requests = get_creation_requests(project_root, "proj")
    assert all(r.status == STATUS_PENDING for r in requests)


def test_creation_dispatch_no_escribe_entidades_de_backlog(tmp_path, monkeypatch) -> None:
    """Guardián: el ciclo de despacho NO genera ni escribe ninguna entidad
    del backlog (ni Epic ni US ni Task) — solo despacha la petición."""
    project_root = tmp_path / "project"
    _mock_creation_send(tmp_path, monkeypatch)
    _seed_us_request(project_root, "AF-999", "Descripción para una US.", "2026-08-25T00:00:00+00:00")

    session, _ = _architect_session()
    run_creation_dispatch_cycle(project_root, "proj", session, inflight_creation={})

    assert not (project_root / "02-backlog" / "user-stories").exists()
    assert not (project_root / "02-backlog" / "epics").exists()
    assert not (project_root / "02-backlog" / "tasks").exists()