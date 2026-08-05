from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from brain.models import Agent, DevelopmentSession, Runtime
    from brain.runtime import RuntimeInstance


@dataclass
class RoleConfig:
    role: str
    governance_filename: str
    prompt: str
    prompt_builder: Callable[[str], str] | None = None
    register_fn: Callable[..., tuple[Any, Any]] | None = None


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
