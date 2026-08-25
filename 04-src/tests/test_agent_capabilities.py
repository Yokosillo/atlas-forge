"""Tests deterministas de la lógica central de declaración de capacidades
(T-AF005-US03-01, US-AF005-03) — capa de dominio pura, sin infraestructura."""

from atlas_forge.core.agent_capabilities import (
    AgentCapabilityRegistry,
    build_default_capability_declarations,
)


def test_declare_y_consultar_capacidades_de_un_agente():
    reg = AgentCapabilityRegistry()
    reg.declare("Developer-1", ["code.write", "code.review"])
    assert reg.capabilities_of("Developer-1") == ("code.review", "code.write")
    assert reg.has_capability("Developer-1", "code.write")


def test_consulta_inversa_agentes_con_capacidad():
    reg = AgentCapabilityRegistry()
    reg.declare("Developer-1", ["code.write", "code.review"])
    reg.declare("Critic-1", ["code.review"])
    assert reg.agents_with_capability("code.review") == ("Critic-1", "Developer-1")
    assert reg.agents_with_capability("code.write") == ("Developer-1",)


def test_agente_sin_capacidades_devuelve_vacio():
    reg = AgentCapabilityRegistry()
    assert reg.capabilities_of("Developer-1") == ()
    assert reg.agents_with_capability("code.write") == ()


def test_add_capability_no_borra_las_existentes():
    reg = AgentCapabilityRegistry({"Developer-1": ["code.write"]})
    reg.add_capability("Developer-1", "code.review")
    assert reg.capabilities_of("Developer-1") == ("code.review", "code.write")


def test_mapping_round_trip_conserva_la_relacion():
    reg = AgentCapabilityRegistry({"Developer-1": ["code.write", "code.review"], "Critic-1": ["code.review"]})
    data = reg.to_mapping()
    assert data["Developer-1"] == ["code.review", "code.write"]
    rebuilt = AgentCapabilityRegistry.from_mapping(data)
    assert rebuilt.capabilities_of("Developer-1") == ("code.review", "code.write")
    assert rebuilt.agents_with_capability("code.review") == ("Critic-1", "Developer-1")


def test_declaraciones_por_defecto_por_rol():
    defaults = build_default_capability_declarations()
    reg = AgentCapabilityRegistry(defaults)
    assert reg.capabilities_of("developer") == ("code.review", "code.write")
    assert reg.capabilities_of("critic") == ("code.review",)
    # La relación es metadato, no hay lógica de decisión/comparación.
    assert reg.has_capability("developer", "code.write")
    assert not reg.has_capability("critic", "code.write")


def test_es_json_serializable():
    import json

    reg = AgentCapabilityRegistry({"Developer-1": ["code.write"]})
    json.dumps(reg.to_mapping())  # no debe lanzar

# ── T-AF005-US03-02: conexión al contexto de uso (modelo de agente) ──

def test_agente_developer_lleva_capacidades_declaradas():
    from atlas_forge.core.agent_capabilities import build_default_capability_declarations
    from atlas_forge.models import Agent
    # Simula lo que `register_agent` asigna: el rol developer declara sus
    # capacidades desde las declaraciones por defecto.
    caps = tuple(build_default_capability_declarations().get("developer", []))
    agent = Agent(id="a1", name="Developer-1", role="developer", prompt="",
                  runtime_id="r", capabilities=caps)
    assert "code.write" in agent.capabilities
    assert "code.review" in agent.capabilities
    # El metadato es consultable desde el agente (contexto de uso del Dispatcher).
    assert set(agent.capabilities) >= {"code.write", "code.review"}


def test_agente_legacy_sin_capacidades_no_rompe_serializacion():
    from atlas_forge.models import Agent
    # Un agente creado antes del campo no tiene `capabilities` -> `getattr`
    # devuelve la lista vacía sin romper.
    agent = Agent(id="a1", name="X", role="arquitecto", prompt="", runtime_id="r")
    assert list(getattr(agent, "capabilities", None) or []) == []
