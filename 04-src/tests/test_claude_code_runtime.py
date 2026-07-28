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


def test_register_claude_code_runtime_includes_autonomy_flag_by_default() -> None:
    # T-FB002-US01-01: el comando de arranque debe incluir por defecto la
    # flag de máxima autonomía, mismo criterio ya en uso en la sesión tmux
    # real `claude-factory-brain` de este proyecto.
    runtime = register_claude_code_runtime()

    assert "--dangerously-skip-permissions" in runtime.args
