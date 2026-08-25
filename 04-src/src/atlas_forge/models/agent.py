from dataclasses import dataclass, field


@dataclass
class Agent:
    id: str
    name: str
    role: str
    prompt: str
    runtime_id: str
    status: str = "idle"
    last_command_at: str = ""
    # T-AF008-US18-04: motivo consultable del fallo de auto-liberación
    # ("working sin Job en vuelo"), expuesto en GET /agents y en la UI. Se
    # fija al marcar `status == "failed"` y se limpia al volver a `idle`.
    failure_reason: str | None = None
    limited_until: str | None = None
    # T-AF023-US03-01: si el agente es una instancia PERSISTENTE del rol
    # (Arquitecto y otros roles de instancia única: true) o bajo demanda
    # (Developer/Tester: false). Se decide por rol al lanzar, no es
    # configurable libremente por instancia.
    persistent: bool = False
    # T-AF005-US03-01/-02: capacidades que este agente declara ejecutar (p. ej.
    # `code.write`, `code.review`) — metadato propio, consultable por el
    # Dispatcher/AF-010 sin conocer el rol por nombre. Se asigna al crear el
    # agente desde las declaraciones por rol (US-AF005-03).
    capabilities: tuple[str, ...] = field(default_factory=tuple)
    # T-AF023-US01-02: estado de supervisión (vivo/colgado/detenido), distinto
    # del estado funcional `status`. Se calcula perezosamente al consultar
    # (`refresh_agent_supervision`) y se expone en `GET /agents`. No participa
    # en el flujo del pipeline.
    supervision_status: str = "vivo"
    # Historial acotado de timestamps de última actividad observados entre
    # lecturas — alimenta la detección de cuelgue (T-AF023-US01-01).
    activity_history: list[float] = field(default_factory=list)
