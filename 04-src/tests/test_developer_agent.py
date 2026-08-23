import time
import uuid
from pathlib import Path

import libtmux
import pytest

from atlas_forge.agents import (
    DEVELOPER_PROMPT,
    DEVELOPER_ROLE,
    get_agent_state,
    mark_unavailable,
    mark_working,
    register_developer,
    release_agent,
)
from atlas_forge.core import activate, list_agents
from atlas_forge.models import Agent, DevelopmentSession, Runtime
from atlas_forge.runtime import is_runtime_alive


@pytest.fixture
def isolated_socket():
    """Aísla los tests de esta Task en su propio servidor tmux, para no
    interferir con sesiones tmux reales del entorno (nunca lanzar el
    binario real de Claude Code/OpenCode en tests — misma precaución ya
    aplicada en las Tasks de AF-004 y T-AF005-US01-01)."""
    name = f"atlas_forge-test-{uuid.uuid4().hex[:8]}"
    yield name
    try:
        libtmux.Server(socket_name=name).kill()
    except Exception:
        pass


def _test_runtime() -> Runtime:
    # Comando de prueba inocuo (`sleep`), NO el binario real de Claude
    # Code/OpenCode.
    return Runtime(
        id="test-runtime",
        name="Test Runtime",
        type="test",
        command="sleep",
        args=["5"],
    )


def _active_session() -> DevelopmentSession:
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    return session


def test_developer_registers_with_fixed_role_and_prompt(
    isolated_socket: str, tmp_path
) -> None:
    session = _active_session()
    runtime = _test_runtime()

    agent, _ = register_developer(
        session, runtime, str(tmp_path), socket_name=isolated_socket
    )

    assert agent.role == DEVELOPER_ROLE
    # T-AF005-US01-07: el prompt ya no es exactamente DEVELOPER_PROMPT —
    # incluye siempre la capa de identidad del proyecto activo a
    # continuación.
    assert agent.prompt.startswith(DEVELOPER_PROMPT)
    assert tmp_path.name in agent.prompt


def test_developer_associated_with_runtime_and_active_session(
    isolated_socket: str, tmp_path
) -> None:
    session = _active_session()
    runtime = _test_runtime()

    agent, runtime_instance = register_developer(
        session, runtime, str(tmp_path), socket_name=isolated_socket
    )
    time.sleep(0.3)

    assert agent in list_agents(session)
    assert agent.runtime_id == runtime.id
    assert is_runtime_alive(runtime_instance, socket_name=isolated_socket) is True


def test_developer_state_can_be_queried_idle_working_unavailable(
    isolated_socket: str, tmp_path
) -> None:
    session = _active_session()
    runtime = _test_runtime()

    agent, _ = register_developer(
        session, runtime, str(tmp_path), socket_name=isolated_socket
    )

    assert get_agent_state(agent)["status"] == "idle"

    mark_working(agent)
    assert get_agent_state(agent)["status"] == "working"


def test_registering_developer_twice_creates_two_distinct_instances(
    isolated_socket: str, tmp_path
) -> None:
    """T-AF005-US01-04: `register_developer` deja de reutilizar — cada
    llamada crea un `Agent`/`RuntimeInstance` NUEVO, a diferencia del
    comportamiento anterior (y del que sigue teniendo Critic, ver
    `test_critic_agent.py`). Verificado con tmux real: dos sesiones
    distintas, ambas vivas simultáneamente."""
    session = _active_session()
    runtime = _test_runtime()

    first_agent, first_instance = register_developer(
        session, runtime, str(tmp_path), socket_name=isolated_socket
    )
    time.sleep(0.3)

    second_agent, second_instance = register_developer(
        session, runtime, str(tmp_path), socket_name=isolated_socket
    )
    time.sleep(0.3)

    # Agent distinto (id distinto), RuntimeInstance distinto (sesión tmux
    # distinta) — nunca la misma instancia devuelta dos veces.
    assert second_agent is not first_agent
    assert second_agent.id != first_agent.id
    assert second_instance.session_name != first_instance.session_name

    # Ambas sesiones tmux reales están vivas SIMULTÁNEAMENTE (criterio de
    # aceptación explícito) — no se detiene la primera al lanzar la
    # segunda.
    assert is_runtime_alive(first_instance, socket_name=isolated_socket) is True
    assert is_runtime_alive(second_instance, socket_name=isolated_socket) is True

    # Dos Developer en la sesión, no uno reutilizado.
    developers = [a for a in list_agents(session) if a.role == DEVELOPER_ROLE]
    assert len(developers) == 2


