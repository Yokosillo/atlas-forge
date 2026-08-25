"""Aislamiento de estado entre tests + división de suite unit/integration
(T-AF025-US04-02, US-AF025-04).

## División de suite (marcador `unit`)

`run_tests` ejecuta por defecto el subconjunto DETERMINISTA y rápido de la
suite — los tests marcados `unit` (aquí, vía `pytest_collection_modifyitems`:
todo módulo NO listado en `INTEGRATION_MODULES` se etiqueta `unit`). Los
módulos `integration` refieren tmux real / agentes reales / backend en vivo
(arrancan sesiones y procesos que, al correr la suite completa de forma
secuencial, contaminaban el estado y colgaban la ejecución). Con esto el
ciclo Tester corre `pytest tests -m unit` (rápido, determinista, sin
cuelgues); la integración completa queda disponible vía `scope=all` de
`run_tests` (o `pytest tests` a secas).

Modelo de "etiquetar según la decisión" (criterio de la Task): los tests NO
se mueven; se MARCA con `unit`/`integration` a nivel de módulo desde este
hook, sin editar cada fichero.

## Aislamiento de estado entre tests (sesión)

Los módulos de integración usan sockets tmux aislados `atlas_forge-test-*`
(`pytest.fixture isolated_socket` en `test_api_routes_agents.py` y
`running_backend` en `tests/fixtures/backend_server.py`). Si un test falla a
medio camino, su socket puede quedar vivo y la siguiente apertura de un
`TestClient(create_app())` que reconcilia sesiones
(`reconcile_session_agents`) puede colgarse. Esta fixtura de sesión limpia
cualquier socket tmux huérfano `atlas_forge-test-*` ANTES de arrancar cada
sesión pytest, garantizando un arranque limpio y reproducible.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# Módulos de INTEGRACIÓN: usan tmux real / agentes reales / backend en vivo.
# Se excluyen del subconjunto `unit` que `run_tests` ejecuta por defecto.
INTEGRATION_MODULES = frozenset({
    "test_af023_us02_flow.py",
    "test_agent_liveness.py",
    "test_agent_persistent.py",
    "test_agent_registry.py",
    "test_agent_runtime_preference.py",
    "test_agent_runtime_registry.py",
    "test_agent_stop.py",
    "test_api_agent_persistent.py",
    # T-AF025-US04-02 (hallazgo del Tester): este módulo NO puede ir en el
    # subconjunto `unit` — `test_action_list_is_known` hace
    # `POST /project/actions/testear` → la acción `testear` ejecuta
    # `pytest -m unit` anidado, que re-colecta este mismo test y vuelve a
    # anidar → recursión infinita hasta el timeout de 1800s por-call. Se
    # excluye de `unit` (queda disponible con `scope=all`).
    "test_api_project_actions.py",
    "test_api_routes_agent_release.py",
    "test_api_routes_agent_stop.py",
    "test_api_routes_agents.py",
    "test_api_routes_jobs.py",
    "test_api_routes_launch_development.py",
    "test_api_routes_plan_cancel.py",
    "test_api_routes_plans.py",
    "test_api_routes_project_selection.py",
    "test_auditor_oss_agent.py",
    "test_developer_agent.py",
    "test_dispatch_queue_worker.py",
    "test_job_cancellation.py",
    "test_job_chaining.py",
    "test_job_dispatch.py",
    "test_job_plan_cancellation.py",
    "test_job_plan_dispatch.py",
    "test_job_plan_flow.py",
    "test_launch_agent.py",
    "test_launch_agent_initial_job.py",
    "test_opencode_runtime.py",
    "test_persistent_watcher.py",
    "test_project_governance.py",
    "test_runtime_generic.py",
    "test_scribe_dispatch_integration.py",
    "test_session_limit_watcher.py",
    "test_session_reconciliation.py",
    "test_session_reconciliation_ignored.py",
    "test_start_runtime_sends_prompt.py",
    "test_t_af023_us05_03.py",
    "test_tmux_capture.py",
    "test_tmux_manager.py",
    "test_ui_tester_queue.py",
    "test_ux_agent.py",
    "test_ws_agent_pane.py",
})


def pytest_collection_modifyitems(config, items):
    """Marca `unit` todo módulo test que no esté en la lista de integración —
    el subconjunto determinista que `run_tests` ejecuta por defecto (y que
    `test_workspace_generic_scripts::_any_unit_marker` detecta como
    "el proyecto sí divide la suite")."""
    for item in items:
        module_name = Path(item.module.__file__).name
        if module_name not in INTEGRATION_MODULES:
            item.add_marker(pytest.mark.unit)


@pytest.fixture(scope="session", autouse=True)
def _clean_isolated_tmux_sockets_before_session():
    """Limpia los sockets tmux aislados `atlas_forge-test-*` que hayan
    quedado vivos de una ejecución anterior (crash a mitad de un test de
    integración): una sesión tmux huérfana en el arranque de otro test
    envenena la reconciliación del `_lifespan` y es la causa conocida del
    cuelgue de la suite completa. Mejor esfuerzo: si `libtmux` no está
    disponible o falla, no se aborta la sesión pytest."""
    try:
        import libtmux

        server = libtmux.Server()
        for session in list(server.sessions):
            socket_name = getattr(session, "socket_name", "") or ""
            if socket_name.startswith("atlas_forge-test-"):
                try:
                    libtmux.Server(socket_name=socket_name).kill()
                except Exception:
                    pass
    except Exception:
        pass
    yield