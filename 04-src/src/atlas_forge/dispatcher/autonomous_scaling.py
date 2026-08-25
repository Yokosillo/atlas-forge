"""Modo autónomo del Dispatcher (T-AF023-US03-02, US-AF023-03 · "Modo
autónomo: escalado y liberación por demanda").

En modo autónomo el Dispatcher decide **levantar** Developers/Testers cuando
hay cola pendiente y **liberarlos cuando ya no hay demanda** (no al terminar
cada tarea), con escalado por rol configurable y control de no saturar la
máquina.

## Reglas (decisión de producto 2026-08-23)

- `desired = clamp(ceil(pending / tasks_per_agent), min, max)` por rol.
  Con más cola pendiente se mantienen más agentes; sin demanda se libera el
  excedente hasta `min` (por defecto 0 para Developer/Tester → se libera todo).
- **Saturación:** nunca se lanzan más de `max_agents_total` agentes vivos a
  la vez (suma de todos los roles escalables).
- **Liberación segura frente al redespacho por corrección del Tester:** solo
  se libera un agente que esté `idle`, NO `persistent`, y que no sea el
  Developer retenido de una Task en `IN_REVIEW` (que volvería a él) ni tenga
  un Job en vuelo — se libera cuando la Task quedó `DONE`, no al dejarla en
  `IN_REVIEW`.
- **Persistentes intactos:** un agente `persistent=true` (Arquitecto y otros
  roles de instancia única) NUNCA es liberado ni escalado por el modo
  autónomo.

La orquestación (`autonomous_scale`) recibe `launch`/`release` como
callables inyectados para poder testear el escalado/liberación de forma
determinista sin tmux real; el cableado de producción usa
`launch_agent`/`stop_agent` de `atlas_forge.agents`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable

from atlas_forge.models import DevelopmentSession

# Roles que el modo autónomo escala/libera (los `persistent=false` típicos).
DEFAULT_SCALABLE_ROLES = ("developer", "tester")

# Configuración por defecto del modo autónomo (2026-08-23). Coherente con
# `DEFAULT_MAX_SIMULTANEOUS_DEVELOPERS = 3` de `system_preferences`.
DEFAULT_AUTONOMOUS_PREFERENCES = {
    "enabled": False,
    "roles": {
        "developer": {"min": 0, "max": 3, "tasks_per_agent": 3},
        "tester": {"min": 0, "max": 2, "tasks_per_agent": 4},
    },
    "max_agents_total": 6,
}


@dataclass(frozen=True)
class RoleScaleConfig:
    """Escalado configurable para un rol (Developer/Tester)."""

    min: int = 0
    max: int = 3
    tasks_per_agent: int = 3

    def __post_init__(self) -> None:
        if self.min < 0 or self.max < 0 or self.max < self.min:
            raise ValueError(
                f"Configuración de escalado inválida: min={self.min}, max={self.max}."
            )
        if self.tasks_per_agent <= 0:
            raise ValueError("tasks_per_agent debe ser > 0.")


@dataclass(frozen=True)
class AutonomousConfig:
    """Configuración completa del modo autónomo."""

    enabled: bool = False
    roles: dict[str, RoleScaleConfig] = field(default_factory=dict)
    max_agents_total: int = DEFAULT_AUTONOMOUS_PREFERENCES["max_agents_total"]

    def __post_init__(self) -> None:
        if self.max_agents_total <= 0:
            raise ValueError("max_agents_total debe ser > 0.")
        for role, cfg in self.roles.items():
            if cfg.max > self.max_agents_total:
                raise ValueError(
                    f"max del rol '{role}' ({cfg.max}) excede max_agents_total "
                    f"({self.max_agents_total})."
                )


def config_from_preferences(prefs: dict | None) -> AutonomousConfig:
    """Construye un `AutonomousConfig` desde el dict de preferencias de
    sistema (o desde los defaults si `prefs` es `None`)."""
    p = prefs or {}
    roles_raw = p.get("roles") or DEFAULT_AUTONOMOUS_PREFERENCES["roles"]
    roles = {
        role: RoleScaleConfig(**raw)
        for role, raw in roles_raw.items()
        if role in DEFAULT_SCALABLE_ROLES
    }
    return AutonomousConfig(
        enabled=bool(p.get("enabled", False)),
        roles=roles,
        max_agents_total=int(
            p.get("max_agents_total", DEFAULT_AUTONOMOUS_PREFERENCES["max_agents_total"])
        ),
    )


def compute_desired_agent_count(pending: int, cfg: RoleScaleConfig) -> int:
    """Devuelve cuántos agentes del rol `cfg` deberían estar activos con
    `pending` Tasks pendientes en la cola.

    `desired = clamp(ceil(pending / tasks_per_agent), min, max)`. Con
    `pending == 0` devuelve `min` (por defecto 0 → se libera todo)."""
    if pending <= 0:
        return cfg.min
    desired = math.ceil(pending / cfg.tasks_per_agent)
    return max(cfg.min, min(cfg.max, desired))


def count_pending(entries: list[Any]) -> int:
    """Cuenta las entradas de la cola que representan demanda pendiente de
    despachar: las `queued` (aún no tomadas por un Developer)."""
    return sum(1 for e in entries if getattr(e, "status", None) == "queued")


def select_agents_to_release(
    agents: list[Any],
    *,
    role: str,
    desired: int,
    retained_agent_ids: set[str] | None = None,
    inflight_agent_ids: set[str] | None = None,
) -> list[Any]:
    """Devuelve la lista de agentes del rol `role` que hay que liberar para
    bajar de `len(active)` a `desired`, respetando:

    - solo agentes NO persistentes (`persistent is False`);
    - solo agentes `idle` (no trabajando);
    - solo agentes que NO sean el Developer retenido de una Task en
      `IN_REVIEW` (`retained_agent_ids`) — liberarlos rompería el redespacho
      por corrección del Tester;
    - solo agentes sin Job en vuelo (`inflight_agent_ids`).

    Devuelve `[]` si no hay excedente liberable. La liberación real la hace
    el llamador con `release` (stop/release)."""
    retained = retained_agent_ids or set()
    inflight = inflight_agent_ids or set()
    candidates = [
        a for a in agents
        if getattr(a, "role", None) == role
        and not getattr(a, "persistent", False)
        and getattr(a, "status", None) == "idle"
        and getattr(a, "id", None) not in retained
        and getattr(a, "id", None) not in inflight
    ]
    surplus = len(candidates) - desired
    if surplus <= 0:
        return []
    return candidates[:surplus]


def autonomous_scale(
    session: DevelopmentSession,
    *,
    config: AutonomousConfig,
    pending: int,
    agents: list[Any],
    project_path: str,
    socket_name: str,
    retained_agent_ids: set[str] | None = None,
    inflight_agent_ids: set[str] | None = None,
    launch: Callable[..., Any],
    release: Callable[..., None],
    runtime_type: str | None = None,
    model: str | None = None,
) -> dict:
    """Ejecuta UN ciclo del modo autónomo: sube el nº de agentes activos de
    cada rol escalable hasta lo que pide la demanda (respetando
    `max_agents_total`) y libera el excedente que ya no se necesita (solo
    agentes liberables y `persistent=false`).

    `launch(role, ...)` y `release(agent, session)` son callables inyectados
    (producción usa `launch_agent`/`stop_agent`; tests usan mocks). Devuelve
    un resumen de las acciones tomadas:
    `{"launched": [role,...], "released": [agent_id,...]}`.

    Nunca lanza si `config.enabled` es False. Nunca toca agentes
    `persistent=true` (Arquitecto y otros)."""
    if not config.enabled:
        return {"launched": [], "released": []}

    launched: list[str] = []
    released: list[str] = []
    active = {a.id: a for a in agents}

    for role, cfg in config.roles.items():
        active_role = [a for a in active.values() if getattr(a, "role", None) == role]
        desired = compute_desired_agent_count(pending, cfg)

        # Lanzar hasta `desired`, sin superar `max_agents_total` (saturación).
        to_launch = desired - len(active_role)
        while to_launch > 0 and len(active) < config.max_agents_total:
            launch(role=role, session=session, project_path=project_path,
                   socket_name=socket_name, runtime_type=runtime_type, model=model)
            launched.append(role)
            to_launch -= 1

        # Liberar excedente que ya no se necesita.
        active_role = [a for a in active.values() if getattr(a, "role", None) == role]
        for agent in select_agents_to_release(
            active_role, role=role, desired=desired,
            retained_agent_ids=retained_agent_ids,
            inflight_agent_ids=inflight_agent_ids,
        ):
            release(agent, session)
            released.append(getattr(agent, "id", None))
            active.pop(getattr(agent, "id", None), None)

    return {"launched": launched, "released": released}