def test_each_developer_instance_has_a_distinguishable_name(
    isolated_socket: str, tmp_path
) -> None:
    """Criterio de aceptación: 'cada Developer lanzado tiene un nombre
    distinguible en GET /agents (no todos aparecen como Developer
    indistinguibles)'. Esquema elegido: numeración incremental
    (Developer-1, Developer-2, ...) — ver justificación completa en el
    docstring de `_next_developer_name`, `agents/developer.py`."""
    session = _active_session()
    runtime = _test_runtime()
    # state_dir aislado (T-AF005-US01-09): estos tests suponen el límite por
    # defecto (MAX_SIMULTANEOUS_DEVELOPERS=3), no el que pudiera tener el
    # state_dir real del proceso — se aisla para no depender del entorno.
    state_dir = tmp_path / "state"

    first_agent, _ = register_developer(
        session, runtime, str(tmp_path), socket_name=isolated_socket, state_dir=state_dir
    )
    second_agent, _ = register_developer(
        session, runtime, str(tmp_path), socket_name=isolated_socket, state_dir=state_dir
    )
    third_agent, _ = register_developer(
        session, runtime, str(tmp_path), socket_name=isolated_socket, state_dir=state_dir
    )

    assert first_agent.name == "Developer-1"
    assert second_agent.name == "Developer-2"
    assert third_agent.name == "Developer-3"
    assert len({first_agent.name, second_agent.name, third_agent.name}) == 3


def test_session_name_for_does_not_collide_between_multiple_developers(
    isolated_socket: str, tmp_path
) -> None:
    """Criterio de aceptación explícito (T-AF030-US01-01): verificar que
    `session_name_for` sigue generando nombres de sesión tmux únicos para
    cada Developer nuevo del mismo proyecto bajo el esquema nuevo
    (determinista `developer-N-<project_name>`, no el UUID opaco
    anterior) — el número de instancia visible en `agent.name`
    ("Developer-1"/"Developer-2"/"Developer-3") es lo que garantiza la
    ausencia de colisión aquí, verificado explícitamente en vez de
    asumirlo."""
    from atlas_forge.runtime import session_name_for

    session = _active_session()
    runtime = _test_runtime()
    project_path = str(tmp_path)
    state_dir = tmp_path / "state"

    agents_and_instances = [
        register_developer(
            session, runtime, project_path, socket_name=isolated_socket, state_dir=state_dir
        )
        for _ in range(3)
    ]

    session_names = {
        session_name_for(runtime, agent, project_path)
        for agent, _instance in agents_and_instances
    }
    assert len(session_names) == 3  # las 3 llamadas a session_name_for son únicas

    # Coincide exactamente con el session_name real que start_runtime ya
    # asignó a cada RuntimeInstance devuelto.
    for agent, instance in agents_and_instances:
        assert session_name_for(runtime, agent, project_path) == instance.session_name

    # Esquema nuevo: cada nombre incluye el número visible en agent.name y
    # el nombre del proyecto (T-AF030-US01-01, criterio 3 de US-AF030-01).
    project_name = Path(project_path).name.lower()
    for agent, instance in agents_and_instances:
        expected_role_part = agent.name.lower()
        assert instance.session_name == f"{expected_role_part}-{project_name}"


