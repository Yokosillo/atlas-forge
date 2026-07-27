from brain.runtime.claude_code import register_claude_code_runtime


def test_register_claude_code_runtime_has_minimal_configuration() -> None:
    runtime = register_claude_code_runtime()

    assert runtime.id == "claude-code"
    assert runtime.type == "claude-code"
    assert runtime.command == "claude"
    assert isinstance(runtime.args, list)
    # No se ejecuta el comando real en este test: solo se verifica que la
    # configuración por defecto está bien formada (ver precaución de
    # T-FB004-US01-02 y T-FB004-US02-01: nunca lanzar el binario `claude`
    # real en tests, este entorno ya usa sesiones tmux reales con `claude`
    # para el ciclo worker/crítico).
