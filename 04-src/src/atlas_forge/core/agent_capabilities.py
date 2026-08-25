"""Lógica central de declaración de capacidades de agentes
(T-AF005-US03-01, US-AF005-03 · "Declarar qué capacidades puede ejecutar cada
agente").

Capa de DOMINIO pura: modela la relación agente→capacidades (metadato
declarado, sin lógica de decisión) y la expone de forma invocable
programáticamente, SIN dependencias de infraestructura (HTTP, persistencia,
I/O). AF-010 (Capability Engine) es quien decide/compara candidatos a partir
de este catálogo — esta Story solo DECLARA y consulta.

## Decisiones de dominio (US-AF005-03)

- Una `capability` es una cadena plana (p. ej. `code.write`, `code.review`).
- Cada agente declara un conjunto de capacidades como metadato propio.
- Consultas: `capabilities_of(agent_id)` (qué capacidades tiene un agente) y
  `agents_with_capability(capability)` (qué agentes la declaran).
- La relación es consultable y portable (`to_mapping`/`from_mapping`) para
  que la capa de persistencia la conserve junto a la configuración del agente,
  sin que este módulo haga I/O.
"""

from __future__ import annotations

from typing import Iterable, Mapping


class AgentCapabilityRegistry:
    """Registro puro agente→capacidades.

    Almacena para cada `agent_id` un conjunto de capacidades declaradas.
    Métodos de consulta puros; el `to_mapping()` devuelve una forma portable
    (JSON-serializable) y `from_mapping()` la reconstruye — sin tocar disco."""

    def __init__(
        self,
        declarations: Mapping[str, Iterable[str]] | None = None,
    ) -> None:
        self._declarations: dict[str, set[str]] = {
            str(agent_id): {str(c) for c in caps}
            for agent_id, caps in (declarations or {}).items()
        }

    def declare(self, agent_id: str, capabilities: Iterable[str]) -> None:
        """Declara/actualiza la lista de capacidades de `agent_id`
        (metadato propio del agente, sin lógica de decisión)."""
        self._declarations[str(agent_id)] = {str(c) for c in capabilities}

    def add_capability(self, agent_id: str, capability: str) -> None:
        """Añade una capacidad concreta a `agent_id` (sin tocar las demás)."""
        self._declarations.setdefault(str(agent_id), set()).add(str(capability))

    def capabilities_of(self, agent_id: str) -> tuple[str, ...]:
        """Consulta: qué capacidades tiene declaradas `agent_id`."""
        return tuple(sorted(self._declarations.get(str(agent_id), set())))

    def has_capability(self, agent_id: str, capability: str) -> bool:
        """`True` si `agent_id` declara `capability`."""
        return str(capability) in self._declarations.get(str(agent_id), set())

    def agents_with_capability(self, capability: str) -> tuple[str, ...]:
        """Consulta inversa: qué agentes declaran `capability`."""
        cap = str(capability)
        return tuple(
            sorted(
                agent_id
                for agent_id, caps in self._declarations.items()
                if cap in caps
            )
        )

    def to_mapping(self) -> dict[str, list[str]]:
        """Forma portable (JSON-serializable) de la relación agente→capacidades,
        para que la capa de persistencia la conserve. No hace I/O aquí."""
        return {
            agent_id: sorted(caps)
            for agent_id, caps in self._declarations.items()
        }

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Iterable[str]]) -> "AgentCapabilityRegistry":
        """Reconstruye el registro desde un mapping portable."""
        return cls(declarations=mapping)


def build_default_capability_declarations() -> dict[str, list[str]]:
    """Capacidades por rol declaradas por defecto (US-AF005-03, criterio 1):
    Developer declara `code.write`/`code.review`; Critic declara `code.review`.
    Es metadato por defecto, sin lógica de decisión."""
    return {
        "developer": ["code.write", "code.review"],
        "critic": ["code.review"],
    }