def test_t_af005_us01_08_killing_developer_1_does_not_produce_a_second_developer_2(
    isolated_socket: str, tmp_path
) -> None:
    """T-AF005-US01-08: con Developer-1 y Developer-2 vivos, matar
    Developer-1 (T-AF024-US12-02 lo retira de `session.agents`) y lanzar
    un Developer nuevo NO produce un segundo Developer-2 colisionando con
    el vivo — el nuevo recibe un número único entre los vivos
    (Developer-3), y los nombres de sesión tmux reales siguen siendo todos
    distintos entre sí."""
    from atlas_forge.agents.stop import stop_agent
    from atlas_forge.runtime import session_name_for

    session = _active_session()
    runtime = _test_runtime()
    project_path = str(tmp_path)

    first, first_instance = register_developer(
        session, runtime, project_path, socket_name=isolated_socket
    )
    time.sleep(0.3)
    second, second_instance = register_developer(
        session, runtime, project_path, socket_name=isolated_socket
    )
    time.sleep(0.3)

    assert first.name == "Developer-1"
    assert second.name == "Developer-2"

    # Matar Developer-1: se retira de session.agents (T-AF024-US12-02).
    stop_agent(first, session, socket_name=isolated_socket)
    assert first not in list_agents(session)

    # El siguiente lanzamiento NO reutiliza el número 2, aún en uso por
    # el Developer-2 vivo — recibe Developer-3 (criterios 1 y 3).
    third, third_instance = register_developer(
        session, runtime, project_path, socket_name=isolated_socket
    )
    time.sleep(0.3)

    assert third.name == "Developer-3"
    assert third.name != second.name

    # Criterio 2: los nombres de sesión tmux de los Developers vivos son
    # siempre distintos entre sí, y coinciden con el nombre real de cada
    # RuntimeInstance (sin colisión de sesión).
    live = (second, second_instance), (third, third_instance)
    assert len({session_name_for(runtime, agent, project_path) for agent, _ in live}) == 2
    for agent, instance in live:
        assert session_name_for(runtime, agent, project_path) == instance.session_name
    assert is_runtime_alive(second_instance, socket_name=isolated_socket) is True
    assert is_runtime_alive(third_instance, socket_name=isolated_socket) is True


def test_register_developer_rejects_when_limit_exceeded(
    isolated_socket: str, tmp_path
) -> None:
    """T-AF022-US06-02: superar MAX_SIMULTANEOUS_DEVELOPERS se rechaza con
    mensaje claro, no falla en silencio."""
    from atlas_forge.agents.developer import MAX_SIMULTANEOUS_DEVELOPERS

    session = _active_session()
    runtime = _test_runtime()
    state_dir = tmp_path / "state"

    for i in range(MAX_SIMULTANEOUS_DEVELOPERS):
        register_developer(
            session, runtime, str(tmp_path), socket_name=isolated_socket, state_dir=state_dir
        )

    developers = [a for a in list_agents(session) if a.role == DEVELOPER_ROLE]
    assert len(developers) == MAX_SIMULTANEOUS_DEVELOPERS

    with pytest.raises(RuntimeError, match="No se puede lanzar otro Developer"):
        register_developer(
            session, runtime, str(tmp_path), socket_name=isolated_socket, state_dir=state_dir
        )


def test_register_developer_reads_limit_from_system_preferences(
    isolated_socket: str, tmp_path
) -> None:
    """US-AF024-12: el límite ya no es la constante fija — si hay una
    preferencia de sistema guardada, `register_developer` la respeta en
    vez de `MAX_SIMULTANEOUS_DEVELOPERS`."""
    from atlas_forge.system_preferences import save_system_preferences

    state_dir = tmp_path / "state"
    save_system_preferences({"max_simultaneous_developers": 1}, state_dir=state_dir)

    session = _active_session()
    runtime = _test_runtime()

    register_developer(
        session, runtime, str(tmp_path), socket_name=isolated_socket, state_dir=state_dir
    )

    with pytest.raises(RuntimeError, match="máximo 1"):
        register_developer(
            session, runtime, str(tmp_path), socket_name=isolated_socket, state_dir=state_dir
        )


def test_register_developer_without_saved_preference_uses_default(
    isolated_socket: str, tmp_path
) -> None:
    """Sin preferencia guardada (`state_dir` vacío), el comportamiento es
    idéntico al anterior: usa `MAX_SIMULTANEOUS_DEVELOPERS` (3) como
    default."""
    from atlas_forge.agents.developer import MAX_SIMULTANEOUS_DEVELOPERS

    state_dir = tmp_path / "empty_state"
    session = _active_session()
    runtime = _test_runtime()

    for _ in range(MAX_SIMULTANEOUS_DEVELOPERS):
        register_developer(
            session, runtime, str(tmp_path), socket_name=isolated_socket, state_dir=state_dir
        )

    with pytest.raises(RuntimeError, match="No se puede lanzar otro Developer"):
        register_developer(
            session, runtime, str(tmp_path), socket_name=isolated_socket, state_dir=state_dir
        )


