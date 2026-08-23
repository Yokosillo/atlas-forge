from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from atlas_forge.models import Agent, DevelopmentSession, Runtime
    from atlas_forge.runtime import RuntimeInstance


@dataclass
class RoleConfig:
    role: str
    governance_filename: str
    prompt: str
    prompt_builder: Callable[[str], str] | None = None
    register_fn: Callable[..., tuple[Any, Any]] | None = None
    # T-AF023-US03-01: si el rol crea instancias PERSISTENTES (de instancia
    # única, p. ej. Arquitecto) o bajo demanda (Developer/Tester). Se decide
    # por rol al lanzar; no es configurable por instancia.
    persistent: bool = False


_role_registry: dict[str, RoleConfig] = {}


def register_role(config: RoleConfig) -> None:
    _role_registry[config.role] = config


def get_role(role: str) -> RoleConfig | None:
    return _role_registry.get(role)


def list_roles() -> list[str]:
    return sorted(_role_registry.keys())


def get_governance_filename_for_role(role: str) -> str | None:
    config = _role_registry.get(role)
    return config.governance_filename if config else None


def get_register_fn_for_role(role: str) -> Callable[..., tuple[Any, Any]] | None:
    config = _role_registry.get(role)
    return config.register_fn if config else None


def is_persistent_role(role: str) -> bool:
    """`True` si el rol crea instancias persistentes (de instancia única,
    p. ej. Arquitecto). Fuente única para asignar `Agent.persistent` al
    lanzar (T-AF023-US03-01)."""
    config = _role_registry.get(role)
    return bool(config and config.persistent)
