"""Registro consultable de `RuntimeInstance` por `agent.id` (T-AF002-US03-00,
AF-002 Dashboard): cierra el gap de que `Agent` (AF-005) no guarda
ninguna referencia a su `RuntimeInstance` (AF-004) — hasta ahora ese dato
solo existía como valor de retorno de `register_agent`/`launch_agent` en
el momento del lanzamiento, y se perdía después. `dispatch_job`
(T-AF002-US03-01) necesita recuperar el `RuntimeInstance` del agente
destinatario para enviarle un Job desde la pantalla Jobs de la TUI.

## Decisión: registro nuevo en `runtime/`, no un campo en `Agent`

Se descarta añadir un campo a `models/agent.py`: acoplaría el modelo de
dominio de AF-005 (agentes conversacionales) a un detalle de AF-004
(runtimes/tmux) — mismo criterio ya aplicado en T-AF008-US03-02 para no
extender `DevelopmentSession` con el conteo de Jobs por agente. Se elige
un registro en memoria de proceso indexado por `agent.id`, mismo patrón
ya establecido en este proyecto para `_SessionRegistry`
(`session_registry.py`) y `_JobCountRegistry` (`job_count_registry.py`):
incluye `_reset_registry_for_tests()` para el mismo motivo (evitar que
los tests dependan del orden de ejecución de otros tests). Vive en
`runtime/` (no en `dashboard/`) porque opera exclusivamente sobre
`RuntimeInstance`, un concepto de AF-004, y no depende de nada de
`dashboard/` (que sí depende de `runtime/`, no al revés).

## Punto único de registro: `register_agent`

Se registra únicamente en `register_agent` (`agents/registry.py`) — el
único punto donde se invoca `start_runtime` de verdad. El caso de
reutilización (`register_agent_with_reuse`) no necesita registrar de
nuevo: `RuntimeInstance` es determinista a partir de `(agent.name,
project_path)` vía `session_name_for` (ver `runtime/generic.py`,
AF-030), así que la asociación ya registrada en el primer lanzamiento
sigue siendo válida —
duplicar el registro en el punto de reutilización no se pierde nada
(mismo `session_name`) pero tampoco aporta nada, y evita depender de que
todos los futuros llamadores de "reutilización" recuerden registrar
también.
"""


from atlas_forge.runtime.generic import RuntimeInstance


class _AgentRuntimeRegistry:
    def __init__(self) -> None:
        self._instances: dict[str, RuntimeInstance] = {}

    def register(self, agent_id: str, runtime_instance: RuntimeInstance) -> None:
        self._instances[agent_id] = runtime_instance

    def get(self, agent_id: str) -> RuntimeInstance | None:
        return self._instances.get(agent_id)


_registry = _AgentRuntimeRegistry()


def register_runtime_instance_for_agent(
    agent_id: str, runtime_instance: RuntimeInstance
) -> None:
    """Asocia `runtime_instance` a `agent_id`, sustituyendo cualquier
    asociación anterior (mismo criterio que `save_active_project`, AF-001:
    la última asociación registrada gana, sin acumular histórico)."""
    _registry.register(agent_id, runtime_instance)


def get_runtime_instance_for_agent(agent_id: str) -> RuntimeInstance | None:
    """Consulta el `RuntimeInstance` asociado a `agent_id`, o `None`
    explícito si ese agente nunca se registró (nunca lanzado, o `agent_id`
    desconocido) — nunca lanza una excepción."""
    return _registry.get(agent_id)


def _reset_registry_for_tests() -> None:
    """Reinicia el registro interno. Uso exclusivo de la suite de tests
    (mismo patrón que `session_registry`/`job_count_registry`), para que
    cada test parta de un estado limpio sin depender del orden de
    ejecución de otros tests."""
    global _registry
    _registry = _AgentRuntimeRegistry()