def test_register_developer_honors_explicit_developer_number(
    isolated_socket: str, tmp_path
) -> None:
    """T-AF005-US01-08 (2026-08-18): los Developers son slots fijos e
    independientes (Developer-1/2/3, criterio nuevo de US-AF005-01) — al
    indicar `developer_number`, el agente nace con ESE número aunque no
    sea el siguiente por orden de lanzamiento. Lanzar fuera de orden
    (primero el 2 y luego el 1) respeta cada slot."""
    session = _active_session()
    runtime = _test_runtime()

    second_agent, _ = register_developer(
        session, runtime, str(tmp_path), socket_name=isolated_socket,
        developer_number=2,
    )
    first_agent, _ = register_developer(
        session, runtime, str(tmp_path), socket_name=isolated_socket,
        developer_number=1,
    )

    assert second_agent.name == "Developer-2"
    assert first_agent.name == "Developer-1"


def test_register_developer_rejects_duplicate_explicit_number(
    isolated_socket: str, tmp_path
) -> None:
    """T-AF005-US01-08: relanzar el slot de un Developer aún vivo se
    rechaza con mensaje claro — un número nunca se reutiliza mientras su
    Developer siga vivo (garantiza nombres únicos y ausencia de colisión
    de sesión tmux)."""
    session = _active_session()
    runtime = _test_runtime()

    first, _ = register_developer(
        session, runtime, str(tmp_path), socket_name=isolated_socket,
        developer_number=2,
    )
    assert first.name == "Developer-2"

    with pytest.raises(RuntimeError, match="Ya existe un Developer 'Developer-2'"):
        register_developer(
            session, runtime, str(tmp_path), socket_name=isolated_socket,
            developer_number=2,
        )


def test_register_developer_rejects_invalid_developer_number(
    isolated_socket: str, tmp_path
) -> None:
    """T-AF005-US01-08: un `developer_number` < 1 es inválido (no existe
    el slot Developer-0)."""
    session = _active_session()
    runtime = _test_runtime()

    with pytest.raises(RuntimeError, match="Número de Developer inválido"):
        register_developer(
            session, runtime, str(tmp_path), socket_name=isolated_socket,
            developer_number=0,
        )


def _build_developer(status: str, name: str, runtime_id: str) -> Agent:
    agent = Agent(
        id=f"d-{uuid.uuid4().hex[:8]}",
        name=name,
        role=DEVELOPER_ROLE,
        prompt="p",
        runtime_id=runtime_id,
        status="idle",
    )
    if status == "working":
        mark_working(agent)
    elif status == "unavailable":
        mark_unavailable(agent)
    elif status != "idle":
        agent.status = status
    return agent


def _stub_register_agent(monkeypatch):
    """Sustituye `register_agent` (que lanza un runtime real tmux) por un
    stub inerte — permite probar SOLO la lógica de límite/duplicados de
    `register_developer` de forma determinista sin tocar tmux."""
    from atlas_forge.agents.registry import register_agent

    def fake_register(name, role, prompt, runtime, session, project_path, socket_name=None):
        agent = Agent(
            id=f"d-{uuid.uuid4().hex[:8]}",
            name=name,
            role=role,
            prompt=prompt,
            runtime_id=runtime.id,
        )
        session.agents.append(agent)
        return agent, None

    monkeypatch.setattr("atlas_forge.agents.developer.register_agent", fake_register)


