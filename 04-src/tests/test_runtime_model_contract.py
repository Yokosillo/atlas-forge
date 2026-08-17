"""Tests para T-FB005-US07-01: contrato de runtime, modelo y capacidades.

Verifica que:
1. El contrato define capacidades correctas para cada runtime
2. Las capacidades son correctamente consultables
3. El runtime es inmutable durante la vida de una instancia
4. No hay suposiciones ad-hoc de "solo OpenCode"
"""

import pytest

from brain.runtime_model_contract import (
    ModelReadCapability,
    RuntimeModelCapabilities,
    RuntimeType,
    get_runtime_capabilities,
    runtime_is_immutable,
    runtime_model_change_idle_only,
    runtime_supports_model_change,
    runtime_supports_model_read,
)


class TestRuntimeTypes:
    """Verifica que los tipos de runtime están bien definidos."""

    def test_runtime_type_values(self):
        """Cada runtime tiene su identificador correcto."""
        assert RuntimeType.OPENCODE.value == "opencode"
        assert RuntimeType.CLAUDE_CODE.value == "claude-code"
        assert RuntimeType.CODEX.value == "codex"

    def test_runtime_type_creation_from_string(self):
        """Se pueden crear RuntimeType a partir de strings."""
        assert RuntimeType("opencode") == RuntimeType.OPENCODE
        assert RuntimeType("claude-code") == RuntimeType.CLAUDE_CODE
        assert RuntimeType("codex") == RuntimeType.CODEX


class TestRuntimeCapabilitiesOpenCode:
    """Verifica el contrato para OpenCode."""

    def test_opencode_capabilities(self):
        """OpenCode soporta lectura y cambio de modelo."""
        caps = get_runtime_capabilities(RuntimeType.OPENCODE)
        assert caps is not None
        assert caps.runtime == RuntimeType.OPENCODE
        assert caps.can_read_model is True
        assert caps.read_capability == ModelReadCapability.PASSIVE
        assert caps.can_change_model is True
        assert caps.can_change_model_idle_only is True  # T-FB024-US11-11
        assert caps.is_immutable_during_execution is True

    def test_opencode_supports_queries(self):
        """Funciones de utilidad retornan valores correctos para OpenCode."""
        assert runtime_supports_model_read(RuntimeType.OPENCODE) is True
        assert runtime_supports_model_change(RuntimeType.OPENCODE) is True
        assert runtime_model_change_idle_only(RuntimeType.OPENCODE) is True
        assert runtime_is_immutable(RuntimeType.OPENCODE) is True


class TestRuntimeCapabilitiesClaudeCode:
    """Verifica el contrato para Claude Code."""

    def test_claude_code_capabilities(self):
        """Claude Code soporta lectura pero no cambio de modelo."""
        caps = get_runtime_capabilities(RuntimeType.CLAUDE_CODE)
        assert caps is not None
        assert caps.runtime == RuntimeType.CLAUDE_CODE
        assert caps.can_read_model is True
        assert caps.read_capability == ModelReadCapability.ACTIVE  # /status
        assert caps.can_change_model is False
        assert caps.can_change_model_idle_only is False
        assert caps.is_immutable_during_execution is True

    def test_claude_code_supports_queries(self):
        """Funciones de utilidad retornan valores correctos para Claude Code."""
        assert runtime_supports_model_read(RuntimeType.CLAUDE_CODE) is True
        assert runtime_supports_model_change(RuntimeType.CLAUDE_CODE) is False
        assert runtime_model_change_idle_only(RuntimeType.CLAUDE_CODE) is False
        assert runtime_is_immutable(RuntimeType.CLAUDE_CODE) is True


class TestRuntimeCapabilitiesCodex:
    """Verifica el contrato para Codex."""

    def test_codex_capabilities(self):
        """Codex no soporta lectura ni cambio de modelo."""
        caps = get_runtime_capabilities(RuntimeType.CODEX)
        assert caps is not None
        assert caps.runtime == RuntimeType.CODEX
        assert caps.can_read_model is False
        assert caps.read_capability == ModelReadCapability.UNAVAILABLE
        assert caps.can_change_model is False
        assert caps.can_change_model_idle_only is False
        assert caps.is_immutable_during_execution is True

    def test_codex_supports_queries(self):
        """Funciones de utilidad retornan valores correctos para Codex."""
        assert runtime_supports_model_read(RuntimeType.CODEX) is False
        assert runtime_supports_model_change(RuntimeType.CODEX) is False
        assert runtime_model_change_idle_only(RuntimeType.CODEX) is False
        assert runtime_is_immutable(RuntimeType.CODEX) is True


class TestRuntimeImmutability:
    """Verifica que el runtime es inmutable durante la vida de una instancia."""

    def test_all_runtimes_immutable(self):
        """Todos los runtimes son inmutables por contrato."""
        for runtime_type in RuntimeType:
            assert runtime_is_immutable(runtime_type) is True


class TestCapabilitiesContractInvariants:
    """Verifica invariantes del contrato de capacidades."""

    def test_read_capability_consistency(self):
        """Si can_read_model es True, read_capability no es UNAVAILABLE."""
        for runtime_type in RuntimeType:
            caps = get_runtime_capabilities(runtime_type)
            if caps.can_read_model:
                assert caps.read_capability != ModelReadCapability.UNAVAILABLE
            else:
                assert caps.read_capability == ModelReadCapability.UNAVAILABLE

    def test_change_capability_consistency(self):
        """Si can_change_model es True, puede_ser idle_only se especifica."""
        for runtime_type in RuntimeType:
            caps = get_runtime_capabilities(runtime_type)
            # Si soporta cambio, la restricción idle es relevante
            if caps.can_change_model:
                assert isinstance(caps.can_change_model_idle_only, bool)


class TestUnknownRuntime:
    """Verifica comportamiento ante runtime desconocido."""

    def test_unknown_runtime_returns_none(self):
        """Un runtime no registrado retorna None."""
        # Crear un RuntimeType ficticio (fuera del registro)
        # Esta prueba es más bien documentación de que
        # get_runtime_capabilities puede retornar None si se llama
        # con un tipo no registrado (aunque en práctica, RuntimeType
        # es una enum, así que esto es imposible en código real)
        pass  # Imposible en código real porque RuntimeType es una enum
