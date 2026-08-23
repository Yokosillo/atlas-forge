"""Contrato de dominio para capacidades de runtime, modelo y cambio de modelo
(T-AF005-US07-01): define qué operaciones de modelo cada runtime soporta.

Este módulo formaliza las decisiones de modelo/runtime como un contrato
explícito, reemplazando comprobaciones implícitas de "solo OpenCode"
por declaraciones de capacidades por runtime.

## Conceptos fundamentales

- **Runtime**: Motor de ejecución (OpenCode, Claude Code, Codex) — INMUTABLE
  durante la vida de una instancia. No se puede cambiar sin relanzar.
- **Modelo**: Versión dentro del runtime activo (p. ej., claude-3.5-sonnet
  dentro de Claude Code).
- **Capacidades del runtime**: Qué operaciones de modelo el runtime soporta
  (lectura de modelo, cambio en caliente, etc.).

## Matriz de capacidades

| Runtime      | Lee modelo | Cambia modelo | Modo lectura |
|--------------|-----------|---------------|--------------|
| OpenCode     | Sí (pasiva)| Sí (teclas)   | Pasiva (barra) |
| Claude Code  | Sí (activa)| No            | Activa (/status) |
| Codex        | No        | No            | N/A           |

Definidas por la Task `US-AF005-07` como requerimiento de dominio.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RuntimeType(str, Enum):
    """Runtimes soportados por el sistema. Valores usados en configuración
    y runtime registry. IMPORTANTE: estos nombres DEBEN coincidir con los
    registrados en `register_*_runtime` (p. ej. `register_claude_code_runtime`
    usa `"claude-code"` en kebab-case)."""

    OPENCODE = "opencode"
    CLAUDE_CODE = "claude-code"
    CODEX = "codex"


class ModelReadCapability(str, Enum):
    """Modo en que el runtime puede leer el modelo activo."""

    PASSIVE = "passive"      # Lectura sin interactuar (p. ej., barra de OpenCode)
    ACTIVE = "active"        # Lectura con interacción (p. ej., /status de Claude Code)
    UNAVAILABLE = "unavailable"  # No soporta lectura de modelo


@dataclass(frozen=True)
class RuntimeModelCapabilities:
    """Declara qué operaciones de modelo un runtime soporta. Contrato formal
    de dominio para reemplazar comprobaciones ad-hoc de "solo OpenCode"."""

    runtime: RuntimeType
    can_read_model: bool  # ¿Se puede leer qué modelo está activo?
    read_capability: ModelReadCapability  # Si es True, ¿cómo se lee?
    can_change_model: bool  # ¿Se puede cambiar el modelo en caliente?
    can_change_model_idle_only: bool  # Si es True, solo en estado idle
    is_immutable_during_execution: bool  # True siempre (por diseño)

    def __post_init__(self):
        """Validar invariantes del contrato."""
        if self.can_read_model and self.read_capability == ModelReadCapability.UNAVAILABLE:
            raise ValueError(
                f"Invariante violado: {self.runtime} no puede leer modelo pero "
                f"read_capability es UNAVAILABLE"
            )
        if not self.can_read_model and self.read_capability != ModelReadCapability.UNAVAILABLE:
            raise ValueError(
                f"Invariante violado: {self.runtime} no soporta lectura de modelo "
                f"pero read_capability no es UNAVAILABLE"
            )
        # El runtime es siempre inmutable durante ejecución (por diseño de sistema)
        assert self.is_immutable_during_execution, (
            "Invariante: el runtime DEBE ser inmutable durante la vida de una instancia"
        )


# Registro de capacidades por runtime (contrato formalizado)
_RUNTIME_CAPABILITIES: dict[RuntimeType, RuntimeModelCapabilities] = {
    RuntimeType.OPENCODE: RuntimeModelCapabilities(
        runtime=RuntimeType.OPENCODE,
        can_read_model=True,
        read_capability=ModelReadCapability.PASSIVE,
        can_change_model=True,
        can_change_model_idle_only=True,  # T-AF024-US11-11: riesgo, solo en idle
        is_immutable_during_execution=True,
    ),
    RuntimeType.CLAUDE_CODE: RuntimeModelCapabilities(
        runtime=RuntimeType.CLAUDE_CODE,
        can_read_model=True,
        read_capability=ModelReadCapability.ACTIVE,
        can_change_model=False,  # Claude Code no soporta cambio en caliente
        can_change_model_idle_only=False,
        is_immutable_during_execution=True,
    ),
    RuntimeType.CODEX: RuntimeModelCapabilities(
        runtime=RuntimeType.CODEX,
        can_read_model=False,  # Codex no soporta lectura de modelo
        read_capability=ModelReadCapability.UNAVAILABLE,
        can_change_model=False,
        can_change_model_idle_only=False,
        is_immutable_during_execution=True,
    ),
}


def get_runtime_capabilities(runtime_type: RuntimeType) -> RuntimeModelCapabilities | None:
    """Obtiene el contrato de capacidades para un runtime específico.
    Retorna None si el runtime no está registrado (error de configuración)."""
    return _RUNTIME_CAPABILITIES.get(runtime_type)


def runtime_supports_model_read(runtime_type: RuntimeType) -> bool:
    """¿Este runtime puede leer el modelo activo?"""
    caps = get_runtime_capabilities(runtime_type)
    return caps is not None and caps.can_read_model


def runtime_supports_model_change(runtime_type: RuntimeType) -> bool:
    """¿Este runtime puede cambiar el modelo en caliente?"""
    caps = get_runtime_capabilities(runtime_type)
    return caps is not None and caps.can_change_model


def runtime_model_change_idle_only(runtime_type: RuntimeType) -> bool:
    """¿El cambio de modelo está restringido a agentes en estado idle?
    (Precondición: runtime_supports_model_change() debe ser True)."""
    caps = get_runtime_capabilities(runtime_type)
    if caps is None or not caps.can_change_model:
        return False
    return caps.can_change_model_idle_only


def runtime_is_immutable(runtime_type: RuntimeType) -> bool:
    """¿El runtime es inmutable durante la vida de una instancia?
    Siempre True por diseño del sistema — una instancia nace con un
    runtime y no puede cambiarlo sin relanzarse."""
    caps = get_runtime_capabilities(runtime_type)
    return caps is not None and caps.is_immutable_during_execution