def test_register_developer_limit_counts_only_active_developers(
    isolated_socket: str, tmp_path, monkeypatch
) -> None:
    """T-AF005-US01-09 criterio 1: con Developer-1 `unavailable` y
    Developer-2 `working` (límite 2), `register_developer` cuenta 1 activo
    → se puede lanzar un Developer nuevo. Determinista, sin tmux (stub de
    `register_agent`)."""
    from atlas_forge.system_preferences import save_system_preferences

    _stub_register_agent(monkeypatch)

    state_dir = tmp_path / "state"
    save_system_preferences({"max_simultaneous_developers": 2}, state_dir=state_dir)

    session = _active_session()
    session.agents.append(_build_developer("unavailable", "Developer-1", "r1"))
    session.agents.append(_build_developer("working", "Developer-2", "r2"))

    # No debe lanzar RuntimeError de límite: solo 1 activo (< 2).
    agent, _ = register_developer(
        session,
        _test_runtime(),
        str(tmp_path),
        socket_name=isolated_socket,
        state_dir=state_dir,
    )
    assert agent.role == DEVELOPER_ROLE


def test_register_developer_limit_counts_only_active_developers_with_stopped(
    isolated_socket: str, tmp_path, monkeypatch
) -> None:
    """T-AF005-US01-09 criterio 1 (borde): un Developer `stopped` (detenido a
    propósito) tampoco ocupa plaza del límite, igual que un `unavailable`.
    Con límite 1 y un solo `stopped` en la sesión (0 activos), `register_developer`
    debe poder lanzar un Developer nuevo."""
    from atlas_forge.system_preferences import save_system_preferences

    _stub_register_agent(monkeypatch)

    state_dir = tmp_path / "state"
    save_system_preferences({"max_simultaneous_developers": 1}, state_dir=state_dir)

    session = _active_session()
    session.agents.append(_build_developer("stopped", "Developer-1", "r1"))

    agent, _ = register_developer(
        session,
        _test_runtime(),
        str(tmp_path),
        socket_name=isolated_socket,
        state_dir=state_dir,
    )
    assert agent.role == DEVELOPER_ROLE


def test_register_developer_limit_still_counts_two_active_developers(
    isolated_socket: str, tmp_path, monkeypatch
) -> None:
    """T-AF005-US01-09: con DOS activos (`working` + `idle`) el límite se
    sigue respetando — un `unavailable` adicional no se cuenta, pero dos
    activos sí bloquean."""
    from atlas_forge.system_preferences import save_system_preferences

    _stub_register_agent(monkeypatch)

    state_dir = tmp_path / "state"
    save_system_preferences({"max_simultaneous_developers": 2}, state_dir=state_dir)

    session = _active_session()
    session.agents.append(_build_developer("working", "Developer-1", "r1"))
    session.agents.append(_build_developer("idle", "Developer-2", "r2"))
    session.agents.append(_build_developer("unavailable", "Developer-3", "r3"))

    with pytest.raises(RuntimeError, match="No se puede lanzar otro Developer"):
        register_developer(
            session,
            _test_runtime(),
            str(tmp_path),
            socket_name=isolated_socket,
            state_dir=state_dir,
        )


def test_releasing_unavailable_unblocks_relaunching_its_slot(
    isolated_socket: str, tmp_path, monkeypatch
) -> None:
    """T-AF005-US01-09 criterio 3: tras liberar un `unavailable` con nombre
    "Developer-N", lanzar con `developer_number: N` vuelve a funcionar (el
    duplicado ya no está). Determinista, sin tmux."""
    from atlas_forge.system_preferences import save_system_preferences

    _stub_register_agent(monkeypatch)

    state_dir = tmp_path / "state"
    save_system_preferences({"max_simultaneous_developers": 2}, state_dir=state_dir)

    session = _active_session()
    crashed = _build_developer("unavailable", "Developer-2", "r2")
    session.agents.append(crashed)

    # Antes de liberar, el slot Developer-2 está bloqueado por el duplicado.
    with pytest.raises(RuntimeError, match="Ya existe un Developer 'Developer-2'"):
        register_developer(
            session,
            _test_runtime(),
            str(tmp_path),
            socket_name=isolated_socket,
            state_dir=state_dir,
            developer_number=2,
        )

    release_agent(crashed, session)
    assert all(a.name != "Developer-2" for a in list_agents(session))

    # Tras liberar, relanzar el slot vuelve a funcionar.
    agent, _ = register_developer(
        session,
        _test_runtime(),
        str(tmp_path),
        socket_name=isolated_socket,
        state_dir=state_dir,
        developer_number=2,
    )
    assert agent.name == "Developer-2"

